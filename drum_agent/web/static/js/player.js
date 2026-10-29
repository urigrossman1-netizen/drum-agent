// Drum playback with Web Audio.
//
// Strokes are scheduled on the audio clock (a short look-ahead loop that queues every
// stroke due in the next 120 ms), so timing doesn't drift with the page's timers. Sounds:
// the "acoustic" kit uses drum samples rendered on the server from the FluidR3 GM
// soundfont; the "electronic" kit (and any instrument without a sample) is synthesized
// here. The visual position comes from the same clock, read on every animation frame.
//
// Listening along: a chart transcribed from a recording knows where each bar starts in it
// (the performed bar starts). With the recording on, the bars and strokes are moved onto the
// recording's own time and the recording plays on the same clock, so the cursor, the loop
// and the chart's strokes follow the real performance, tempo drift included.

import { events as buildEvents, beats } from "./score.js";

const LOOKAHEAD = 0.12;
const TICK_MS = 25;
const CHOKE_GROUPS = { hihat: "hh", hihat_open: "hh", hihat_half: "hh", hihat_pedal: "hh", hihat_splash: "hh" };

export class Player {
  constructor() {
    this.ctx = null;
    this.kit = "acoustic";
    this.buffers = new Map();
    this.samplesAvailable = false;
    this.volume = 0.85;
    this.speed = 1;
    this.metronome = false;
    this.countIn = false;
    this.loop = false;
    this.range = null; // [firstBar, lastBar] (0-based) to play, or null for the whole chart
    this.muted = new Set();
    this.soloed = new Set();
    this.state = "stopped";
    this.onPosition = null; // (bar, seconds into bar, event) => void
    this.onState = null;
    this.onHit = null; // (event) => void, called when a stroke sounds
    this.scheduledLog = []; // for tests: what was scheduled, in song time
    this._ringing = new Map();
    this.recording = null; // the chart's recording (an AudioBuffer), once loaded
    this.timeline = null; // where each bar starts in the recording (s)
    this.recordingOn = false; // play the recording, in time with the chart
    this.drumsOn = true; // play the chart's own drum sounds
    this.following = false; // this run plays the recording
    this._sources = [];
  }

