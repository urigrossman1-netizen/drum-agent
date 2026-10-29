// The chart workspace: notation, grid, playback, editing, versions and export, all on one
// working score. A saved chart version is immutable; edits make a working score that is
// re-engraved for the screen as you go, kept as a draft on the server (and in this browser),
// and saved as the next version when you choose.

import { h, icon, api, toast, dialog, prefs, menu, statusBadge, ago, reducedMotion } from "./ui.js";
import { Frac, clone, sameScore, barTimes, hitCount } from "./score.js";
import { GridEditor } from "./grid.js";
import { Player } from "./player.js";

export const player = new Player();
let current = null; // the open workspace, for keyboard shortcuts and navigation guards
// Read-only handles for automated browser tests: what the player scheduled, and the working score.
window.__drumAgent = { player, get score() { return current && current.score; }, get workspace() { return current; } };

export function leaveGuard() {
  return current && current.pendingDraft ? "Your latest edits are still being saved." : null;
}

export function closeWorkspace() {
  if (current) current.destroy();
  current = null;
}

export async function showWorkspace(root, chartId, app) {
  closeWorkspace();
  root.replaceChildren(h("div", { class: "stack" }, h("div", { class: "skeleton", style: { height: "56px" } }),
    h("div", { class: "skeleton", style: { height: "64px" } }), h("div", { class: "skeleton", style: { height: "520px" } })));
  let chart, project, saved;
  try {
    chart = await api(`/api/charts/${chartId}`);
    [project, saved] = await Promise.all([api(`/api/projects/${chart.song_id}`), api(`/api/charts/${chartId}/files/chart.json`)]);
  } catch (e) {
    root.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "This chart could not be opened"), e.message,
      h("div", { style: { "margin-top": "14px" } }, h("a", { class: "btn", href: "#/library" }, "Go to My Charts"))));
    return;
  }
  current = new Workspace(root, { chart, project, saved, app });
  current.mount();
}

class Workspace {
  constructor(root, { chart, project, saved, app }) {
    Object.assign(this, { root, chart, project, app });
    this.saved = saved;
    this.score = clone(saved);
    this.undoStack = [];
    this.redoStack = [];
    this.selection = [0, 0];
    this.tab = prefs.get("ws-tab", "both");
    this.zoom = prefs.get("zoom", null);
    this.follow = prefs.get("follow", true);
    this.view = chart.view;
    this.viewSrc = { kind: "chart", id: chart.id };
    this.validation = chart.validation;
    this.previewSeq = 0;
    this.draftTimer = null;
    this.pendingDraft = false;
    this.draftState = "saved";
    this.kind = project.kind === "beat" || saved.chart_type === "original_beat" ? "beat" : "song";
    this.generated = !!(saved.analysis && saved.analysis.generator);
    this._keys = (e) => this.onKey(e);
    document.addEventListener("keydown", this._keys);
    player.stop(true);
    player.kit = prefs.get("kit", "acoustic");
    player.samplesAvailable = !!app.kitInfo.samples;
    if (!player.samplesAvailable) player.kit = "electronic";
    player.metronome = prefs.get("metronome", false);
    player.countIn = prefs.get("countin", false);
    player.speed = 1;
    player.loop = false;
    player.range = null;
    player.setVolume(prefs.get("volume", 0.85));
    player.onPosition = (bar, sec) => this.onPosition(bar, sec);
    player.onState = (s) => this.onPlayState(s);
    player.onHit = (e) => this.onHit(e);
  }

  destroy() {
    player.stop(true);
    player.onPosition = player.onState = player.onHit = null;
    document.removeEventListener("keydown", this._keys);
    clearTimeout(this.previewTimer);
    clearTimeout(this.draftTimer);
    if (this.pendingDraft) this.saveDraft(true);
  }

  get dirty() { return !sameScore(this.score, this.saved); }

  // ---- layout --------------------------------------------------------------------
  mount() {
    this.headEl = h("div", { class: "ws-head" });
    this.bannerEl = h("div", {});
    this.transportEl = h("div", { class: "transport", role: "toolbar", "aria-label": "Playback" });
    this.pagesEl = h("div", { class: "pages" });
    this.engravingEl = h("span", { class: "engraving", hidden: true, role: "status" }, h("span", { class: "spinner" }), "Engraving…");
    this.notationEl = h("section", { class: "notation", "aria-label": "Notation" },
      h("div", { class: "notation-tools" },
        h("div", { class: "tabs", role: "tablist", "aria-label": "View" },
          ...[["notation", "Notation", "score"], ["grid", "Grid", "grid"], ["both", "Both", "split"]].map(([k, label, ic]) =>
            h("button", { role: "tab", type: "button", "aria-selected": String(this.tab === k), onclick: () => this.setTab(k) }, icon(ic), label))),
        h("span", { class: "spacer" }),
        h("button", { class: "btn sm icon-only ghost", type: "button", "aria-label": "Zoom out", onclick: () => this.setZoom(this.zoom / 1.15) }, icon("zoomOut")),
        h("span", { class: "small muted num", id: "zoom-label" }, `${Math.round(this.zoom * 100)}%`),
        h("button", { class: "btn sm icon-only ghost", type: "button", "aria-label": "Zoom in", onclick: () => this.setZoom(this.zoom * 1.15) }, icon("zoomIn")),
        h("button", { class: "btn sm ghost", type: "button", onclick: () => this.setZoom(this.fitZoom()) }, "Fit")),
      this.pagesEl);
    this.gridEl = h("section", { class: "gridpanel", "aria-label": "Beat grid editor" });
    this.sideEl = h("aside", { class: "ws-side", "aria-label": "Chart tools" });
    this.root.replaceChildren(this.headEl, this.bannerEl, this.transportEl,
      h("div", { class: "ws-body" }, h("div", { class: "ws-main" }, this.notationEl, this.gridEl), this.sideEl));
    this.grid = new GridEditor(this.gridEl, { kit: this.app.kitInfo.instruments, player,
      onEdit: (score, label) => this.commit(score, label),
      onSelect: (sel, fromStrip) => { this.select(sel, fromStrip); } });
    this.restoreDraft();
    this.renderHead();
    this.renderTransport();
    this.renderPages(true);
    this.renderGrid();
    this.renderSide();
    this.applyTab();
    this.setZoom(window.innerWidth < 900 ? this.fitZoom() : this.zoom ?? 1);
    if (this.dirty) this.schedulePreview(0);
  }

