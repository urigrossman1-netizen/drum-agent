// Create: Song to Chart, or Create a Beat.

import { h, icon, api, toast, prefs, fmtDur, statusBadge, ago } from "./ui.js";
import { progressCard, watchJob } from "./progress.js";

const EXAMPLES = [
  ["Heavy Rock", "Give me a heavy rock beat at 120 BPM with open hi-hats, syncopated kicks, crash accents, and a dramatic ending."],
  ["Pop-Punk", "Create a powerful pop-punk beat at 165 BPM in 4/4. Use fast eighth-note hi-hats, a driving kick, strong snare hits, energetic crashes, and a two-bar tom fill every eight bars. Make it suitable for an intermediate drummer."],
  ["Funk Groove", "A funky 16th-note groove at 96 BPM with ghost notes on the snare, a syncopated kick and an open hi-hat at the end of every other bar."],
  ["Half-Time Beat", "A heavy half-time beat at 140 BPM, ride cymbal, big crashes, 8 bars with a tom fill at the end."],
  ["Fast Metal Groove", "A fast metal groove at 180 BPM with double bass, crash on the quarter notes in the chorus and a snare fill every 4 bars. Advanced."],
  ["Relaxed R&B", "Make a relaxed R&B groove at 82 BPM, with subtle hi-hat variations, a syncopated kick, a strong backbeat, ghost notes, and a four-bar arrangement."],
  ["Hip-Hop", "A syncopated boom-bap hip-hop beat at 90 BPM with a lazy kick, a hard backbeat and an open hi-hat, 8 bars."],
  ["Custom Fill", "A 4-bar rock groove at 110 BPM where bar 4 is a big tom fill with 16th notes moving down the toms."],
];
const SETTINGS = [
  ["style", "Style"], ["bpm", "BPM"], ["time_signature", "Time"], ["bars", "Bars"], ["difficulty", "Difficulty"],
  ["complexity", "Complexity"], ["feel", "Feel"], ["cymbal", "Cymbal"], ["fill_every", "Fills"], ["ending", "Ending"],
  ["ghost_notes", "Ghost notes"], ["open_hats", "Open hi-hats"],
];

