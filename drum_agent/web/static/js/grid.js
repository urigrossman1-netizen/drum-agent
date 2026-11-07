// The beat grid: one lane per instrument, one cell per step, for the bars in view. Editing a
// cell writes a new working score (the same object the notation is engraved from), so the
// grid and the notation can't disagree.

import { h, icon, toast } from "./ui.js";
import { Frac, clone, gridSteps, stepPositions, loudness, GHOST_MAX, ACCENT_MIN } from "./score.js";

const ALWAYS = ["crash", "ride", "hihat_open", "hihat", "tom1", "tom2", "snare", "floor_tom", "kick", "hihat_pedal"];
const HATS = new Set(["hihat", "hihat_open", "hihat_half"]);
const COLOR = (inst, family) => (
  inst === "kick" || inst === "kick2" ? "var(--mint)" :
  inst === "snare" || inst === "cross_stick" || inst === "rimshot" ? "var(--violet)" :
  inst.startsWith("tom") || inst.startsWith("floor_tom") ? "var(--coral)" :
  HATS.has(inst) || inst.startsWith("hihat") ? "var(--cyan)" :
  family === "cymbal" ? "var(--amber)" : "var(--text-2)");
const DEFAULT_VEL = { kick: 100, snare: 104, hihat: 82, hihat_open: 88, ride: 84, crash: 116 };
const RESOLUTIONS = [["auto", "Auto"], [2, "8ths"], [4, "16ths"], [3, "Triplets"], [6, "16th triplets"], [8, "32nds"]];
const TOOLS = [["hit", "Hit"], ["accent", "Accent"], ["ghost", "Ghost"], ["flam", "Flam"], ["erase", "Erase"], ["adjust", "Adjust"]];
const samePos = (x, key) => Frac.parse(x.pos).toString() === key;

export class GridEditor {
  constructor(root, { kit, onEdit, onSelect, player }) {
    this.root = root;
    this.kit = kit; // [{id, name, family, position, foot}]
    this.onEdit = onEdit;
    this.onSelect = onSelect;
    this.player = player;
    this.tool = "hit";
    this.picked = null; // {bar, pos, inst}: the note the Adjust tool is on
    this.res = "auto";
    this.first = 0;
    this.perView = window.innerWidth < 760 ? 1 : 2;
    this.selection = [0, 0];
    this.cells = new Map(); // "bar|pos|inst" -> button
    this.cols = new Map(); // "bar|pos" -> [buttons]
    this.flags = new Set();
    this.sectionAt = new Map();
  }

  lanes(score) {
    const used = new Set(score.measures.flatMap((m) => m.hits.map((x) => x.inst)));
    return this.kit.filter((i) => ALWAYS.includes(i.id) || used.has(i.id));
  }

  render(score, { flags = new Set(), focusBar = null } = {}) {
    this.score = score;
    this.flags = flags;
    if (focusBar !== null && (focusBar < this.first || focusBar >= this.first + this.perView)) this.first = Math.max(0, Math.min(focusBar, score.measures.length - this.perView));
    this.first = Math.max(0, Math.min(this.first, score.measures.length - 1));
    if (this.picked && !this._hit(score, this.picked)) this.picked = null;
    const toolbar = h("div", { class: "grid-toolbar" },
      h("div", { class: "seg tools", role: "group", "aria-label": "Edit tool" },
        ...TOOLS.map(([k, label]) =>
          h("button", { type: "button", "aria-pressed": String(this.tool === k), title: k === "adjust" ? "Click a note to change how loud it is, its drum or its place" : null,
            onclick: () => { this.tool = k; if (k !== "adjust") this.picked = null; this.render(this.score, { flags: this.flags }); } }, label))),
      h("label", { class: "row small muted" }, "Grid",
        h("select", { class: "select", style: { width: "130px", "min-height": "32px" }, "aria-label": "Grid resolution",
          onchange: (e) => { this.res = e.target.value === "auto" ? "auto" : Number(e.target.value); this.render(this.score, { flags: this.flags }); } },
        RESOLUTIONS.map(([v, l]) => h("option", { value: v, selected: String(v) === String(this.res) }, l)))),
      h("button", { class: "btn sm", type: "button", title: "Copy the selected bar onto the next one", onclick: () => this.copyBar() }, icon("copy"), "Copy bar → next"),
      h("button", { class: "btn sm ghost", type: "button", title: "Remove every stroke in the selected bar", onclick: () => this.clearBar() }, icon("trash"), "Clear bar"),
      h("span", { class: "spacer" }),
      h("button", { class: "btn sm icon-only", type: "button", "aria-label": "Previous bar", onclick: () => this.go(this.first - 1) }, icon("chevron", "flip")),
      h("span", { class: "small muted num" }, `Bar${this.perView > 1 ? "s" : ""} ${this.first + 1}${this.perView > 1 && this.first + 1 < score.measures.length ? "–" + Math.min(score.measures.length, this.first + this.perView) : ""} of ${score.measures.length}`),
      h("button", { class: "btn sm icon-only", type: "button", "aria-label": "Next bar", onclick: () => this.go(this.first + 1) }, icon("chevron")));
    toolbar.querySelector(".flip")?.style.setProperty("transform", "rotate(180deg)");
    this.root.replaceChildren(...[toolbar, this._adjuster(score), this._strip(score), this._grid(score)].filter(Boolean));
    if (this._refocus) { this.root.querySelector(this._refocus)?.focus(); this._refocus = null; }
  }

