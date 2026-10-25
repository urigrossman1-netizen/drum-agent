"use strict";
// Drum Agent page: search -> song -> source -> job progress -> chart (view, print, download).
// Routes live in the URL hash (#/search?q=..., #/song/<id>, #/chart/<id>) so a refresh keeps the place.

const $ = (sel) => document.querySelector(sel);
const STATUS_TEXT = {
  NOT_STARTED: "Not started", ANALYZING: "Analyzing", TRANSCRIBING: "Transcribing", VERIFYING: "Verifying",
  NEEDS_SOURCE: "Needs a recording", NEEDS_CORRECTION: "Needs review", COMPLETE: "Complete",
};
const CASE_TEXT = {
  EXISTING_CHART: "A chart for this recording is stored.",
  AUTHORIZED_ASSET: "An authorized recording is available on the server.",
  USER_UPLOAD: "You uploaded a recording for this song.",
  LICENSED_SOURCE: "A licensed audio source is available.",
  NEEDS_SOURCE: "This recording is identified, but no authorized audio is available to transcribe.",
};
let health = null;
let poll = null;
let searchSeq = 0; // a newer search or listing makes older answers stale

function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { Accept: "application/json", ...(opts.json ? { "Content-Type": "application/json" } : {}) },
                                  method: opts.method || (opts.json ? "POST" : "GET"),
                                  body: opts.json ? JSON.stringify(opts.json) : opts.body });
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) {
    const detail = body && (body.detail || body.error);
    const err = new Error(typeof detail === "string" ? detail : `request failed (HTTP ${res.status})`);
    err.status = res.status; err.code = body && body.error;
    throw err;
  }
  return body;
}

const fmtDur = (s) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "");
const badge = (status) => h("span", { class: `badge ${status}` }, STATUS_TEXT[status] || status);

function show(view) {
  for (const id of ["search-view", "song-view", "chart-view"]) $("#" + id).hidden = id !== view;
  if (poll && view !== "song-view") { clearTimeout(poll); poll = null; }
}

// ---- health -------------------------------------------------------------------------
async function loadHealth() {
  try {
    const res = await fetch("/api/health");
    health = await res.json();
    const c = health.checks;
    const parts = [c.lilypond.ok ? `LilyPond ${c.lilypond.version}` : "LilyPond missing",
                   c.ffmpeg.ok ? "ffmpeg ok" : "ffmpeg missing",
                   c.onset_classifier.ok ? "classifier ready" : "classifier weights missing",
                   health.claude.configured ? "Claude configured" : "Claude not configured"];
    $("#health").textContent = (health.ok ? "" : "Not ready: ") + parts.join(" · ");
    $("#health").classList.toggle("error-text", !health.ok);
  } catch {
    $("#health").textContent = "The server is not reachable.";
    $("#health").classList.add("error-text");
  }
}

// ---- search -------------------------------------------------------------------------
async function runSearch(q) {
  show("search-view");
  $("#q").value = q;
  const state = $("#search-state"), out = $("#results");
  const seq = ++searchSeq;
  out.replaceChildren();
  if (!q) { state.textContent = ""; state.className = "state"; return listCatalog(seq); }
  state.className = "state";
  state.replaceChildren(h("span", { class: "spinner" }), `Searching for “${q}”…`);
  let data;
  try {
    data = await api(`/api/search?q=${encodeURIComponent(q)}`);
  } catch (e) {
    if (seq !== searchSeq) return;
    state.className = "state error"; state.textContent = `Search failed: ${e.message}`;
    return;
  }
  if (seq !== searchSeq) return;
  state.textContent = "";
  if (data.catalog.length) {
    out.append(h("h2", {}, "In the chart catalog"),
               h("div", { class: "list" }, data.catalog.map(songCard)));
  }
  if (data.results.length) {
    out.append(h("h2", {}, "Recordings found"),
               h("div", { class: "list" }, data.results.map(resultCard)));
  }
  if (!data.catalog.length && !data.results.length) {
    out.append(h("p", {}, "No recordings found."));
  }
  out.append(providerStates(data.providers), manualEntry(data.title, data.artist));
}