  renderHead() {
    const kindBadge = this.kind === "beat" ? h("span", { class: "badge ai plain" }, "Original beat")
      : this.chart.origin === "library_chart" ? h("span", { class: "badge plain" }, "Library chart")
      : h("span", { class: "badge busy plain" }, this.chart.source_id ? "Transcription" : "Chart");
    const title = h("h1", { title: this.project.title }, this.project.title);
    const rename = h("button", { class: "btn sm icon-only ghost", type: "button", "aria-label": "Rename", onclick: () => this.rename() }, icon("edit"));
    this.saveStateEl = h("span", { class: "save-state", role: "status", "aria-live": "polite" });
    const exportBtn = h("button", { class: "btn", type: "button" }, icon("download"), "Export");
    menu(exportBtn, () => [
      { label: "Download PDF", icon: "download", onClick: () => this.exportFile("chart.pdf") },
      { label: "Download MusicXML", icon: "download", onClick: () => this.exportFile("chart.musicxml") },
      { label: "Download MIDI", icon: "download", onClick: () => this.exportFile("chart.mid") },
      { label: "Download chart data (JSON)", icon: "download", onClick: () => this.exportFile("chart.json") },
    ]);
    this.undoBtn = h("button", { class: "btn icon-only ghost", type: "button", "aria-label": "Undo", title: "Undo (Ctrl+Z)", onclick: () => this.undo() }, icon("undo"));
    this.redoBtn = h("button", { class: "btn icon-only ghost", type: "button", "aria-label": "Redo", title: "Redo (Ctrl+Shift+Z)", onclick: () => this.redo() }, icon("redo"));
    this.saveBtn = h("button", { class: "btn primary", type: "button", onclick: () => this.saveVersion() }, icon("save"), "Save version");
    this.headEl.replaceChildren(
      h("a", { class: "btn icon-only ghost", href: this.kind === "beat" ? "#/library" : `#/song/${this.project.id}`, "aria-label": "Back" }, icon("arrowLeft")),
      h("div", { class: "ws-title" }, title, rename, kindBadge,
        h("span", { class: "badge plain num" }, `v${this.chart.version}`), statusBadge(this.chart.status, this.kind),
        this.kind !== "beat" && this.chart.shareable === false ? h("span", { class: "badge warn plain",
          title: "Transcribed for your own practice: play along and print it for yourself. Posting it publicly needs the music publisher's permission." }, "Personal practice") : null),
      this.saveStateEl, this.undoBtn, this.redoBtn, this.saveBtn, h("div", { class: "menu" }, exportBtn),
      h("button", { class: "btn", type: "button", onclick: () => this.print() }, icon("print"), "Print"));
    this.updateSaveState();
  }

  updateSaveState() {
    if (!this.saveStateEl) return;
    const el = this.saveStateEl;
    el.className = "save-state";
    if (!this.dirty) { el.replaceChildren(icon("check"), `Saved as version ${this.chart.version}`); }
    else if (this.draftState === "saving") { el.classList.add("dirty"); el.replaceChildren(h("span", { class: "spinner" }), "Saving draft…"); }
    else if (this.draftState === "error") { el.classList.add("error"); el.replaceChildren(icon("alert"), "Draft not saved to the server (kept in this browser)"); }
    else { el.classList.add("dirty"); el.replaceChildren(icon("edit"), "Unsaved changes · draft kept"); }
    this.undoBtn.disabled = !this.undoStack.length;
    this.redoBtn.disabled = !this.redoStack.length;
  }