  _hit(score, { bar, pos, inst }) {
    return score.measures[bar]?.hits.find((x) => x.inst === inst && samePos(x, pos)) || null;
  }

  _name(inst) { return this.kit.find((i) => i.id === inst)?.name || inst; }

  _steps(m) { return stepPositions(m, this.res === "auto" ? gridSteps(m) : gridSteps(m, this.res)); }

  _hear(inst, vel) { if (this.player.state !== "playing") this.player.audition(inst, vel).catch(() => {}); }

  /** The Adjust tool's controls, for the note picked in the grid. */
  _adjuster(score) {
    if (this.tool !== "adjust") return null;
    const hit = this.picked && this._hit(score, this.picked);
    if (!hit) return h("div", { class: "note-tools" }, h("span", { class: "small muted" }, "Click a note in the grid to change how loud it is, which drum it's on, or where it sits."));
    const { bar, pos, inst } = this.picked;
    const shown = h("span", { class: "num small" }, String(loudness(hit)));
    const slider = h("input", { type: "range", min: 1, max: 127, value: loudness(hit), "aria-label": "Loudness" });
    slider.addEventListener("input", () => {
      shown.textContent = slider.value;
      this.cells.get(`${bar}|${pos}|${inst}`)?.style.setProperty("--v", (slider.value / 127).toFixed(3));
    });
    slider.addEventListener("change", () => this.setLoudness(Number(slider.value)));
    const drum = h("select", { class: "select", style: { width: "150px", "min-height": "32px" }, "aria-label": "Drum", onchange: (e) => this.changeDrum(e.target.value) },
      this.kit.map((i) => h("option", { value: i.id, selected: i.id === inst }, i.name)));
    return h("div", { class: "note-tools" },
      h("strong", { class: "small" }, `${this._name(inst)}, bar ${bar + 1}`),
      h("label", { class: "row small muted" }, "Loudness", slider, shown),
      h("label", { class: "row small muted" }, "Drum", drum),
      h("button", { class: "btn sm", type: "button", "data-act": "earlier", title: "One grid step earlier", onclick: () => this.moveNote(-1) }, "‹ Earlier"),
      h("button", { class: "btn sm", type: "button", "data-act": "later", title: "One grid step later", onclick: () => this.moveNote(1) }, "Later ›"),
      h("button", { class: "btn sm ghost", type: "button", onclick: () => this.deleteNote() }, icon("trash"), "Delete"));
  }

  pick(bar, pos, inst, hit) {
    this.picked = hit ? { bar, pos, inst } : null;
    this.render(this.score, { flags: this.flags });
    this.cells.get(`${bar}|${pos}|${inst}`)?.focus();
    if (hit) this._hear(inst, loudness(hit));
  }

  /** Edit the picked note on a copy of the score; `change` returns the edit's label. */
  _adjust(change, refocus, moved = null) {
    const score = clone(this.score);
    const hit = this._hit(score, this.picked);
    if (!hit) return null;
    const label = change(hit, score);
    if (!label) return null;
    this._refocus = refocus;
    if (moved) this.picked = moved; // its new address, for the render that follows
    this.onEdit(score, label);
    return hit;
  }

  setLoudness(v) {
    const { bar, inst } = this.picked;
    const hit = this._adjust((x) => {
      if (loudness(x) === v) return null;
      x.velocity = v;
      if (x.ghost && v > GHOST_MAX) delete x.ghost; // past what its mark allows it is no longer one
      if (x.accent && v < ACCENT_MIN) delete x.accent;
      return `Loudness ${v}: ${this._name(inst)} in bar ${bar + 1}`;
    }, '.note-tools input[type="range"]');
    if (hit) this._hear(inst, v);
  }