  async init() {
    if (this.ctx) {
      if (this.ctx.state === "suspended") await this.ctx.resume();
      return;
    }
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) throw new Error("This browser has no Web Audio support, so the chart can't be played here.");
    this.ctx = new AC({ latencyHint: "interactive" });
    this.master = this.ctx.createGain();
    this.master.gain.value = this.volume;
    const comp = this.ctx.createDynamicsCompressor();
    comp.threshold.value = -10; comp.ratio.value = 3;
    this.master.connect(comp).connect(this.ctx.destination);
    this.noise = this._noiseBuffer();
    if (this.ctx.state === "suspended") await this.ctx.resume();
  }

  async loadSamples(instruments) {
    if (!this.samplesAvailable || !this.ctx) return;
    await Promise.all(instruments.filter((i) => !this.buffers.has(i)).map(async (inst) => {
      try {
        const res = await fetch(`/api/kit/samples/${inst}.wav`);
        if (!res.ok) return;
        this.buffers.set(inst, await this.ctx.decodeAudioData(await res.arrayBuffer()));
      } catch { /* that instrument falls back to the synthesized sound */ }
    }));
  }

  /** The chart's recording, decoded once, and the performed start of every bar in it. */
  async loadRecording(url, timeline) {
    await this.init();
    const res = await fetch(url);
    if (!res.ok) throw new Error(`The recording could not be loaded (HTTP ${res.status}).`);
    this.recording = await this.ctx.decodeAudioData(await res.arrayBuffer());
    this.timeline = timeline;
  }

  /** Can the recording follow this score: one start per bar, in order, inside the recording? */
  canFollow(score) {
    const t = this.timeline;
    return !!(this.recording && Array.isArray(t) && t.length === score.measures.length
      && t.every((x, i) => Number.isFinite(x) && x >= 0 && x < this.recording.duration && (i === 0 || x > t[i - 1])));
  }

  setVolume(v) { this.volume = v; if (this.master) this.master.gain.setTargetAtTime(v, this.ctx.currentTime, 0.02); }

  audible(inst) {
    if (this.soloed.size) return this.soloed.has(inst);
    return !this.muted.has(inst);
  }

  /** Start playing `score` from `fromBar` (or the start of the range). */
  async play(score, fromBar = null) {
    await this.init();
    const used = [...new Set(score.measures.flatMap((m) => m.hits.map((h) => h.inst)))];
    if (this.kit === "acoustic") await this.loadSamples(used);
    this.stop(true);
    this.score = score;
    const built = buildEvents(score, this.speed);
    this.times = built.times;
    const first = this.range ? this.range[0] : (fromBar ?? 0);
    const last = this.range ? this.range[1] : score.measures.length - 1;
    this.following = this.recordingOn && this.canFollow(score);
    let events = built.events;
    this.clicks = this.metronome ? this._clicks(score, first, last) : [];
    if (this.following) {
      const warp = this._warp(built.times);
      events = events.map((e) => ({ ...e, t: warp.at(e.t, e.bar) }));
      this.clicks = this.clicks.map((c) => ({ ...c, t: warp.at(c.t, c.bar) }));
      this.times = warp.times;
    }
    this.segStart = this.times[first].start;
    this.segEnd = this.times[last].start + this.times[last].dur;
    this.events = events.filter((e) => e.t >= this.segStart - 0.06 && e.t < this.segEnd - 1e-6);
    const lead = 0.08;
    let countInDur = 0;
    if (this.countIn) {
      const m = score.measures[first];
      const bts = beats(m);
      const spw = (4 * 60) / this.times[first].tempo;
      countInDur = this.times[first].dur;
      const t0 = this.ctx.currentTime + lead;
      bts.forEach(([s], k) => this._click(t0 + s.value * spw, k === 0));
    }
    this.t0 = this.ctx.currentTime + lead + countInDur - this.segStart; // audio time of song time 0
    this.cursor = 0; this.clickCursor = 0; this.pass = 0;
    this.scheduledLog = [];
    this.state = "playing";
    this.countInUntil = this.ctx.currentTime + lead + countInDur;
    if (this.following) this._startRecording(this.t0 + this.segStart);
    this.onState && this.onState(this.state);
    this._timer = setInterval(() => this._schedule(), TICK_MS);
    this._schedule();
    this._raf = requestAnimationFrame(() => this._frame());
  }

  stop(silent = false) {
    clearInterval(this._timer);
    cancelAnimationFrame(this._raf);
    this._timer = null;
    if (this.ctx) for (const [, nodes] of this._ringing) for (const n of nodes) { try { n.g.gain.cancelScheduledValues(this.ctx.currentTime); n.g.gain.setTargetAtTime(0, this.ctx.currentTime, 0.03); } catch { /* ended */ } }
    this._ringing.clear();
    for (const src of this._sources) { try { src.stop(); } catch { /* not started */ } }
    this._sources = [];
    if (this.state !== "stopped") {
      this.state = "stopped";
      if (!silent) this.onState && this.onState(this.state);
    }
  }

  /** Song time (s) now, or null when not playing. */
  now() {
    if (this.state !== "playing") return null;
    const t = this.ctx.currentTime - (this.ctx.outputLatency || 0) - this.t0;
    return t;
  }

  _schedule() {
    const horizon = this.ctx.currentTime + LOOKAHEAD;
    const len = this.segEnd - this.segStart;
    for (;;) {
      const base = this.t0 + this.pass * len;
      while (this.cursor < this.events.length && base + this.events[this.cursor].t <= horizon) {
        const e = this.events[this.cursor++];
        const at = Math.max(base + e.t, this.ctx.currentTime);
        if (this.drumsOn && this.audible(e.inst)) this._voice(e.inst, at, e.vel / 127, e);
        this.scheduledLog.push({ t: +(e.t - this.segStart + this.pass * len).toFixed(4), inst: e.inst, bar: e.bar, pos: e.pos, grace: !!e.grace });
        if (this.onHit) { const delay = Math.max(0, (at - this.ctx.currentTime) * 1000); setTimeout(() => this.onHit && this.onHit(e), delay); }
      }
      while (this.clickCursor < this.clicks.length && base + this.clicks[this.clickCursor].t <= horizon) {
        const c = this.clicks[this.clickCursor++];
        this._click(Math.max(base + c.t, this.ctx.currentTime), c.down);
      }
      const done = this.cursor >= this.events.length && this.clickCursor >= this.clicks.length;
      if (!done) break;
      if (this.loop) {
        if (base + this.segEnd > horizon) break; // the next pass starts when this one ends
        this.pass += 1; this.cursor = 0; this.clickCursor = 0;
        if (this.following) this._startRecording(this.t0 + this.pass * len + this.segStart);
        continue;
      }
      if (this.ctx.currentTime > base + this.segEnd + 0.05) { this.stop(); }
      break;
    }
  }

  _frame() {
    if (this.state !== "playing") return;
    const len = this.segEnd - this.segStart;
    let t = this.now();
    if (t !== null && this.ctx.currentTime >= this.countInUntil) {
      if (this.loop && len > 0) t = this.segStart + ((t - this.segStart) % len + len) % len;
      if (t >= this.segStart && t <= this.segEnd) {
        let bar = 0;
        for (let i = 0; i < this.times.length; i++) if (this.times[i].start <= t + 1e-6) bar = i;
        this.onPosition && this.onPosition(bar, t - this.times[bar].start, t);
      }
    }
    this._raf = requestAnimationFrame(() => this._frame());
  }

  _clicks(score, first, last) {
    const out = [];
    for (let i = first; i <= last; i++) {
      const spw = (4 * 60) / this.times[i].tempo;
      beats(score.measures[i]).forEach(([s], k) => out.push({ t: this.times[i].start + s.value * spw, down: k === 0, bar: i }));
    }
    return out;
  }

  /** The bars on the recording's own time at this speed, and the map of a chart time in a bar onto it. */
  _warp(times) {
    const p = this.timeline;
    const warped = times.map((b, i) => {
      const next = i + 1 < p.length ? p[i + 1] : Math.min(this.recording.duration, p[i] + b.dur * this.speed);
      return { ...b, start: p[i] / this.speed, dur: Math.max(0.05, (next - p[i]) / this.speed) };
    });
    const at = (t, bar) => {
      const b = times[bar], w = warped[bar];
      return w.start + (b.dur > 0 ? (t - b.start) / b.dur : 0) * w.dur;
    };
    return { times: warped, at };
  }

  /** The recording from the segment's start, at `at` on the audio clock, for one pass. */
  _startRecording(at) {
    const src = this.ctx.createBufferSource();
    src.buffer = this.recording;
    src.playbackRate.value = this.speed;
    src.connect(this.master);
    const late = Math.max(0, this.ctx.currentTime - at);
    src.start(at + late, (this.segStart + late) * this.speed, Math.max(0.01, (this.segEnd - this.segStart - late) * this.speed));
    this._sources.push(src);
  }

  // ---- sounds -------------------------------------------------------------------
  _out(at, inst) {
    const g = this.ctx.createGain();
    g.connect(this.master);
    return g;
  }

  _voice(inst, at, vel, e) {
    const group = CHOKE_GROUPS[inst];
    if (group) this._choke(group, at, inst === "hihat_open" || inst === "hihat_half" ? 0.02 : 0.008);
    if (inst === "crash" || inst === "crash2" || inst === "china" || inst === "splash") {
      if (e && e.choke) setTimeout(() => this._choke("cym", this.ctx.currentTime + 0.18, 0.03), 0);
    }
    const buf = this.kit === "acoustic" ? this.buffers.get(inst) : null;
    const nodes = buf ? this._sample(buf, at, vel) : this._synth(inst, at, vel);
    if (group || (e && e.choke)) {
      const key = group || "cym";
      if (!this._ringing.has(key)) this._ringing.set(key, []);
      this._ringing.get(key).push(...nodes);
      if (this._ringing.get(key).length > 24) this._ringing.get(key).splice(0, 12);
    }
  }

  _choke(group, at, tau) {
    const nodes = this._ringing.get(group);
    if (!nodes) return;
    for (const n of nodes) {
      if (n.start < at) { try { n.g.gain.cancelScheduledValues(at); n.g.gain.setTargetAtTime(0, at, tau); } catch { /* ended */ } }
    }
    this._ringing.set(group, nodes.filter((n) => n.start >= at));
  }

  _sample(buf, at, vel) {
    const src = this.ctx.createBufferSource();
    src.buffer = buf;
    const g = this.ctx.createGain();
    g.gain.value = Math.pow(vel, 1.6) * 1.05;
    src.connect(g).connect(this.master);
    src.start(at);
    return [{ g, start: at }];
  }

  _noiseBuffer() {
    const len = this.ctx.sampleRate * 2;
    const b = this.ctx.createBuffer(1, len, this.ctx.sampleRate);
    const d = b.getChannelData(0);
    for (let i = 0; i < len; i++) d[i] = Math.random() * 2 - 1;
    return b;
  }

  _noise(at, dur, filters, gain, decay) {
    const src = this.ctx.createBufferSource();
    src.buffer = this.noise;
    let node = src;
    for (const [type, f, q] of filters) {
      const flt = this.ctx.createBiquadFilter();
      flt.type = type; flt.frequency.value = f; if (q) flt.Q.value = q;
      node.connect(flt); node = flt;
    }
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0, at);
    g.gain.linearRampToValueAtTime(gain, at + 0.002);
    g.gain.exponentialRampToValueAtTime(0.0008, at + decay);
    node.connect(g).connect(this.master);
    src.start(at, Math.random() * 1.5);
    src.stop(at + dur);
    return { g, start: at };
  }

  _tone(at, f0, f1, decay, gain, type = "sine") {
    const o = this.ctx.createOscillator();
    o.type = type;
    o.frequency.setValueAtTime(f0, at);
    o.frequency.exponentialRampToValueAtTime(Math.max(20, f1), at + decay * 0.6);
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0, at);
    g.gain.linearRampToValueAtTime(gain, at + 0.003);
    g.gain.exponentialRampToValueAtTime(0.0008, at + decay);
    o.connect(g).connect(this.master);
    o.start(at); o.stop(at + decay + 0.05);
    return { g, start: at };
  }

  _metal(at, decay, gain, hp = 7000, bp = 10000) {
    const ratios = [2, 3, 4.16, 5.43, 6.79, 8.21];
    const g = this.ctx.createGain();
    const band = this.ctx.createBiquadFilter(); band.type = "bandpass"; band.frequency.value = bp;
    const high = this.ctx.createBiquadFilter(); high.type = "highpass"; high.frequency.value = hp;
    g.gain.setValueAtTime(0, at);
    g.gain.linearRampToValueAtTime(gain, at + 0.002);
    g.gain.exponentialRampToValueAtTime(0.0008, at + decay);
    band.connect(high).connect(g).connect(this.master);
    for (const r of ratios) {
      const o = this.ctx.createOscillator(); o.type = "square"; o.frequency.value = 40 * r;
      o.connect(band); o.start(at); o.stop(at + decay + 0.05);
    }
    return { g, start: at };
  }

  _synth(inst, at, v) {
    const n = [];
    switch (inst) {
      case "kick": case "kick2":
        n.push(this._tone(at, 150, 42, 0.42, 1.1 * v)); n.push(this._noise(at, 0.02, [["lowpass", 3000]], 0.25 * v, 0.015)); break;
      case "snare": case "rimshot":
        n.push(this._noise(at, 0.25, [["highpass", 1200], ["bandpass", 2800, 0.7]], 0.9 * v, inst === "rimshot" ? 0.16 : 0.2));
        n.push(this._tone(at, 230, 180, 0.12, 0.45 * v, "triangle")); break;
      case "cross_stick":
        n.push(this._noise(at, 0.05, [["bandpass", 1800, 4]], 0.9 * v, 0.04)); n.push(this._tone(at, 1300, 900, 0.03, 0.25 * v, "square")); break;
      case "hihat": n.push(this._metal(at, 0.06, 0.32 * v)); break;
      case "hihat_half": n.push(this._metal(at, 0.22, 0.3 * v)); break;
      case "hihat_open": n.push(this._metal(at, 0.55, 0.3 * v)); break;
      case "hihat_pedal": case "hihat_splash": n.push(this._metal(at, inst === "hihat_splash" ? 0.35 : 0.05, 0.18 * v)); break;
      case "ride": n.push(this._metal(at, 1.1, 0.16 * v, 4500, 6500)); n.push(this._tone(at, 820, 800, 0.4, 0.05 * v, "triangle")); break;
      case "ride_bell": n.push(this._metal(at, 0.9, 0.12 * v, 3000, 4800)); n.push(this._tone(at, 1250, 1240, 0.7, 0.16 * v, "triangle")); break;
      case "crash": case "crash2": case "china": case "splash": {
        const d = inst === "splash" ? 0.8 : inst === "china" ? 1.4 : 2.0;
        n.push(this._noise(at, d, [["highpass", 3500]], 0.55 * v, d)); n.push(this._metal(at, d * 0.8, 0.12 * v, 5000, 8000)); break;
      }
      case "tom1": n.push(this._tone(at, 260, 190, 0.38, 0.9 * v)); break;
      case "tom2": n.push(this._tone(at, 200, 150, 0.42, 0.9 * v)); break;
      case "floor_tom": n.push(this._tone(at, 140, 100, 0.5, 0.95 * v)); break;
      case "floor_tom2": n.push(this._tone(at, 115, 82, 0.55, 0.95 * v)); break;
      case "cowbell": n.push(this._tone(at, 560, 560, 0.25, 0.25 * v, "square")); n.push(this._tone(at, 845, 845, 0.25, 0.18 * v, "square")); break;
      default: n.push(this._noise(at, 0.1, [["bandpass", 2000]], 0.5 * v, 0.08));
    }
    return n;
  }

  _click(at, down) {
    const o = this.ctx.createOscillator();
    o.type = "sine";
    o.frequency.value = down ? 1760 : 1320;
    const g = this.ctx.createGain();
    g.gain.setValueAtTime(0, at);
    g.gain.linearRampToValueAtTime(down ? 0.35 : 0.22, at + 0.001);
    g.gain.exponentialRampToValueAtTime(0.0005, at + 0.05);
    o.connect(g).connect(this.master);
    o.start(at); o.stop(at + 0.06);
  }
}