async function listCatalog(seq) {
  const out = $("#results");
  try {
    const data = await api("/api/songs");
    if (seq !== searchSeq) return;
    if (data.songs.length) out.append(h("h2", {}, "Chart catalog"), h("div", { class: "list" }, data.songs.map(songCard)));
    else out.append(h("p", { class: "note" }, "The catalog is empty. Search for a song to begin."));
  } catch (e) {
    out.append(h("p", { class: "error-text" }, `Could not load the catalog: ${e.message}`));
  }
}

function songCard(s) {
  const meta = [s.album, s.year, s.version, fmtDur(s.duration_s)].filter(Boolean).join(" · ");
  return h("div", { class: "card" },
    h("div", { class: "what" }, h("div", { class: "title" }, `${s.title} — ${s.artist}`, badge(s.status)),
      h("div", { class: "meta" }, meta || "—", s.chart ? ` · chart v${s.chart.version}, ${s.chart.bars} bars` : "")),
    s.chart ? h("button", { onclick: () => (location.hash = `#/chart/${s.chart.id}`) }, "Open chart")
            : h("button", { class: "secondary", onclick: () => (location.hash = `#/song/${s.id}`) }, "Open"));
}

function resultCard(r) {
  const meta = [r.album, r.year, fmtDur(r.duration_s), r.isrc ? `ISRC ${r.isrc}` : null].filter(Boolean).join(" · ");
  return h("div", { class: "card" },
    h("div", { class: "what" },
      h("div", { class: "title" }, `${r.title} — ${r.artist}`, h("span", { class: `badge ${r.version}` }, r.version),
        badge(r.status)),
      h("div", { class: "meta" }, meta || "—", ` · from ${r.providers.join(", ")}`,
        r.url ? [" · ", h("a", { href: r.url, target: "_blank", rel: "noopener noreferrer" }, "listen")] : null)),
    h("button", { onclick: () => pick(r) }, "Select"));
}

function providerStates(states) {
  const label = { ok: "searched", error: "unavailable", not_configured: "not configured" };
  return h("ul", { class: "providers" }, states.map((p) =>
    h("li", {}, `${p.provider}: ${label[p.state] || p.state}`, p.detail ? ` — ${p.detail}` : "")));
}

function manualEntry(title, artist) {
  const t = h("input", { name: "title", value: title || "", placeholder: "Title", required: true, maxlength: 300 });
  const a = h("input", { name: "artist", value: artist || "", placeholder: "Artist", required: true, maxlength: 300 });
  const form = h("form", { class: "panel" },
    h("h3", {}, "Not listed? Add the song yourself"),
    h("div", { class: "row" }, t, a, h("button", { type: "submit" }, "Add song")),
    h("p", { class: "note" }, "You will be asked for a recording you have the right to transcribe."));
  form.addEventListener("submit", (ev) => { ev.preventDefault(); pick({ title: t.value, artist: a.value }); });
  return form;
}

async function pick(r) {
  try {
    const d = await api("/api/songs", { json: r });
    location.hash = `#/song/${d.song.id}`;
  } catch (e) {
    $("#search-state").className = "state error";
    $("#search-state").textContent = `Could not select it: ${e.message}`;
  }
}

// ---- song ---------------------------------------------------------------------------
async function showSong(id) {
  show("song-view");
  const view = $("#song-view");
  let d;
  try {
    d = await api(`/api/songs/${id}`);
  } catch (e) {
    view.replaceChildren(h("p", { class: "error-text" }, `Could not load the song: ${e.message}`));
    return;
  }
  const s = d.song;
  const meta = [s.album, s.year, s.version, fmtDur(s.duration_s), s.isrc ? `ISRC ${s.isrc}` : null].filter(Boolean).join(" · ");
  const parts = [h("p", {}, h("a", { href: "#/" }, "← Search")),
                 h("h2", {}, `${s.title} — ${s.artist}`, badge(d.status)),
                 h("p", { class: "meta" }, meta)];
  const job = d.jobs[0];
  const running = job && (job.status === "queued" || job.status === "running");
  parts.push(h("div", { class: "panel" }, h("h3", {}, "Source"), h("p", {}, CASE_TEXT[d.resolution.case] || d.resolution.case),
    h("p", { class: "note" }, d.resolution.detail)));
  if (job) parts.push(jobPanel(job, s.id));
  if (d.charts.length) {
    parts.push(h("div", { class: "panel" }, h("h3", {}, "Charts"),
      h("div", { class: "list" }, d.charts.map((c) => h("div", { class: "card" },
        h("div", { class: "what" }, h("div", { class: "title" }, `Version ${c.version}`, badge(c.status)),
          h("div", { class: "meta" }, `${c.bars} bars · ${c.origin.replace("_", " ")} · ${new Date(c.created_at * 1000).toLocaleString()}`)),
        h("button", { onclick: () => (location.hash = `#/chart/${c.id}`) }, "Open chart"))))));
  }
  if (!running) {
    if (d.resolution.case === "AUTHORIZED_ASSET" && !d.sources.length) {
      parts.push(h("div", { class: "panel" }, h("button", { onclick: () => useAsset(s.id) }, "Transcribe the authorized recording")));
    }
    parts.push(uploadPanel(s.id, d.sources.length > 0));
  }
  view.replaceChildren(...parts);
  if (running) poll = setTimeout(() => showSong(id), 1000);
}