export function showCreate(root, app, params) {
  const mode = params.get("mode") || prefs.get("mode", "beat");
  const state = { mode };
  const hero = h("div", { class: "hero" },
    h("h1", { class: "enter", style: { "--i": 0 } }, "Your next groove ", h("span", { class: "accent" }, "starts here.")),
    h("p", { class: "enter", style: { "--i": 1 } }, "Describe a beat and get an original drum chart you can hear, edit and print. Or find a song: open its chart, or transcribe a recording you have the rights to."));
  const tabs = h("div", { class: "modes enter", role: "tablist", "aria-label": "What do you want to make?", style: { "--i": 2 } });
  const songTab = modeButton("song", "disc", "Song to Chart", "Find the recording. Open its chart, or transcribe audio you're allowed to use.", state, () => switchTo("song"));
  const beatTab = modeButton("beat", "sparkle", "Create a Beat", "Describe the groove in your own words. Get a real, playable, printable chart.", state, () => switchTo("beat"));
  tabs.append(songTab, beatTab);
  tabs.addEventListener("keydown", (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") { e.preventDefault(); switchTo(state.mode === "song" ? "beat" : "song"); (state.mode === "song" ? songTab : beatTab).focus(); } });
  const panelHost = h("div", { class: "enter", style: { "--i": 3 } });
  const recent = h("div", {});
  root.replaceChildren(hero, tabs, panelHost, recent);

  function switchTo(m) {
    state.mode = m; prefs.set("mode", m);
    songTab.setAttribute("aria-selected", String(m === "song")); songTab.tabIndex = m === "song" ? 0 : -1;
    beatTab.setAttribute("aria-selected", String(m === "beat")); beatTab.tabIndex = m === "beat" ? 0 : -1;
    panelHost.replaceChildren(m === "song" ? songPanel(app, params) : beatPanel(app));
    const q = new URLSearchParams(location.hash.split("?")[1] || "");
    if (q.get("mode") !== m) history.replaceState(null, "", `#/?mode=${m}${m === "song" && q.get("q") ? "&q=" + encodeURIComponent(q.get("q")) : ""}`);
  }
  switchTo(state.mode);
  loadRecent(recent);
}

function modeButton(key, ic, title, desc, state, onclick) {
  return h("button", { class: `mode ${key}`, type: "button", role: "tab", id: `mode-${key}`, "aria-selected": String(state.mode === key), tabindex: state.mode === key ? 0 : -1, "aria-controls": "mode-panel", onclick },
    h("span", { class: "glyph" }, icon(ic)), h("span", {}, h("strong", {}, title), h("span", { class: "desc" }, desc)));
}

// ---- Song to Chart ------------------------------------------------------------------

function songPanel(app, params) {
  const input = h("input", { class: "input", type: "search", id: "song-q", name: "q", autocomplete: "off", maxlength: 300,
    placeholder: "Search by song title and artist…", "aria-label": "Song title and artist", value: params.get("q") || "" });
  const btn = h("button", { class: "btn primary lg", type: "submit" }, icon("search"), "Search");
  const stateEl = h("div", { class: "state-line", role: "status", "aria-live": "polite" });
  const results = h("div", { class: "results", id: "song-results" });
  const form = h("form", { class: "composer", role: "tabpanel", id: "mode-panel", "aria-labelledby": "mode-song" },
    h("div", { class: "search-row" }, h("div", { class: "search-box" }, icon("search"), input), btn),
    h("p", { class: "tiny muted", style: { "margin-top": "10px" } }, "Try “American Idiot - Green Day”. The chart catalog is searched first, then music metadata services. Streaming services identify recordings only; their audio is never downloaded or analyzed."),
    stateEl);
  let seq = 0;
  async function run(q) {
    const my = ++seq;
    results.replaceChildren();
    stateEl.className = "state-line";
    stateEl.replaceChildren(h("span", { class: "spinner" }), `Finding recordings for “${q}”…`);
    let data;
    try {
      data = await api(`/api/search?q=${encodeURIComponent(q)}`);
    } catch (e) {
      if (my !== seq) return;
      stateEl.className = "state-line error";
      stateEl.replaceChildren(icon("alert"), `Search failed: ${e.message}`);
      return;
    }
    if (my !== seq) return;
    stateEl.replaceChildren();
    let k = 0;
    if (data.catalog.length) {
      results.append(h("h2", {}, "In your chart catalog"), ...data.catalog.map((s) => catalogCard(s, k++)));
    }
    if (data.results.length) {
      results.append(h("h2", {}, "Recordings found"), ...data.results.map((r) => resultCard(r, k++)));
    }
    if (!data.catalog.length && !data.results.length) {
      results.append(h("div", { class: "empty" }, h("strong", {}, "No recordings found"), "You can add the song yourself below, then upload a recording you have the right to transcribe."));
    }
    results.append(h("div", { class: "provider-states", "aria-label": "Search sources" }, data.providers.map((p) =>
      h("span", { class: `badge ${p.state === "ok" ? "ok" : p.state === "error" ? "bad" : "plain"}`, title: p.detail || "" },
        `${p.provider}: ${p.state === "ok" ? "searched" : p.state === "error" ? "unavailable" : "not configured"}`))));
    results.append(manualAdd(data.title, data.artist));
  }
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (!q) { input.focus(); return; }
    history.replaceState(null, "", `#/?mode=song&q=${encodeURIComponent(q)}`);
    run(q);
  });
  if (params.get("q")) setTimeout(() => run(params.get("q")));
  setTimeout(() => input.focus(), 50);
  return h("div", {}, form, results);
}

function catalogCard(s, i) {
  const meta = [s.album, s.year, s.version, fmtDur(s.duration_s)].filter(Boolean).join(" · ");
  return h("div", { class: "result enter", style: { "--i": i } },
    h("div", { class: "art" }, icon(s.chart ? "score" : "disc")),
    h("div", { class: "what" }, h("div", { class: "title" }, `${s.title} — ${s.artist}`),
      h("div", { class: "meta" }, meta || "In your catalog", s.chart ? ` · chart v${s.chart.version}, ${s.chart.bars} bars` : "")),
    statusBadge(s.status, s.kind),
    s.chart ? h("a", { class: "btn primary", href: `#/chart/${s.chart.id}` }, "Open chart") : h("a", { class: "btn", href: `#/song/${s.id}` }, "Open"));
}