  renderTransport() {
    const t = this.transportEl;
    this.playBtn = h("button", { class: "btn primary play", type: "button", "aria-label": "Play (Space)", title: "Play / pause (Space)", onclick: () => this.togglePlay() }, icon("play", "fill"));
    this.posEl = h("span", { class: "position", "aria-live": "off" }, "Bar 1 · 1");
    const toggle = (key, label, ic, get, set) => {
      const b = h("button", { class: "btn sm", type: "button", "aria-pressed": String(get()), title: label, "aria-label": label }, icon(ic), h("span", { class: "lbl" }, label));
      b.addEventListener("click", () => { set(!get()); b.setAttribute("aria-pressed", String(get())); prefs.set(key, get()); if (player.state === "playing") this.restartPlayback(); });
      return b;
    };
    const tempo = this.score.measures[0].tempo || 120;
    this.bpmInput = h("input", { class: "input bpm", type: "number", min: 30, max: 300, step: 1, value: Math.round(tempo), "aria-label": "Tempo (BPM)" });
    this.bpmInput.addEventListener("change", () => this.setTempo(Number(this.bpmInput.value)));
    const speed = h("input", { type: "range", min: 50, max: 150, step: 5, value: 100, "aria-label": "Practice speed" });
    const speedLabel = h("span", { class: "small muted num" }, "100%");
    speed.addEventListener("input", () => { player.speed = speed.value / 100; speedLabel.textContent = `${speed.value}%`; });
    speed.addEventListener("change", () => { if (player.state === "playing") this.restartPlayback(); });
    const vol = h("input", { type: "range", min: 0, max: 100, value: Math.round(player.volume * 100), "aria-label": "Volume" });
    vol.addEventListener("input", () => { player.setVolume(vol.value / 100); prefs.set("volume", vol.value / 100); });
    const kit = h("select", { class: "select", style: { width: "136px", "min-height": "34px" }, "aria-label": "Drum sounds" },
      h("option", { value: "acoustic", selected: player.kit === "acoustic", disabled: !player.samplesAvailable }, player.samplesAvailable ? "Acoustic kit" : "Acoustic (unavailable)"),
      h("option", { value: "electronic", selected: player.kit === "electronic" }, "Electronic kit"));
    kit.addEventListener("change", () => { player.kit = kit.value; prefs.set("kit", kit.value); if (player.state === "playing") this.restartPlayback(); });
    this.selOnly = false;
    const selBtn = h("button", { class: "btn sm", type: "button", "aria-pressed": "false", title: "Play only the selected bars", "aria-label": "Play only the selected bars" }, icon("layers"), h("span", { class: "lbl" }, "Selection"));
    selBtn.addEventListener("click", () => { this.selOnly = !this.selOnly; selBtn.setAttribute("aria-pressed", String(this.selOnly)); if (player.state === "playing") this.restartPlayback(); });
    t.replaceChildren(
      h("div", { class: "group" }, this.playBtn,
        h("button", { class: "btn icon-only", type: "button", "aria-label": "Stop", onclick: () => { player.stop(); this.onPosition(this.selection[0], 0); } }, icon("stop")),
        this.posEl),
      h("div", { class: "group" },
        toggle("loop", "Loop", "loop", () => player.loop, (v) => (player.loop = v)), selBtn,
        toggle("countin", "Count-in", "count", () => player.countIn, (v) => (player.countIn = v)),
        toggle("metronome", "Click", "metronome", () => player.metronome, (v) => (player.metronome = v))),
      h("div", { class: "group" }, h("label", { class: "mini" }, "BPM", this.bpmInput)),
      h("div", { class: "group optional" }, h("label", { class: "mini" }, "Speed", speed, speedLabel)),
      h("div", { class: "group optional" }, h("label", { class: "mini" }, icon("volume"), vol)),
      h("div", { class: "group" }, kit,
        toggle("follow", "Follow", "score", () => this.follow, (v) => (this.follow = v))),
      this.engravingEl);
  }

  // ---- notation ------------------------------------------------------------------
  pageUrl(file) {
    return this.viewSrc.kind === "chart" ? `/api/charts/${this.viewSrc.id}/files/${file}` : `/api/previews/${this.viewSrc.key}/${file}`;
  }

  async renderPages(first = false) {
    const view = this.view;
    const pages = view.pages.map((p, k) => {
      const img = h("img", { src: this.pageUrl(p.file), alt: `Page ${k + 1} of ${view.pages.length} of ${this.project.title}`, draggable: "false" });
      return h("div", { class: "page", "data-page": k, style: { "--i": k } }, img);
    });
    await Promise.all(pages.map((p) => new Promise((res) => { const img = p.querySelector("img"); if (img.complete) res(); else { img.onload = res; img.onerror = res; } })));
    this.boxes = [];
    this.barToBox = new Map();
    view.bars.forEach((b, i) => {
      if (!b.box) return;
      const el = h("div", { class: "box" + (b.uncertain ? " flag" : ""), "data-bar": i, role: "button", tabindex: "-1",
        title: `Bar ${b.printed}${b.uncertain ? " — flagged for review" : ""}`, "aria-label": `Bar ${b.printed}` });
      Object.assign(el.style, { left: `${100 * b.box.x0}%`, width: `${100 * (b.box.x1 - b.box.x0)}%`, top: `${100 * b.box.y0}%`, height: `${100 * (b.box.y1 - b.box.y0)}%` });
      el.addEventListener("click", (e) => {
        const sb = b.score_bars[0] - 1;
        this.select(e.shiftKey ? [Math.min(this.selection[0], sb), Math.max(this.selection[1], sb)] : [sb, sb], true);
      });
      pages[b.box.page].append(el);
      this.boxes[i] = el;
      for (const sb of b.score_bars) if (!this.barToBox.has(sb - 1)) this.barToBox.set(sb - 1, i);
    });
    this.playheadEl = h("div", { class: "playhead", hidden: true });
    this.pagesEl.classList.remove("stale", "reveal");
    this.pagesEl.replaceChildren(...pages);
    if (first && !reducedMotion()) { this.pagesEl.classList.add("reveal"); setTimeout(() => this.pagesEl.classList.remove("reveal"), 900); }
    this.markSelection();
  }

  fitZoom() {
    const w = this.pagesEl.clientWidth || this.root.clientWidth || 816;
    return Math.max(0.35, Math.min(1.6, (w - 8) / 816));
  }

  setZoom(z) {
    this.zoom = Math.max(0.35, Math.min(2.5, z));
    prefs.set("zoom", this.zoom);
    this.root.style.setProperty("--zoom", this.zoom.toFixed(3));
    const l = this.root.querySelector("#zoom-label");
    if (l) l.textContent = `${Math.round(this.zoom * 100)}%`;
  }