function jobPanel(job, songId) {
  const mark = { done: "✓", running: "", failed: "✗", cancelled: "✗" };
  const items = job.stages.map((st) => h("li", { class: st.status },
    h("span", { class: "mark" }, st.status === "running" ? h("span", { class: "spinner" }) : mark[st.status] || ""),
    st.label, st.ended_at ? h("span", { class: "time" }, `${(st.ended_at - st.started_at).toFixed(1)} s`) : null));
  const panel = h("div", { class: "panel", id: "job" }, h("h3", {}, "Transcription"));
  if (job.status === "queued") panel.append(h("p", {}, h("span", { class: "spinner" }), "Waiting for the worker…"));
  panel.append(h("ul", { class: "stages" }, items));
  if (job.status === "queued" || job.status === "running") {
    panel.append(h("button", { class: "secondary", onclick: async () => { await api(`/api/jobs/${job.id}/cancel`, { method: "POST" }); showSong(songId); } }, "Cancel"));
  } else if (job.status === "failed" || job.status === "cancelled") {
    panel.append(h("p", { class: "error-text" }, job.status === "cancelled" ? "Cancelled." : `Failed: ${job.error}`),
      h("button", { onclick: async () => {
        try { await api(`/api/jobs/${job.id}/retry`, { method: "POST" }); } catch (e) { alert(e.message); }
        showSong(songId);
      } }, "Retry"));
  } else if (job.status === "succeeded" && job.chart_id) {
    panel.append(h("button", { onclick: () => (location.hash = `#/chart/${job.chart_id}`) }, "Open the chart"));
  }
  return panel;
}