function resultCard(r, i) {
  const meta = [r.album, r.year, fmtDur(r.duration_s), r.isrc ? `ISRC ${r.isrc}` : null].filter(Boolean).join(" · ");
  const version = h("span", { class: `badge plain ${["live", "demo", "remix", "cover"].includes(r.version) ? "warn" : ""}` }, r.version);
  const pick = h("button", { class: "btn", type: "button" }, "Select");
  pick.addEventListener("click", async () => {
    pick.disabled = true;
    try { const d = await api("/api/songs", { json: r }); location.hash = `#/song/${d.song.id}`; }
    catch (e) { toast(`Could not select it: ${e.message}`, "bad"); pick.disabled = false; }
  });
  return h("div", { class: "result enter", style: { "--i": i } },
    h("div", { class: "art" }, icon("disc")),
    h("div", { class: "what" }, h("div", { class: "title" }, `${r.title} — ${r.artist}`),
      h("div", { class: "meta" }, meta || "—", ` · ${r.providers.join(", ")}`, r.url ? [" · ", h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, "listen")] : null)),
    version, statusBadge(r.status, "song"), pick);
}

function manualAdd(title, artist) {
  const t = h("input", { class: "input", value: title || "", placeholder: "Title", required: true, maxlength: 300, "aria-label": "Title" });
  const a = h("input", { class: "input", value: artist || "", placeholder: "Artist", required: true, maxlength: 300, "aria-label": "Artist" });
  const form = h("form", { class: "panel" }, h("h3", {}, "Not listed? Add the song yourself"),
    h("div", { class: "row" }, h("div", { style: { flex: 2, "min-width": "180px" } }, t), h("div", { style: { flex: 2, "min-width": "160px" } }, a), h("button", { class: "btn", type: "submit" }, icon("plus"), "Add song")),
    h("p", { class: "tiny muted", style: { "margin-top": "8px" } }, "Next you'll be asked for a recording you have the right to transcribe."));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try { const d = await api("/api/songs", { json: { title: t.value, artist: a.value } }); location.hash = `#/song/${d.song.id}`; }
    catch (err) { toast(err.message, "bad"); }
  });
  return form;
}

// ---- Create a Beat --------------------------------------------------------------------