  setTab(k) { this.tab = k; prefs.set("ws-tab", k); this.applyTab(); }
  applyTab() {
    for (const b of this.notationEl.querySelectorAll('[role="tab"]')) b.setAttribute("aria-selected", String(b.textContent.toLowerCase() === this.tab));
    this.pagesEl.hidden = this.tab === "grid";
    this.gridEl.hidden = this.tab === "notation";
  }

  markSelection() {
    for (const el of this.boxes || []) if (el) el.classList.remove("selected");
    for (let b = this.selection[0]; b <= this.selection[1]; b++) {
      const i = this.barToBox?.get(b);
      if (i !== undefined && this.boxes[i]) this.boxes[i].classList.add("selected");
    }
  }

  select(sel, scrollNotation) {
    this.selection = sel;
    this.grid.setSelection(sel);
    this.grid.render(this.score, { flags: this.flags(), focusBar: sel[0] });
    this.markSelection();
    if (scrollNotation) {
      const i = this.barToBox.get(sel[0]);
      if (i !== undefined && this.boxes[i] && this.tab !== "both") this.boxes[i].scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
    }
    this.renderReview();
    if (!player.state || player.state === "stopped") this.onPosition(sel[0], 0, true);
  }

  range() { const out = []; for (let b = this.selection[0]; b <= this.selection[1]; b++) out.push(b + 1); return out; }

  flags() { return new Set(this.score.measures.map((m, i) => (m.uncertain ? i : -1)).filter((i) => i >= 0)); }

  renderGrid() { this.grid.setSelection(this.selection); this.grid.render(this.score, { flags: this.flags(), focusBar: this.selection[0] }); }

  // ---- editing -------------------------------------------------------------------
  commit(score, label) {
    this.undoStack.push({ score: this.score, label });
    if (this.undoStack.length > 200) this.undoStack.shift();
    this.redoStack = [];
    this.lastLabel = label;
    this.apply(score);
  }

  apply(score) {
    this.score = score;
    const tempo = score.measures[0].tempo || 120;
    if (this.bpmInput && Number(this.bpmInput.value) !== Math.round(tempo)) this.bpmInput.value = Math.round(tempo);
    if (this.selection[1] >= score.measures.length) this.selection = [0, 0];
    this.renderGrid();
    this.renderSections();
    this.renderReview();
    this.schedulePreview();
    this.scheduleDraft();
    this.updateSaveState();
    if (player.state === "playing") this.restartPlayback();
  }

  undo() { const e = this.undoStack.pop(); if (!e) return; this.redoStack.push({ score: this.score, label: e.label }); this.apply(e.score); toast(`Undid: ${e.label}`, "info", 2200); }
  redo() { const e = this.redoStack.pop(); if (!e) return; this.undoStack.push({ score: this.score, label: e.label }); this.apply(e.score); toast(`Redid: ${e.label}`, "info", 2200); }

  setTempo(bpm) {
    if (!(bpm >= 30 && bpm <= 300)) { toast("The tempo must be between 30 and 300 BPM", "bad"); this.bpmInput.value = Math.round(this.score.measures[0].tempo || 120); return; }
    const s = clone(this.score);
    s.measures[0].tempo = bpm;
    if (s.analysis?.generator?.spec) s.analysis.generator.spec.bpm = bpm;
    this.commit(s, `Tempo ${bpm} BPM`);
  }

  schedulePreview(delay = 350) {
    clearTimeout(this.previewTimer);
    this.pagesEl.classList.add("stale");
    this.engravingEl.hidden = false;
    this.previewTimer = setTimeout(() => this.preview(), delay);
  }

  async preview() {
    const seq = ++this.previewSeq;
    if (this.previewAbort) this.previewAbort.abort();
    this.previewAbort = new AbortController();
    if (!this.dirty) {
      this.view = this.chart.view; this.viewSrc = { kind: "chart", id: this.chart.id }; this.validation = this.chart.validation;
      await this.renderPages();
      this.engravingEl.hidden = true; this.renderChecks(); this.setBanner(null);
      return;
    }
    try {
      const r = await api("/api/preview", { json: { score: this.score }, signal: this.previewAbort.signal });
      if (seq !== this.previewSeq) return;
      this.view = r.view; this.viewSrc = { kind: "preview", key: r.key }; this.validation = r.validation;
      await this.renderPages();
      this.setBanner(null);
    } catch (e) {
      if (e.name === "AbortError" || seq !== this.previewSeq) return;
      this.setBanner("bad", `This version can't be engraved: ${e.message}`);
    } finally {
      if (seq === this.previewSeq) { this.engravingEl.hidden = true; this.renderChecks(); }
    }
  }

  setBanner(kind, text, actions = []) {
    if (!kind) { this.bannerEl.replaceChildren(); return; }
    this.bannerEl.replaceChildren(h("div", { class: `banner ${kind === "info" ? "info" : ""}`, role: kind === "bad" ? "alert" : "status" },
      icon(kind === "bad" ? "alert" : "info"), h("span", {}, text), h("span", { class: "spacer" }), ...actions));
  }

  scheduleDraft() {
    clearTimeout(this.draftTimer);
    this.pendingDraft = this.dirty;
    const key = `draft:${this.project.id}`;
    if (this.dirty) prefs.set(key, { score: this.score, base_chart_id: this.chart.id, saved_at: Date.now() / 1000 });
    else prefs.remove(key);
    this.draftTimer = setTimeout(() => this.saveDraft(), 1200);
  }

  async saveDraft(sync = false) {
    const pid = this.project.id;
    try {
      this.draftState = "saving"; this.updateSaveState();
      if (this.dirty) await api(`/api/projects/${pid}/draft`, { method: "PUT", json: { score: this.score, base_chart_id: this.chart.id } });
      else await api(`/api/projects/${pid}/draft`, { method: "DELETE" });
      this.draftState = "saved";
      this.pendingDraft = false;
    } catch (e) {
      this.draftState = "error";
    }
    if (!sync) this.updateSaveState();
  }