function uploadPanel(songId, hasSource) {
  const rights = health ? health.rights_options : {};
  const file = h("input", { type: "file", name: "file", accept: ".wav,.mp3,.flac,.m4a,.aac,.ogg,audio/*", required: true });
  const select = h("select", { name: "rights", required: true },
    h("option", { value: "" }, "Choose your rights basis…"),
    Object.entries(rights).map(([k, v]) => h("option", { value: k }, v)));
  const bar = h("progress", { max: 100, value: 0, hidden: true });
  const msg = h("p", { class: "note" });
  const button = h("button", { type: "submit" }, "Upload and transcribe");
  const form = h("form", { class: "panel upload" },
    h("h3", {}, hasSource ? "Upload another recording" : "Upload a recording"),
    h("p", { class: "note" }, "WAV, MP3, FLAC, M4A, AAC or OGG, up to " + (health ? health.limits.max_upload_mb : 200) +
      " MB. Full transcription needs a rights basis: a recording you own or made, permission from the rights holder, " +
      "a licence, public-domain material, or your own composition. Streaming services are not a source."),
    file, select, button, bar, msg);
  form.addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (!file.files.length || !select.value) { msg.textContent = "Choose a file and your rights basis."; return; }
    const fd = new FormData();
    fd.append("file", file.files[0]);
    fd.append("rights", select.value);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/songs/${songId}/upload`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) { bar.hidden = false; bar.value = (100 * e.loaded) / e.total; } };
    xhr.onload = () => {
      let body = null;
      try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      if (xhr.status >= 200 && xhr.status < 300) { showSong(songId); return; }
      button.disabled = false; bar.hidden = true;
      msg.className = "error-text";
      msg.textContent = "The file was not accepted: " + ((body && (body.detail || body.error)) || `HTTP ${xhr.status}`);
    };
    xhr.onerror = () => { button.disabled = false; msg.className = "error-text"; msg.textContent = "The upload failed (network error)."; };
    button.disabled = true;
    msg.className = "note"; msg.textContent = "Uploading, then checking and decoding the audio…";
    xhr.send(fd);
  });
  return form;
}

async function useAsset(songId) {
  try { await api(`/api/songs/${songId}/use-asset`, { method: "POST" }); } catch (e) { alert(e.message); }
  showSong(songId);
}

// ---- chart --------------------------------------------------------------------------
const chartState = { chart: null, current: null, zoom: 1, flags: [], flagIndex: -1, follow: true };

async function showChart(id) {
  show("chart-view");
  let c;
  try {
    c = await api(`/api/charts/${id}`);
  } catch (e) {
    $("#chart-bar").replaceChildren(h("p", { class: "error-text" }, `Could not load the chart: ${e.message}`));
    $("#pages").replaceChildren(); $("#chart-side").replaceChildren();
    return;
  }
  chartState.chart = c; chartState.current = null; chartState.flagIndex = -1;
  chartState.flags = c.view.bars.map((b, i) => (b.uncertain ? i : -1)).filter((i) => i >= 0);
  renderPages(c);
  renderBar(c);
  renderSide(c);
}

function renderPages(c) {
  const pages = $("#pages");
  pages.replaceChildren();
  c.view.pages.forEach((p, k) => {
    const page = h("div", { class: "page", "data-page": k },
      h("img", { src: `/api/charts/${c.id}/files/${p.file}`, alt: `Page ${k + 1} of ${c.view.pages.length}` }));
    pages.append(page);
  });
  c.view.bars.forEach((b, i) => {
    if (!b.box) return;
    const box = h("div", { class: "box" + (b.uncertain ? " flag" : ""), "data-bar": i,
                           title: `Bar ${b.printed}` + (b.uncertain ? " — flagged for review" : "") });
    Object.assign(box.style, { left: `${100 * b.box.x0}%`, width: `${100 * (b.box.x1 - b.box.x0)}%`,
                               top: `${100 * b.box.y0}%`, height: `${100 * (b.box.y1 - b.box.y0)}%` });
    box.addEventListener("click", () => select(i, false));
    pages.children[b.box.page].append(box);
  });
  setZoom(chartState.zoom);
}

function renderBar(c) {
  const s = c.song;
  const jump = h("input", { type: "number", min: 1, placeholder: "bar", "aria-label": "Go to bar" });
  const go = () => {
    const n = parseInt(jump.value, 10);
    const i = c.view.bars.findIndex((b) => b.printed === n);
    if (i >= 0) select(i, true); else jump.setCustomValidity("No such bar"), jump.reportValidity(), jump.setCustomValidity("");
  };
  jump.addEventListener("keydown", (e) => { if (e.key === "Enter") go(); });
  const files = c.files;
  const dl = (name, label) => (files[name] ? h("a", { class: "btn secondary", href: `${files[name]}?download=1`, download: "" }, label) : null);
  const items = [
    h("a", { href: `#/song/${s.id}` }, "←"),
    h("span", { class: "name" }, `${s.title} — ${s.artist}`), h("span", { class: "meta" }, `v${c.version}`), badge(c.status),
    h("span", { class: "group" }, h("button", { onclick: () => window.print() }, "Print"),
      dl("chart.pdf", "PDF"), dl("chart.musicxml", "MusicXML"), dl("chart.mid", "MIDI")),
    h("span", { class: "group" }, h("button", { class: "secondary", "aria-label": "Zoom out", onclick: () => setZoom(chartState.zoom / 1.2) }, "−"),
      h("button", { class: "secondary", "aria-label": "Zoom in", onclick: () => setZoom(chartState.zoom * 1.2) }, "+"),
      h("button", { class: "secondary", onclick: () => setZoom(1) }, "100%")),
    h("span", { class: "group" }, jump, h("button", { class: "secondary", onclick: go }, "Go")),
  ];
  if (chartState.flags.length) {
    items.push(h("span", { class: "group" }, `${chartState.flags.length} bar(s) to review`,
      h("button", { class: "secondary", onclick: () => stepFlag(-1) }, "‹ Prev"),
      h("button", { class: "secondary", onclick: () => stepFlag(1) }, "Next ›")));
  }
  if (c.has_audio) {
    const audio = h("audio", { controls: true, preload: "none", src: `/api/charts/${c.id}/audio` });
    const follow = h("input", { type: "checkbox", checked: chartState.follow, id: "follow" });
    follow.addEventListener("change", () => (chartState.follow = follow.checked));
    audio.addEventListener("timeupdate", () => chartState.follow && followTime(audio.currentTime));
    items.push(h("span", { class: "group" }, audio, follow, h("label", { for: "follow" }, "Follow")));
  }
  $("#chart-bar").replaceChildren(...items);
}

