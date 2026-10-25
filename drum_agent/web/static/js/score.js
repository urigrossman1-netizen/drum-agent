// The working score in the browser: the IR exactly as the server writes it (`Score.to_dict`),
// with exact fractions for positions. The grid, the player and the notation all read this one
// object; edits replace it with a new one (undo keeps the old).

export class Frac {
  constructor(n, d = 1) {
    if (d < 0) { n = -n; d = -d; }
    const g = gcd(Math.abs(n), d) || 1;
    this.n = n / g; this.d = d / g;
  }
  static parse(s) {
    if (s instanceof Frac) return s;
    if (typeof s === "number") return Frac.fromFloat(s);
    const [a, b] = String(s).split("/");
    return new Frac(parseInt(a, 10), b === undefined ? 1 : parseInt(b, 10));
  }
  static fromFloat(x, maxDen = 192) { const d = maxDen; return new Frac(Math.round(x * d), d); }
  add(o) { return new Frac(this.n * o.d + o.n * this.d, this.d * o.d); }
  sub(o) { return new Frac(this.n * o.d - o.n * this.d, this.d * o.d); }
  mul(o) { return new Frac(this.n * o.n, this.d * o.d); }
  div(o) { return new Frac(this.n * o.d, this.d * o.n); }
  cmp(o) { return this.n * o.d - o.n * this.d; }
  eq(o) { return this.n === o.n && this.d === o.d; }
  get value() { return this.n / this.d; }
  toString() { return this.d === 1 ? String(this.n) : `${this.n}/${this.d}`; }
}

function gcd(a, b) { while (b) [a, b] = [b, a % b]; return a; }
function lcm(a, b) { return (a / gcd(a, b)) * b; }

export function timeSig(m) {
  const [num, den] = m.time.split("/").map(Number);
  return { num, den, groups: m.beat_groups || null, text: m.time };
}

export function barLength(m) {
  if (m.length) return Frac.parse(m.length);
  const { num, den } = timeSig(m);
  return new Frac(num, den);
}

/** Beats of a bar as [start, length] fractions of a whole note (the server's TimeSig.beats). */
export function beats(m) {
  const { num, den, groups } = timeSig(m);
  const out = [];
  if (groups && groups.length) {
    let pos = new Frac(0);
    for (const g of groups) { const len = new Frac(g, den); out.push([pos, len]); pos = pos.add(len); }
  } else if (den === 8 && num % 3 === 0) {
    const len = new Frac(3, 8);
    for (let k = 0; k < num / 3; k++) out.push([len.mul(new Frac(k)), len]);
  } else if (den === 8 && num % 3 !== 0) {
    const parts = [];
    let rest = num;
    while (rest > 0) { const g = rest === 4 ? 2 : rest >= 3 && rest !== 4 ? (rest % 2 === 1 ? 3 : 2) : rest; parts.push(g); rest -= g; }
    let pos = new Frac(0);
    for (const g of parts.reverse()) { const len = new Frac(g, 8); out.push([pos, len]); pos = pos.add(len); }
  } else {
    const len = new Frac(1, den);
    for (let k = 0; k < num; k++) out.push([len.mul(new Frac(k)), len]);
  }
  const L = barLength(m);
  return out.filter(([s]) => s.cmp(L) < 0);
}

export function tempoMap(score) {
  let t = score.measures[0]?.tempo ?? 120;
  return score.measures.map((m) => (m.tempo != null ? (t = m.tempo) : t));
}

/** Start time (s) and duration (s) of every bar at the written tempi, scaled by `speed`. */
export function barTimes(score, speed = 1) {
  const tempi = tempoMap(score);
  const out = [];
  let t = 0;
  score.measures.forEach((m, i) => {
    const dur = (barLength(m).value * 4 * 60) / tempi[i] / speed;
    out.push({ start: t, dur, tempo: tempi[i] * speed });
    t += dur;
  });
  return out;
}

/** Every stroke the player schedules, in time order: {t, inst, vel, bar, pos, grace, roll}. */
export function events(score, speed = 1) {
  const times = barTimes(score, speed);
  const out = [];
  score.measures.forEach((m, i) => {
    const { start, tempo } = times[i];
    const spw = (4 * 60) / tempo; // seconds per whole note
    const bl = beats(m);
    for (const hit of m.hits) {
      let pos = Frac.parse(hit.pos);
      let p = pos.value;
      if (score.swing) { // swung 8ths: the offbeat 8th lands on the last triplet
        for (const [bs, len] of bl) {
          const rel = pos.sub(bs);
          if (len.eq(new Frac(1, 4)) && rel.eq(new Frac(1, 8))) p = bs.value + (2 / 3) * len.value;
        }
      }
      const t = start + p * spw;
      const vel = hit.ghost ? Math.min(hit.velocity ?? 40, 45) : hit.accent ? Math.max(hit.velocity ?? 118, 112) : (hit.velocity ?? 90);
      if (hit.flam) out.push({ t: t - 0.022, inst: hit.inst, vel: vel * 0.45, bar: i, pos: hit.pos, grace: true });
      if (hit.drag) { out.push({ t: t - 0.05, inst: hit.inst, vel: vel * 0.4, bar: i, pos: hit.pos, grace: true }); out.push({ t: t - 0.027, inst: hit.inst, vel: vel * 0.4, bar: i, pos: hit.pos, grace: true }); }
      if (hit.roll) {
        const len = Frac.parse(hit.roll).value * spw;
        const step = Math.min(0.06, spw / 32);
        for (let x = 0; x < len - 1e-6; x += step) out.push({ t: t + x, inst: hit.inst, vel: vel * (x === 0 ? 1 : 0.7), bar: i, pos: hit.pos, roll: x > 0 });
      } else {
        out.push({ t, inst: hit.inst, vel, bar: i, pos: hit.pos, choke: !!hit.choke });
      }
    }
  });
  out.sort((a, b) => a.t - b.t);
  return { events: out, times, end: times.length ? times[times.length - 1].start + times[times.length - 1].dur : 0 };
}

/** The finest grid that shows every stroke of a bar: steps per beat (4 = 16ths, 3 = triplets ...). */
export function gridSteps(m, preferred = null) {
  const bl = beats(m);
  let per = preferred || 4;
  for (const hit of m.hits) {
    const pos = Frac.parse(hit.pos);
    const b = bl.find(([s, len]) => pos.cmp(s) >= 0 && pos.cmp(s.add(len)) < 0) || bl[0];
    const rel = pos.sub(b[0]).div(b[1]); // position within the beat, 0..1
    per = lcm(per, rel.d);
  }
  if (per > 12 && per % 3 === 0 && per !== 24) per = 24;
  return Math.min(per, 32);
}

export function stepPositions(m, per) {
  const out = [];
  for (const [s, len] of beats(m)) {
    const n = Math.max(1, Math.round((len.value / 0.25) * per));
    for (let k = 0; k < n; k++) out.push({ pos: s.add(len.mul(new Frac(k, n))), beatStart: k === 0, index: k, n });
  }
  return out;
}

export function clone(score) { return JSON.parse(JSON.stringify(score)); }

export function hitCount(score) { return score.measures.reduce((a, m) => a + m.hits.length, 0); }

export function sameScore(a, b) { return JSON.stringify(a.measures) === JSON.stringify(b.measures) && a.title === b.title; }