  restoreDraft() {
    const server = this.project.draft;
    const local = prefs.get(`draft:${this.project.id}`, null);
    const pick = [server, local].filter((d) => d && d.base_chart_id === this.chart.id && d.score)
      .sort((a, b) => (b.saved_at || 0) - (a.saved_at || 0))[0];
    if (!pick || sameScore(pick.score, this.saved)) return;
    this.score = pick.score;
    this.setBanner("info", `Restored your unsaved changes from ${ago(pick.saved_at)}${pick === local && pick !== server ? " (kept in this browser)" : ""}.`,
      [h("button", { class: "btn sm", type: "button", onclick: async () => {
        const ok = await dialog({ title: "Discard unsaved changes?", body: `The chart goes back to version ${this.chart.version}.`, confirm: "Discard", danger: true });
        if (!ok) return;
        this.undoStack = []; this.redoStack = [];
        this.apply(clone(this.saved));
        this.setBanner(null);
      } }, "Discard changes")]);
  }

  async saveVersion(note) {
    if (!this.dirty) { toast(`Already saved as version ${this.chart.version}`, "info", 2000); return this.chart; }
    if (this.validation && !this.validation.ok) {
      toast("Fix the problems listed under Checks before saving.", "bad");
      return null;
    }
    this.saveBtn.disabled = true;
    this.saveBtn.replaceChildren(h("span", { class: "spinner" }), "Saving…");
    try {
      const c = await api(`/api/projects/${this.project.id}/versions`, { json: { score: this.score, note: note || this.lastLabel || "Edited", base_chart_id: this.chart.id } });
      prefs.remove(`draft:${this.project.id}`);
      toast(`Saved as version ${c.version}`);
      this.pendingDraft = false;
      history.replaceState(null, "", `#/chart/${c.id}`);
      await this.reloadChart(c.id);
      return this.chart;
    } catch (e) {
      toast(`Not saved: ${e.message}. Your edits are still here.`, "bad", 7000);
      return null;
    } finally {
      this.saveBtn.disabled = false;
      this.saveBtn.replaceChildren(icon("save"), "Save version");
    }
  }

  async reloadChart(id) {
    const [chart, saved] = await Promise.all([api(`/api/charts/${id}`), api(`/api/charts/${id}/files/chart.json`)]);
    this.project = await api(`/api/projects/${chart.song_id}`);
    this.chart = chart; this.saved = saved;
    this.score = clone(saved);
    this.view = chart.view; this.viewSrc = { kind: "chart", id: chart.id }; this.validation = chart.validation;
    this.generated = !!(saved.analysis && saved.analysis.generator);
    this.renderHead();
    await this.renderPages();
    this.renderGrid();
    this.renderSide();
    this.setBanner(null);
    this.engravingEl.hidden = true;
  }

  async exportFile(name) {
    let c = this.chart;
    if (this.dirty) {
      c = await this.saveVersion("Saved for export");
      if (!c) return;
    }
    const a = h("a", { href: `/api/charts/${c.id}/files/${name}?download=1`, download: "" });
    document.body.append(a); a.click(); a.remove();
  }

  async print() {
    if (this.dirty) { const c = await this.saveVersion("Saved for printing"); if (!c) return; }
    if (this.tab === "grid") this.setTab("both");
    await this.renderPages();
    window.print();
  }

  async rename() {
    const title = await dialog({ title: "Rename", confirm: "Rename", input: { value: this.project.title, label: "Title" } });
    if (!title) return;
    try {
      this.project = { ...this.project, ...(await api(`/api/projects/${this.project.id}`, { method: "PATCH", json: { title } })) };
      this.renderHead();
      toast("Renamed. The new title is printed from the next saved version.");
    } catch (e) { toast(e.message, "bad"); }
  }

  // ---- playback ------------------------------------------------------------------
  async togglePlay() {
    if (player.state === "playing") { player.stop(); return; }
    try {
      player.range = this.selOnly ? [this.selection[0], this.selection[1]] : null;
      await player.play(this.score, this.selOnly ? null : this.selection[0]);
    } catch (e) {
      toast(e.message || "Playback could not start", "bad");
    }
  }

  restartPlayback() {
    const bar = this.playBar ?? this.selection[0];
    player.range = this.selOnly ? [this.selection[0], this.selection[1]] : null;
    player.play(this.score, this.selOnly ? null : bar).catch((e) => toast(e.message, "bad"));
  }

  onPlayState(s) {
    this.playBtn.replaceChildren(icon(s === "playing" ? "pause" : "play", "fill"));
    this.playBtn.setAttribute("aria-label", s === "playing" ? "Pause (Space)" : "Play (Space)");
    this.posEl.classList.toggle("playing", s === "playing");
    if (s !== "playing") { if (this.playheadEl) this.playheadEl.hidden = true; for (const el of this.boxes || []) el && el.classList.remove("current"); this.grid.playhead(-1, 0); this.playBar = null; }
  }