  changeDrum(target) {
    const { bar, pos, inst } = this.picked;
    if (target === inst) return;
    const hit = this._adjust((x, score) => {
      const m = score.measures[bar];
      x.inst = target;
      delete x.confidence;
      if (this.kit.find((i) => i.id === target)?.family !== "cymbal") delete x.choke;
      // One stroke per drum at a place, and the hi-hat is in one state at a time.
      m.hits = m.hits.filter((y) => y === x || !samePos(y, pos) || !(y.inst === target || (HATS.has(target) && HATS.has(y.inst))));
      m.uncertain = m.uncertain && false;
      this._sort(m);
      return `${this._name(inst)} changed to ${this._name(target)} in bar ${bar + 1}`;
    }, ".note-tools select", { bar, pos, inst: target });
    if (hit) this._hear(target, loudness(hit));
  }

  /** One grid step earlier (-1) or later (1), over the barline if that's where the step is. */
  moveNote(dir) {
    const { bar, pos, inst } = this.picked;
    const here = Frac.parse(pos);
    const steps = this._steps(this.score.measures[bar]);
    const after = steps.filter((s) => s.pos.cmp(here) > 0);
    const before = steps.filter((s) => s.pos.cmp(here) < 0);
    let toBar = bar;
    let target = (dir > 0 ? after[0] : before[before.length - 1])?.pos;
    if (!target) {
      toBar = bar + dir;
      const m = this.score.measures[toBar];
      if (!m) return;
      const next = this._steps(m);
      target = next[dir > 0 ? 0 : next.length - 1].pos;
    }
    const key = target.toString();
    const taken = this.score.measures[toBar].hits.find((x) => samePos(x, key) && (x.inst === inst || (HATS.has(inst) && HATS.has(x.inst))));
    if (taken) { toast(`There's already a ${this._name(taken.inst)} on that step.`, "bad"); return; }
    const hit = this._adjust((x, score) => {
      const from = score.measures[bar], to = score.measures[toBar];
      from.hits.splice(from.hits.indexOf(x), 1);
      x.pos = key;
      delete x.time; delete x.offset_ms; delete x.confidence; // where a person put it, not where it was heard
      to.hits.push(x);
      from.uncertain = from.uncertain && false;
      to.uncertain = to.uncertain && false;
      this._sort(to);
      return `Moved ${this._name(inst)} ${dir > 0 ? "later" : "earlier"} in bar ${toBar + 1}`;
    }, `.note-tools [data-act="${dir > 0 ? "later" : "earlier"}"]`, { bar: toBar, pos: key, inst });
    if (hit) {
      this._hear(inst, loudness(hit));
      if (toBar !== bar) this.onSelect && this.onSelect([toBar, toBar], false);
    }
  }

  deleteNote() {
    const { bar, inst } = this.picked;
    this._adjust((x, score) => {
      const m = score.measures[bar];
      m.hits.splice(m.hits.indexOf(x), 1);
      m.uncertain = m.uncertain && false;
      return `Removed ${this._name(inst)} from bar ${bar + 1}`;
    });
  }

  _sort(m) { m.hits.sort((a, b) => Frac.parse(a.pos).cmp(Frac.parse(b.pos)) || (a.inst < b.inst ? -1 : 1)); }

  go(bar) {
    const n = this.score.measures.length;
    this.first = Math.max(0, Math.min(n - 1, bar));
    this.render(this.score, { flags: this.flags });
    this.onSelect && this.onSelect([this.first, this.first], false);
  }

  _strip(score) {
    const strip = h("div", { class: "bar-strip", role: "toolbar", "aria-label": "Bars" });
    score.measures.forEach((m, i) => {
      const inView = i >= this.first && i < this.first + this.perView;
      const sel = i >= this.selection[0] && i <= this.selection[1];
      const b = h("button", { type: "button", class: [m.section ? "sec" : "", this.flags.has(i) ? "flag" : "", inView || sel ? "sel" : ""].join(" "),
        "data-sec": m.section || null, "data-bar": i, "aria-label": `Bar ${i + 1}${m.section ? ", " + m.section : ""}${this.flags.has(i) ? ", flagged for review" : ""}`,
        "aria-pressed": String(inView) }, String(i + 1));
      b.addEventListener("click", (e) => {
        if (e.shiftKey) { this.selection = [Math.min(this.selection[0], i), Math.max(this.selection[1], i)]; }
        else { this.selection = [i, i]; this.first = Math.max(0, Math.min(i, score.measures.length - this.perView)); }
        this.render(score, { flags: this.flags });
        this.onSelect && this.onSelect(this.selection, true);
      });
      strip.append(b);
    });
    return strip;
  }