function beatPanel(app) {
  const draft = prefs.get("beat-prompt", "");
  const prompt = h("textarea", { class: "textarea prompt", id: "beat-prompt", maxlength: 4000, rows: 4, "aria-label": "Describe the beat",
    placeholder: "Describe the groove, tempo, style, instruments, energy, and difficulty you want…" });
  prompt.value = draft;
  const understood = h("div", { class: "understood", "aria-live": "polite", "aria-label": "What the description means" });
  const chips = h("div", { class: "chips", role: "group", "aria-label": "Examples" }, EXAMPLES.map(([label, text]) => {
    const c = h("button", { class: "chip", type: "button", title: text }, label);
    c.addEventListener("click", () => {
      prompt.value = text; prefs.set("beat-prompt", text);
      for (const x of chips.children) x.classList.toggle("on", x === c);
      interpret();
      prompt.focus();
    });
    return c;
  }));
  const settings = {};
  const quick = quickSettings(app, settings, () => interpret());
  const go = h("button", { class: "btn ai lg", type: "submit", id: "generate" }, icon("sparkle"), "Generate drum chart");
  const progress = h("div", { id: "gen-progress" });
  const form = h("form", { class: "composer beat", role: "tabpanel", id: "mode-panel", "aria-labelledby": "mode-beat" },
    h("label", { class: "visually-hidden", for: "beat-prompt" }, "Describe the beat"), prompt, chips, understood,
    quick.el,
    h("div", { class: "composer-actions" }, go, h("span", { class: "tiny muted" }, app.health?.claude?.configured
      ? "Claude reads your description; the drum parts are written and checked by Drum Agent's generator."
      : "Your description is read by Drum Agent's rule-based generator. No AI service is needed.")));
  let timer = null; let seq = 0;
  async function interpret() {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const my = ++seq;
      const text = prompt.value.trim();
      if (!text && !Object.keys(settings).length) { understood.replaceChildren(h("span", { class: "tiny muted" }, "As you type, what the generator understood appears here.")); return; }
      try {
        const r = await api("/api/beats/interpret", { json: { prompt: text, settings: clean(settings) } });
        if (my !== seq) return;
        understood.replaceChildren(h("span", { class: "tiny muted" }, "Understood:"), ...r.notes.filter((n) => n.field !== "interpreter").map((n) =>
          h("span", { class: `note-chip src-${n.source}`, title: n.detail || (n.source === "default" ? "default" : n.source === "setting" ? "from the quick settings" : "from your description") },
            `${label(n.field)}`, h("b", {}, display(n.value)))));
      } catch { /* the preview of the interpretation is a convenience */ }
    }, 280);
  }
  prompt.addEventListener("input", () => { prefs.set("beat-prompt", prompt.value); interpret(); });
  prompt.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); form.requestSubmit(); } });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = prompt.value.trim();
    if (!text && !Object.keys(clean(settings)).length) { toast("Describe the beat, or pick an example.", "bad"); prompt.focus(); return; }
    go.disabled = true;
    const rid = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2)).replace(/[^A-Za-z0-9_-]/g, "");
    try {
      const r = await api("/api/beats", { json: { prompt: text, settings: clean(settings), request_id: rid } });
      follow(r.job, progress, go);
    } catch (err) {
      toast(`Could not start: ${err.message}`, "bad");
      go.disabled = false;
    }
  });
  interpret();
  setTimeout(() => prompt.focus(), 50);
  return h("div", {}, form, progress);
}

function follow(job, host, go) {
  const draw = (j) => host.replaceChildren(progressCard(j, { title: "Writing your beat",
    onCancel: async () => { try { await api(`/api/jobs/${j.id}/cancel`, { method: "POST" }); } catch (e) { toast(e.message, "bad"); } },
    onRetry: async () => { try { const n = await api(`/api/jobs/${j.id}/retry`, { method: "POST" }); follow(n, host, go); } catch (e) { toast(e.message, "bad"); } } }));
  draw(job);
  host.scrollIntoView({ block: "nearest", behavior: "smooth" });
  watchJob(job.id, (j, err) => {
    if (err) { toast(err.message, "bad"); return; }
    draw(j);
    if (j.status === "succeeded") {
      setTimeout(() => { location.hash = `#/chart/${j.chart_id}`; }, 450);
    } else if (j.status === "failed" || j.status === "cancelled") {
      go.disabled = false;
    }
  });
}