  onPosition(bar, sec, idle = false) {
    const times = this._times && this._timesFor === this.score ? this._times : (this._times = barTimes(this.score, player.speed), this._timesFor = this.score, this._times);
    const tempo = times[bar]?.tempo || 120;
    const pos = (sec * tempo) / 240; // whole notes into the bar
    const m = this.score.measures[bar];
    if (!m) return;
    const [num, den] = m.time.split("/").map(Number);
    const beatLen = den === 8 && num % 3 === 0 ? 3 / 8 : 1 / den;
    this.posEl.textContent = `Bar ${bar + 1} · ${Math.floor(pos / beatLen + 1e-6) + 1}`;
    if (idle) return;
    if (bar !== this.playBar) {
      this.playBar = bar;
      for (const el of this.boxes || []) el && el.classList.remove("current");
      const i = this.barToBox.get(bar);
      const el = i !== undefined ? this.boxes[i] : null;
      if (el) {
        el.classList.add("current");
        if (this.follow && this.tab !== "grid") {
          const r = el.getBoundingClientRect();
          if (r.top < 140 || r.bottom > innerHeight - 20) el.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
        }
        el.parentElement.append(this.playheadEl);
      }
      if (this.follow && (bar < this.grid.first || bar >= this.grid.first + this.grid.perView)) { this.grid.first = bar; this.renderGrid(); }
    }
    this.grid.playhead(bar, pos);
    const i = this.barToBox.get(bar);
    const b = i !== undefined ? this.view.bars[i] : null;
    if (b && b.box && this.playheadEl) {
      const x = this.noteX(b, pos);
      Object.assign(this.playheadEl.style, { left: `${x * 100}%`, top: `${b.box.y0 * 100}%`, height: `${(b.box.y1 - b.box.y0) * 100}%` });
      this.playheadEl.hidden = false;
    }
  }

  noteX(b, pos) {
    const notes = (b.box.notes || []).map((n) => ({ p: Frac.parse(n.pos).value, x: n.x })).sort((a, c) => a.p - c.p);
    const m = this.score.measures[b.score_bars[0] - 1];
    const len = m ? Frac.parse(m.length || m.time).value : 1;
    const pts = [{ p: 0, x: notes.length ? Math.min(notes[0].x, b.box.x0 + 0.01) : b.box.x0 + 0.01 }, ...notes, { p: len, x: b.box.x1 - 0.004 }];
    for (let k = 0; k < pts.length - 1; k++) {
      if (pos >= pts[k].p && pos <= pts[k + 1].p) {
        const f = (pos - pts[k].p) / Math.max(1e-9, pts[k + 1].p - pts[k].p);
        return pts[k].x + f * (pts[k + 1].x - pts[k].x);
      }
    }
    return b.box.x1;
  }

  onHit(e) {
    if (e.grace) return;
    this.grid.flash(e);
    if (this.tab === "grid") return;
    const i = this.barToBox.get(e.bar);
    const b = i !== undefined ? this.view.bars[i] : null;
    if (!b || !b.box || !this.boxes[i]) return;
    const note = (b.box.notes || []).find((n) => Frac.parse(n.pos).value === Frac.parse(e.pos).value);
    if (!note) return;
    const key = `${e.bar}|${e.pos}`;
    if (this._lastGlow === key) return;
    this._lastGlow = key;
    const glow = h("div", { class: "note-glow" });
    Object.assign(glow.style, { left: `${note.x * 100}%`, top: `${b.box.y0 * 100}%`, height: `${(b.box.y1 - b.box.y0) * 100}%` });
    this.boxes[i].parentElement.append(glow);
    setTimeout(() => glow.remove(), 300);
  }