  _grid(score) {
    this.cells.clear(); this.cols.clear();
    const bars = [];
    for (let i = this.first; i < Math.min(score.measures.length, this.first + this.perView); i++) {
      const m = score.measures[i];
      const per = this.res === "auto" ? gridSteps(m) : gridSteps(m, this.res);
      bars.push({ i, m, steps: stepPositions(m, per) });
    }
    const lanes = this.lanes(score);
    const total = bars.reduce((a, b) => a + b.steps.length, 0);
    const g = h("div", { class: "dgrid", role: "grid", "aria-label": "Beat grid", style: { "grid-template-columns": `max-content repeat(${total}, 26px)` } });
    // header row: beat counts
    g.append(h("div", { class: "lane-head", role: "columnheader" }, h("span", { class: "muted tiny" }, "Bar")));
    for (const b of bars) {
      let beat = 0;
      b.steps.forEach((s, k) => {
        if (s.beatStart) beat += 1;
        const label = k === 0 ? String(b.i + 1) : s.beatStart ? String(beat) : s.n === 4 && s.index === 2 ? "&" : s.n === 3 && s.index === 1 ? "" : "";
        g.append(h("div", { class: `col-head${s.beatStart ? " beat" : ""}${k === 0 ? " bar" : ""}`, role: "columnheader" }, label));
      });
    }
    lanes.forEach((lane, li) => {
      const color = COLOR(lane.id, lane.family);
      const head = h("div", { class: "lane-head", role: "rowheader" },
        h("span", { class: "swatch", style: { background: color } }), lane.name,
        h("span", { class: "ms" },
          this._ms("m", lane, "Mute"), this._ms("s", lane, "Solo")));
      g.append(head);
      for (const b of bars) {
        const byPos = new Map(b.m.hits.filter((x) => x.inst === lane.id).map((x) => [Frac.parse(x.pos).toString(), x]));
        b.steps.forEach((s, k) => {
          const key = s.pos.toString();
          const hit = byPos.get(key);
          const picked = hit && this.picked && this.picked.bar === b.i && this.picked.pos === key && this.picked.inst === lane.id;
          const cls = ["cell", s.beatStart ? "beat" : "", k === 0 ? "barstart" : "", hit ? "on" : "", picked ? "picked" : "",
            hit && hit.accent ? "accent" : "", hit && hit.ghost ? "ghost" : "", hit && hit.flam ? "flam" : "", hit && hit.drag ? "drag" : ""].join(" ");
          const cell = h("button", { type: "button", class: cls, role: "gridcell", tabindex: li === 0 && k === 0 && b.i === this.first ? "0" : "-1",
            style: { "--lane": color, ...(hit ? { "--v": (loudness(hit) / 127).toFixed(3) } : {}) }, "data-bar": b.i, "data-pos": key, "data-inst": lane.id,
            "aria-label": `${lane.name}, bar ${b.i + 1}, ${this._count(b.steps, k)}${hit ? `, ${this._describe(hit)}, loudness ${loudness(hit)}` : ", empty"}`,
            "aria-pressed": String(!!hit) });
          cell.addEventListener("click", () => (this.tool === "adjust" ? this.pick(b.i, key, lane.id, hit) : this.toggle(b.i, s.pos, lane.id, cell)));
          cell.addEventListener("keydown", (e) => this._key(e, cell));
          this.cells.set(`${b.i}|${key}|${lane.id}`, cell);
          const ck = `${b.i}|${key}`;
          if (!this.cols.has(ck)) this.cols.set(ck, []);
          this.cols.get(ck).push(cell);
          g.append(cell);
        });
      }
    });
    return h("div", { class: "grid-scroll" }, g);
  }

  _ms(kind, lane, label) {
    const set = kind === "m" ? this.player.muted : this.player.soloed;
    const b = h("button", { type: "button", class: kind, "aria-pressed": String(set.has(lane.id)), "aria-label": `${label} ${lane.name}`, title: `${label} ${lane.name}` }, kind.toUpperCase());
    b.addEventListener("click", (e) => { e.stopPropagation(); if (set.has(lane.id)) set.delete(lane.id); else set.add(lane.id); b.setAttribute("aria-pressed", String(set.has(lane.id))); });
    return b;
  }