function quickSettings(app, settings, onChange) {
  const styles = [["", "From the description"], ...app.styles.map((s) => [s.key, `${s.label} (${s.bpm} BPM)`])];
  const field = (key, lab, control) => { control.addEventListener("change", () => { const v = control.type === "checkbox" ? control.checked : control.value; if (v === "" || v === "auto") delete settings[key]; else settings[key] = control.type === "number" ? Number(v) : v; onChange(); }); return h("label", { class: "field" }, lab, control); };
  const select = (opts) => h("select", { class: "select" }, opts.map(([v, l]) => h("option", { value: v }, l)));
  const grid = h("div", { class: "settings-grid" },
    field("style", "Style", select(styles)),
    field("bpm", "Tempo (BPM)", h("input", { class: "input", type: "number", min: 40, max: 300, placeholder: "auto" })),
    field("time_signature", "Time signature", select([["", "auto"], ...["4/4", "3/4", "6/8", "12/8", "2/4", "5/4", "7/8", "9/8"].map((t) => [t, t])])),
    field("bars", "Length", select([["", "auto"], ...[4, 8, 12, 16, 24, 32].map((n) => [n, `${n} bars`])])),
    field("difficulty", "Difficulty", select([["", "auto"], ["beginner", "Beginner"], ["intermediate", "Intermediate"], ["advanced", "Advanced"]])),
    field("complexity", "Complexity", select([["", "auto"], ["0.15", "Very simple"], ["0.35", "Simple"], ["0.55", "Moderate"], ["0.75", "Busy"], ["0.95", "Very busy"]])),
    field("feel", "Feel", select([["", "auto"], ["straight", "Straight"], ["triplet", "Triplet / shuffle"], ["half_time", "Half-time"], ["double_time", "Double-time"]])),
    field("cymbal", "Cymbal hand", select([["", "auto"], ["hihat", "Hi-hat"], ["ride", "Ride"]])),
    field("fill_every", "Fills", select([["", "auto"], ["0", "No fills"], ["2", "Every 2 bars"], ["4", "Every 4 bars"], ["8", "Every 8 bars"]])),
    field("ending", "Ending", select([["", "auto"], ["none", "None (loops)"], ["crash", "Crash"], ["fill_crash", "Fill and crash"], ["stop", "Stop"], ["dramatic", "Dramatic"]])),
    field("ghost_notes", "Ghost notes", select([["", "auto"], ["true", "On"], ["false", "Off"]])),
    field("open_hats", "Open hi-hats", select([["", "auto"], ["true", "On"], ["false", "Off"]])));
  const body = h("div", { class: "collapse", id: "quick-settings" }, h("div", {}, grid));
  const toggle = h("button", { class: "toggle", type: "button", "aria-expanded": "false", "aria-controls": "quick-settings" }, icon("chevron"), "Quick settings", h("span", { class: "tiny muted" }, " — optional; they override the description"));
  toggle.addEventListener("click", () => { const open = toggle.getAttribute("aria-expanded") !== "true"; toggle.setAttribute("aria-expanded", String(open)); body.classList.toggle("open", open); });
  return { el: h("div", { class: "disclosure" }, toggle, body) };
}

function clean(settings) {
  const out = {};
  for (const [k, v] of Object.entries(settings)) {
    if (v === "true") out[k] = true; else if (v === "false") out[k] = false;
    else if (["bars", "fill_every", "bpm"].includes(k)) out[k] = Number(v);
    else if (k === "complexity") out[k] = Number(v);
    else out[k] = v;
  }
  return out;
}

const LABELS = { bpm: "Tempo", time_signature: "Time", hat_rate: "Hi-hat", fill_length: "Fill length", fill_every: "Fills", fill_voice: "Fill on", ghost_notes: "Ghost notes", open_hats: "Open hi-hats", double_bass: "Double bass", cross_stick: "Cross-stick" };
const label = (f) => (LABELS[f] || f.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())) + ":";
const display = (v) => (v === true ? "yes" : v === false ? "no" : typeof v === "number" && v < 1 && v > 0 ? `${Math.round(v * 100)}%` : String(v));

// ---- recent ------------------------------------------------------------------------------

async function loadRecent(host) {
  let data;
  try { data = await api("/api/projects"); } catch { return; }
  const items = data.projects.slice(0, 6);
  host.replaceChildren(h("div", { class: "section-title" }, h("h2", {}, "Recent charts"), h("a", { href: "#/library" }, "All charts →")),
    h("div", { style: { "max-width": "860px", margin: "0 auto" } }, items.length ? h("div", { class: "tiles" }, items.map((p, i) => {
      const href = p.chart ? `#/chart/${p.chart.id}` : p.kind === "song" ? `#/song/${p.id}` : "#/library";
      return h("a", { class: "tile enter", href, style: { "--i": i } },
        h("div", { class: "row" }, h("span", { class: `badge plain ${p.kind === "beat" ? "ai" : "busy"}` }, p.kind === "beat" ? "Original beat" : "Song"), statusBadge(p.status, p.kind)),
        h("div", { class: "t" }, p.title), h("div", { class: "m" }, [p.chart ? `${p.chart.bars} bars` : "no chart yet", p.chart?.tempo ? `${Math.round(p.chart.tempo)} BPM` : null, ago(p.updated_at)].filter(Boolean).join(" · ")));
    })) : h("div", { class: "empty" }, h("strong", {}, "Nothing here yet"), "Your charts appear here once you create one.")));
}