  onKey(e) {
    const tag = (e.target.tagName || "").toLowerCase();
    const typing = ["input", "textarea", "select"].includes(tag) || e.target.isContentEditable;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); this.saveVersion(); return; }
    if (typing) return;
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) this.redo(); else this.undo(); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "y") { e.preventDefault(); this.redo(); return; }
    if (e.key === " " && tag !== "button") { e.preventDefault(); this.togglePlay(); }
  }

  // ---- side panels ---------------------------------------------------------------
  renderSide() {
    const panels = [];
    if (this.kind === "beat" && this.generated) panels.push(this.panel("Shape the beat", "wand", this.shapeBody(), true));
    this.reviewEl = h("div", { class: "body" });
    if (this.kind === "song") panels.push(this.panel("Review flagged bars", "alert", this.reviewEl, true));
    panels.push(this.panel("Edit with words", "sparkle", this.wordsBody(), this.kind === "beat"));
    this.sectionsEl = h("div", { class: "body" });
    panels.push(this.panel("Sections", "layers", this.sectionsEl, false));
    this.checksEl = h("div", { class: "body" });
    panels.push(this.panel("Checks", "check", this.checksEl, this.kind === "song"));
    panels.push(this.panel("Versions", "refresh", this.versionsBody(), false));
    panels.push(this.panel("Details", "info", this.detailsBody(), false));
    this.sideEl.replaceChildren(...panels);
    this.renderSections(); this.renderChecks(); this.renderReview();
  }

  panel(title, ic, body, open) {
    const d = h("details", { class: "side-panel", open: open || null }, h("summary", {}, icon(ic), title, icon("chevron", "chev")));
    body.classList.add("body");
    d.append(body);
    return d;
  }

  async transform(action, params = {}, label = null) {
    try {
      const r = await api("/api/beats/transform", { json: { score: this.score, action, params } });
      this.commit(r.score, label || r.message);
      toast(r.message, "ok", 2600);
    } catch (e) { toast(e.message, "bad"); }
  }

  shapeBody() {
    const spec = this.score.analysis?.generator?.spec || {};
    const btn = (label, ic, fn, cls = "") => h("button", { class: `btn ${cls}`, type: "button", onclick: fn }, icon(ic), label);
    const sel = (label, options, value, onChange) => {
      const s = h("select", { class: "select", "aria-label": label }, options.map(([v, l]) => h("option", { value: v, selected: String(v) === String(value) }, l)));
      s.addEventListener("change", () => onChange(s.value));
      return h("label", { class: "field" }, label, s);
    };
    const styles = this.app.styles.map((s) => [s.key, s.label]);
    return h("div", {},
      h("div", { class: "actions-grid" },
        btn("New beat", "refresh", () => this.transform("regenerate")),
        btn("Variation", "sparkle", () => this.transform("variation")),
        btn("Simpler", "minus", () => this.transform("simpler")),
        btn("More complex", "plus", () => this.transform("more_complex")),
        btn("Add fill", "drum", () => this.transform("add_fill", { bars: [this.selection[1] + 1] })),
        btn("New hi-hat part", "sticks", () => this.transform("hats")),
        btn("New kick part", "drum", () => this.transform("kick")),
        btn("New ghost notes", "sticks", () => this.transform("snare")),
        btn("Rewrite selection", "refresh", () => this.transform("regenerate_bars", { bars: this.range() }))),
      h("p", { class: "tiny muted", id: "shape-note" }, `“Add fill” and “Rewrite selection” use the selected bars (click a bar; shift-click to extend). Changing a part rewrites only that part; your other edits stay.`),
      h("div", { class: "stack", style: { gap: "8px" } },
        sel("Ending", [["none", "No ending (loops)"], ["crash", "Crash"], ["fill_crash", "Fill and crash"], ["stop", "Stop (choked crash)"], ["dramatic", "Dramatic hits"]],
          this.score.analysis?.generator?.spec?.ending || this.score.analysis?.generator?.ending || "none", (v) => this.transform("ending", { ending: v })),
        sel("Feel", [["", "Style default"], ["straight", "Straight"], ["triplet", "Triplet / shuffle"], ["half_time", "Half-time"], ["double_time", "Double-time"]],
          spec.feel || "", (v) => this.transform("set_feel", { feel: v || null })),
        sel("Length", [4, 8, 12, 16, 24, 32].map((n) => [n, `${n} bars`]), this.score.measures.length, (v) => this.transform("set_bars", { bars: Number(v) })),
        sel("Style", styles, spec.style || "rock", (v) => this.transform("set_style", { style: v }))));
  }

  wordsBody() {
    const input = h("textarea", { class: "textarea", rows: 2, style: { "min-height": "64px" }, placeholder: this.generated ? "e.g. Replace the final bar with a tom fill" : "e.g. Add a crash on bar 9", "aria-label": "Describe a change" });
    const log = h("div", { class: "cmd-log", "aria-live": "polite" });
    const go = h("button", { class: "btn ai", type: "button" }, icon("sparkle"), "Apply");
    const run = async () => {
      const cmd = input.value.trim();
      if (!cmd) return;
      go.disabled = true;
      try {
        const r = await api("/api/beats/command", { json: { score: this.score, command: cmd } });
        this.commit(r.score, r.applied.join(" "));
        log.prepend(h("div", { class: "entry" }, h("strong", {}, cmd), h("div", { class: "muted" }, r.applied.join(" "), r.interpreter?.interpreter === "claude" ? " (read by Claude)" : "")));
        input.value = "";
      } catch (e) {
        log.prepend(h("div", { class: "entry bad" }, h("strong", {}, cmd), h("div", {}, e.message)));
      } finally { go.disabled = false; }
    };
    go.addEventListener("click", run);
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); run(); } });
    const examples = (this.app.editExamples || []).slice(0, 5).map((ex) => h("button", { class: "chip", type: "button", onclick: () => { input.value = ex; input.focus(); } }, ex));
    return h("div", {}, input, h("div", { class: "row" }, go, h("span", { class: "tiny muted" }, "Enter to apply · undo with Ctrl+Z")),
      h("div", { class: "chips", style: { "margin-top": "4px" } }, examples), log);
  }

  renderSections() {
    if (!this.sectionsEl) return;
    const secs = this.score.measures.map((m, i) => ({ name: m.section, i })).filter((s) => s.name);
    if (!secs.length) { this.sectionsEl.replaceChildren(h("p", { class: "small muted" }, "No section labels.")); return; }
    const inputs = secs.map((s) => h("input", { class: "input", value: s.name, maxlength: 40, "aria-label": `Name of the section at bar ${s.i + 1}` }));
    const apply = h("button", { class: "btn sm", type: "button", onclick: () => {
      const sc = clone(this.score);
      secs.forEach((s, k) => { sc.measures[s.i].section = inputs[k].value.trim() || s.name; });
      this.commit(sc, "Renamed sections");
    } }, "Apply names");
    const rows = secs.map((s, k) => h("div", { class: "row" },
      h("button", { class: "btn sm ghost num", type: "button", style: { width: "64px" }, onclick: () => this.select([s.i, s.i], true) }, `Bar ${s.i + 1}`), h("div", { style: { flex: 1 } }, inputs[k])));
    const parts = [...rows, h("div", { class: "row" }, apply)];
    if (this.kind === "song" && !this.dirty) {
      const ask = h("button", { class: "btn sm ai", type: "button", disabled: !this.app.health?.claude?.configured }, icon("sparkle"), "Suggest with Claude");
      ask.addEventListener("click", async () => {
        ask.disabled = true;
        try {
          const r = await api(`/api/charts/${this.chart.id}/suggest-sections`, { method: "POST" });
          r.suggestion.sections.forEach((s, k) => { if (inputs[k]) { inputs[k].value = s.name; inputs[k].title = s.reason; } });
          toast(`Claude's suggestion (${r.suggestion.confidence} confidence). Review the names, then apply them.`, "info", 6000);
        } catch (e) { toast(`Claude is unavailable: ${e.message}`, "bad"); }
        ask.disabled = false;
      });
      parts.push(h("div", { class: "row" }, ask, this.app.health?.claude?.configured ? null : h("span", { class: "tiny muted" }, "Needs ANTHROPIC_API_KEY on the server")));
    }
    this.sectionsEl.replaceChildren(...parts);
  }

  renderChecks() {
    if (!this.checksEl) return;
    const v = this.validation || { checks: [] };
    const items = v.checks.map((c) => h("li", { class: c.ok ? "ok" : c.severity === "review" ? "review" : "bad" },
      icon(c.ok ? "check" : "alert"), h("span", {}, h("strong", {}, c.name), " — ", c.detail)));
    const head = this.kind === "beat"
      ? h("p", { class: "small muted" }, "An original beat is checked for structure and playability. It isn't compared with any recording.")
      : h("p", { class: "small muted" }, "These checks prove the chart is consistent and covers the recording. They don't prove every stroke matches it: listen to the flagged bars.");
    this.checksEl.replaceChildren(head, h("ul", { class: "checks" }, items),
      this.viewSrc.kind === "preview" ? h("p", { class: "tiny muted" }, "For the working copy. Saving re-checks every export.") : null);
  }

  renderReview() {
    if (!this.reviewEl) return;
    const flagged = [...this.flags()];
    if (!flagged.length) { this.reviewEl.replaceChildren(h("p", { class: "small muted" }, "No bar is flagged for review.")); return; }
    const b = this.selection[0];
    const isFlagged = this.score.measures[b]?.uncertain;
    const confirm = h("button", { class: "btn sm", type: "button", disabled: !isFlagged, onclick: () => {
      const s = clone(this.score);
      s.measures[b].uncertain = false;
      s.measures[b].notes = [...(s.measures[b].notes || []), "checked by ear"];
      for (const x of s.measures[b].hits) delete x.confidence;
      this.commit(s, `Bar ${b + 1} checked`);
    } }, icon("check"), isFlagged ? `Bar ${b + 1} is right` : "Select a flagged bar");
    const next = (d) => { const after = flagged.filter((i) => (d > 0 ? i > b : i < b)); const t = d > 0 ? after[0] ?? flagged[0] : after[after.length - 1] ?? flagged[flagged.length - 1]; this.select([t, t], true); };
    this.reviewEl.replaceChildren(
      h("p", { class: "small muted" }, `${flagged.length} bar${flagged.length === 1 ? "" : "s"} hold a stroke the detector was unsure of. Play each, fix it in the grid if needed, and mark it as checked.`),
      h("div", { class: "row" }, h("button", { class: "btn sm", type: "button", onclick: () => next(-1) }, "‹ Previous"), h("button", { class: "btn sm", type: "button", onclick: () => next(1) }, "Next ›"), confirm));
  }

  versionsBody() {
    const list = h("div", { class: "versions" }, (this.project.charts || []).map((c) => h("div", { class: `v${c.id === this.chart.id ? " current" : ""}` },
      h("strong", { class: "num" }, `v${c.version}`), h("span", { class: "muted", style: { flex: 1, overflow: "hidden", "text-overflow": "ellipsis", "white-space": "nowrap" }, title: c.note || c.origin }, c.note || c.origin.replace("_", " ")),
      c.id === this.chart.id ? h("span", { class: "tiny muted" }, "open") : h("a", { class: "btn sm ghost", href: `#/chart/${c.id}` }, "Open"),
      c.id !== this.chart.id ? h("button", { class: "btn sm ghost", type: "button", onclick: async () => {
        const ok = await dialog({ title: `Restore version ${c.version}?`, body: "It becomes the newest version; nothing is deleted.", confirm: "Restore" });
        if (!ok) return;
        try { const n = await api(`/api/charts/${c.id}/restore`, { method: "POST" }); toast(`Version ${c.version} restored as version ${n.version}`); location.hash = `#/chart/${n.id}`; } catch (e) { toast(e.message, "bad"); }
      } }, "Restore") : null)));
    return h("div", {}, list);
  }

  detailsBody() {
    const s = this.chart.summary || {};
    const gen = this.saved.analysis?.generator;
    const rows = [];
    const kv = (k, v) => v !== undefined && v !== null && v !== "" && rows.push(h("dt", {}, k), h("dd", {}, String(v)));
    kv("Bars", `${this.score.measures.length} (${this.view.bars.length} printed, ${this.view.pages.length} page${this.view.pages.length === 1 ? "" : "s"})`);
    kv("Tempo", s.tempo_estimate || `${this.score.measures[0].tempo || 120} BPM`);
    kv("Time", s.meter || this.score.measures[0].time);
    kv("Strokes", hitCount(this.score));
    kv("Engraving", s.lilypond ? `LilyPond ${s.lilypond}${s.rendering_ok ? "; PDF, MusicXML and MIDI match the chart" : ""}` : null);
    if (this.kind === "beat") {
      kv("Made by", gen ? `Drum Agent beat generator (${gen.interpreter?.interpreter === "claude" ? "description read by Claude, notes by the generator" : "rules"})` : "Drum Agent");
      if (gen?.prompt) kv("Description", gen.prompt);
    } else {
      kv("Made by", s.engine || this.chart.origin);
      kv("Rights", s.rights);
      kv("Detected", s.detected_onsets ? `${s.detected_onsets} strokes` : null);
    }
    const notes = gen?.notes || [];
    return h("div", {}, h("dl", { class: "kv" }, rows),
      notes.length ? h("div", { class: "understood" }, notes.map((n) => h("span", { class: `note-chip src-${n.source}` }, `${n.field.replace(/_/g, " ")}:`, h("b", {}, String(n.value))))) : null);
  }
}