function renderSide(c) {
  const side = $("#chart-side");
  const sum = c.summary || {};
  const v = c.validation || { checks: [] };
  const parts = [];
  if (c.view.sections.length) {
    parts.push(h("div", { class: "panel" }, h("h3", {}, "Sections"),
      h("div", { class: "sections" }, c.view.sections.map((sec) => h("button", { class: "secondary", onclick: () => {
        const i = c.view.bars.findIndex((b) => b.printed === sec.printed);
        if (i >= 0) select(i, true);
      } }, sec.name)))));
  }
  parts.push(h("div", { class: "panel" }, h("h3", {}, "Chart"),
    h("dl", { class: "kv" },
      kv("Status", STATUS_TEXT[c.status] || c.status),
      kv("Bars", `${c.bars} (${sum.printed_bars} printed, ${sum.pages} page${sum.pages === 1 ? "" : "s"})`),
      kv("Tempo", sum.tempo_estimate || (sum.tempo ? `${sum.tempo} BPM` : "")),
      kv("Meter", sum.meter || sum.time_signature),
      sum.feel ? kv("Feel", sum.feel) : null,
      sum.detected_onsets ? kv("Strokes", `${sum.detected_onsets} detected`) : null,
      kv("Made by", c.origin === "transcription" ? `automatic transcription (${sum.engine})`
                    : c.origin === "library_chart" ? "the chart library (written chart)" : "a correction of an earlier version"),
      kv("Engraving", `LilyPond ${sum.lilypond}; PDF, MusicXML and MIDI checked against the score: ${sum.rendering_ok ? "match" : "MISMATCH"}`),
      c.versions.length > 1 ? kv("Versions", c.versions.map((x) => `v${x.version} ${STATUS_TEXT[x.status] || x.status}`).join(", ")) : null)));
  parts.push(h("div", { class: "panel" }, h("h3", {}, "Checks"),
    h("ul", { class: "checks" }, v.checks.map((k) => h("li", { class: k.ok ? "ok" : k.severity === "review" ? "review" : "bad" },
      h("strong", {}, k.name), ": ", k.detail)))));
  parts.push(reviewPanel(c), namesPanel(c));
  if (sum.notes && sum.notes.length) {
    parts.push(h("div", { class: "panel" }, h("h3", {}, "Transcription notes"),
      h("ul", { class: "note" }, sum.notes.map((n) => h("li", {}, n)))));
  }
  side.replaceChildren(...parts.filter(Boolean));
}

const kv = (k, v) => [h("dt", {}, k), h("dd", {}, v ?? "")];

function reviewPanel(c) {
  if (!chartState.flags.length) return null;
  const info = h("p", { class: "note", id: "review-info" }, "Select a flagged bar (yellow), listen to it, and confirm it once it is right. " +
    "Confirming changes no notes; it records that a person checked the bar, in a new chart version.");
  const btn = h("button", { id: "confirm-bar", disabled: true, onclick: async () => {
    const b = c.view.bars[chartState.current];
    btn.disabled = true; info.textContent = "Saving a new version…";
    try {
      const nc = await api(`/api/charts/${c.id}/review`, { json: { bars: b.score_bars } });
      location.hash = `#/chart/${nc.id}`;
    } catch (e) { info.textContent = `Not saved: ${e.message}`; btn.disabled = false; }
  } }, "Confirm the selected bar");
  return h("div", { class: "panel" }, h("h3", {}, "Review"), info, btn);
}