  _count(steps, k) {
    let beat = 0;
    for (let j = 0; j <= k; j++) if (steps[j].beatStart) beat += 1;
    const s = steps[k];
    if (s.index === 0) return `beat ${beat}`;
    if (s.n === 4) return `beat ${beat} ${["", "e", "&", "a"][s.index]}`;
    if (s.n === 2) return `beat ${beat} &`;
    if (s.n === 3) return `beat ${beat} triplet ${s.index + 1}`;
    return `beat ${beat}, ${s.index + 1}/${s.n}`;
  }

  _describe(hit) {
    return [hit.accent && "accent", hit.ghost && "ghost note", hit.flam && "flam", hit.drag && "drag", "hit"].filter(Boolean)[0];
  }

  toggle(bar, pos, inst, cell) {
    const score = clone(this.score);
    const m = score.measures[bar];
    const key = pos.toString();
    const idx = m.hits.findIndex((x) => x.inst === inst && Frac.parse(x.pos).toString() === key);
    const existing = idx >= 0 ? m.hits[idx] : null;
    let label;
    const name = this.kit.find((i) => i.id === inst)?.name || inst;
    const want = this.tool;
    if (want === "erase" || (existing && (want === "hit" && !existing.accent && !existing.ghost && !existing.flam || existing[want]))) {
      if (!existing) return;
      m.hits.splice(idx, 1);
      label = `Removed ${name} from bar ${bar + 1}`;
    } else {
      const hit = existing || { pos: key, inst };
      delete hit.accent; delete hit.ghost; delete hit.flam; delete hit.drag;
      hit.velocity = DEFAULT_VEL[inst] || 92;
      if (want === "accent") { hit.accent = true; hit.velocity = 120; }
      if (want === "ghost") { hit.ghost = true; hit.velocity = 36; }
      if (want === "flam") hit.flam = true;
      if (!existing) m.hits.push(hit);
      if (HATS.has(inst)) m.hits = m.hits.filter((x) => x === hit || !(HATS.has(x.inst) && Frac.parse(x.pos).toString() === key));
      label = `${want === "hit" ? "Added" : want[0].toUpperCase() + want.slice(1)} ${name} in bar ${bar + 1}`;
    }
    this._sort(m);
    m.uncertain = m.uncertain && false;
    this.onEdit(score, label, { bar, pos: key, inst });
    const again = this.cells.get(`${bar}|${key}|${inst}`);
    if (again) { again.classList.add("added"); setTimeout(() => again.classList.remove("added"), 260); again.focus(); }
  }

  copyBar() {
    const src = this.selection[0];
    const n = this.score.measures.length;
    if (src >= n - 1) return;
    const score = clone(this.score);
    if (score.measures[src + 1].time !== score.measures[src].time) return;
    score.measures[src + 1].hits = clone(score.measures[src]).hits;
    this.onEdit(score, `Copied bar ${src + 1} to bar ${src + 2}`);
  }

  clearBar() {
    const b = this.selection[0];
    const score = clone(this.score);
    if (!score.measures[b].hits.length) return;
    score.measures[b].hits = [];
    this.onEdit(score, `Cleared bar ${b + 1}`);
  }

  _key(e, cell) {
    const all = [...this.root.querySelectorAll(".cell")];
    const lanes = this.lanes(this.score).length;
    const per = all.length / lanes;
    const i = all.indexOf(cell);
    let j = null;
    if (e.key === "ArrowRight") j = i + 1;
    else if (e.key === "ArrowLeft") j = i - 1;
    else if (e.key === "ArrowDown") j = i + per;
    else if (e.key === "ArrowUp") j = i - per;
    if (j === null) return;
    e.preventDefault();
    if (j >= 0 && j < all.length) { cell.tabIndex = -1; all[j].tabIndex = 0; all[j].focus(); }
  }

  /** Playback position: highlight the step being played. */
  playhead(bar, posFrac) {
    for (const c of this.root.querySelectorAll(".cell.now")) c.classList.remove("now");
    if (bar < this.first || bar >= this.first + this.perView) return;
    let best = null;
    for (const [k, cells] of this.cols) {
      const [b, p] = k.split("|");
      if (Number(b) !== bar) continue;
      const v = Frac.parse(p).value;
      if (v <= posFrac + 1e-9 && (best === null || v > best.v)) best = { v, cells };
    }
    if (best) for (const c of best.cells) c.classList.add("now");
  }

  flash(e) {
    const c = this.cells.get(`${e.bar}|${Frac.parse(e.pos).toString()}|${e.inst}`);
    if (!c) return;
    c.classList.add("hit-now");
    setTimeout(() => c.classList.remove("hit-now"), 110);
  }

  setSelection(sel) { this.selection = sel; }
}