function namesPanel(c) {
  if (!c.view.sections.length) return null;
  const inputs = c.view.sections.map((s) => h("input", { value: s.name, maxlength: 40, "data-bar": s.score_bar, "aria-label": `Name of the section at bar ${s.printed}` }));
  const msg = h("p", { class: "note" });
  let source = "user";
  const apply = h("button", { onclick: async () => {
    apply.disabled = true; msg.textContent = "Engraving a new version…";
    try {
      const nc = await api(`/api/charts/${c.id}/sections`, { json: { source, sections: inputs.map((i) => ({ first_bar: +i.dataset.bar, name: i.value })) } });
      location.hash = `#/chart/${nc.id}`;
    } catch (e) { msg.textContent = `Not applied: ${e.message}`; apply.disabled = false; }
  } }, "Apply names (new version)");
  const configured = health && health.claude.configured;
  const ask = h("button", { class: "secondary", disabled: !configured, onclick: async () => {
    ask.disabled = true; msg.replaceChildren(h("span", { class: "spinner" }), "Asking Claude…");
    try {
      const r = await api(`/api/charts/${c.id}/suggest-sections`, { method: "POST" });
      const sug = r.suggestion;
      sug.sections.forEach((s, k) => { inputs[k].value = s.name; inputs[k].title = s.reason; });
      source = "claude";
      msg.textContent = `Claude's suggestion (${sug.confidence} confidence): ${sug.comment} Review the names, then apply them.`;
    } catch (e) { msg.textContent = `Claude is unavailable: ${e.message}`; }
    ask.disabled = false;
  } }, "Suggest names with Claude");
  return h("div", { class: "panel" }, h("h3", {}, "Section names"), h("div", { class: "names" }, inputs),
    h("div", { class: "row" }, ask, apply),
    configured ? null : h("p", { class: "note" }, "Claude suggestions need ANTHROPIC_API_KEY and DRUM_AGENT_ANTHROPIC_MODEL on the server."),
    msg);
}

function setZoom(z) {
  chartState.zoom = Math.min(3, Math.max(0.4, z));
  document.documentElement.style.setProperty("--zoom", chartState.zoom.toFixed(3));
}

function select(i, scroll) {
  const prev = document.querySelector(".box.current");
  if (prev) prev.classList.remove("current");
  chartState.current = i;
  const box = document.querySelector(`.box[data-bar="${i}"]`);
  if (box) {
    box.classList.add("current");
    if (scroll) box.scrollIntoView({ block: "center", behavior: "smooth" });
  }
  const btn = $("#confirm-bar");
  const b = chartState.chart.view.bars[i];
  if (btn) {
    btn.disabled = !b.uncertain;
    btn.textContent = b.uncertain ? `Confirm bar ${b.printed}` : "Confirm the selected bar";
  }
}

function stepFlag(d) {
  const f = chartState.flags;
  chartState.flagIndex = (chartState.flagIndex + d + f.length) % f.length;
  select(f[chartState.flagIndex], true);
}

function followTime(t) {
  const tl = chartState.chart.view.timeline;
  let lo = 0, hi = tl.length - 1, k = -1;
  while (lo <= hi) { const mid = (lo + hi) >> 1; if (tl[mid].t <= t) { k = mid; lo = mid + 1; } else hi = mid - 1; }
  if (k < 0) return;
  const i = chartState.chart.view.bars.findIndex((b) => b.printed === tl[k].printed);
  if (i >= 0 && i !== chartState.current) {
    const box = document.querySelector(`.box[data-bar="${i}"]`);
    const r = box && box.getBoundingClientRect();
    select(i, !!r && (r.top < 80 || r.bottom > innerHeight));
  }
}

// ---- routing ------------------------------------------------------------------------
function route() {
  const hash = location.hash || "#/";
  let m;
  if ((m = hash.match(/^#\/song\/(s_[0-9a-f]{16})$/))) return showSong(m[1]);
  if ((m = hash.match(/^#\/chart\/(ch_[0-9a-f]{16})$/))) return showChart(m[1]);
  const q = (hash.match(/^#\/search\?q=(.*)$/) || [])[1];
  return runSearch(q ? decodeURIComponent(q) : "");
}

document.addEventListener("DOMContentLoaded", async () => {
  $("#search-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const q = $("#q").value.trim();
    if (!q) return;
    const target = `#/search?q=${encodeURIComponent(q)}`;
    if (location.hash === target) route(); else location.hash = target;
  });
  window.addEventListener("hashchange", route);
  await loadHealth();
  route();
});
