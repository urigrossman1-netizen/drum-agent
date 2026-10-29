// A song: which recording it is, where its audio comes from, and the job that charts it.
// In the personal app (Drum Agent on your own computer) a song is charted from its name: the
// app finds the recording among your own audio files (your music folders) and transcribes it,
// for your own practice. Otherwise the recording is uploaded, with the rights basis that
// allows transcribing it. A song found on YouTube can be played with YouTube's own player;
// its audio is never downloaded.

import { h, icon, api, toast, prefs, fmtDur, statusBadge, dialog } from "./ui.js";
import { progressCard, watchJob } from "./progress.js";

const CASE = {
  EXISTING_CHART: ["A chart for this recording is stored.", "ok"],
  AUTHORIZED_ASSET: ["An authorized recording is available on the server.", "ok"],
  USER_UPLOAD: ["You uploaded a recording for this song.", "ok"],
  LOCAL_FILE: ["The recording was taken from your music folders.", "ok"],
  MUSIC_FOLDERS: ["Ready: Drum Agent will look for this song in your music folders and chart it.", "ok"],
  LICENSED_SOURCE: ["A licensed audio source is available.", "ok"],
  NEEDS_SOURCE: ["Needs source: the recording is identified, but no audio is available to transcribe.", "bad"],
};
const ACK = "personal_ack";

let stopWatch = null;
const autoOpen = new Set();  // jobs started from this page: their chart opens by itself when it's ready

export async function showSong(root, id, app, params = new URLSearchParams()) {
  if (stopWatch) { stopWatch(); stopWatch = null; }
  let d;
  try { d = await api(`/api/projects/${id}`); }
  catch (e) { root.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "This song could not be loaded"), e.message)); return; }
  if (d.kind === "beat") { if (d.chart) location.hash = `#/chart/${d.chart.id}`; else location.hash = "#/library"; return; }
  const lib = !!app.health?.library?.available;
  const meta = [d.album, d.year, d.version, d.chart?.time_signature].filter(Boolean).join(" · ");
  const [text, cls] = CASE[d.resolution.case] || [d.resolution.case, "plain"];
  const job = d.jobs[0];
  const running = job && (job.status === "queued" || job.status === "running");
  const jobHost = h("div", {});
  const file = d.sources.find((s) => s.kind === "library")?.library;
  const left = h("div", { class: "stack" },
    h("div", { class: "panel" }, h("h3", {}, "Source"),
      h("div", { class: "row" }, h("span", { class: `badge ${cls}` }, d.resolution.case.replace(/_/g, " ").toLowerCase()), h("strong", {}, text)),
      h("p", { class: "small muted", style: { "margin-top": "8px" } }, d.resolution.detail),
      file ? fileLine(file) : null),
    youtubePanel(d),
    jobHost);
  const right = h("div", { class: "stack" });
  if (d.charts.length) {
    right.append(h("div", { class: "panel" }, h("h3", {}, "Charts"), h("div", { class: "versions" }, d.charts.map((c) =>
      h("div", { class: "v" }, h("strong", { class: "num" }, `v${c.version}`), statusBadge(c.status, "song"),
        h("span", { class: "muted small", style: { flex: 1 } }, `${c.bars} bars · ${c.note || c.origin.replace("_", " ")}`),
        c.shareable === false ? h("span", { class: "badge plain", title: "For your own practice" }, "personal") : null,
        h("a", { class: "btn sm primary", href: `#/chart/${c.id}` }, "Open"))))));
  }
  // A job was started here: the page is drawn again, with the job and without the other choices.
  const started = (r) => { autoOpen.add(r.job.id); showSong(root, id, app); };
  if (!running) {
    if (lib && !d.charts.length) right.append(libraryPanel(id, params.get("go") === "1", started));
    if (lib) right.append(filesPanel(id, d, started));
    if (d.resolution.case === "AUTHORIZED_ASSET" && !d.resolution.source_id) {
      right.append(h("div", { class: "panel" }, h("h3", {}, "Authorized recording"), h("button", { class: "btn primary", type: "button", onclick: async () => {
        try { started(await api(`/api/songs/${id}/use-asset`, { method: "POST" })); } catch (e) { toast(e.message, "bad"); }
      } }, "Transcribe the authorized recording")));
    }
    if (!lib && app.health?.library?.reason === "shared_server" && !d.charts.length) {
      right.append(h("div", { class: "panel" }, h("h3", {}, "Chart it from its name"),
        h("p", { class: "small" }, "In the Drum Agent app on your own computer you only type the song: it finds the recording among your own music files, listens to it and writes the drum chart. This online studio works from recordings you upload.")));
    }
    right.append(uploadPanel(id, app, d.charts.length > 0 || d.resolution.case === "USER_UPLOAD", lib, started));
  }
  root.replaceChildren(
    h("div", { class: "page-head" },
      h("a", { class: "btn icon-only ghost", href: "#/?mode=song", "aria-label": "Back to search" }, icon("arrowLeft")),
      h("div", { style: { flex: 1, "min-width": "240px" } }, h("h1", {}, `${d.title} — ${d.artist}`), h("p", { class: "muted small" }, meta || "Song")),
      statusBadge(d.status, "song")),
    h("div", { class: "grid-2" }, left, right));

  function watch(j) {
    const title = j.kind === "library" ? "Finding the song and writing the chart" : "Transcribing the recording";
    const draw = (x) => jobHost.replaceChildren(progressCard(x, { title,
      onCancel: async () => { try { await api(`/api/jobs/${x.id}/cancel`, { method: "POST" }); } catch (e) { toast(e.message, "bad"); } },
      onRetry: async () => { try { started({ job: await api(`/api/jobs/${x.id}/retry`, { method: "POST" }) }); } catch (e) { toast(e.message, "bad"); } } }));
    draw(j);
    if (stopWatch) stopWatch();
    stopWatch = watchJob(j.id, (x, err) => {
      if (err) return;
      draw(x);
      if (x.status === "succeeded" && x.chart_id) {
        if (autoOpen.delete(x.id) && location.hash.startsWith(`#/song/${id}`)) { location.hash = `#/chart/${x.chart_id}`; return; }
        jobHost.querySelector(".progress-card")?.append(h("a", { class: "btn primary", href: `#/chart/${x.chart_id}`, style: { "margin-top": "12px" } }, "Open the chart"));
      }
    });
  }
  if (job) watch(job);
}

function fileLine(f) {
  return h("p", { class: "small", style: { "margin-top": "8px" } }, icon("disc"), " From your music: ",
    h("strong", {}, f.file), f.folder ? h("span", { class: "muted" }, ` · ${f.folder}`) : "",
    f.duration_s ? ` · ${fmtDur(f.duration_s)}` : "");
}

/** YouTube's own player, for a song found through the YouTube Data API: to listen, not to chart. */
function youtubePanel(d) {
  const vid = (d.provider_ids || {}).youtube;
  if (!vid || !/^[A-Za-z0-9_-]{6,20}$/.test(vid)) return null;
  return h("div", { class: "panel stack" }, h("h3", {}, "Listen on YouTube"),
    h("div", { class: "embed" }, h("iframe", { src: `https://www.youtube-nocookie.com/embed/${vid}`, title: `${d.title} on YouTube`,
      loading: "lazy", allow: "encrypted-media; picture-in-picture; fullscreen", referrerpolicy: "strict-origin-when-cross-origin" })),
    h("p", { class: "tiny muted" }, "YouTube's own player, for listening. Drum Agent never downloads YouTube audio: to chart the song, use a recording you have."));
}

/** The personal-practice confirmation and the button that finds and charts the song. With the
 *  confirmation given before and `go` (the user came here by choosing the song), it starts at once. */
function libraryPanel(id, go, onStarted) {
  const ack = h("input", { type: "checkbox", id: "personal-ack", checked: !!prefs.get(ACK, false) });
  const btn = h("button", { class: "btn primary lg", type: "button", disabled: !prefs.get(ACK, false) }, icon("sparkle"), "Find it and make the chart");
  const msg = h("p", { class: "small", role: "status", "aria-live": "polite" });
  ack.addEventListener("change", () => { btn.disabled = !ack.checked; });
  const start = async () => {
    btn.disabled = true;
    prefs.set(ACK, true);
    msg.textContent = "Starting…";
    try { onStarted(await api(`/api/songs/${id}/library`, { json: { personal: true } })); }
    catch (e) { btn.disabled = false; msg.style.color = "var(--coral)"; msg.textContent = e.message; }
  };
  btn.addEventListener("click", start);
  const panel = h("div", { class: "panel stack find" },
    h("h3", {}, "Make the chart"),
    h("p", { class: "small" }, "Drum Agent looks for this song among your own audio files (your music folders), listens to the drums and writes the chart. It takes a few minutes; you can watch each step."),
    h("label", { class: "check", for: "personal-ack" }, ack, h("span", { class: "small" }, "This chart is for my own practice. I won't post it publicly (that needs the music publisher's permission).")),
    btn, msg);
  if (go && prefs.get(ACK, false)) setTimeout(start);
  return panel;
}

/** The files in the music folders that match the song (a live take, a remaster...): pick one. */
function filesPanel(id, d, onStarted) {
  const list = h("div", { class: "video-list" });
  const show = h("button", { class: "btn sm", type: "button" }, icon("search"), d.charts.length ? "Chart another file" : "Choose the file yourself");
  const use = async (file) => {
    if (!prefs.get(ACK, false) && !(await dialog({ title: "For your own practice", confirm: "Make the chart",
      body: "The chart is for your own practice. You won't post it publicly: that needs the music publisher's permission." }))) return;
    prefs.set(ACK, true);
    try { onStarted(await api(`/api/songs/${id}/library`, { json: { personal: true, file } })); }
    catch (e) { toast(e.message, "bad"); }
  };
  show.addEventListener("click", async () => {
    show.disabled = true;
    list.replaceChildren(h("div", { class: "state-line" }, h("span", { class: "spinner" }), "Looking in your music folders…"));
    try {
      const r = await api(`/api/songs/${id}/library`);
      list.replaceChildren(...(r.files.length ? r.files.map((f) => h("div", { class: "video" },
        h("div", { class: "what" }, h("div", { class: "title" }, f.name), h("div", { class: "meta small muted" },
          [f.title && f.artist ? `${f.title} - ${f.artist}` : null, fmtDur(f.duration_s), f.folder].filter(Boolean).join(" · "),
          f.length_off != null && !f.length_ok ? h("span", { class: "badge warn", style: { "margin-left": "6px" } }, "different length") : null)),
        h("button", { class: "btn sm", type: "button", onclick: () => use(f.file) }, "Use this"))) : [h("p", { class: "small muted" }, `Nothing found in ${r.folders.join(", ")}.`)]),
        ...r.warnings.map((w) => h("p", { class: "tiny muted" }, w)));
    } catch (e) { list.replaceChildren(h("p", { class: "small", style: { color: "var(--coral)" } }, e.message)); }
    show.disabled = false;
  });
  return h("div", { class: "panel stack" }, h("h3", {}, "Wrong file?"),
    h("p", { class: "small muted" }, "The best match is taken automatically: the same title and artist, the plain recording before a live take or a remix."),
    show, list);
}

function uploadPanel(id, app, again, lib, onStarted) {
  const rights = app.health?.rights_options || {};
  const file = h("input", { type: "file", accept: ".wav,.mp3,.flac,.m4a,.aac,.ogg,audio/*", id: "upload-file" });
  const name = h("div", { class: "small", style: { "margin-top": "6px" } }, "Drop an audio file here, or choose one");
  const zone = h("label", { class: "dropzone", for: "upload-file" }, icon("upload"), name, file);
  const select = h("select", { class: "select", name: "rights", required: true, "aria-label": "Rights basis" },
    h("option", { value: "" }, "Choose your rights basis…"), Object.entries(rights).map(([k, v]) => h("option", { value: k }, v)));
  const bar = h("div", { class: "upload-progress", hidden: true }, h("div", {}));
  const msg = h("p", { class: "small", role: "status", "aria-live": "polite" });
  const go = h("button", { class: "btn primary", type: "submit" }, icon("upload"), "Upload and transcribe");
  let chosen = null;
  const pick = (f) => { chosen = f; name.textContent = f ? `${f.name} · ${(f.size / 2 ** 20).toFixed(1)} MB` : "Drop an audio file here, or choose one"; };
  file.addEventListener("change", () => pick(file.files[0] || null));
  zone.addEventListener("dragover", (e) => { e.preventDefault(); zone.classList.add("over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("over"));
  zone.addEventListener("drop", (e) => { e.preventDefault(); zone.classList.remove("over"); pick(e.dataTransfer.files[0] || null); });
  const form = h("form", { class: "panel stack upload" },
    h("h3", {}, lib ? "Or upload a recording" : again ? "Upload another recording" : "Upload a recording"),
    h("p", { class: "small muted" }, `WAV, MP3, FLAC, M4A, AAC or OGG, up to ${app.health?.limits?.max_upload_mb || 200} MB. ${lib ? "A recording of your band, or a song file you have: say what lets you transcribe it." : "Full transcription needs a rights basis: a recording you made or own, the rights holder's permission, a licence, public-domain material, or your own composition."}`),
    zone, select, go, bar, msg);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    if (!chosen || !select.value) { msg.style.color = "var(--coral)"; msg.textContent = "Choose a file and your rights basis."; return; }
    const fd = new FormData();
    fd.append("file", chosen); fd.append("rights", select.value);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/songs/${id}/upload`);
    xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) { bar.hidden = false; bar.firstChild.style.width = `${(100 * ev.loaded) / ev.total}%`; } };
    xhr.onload = () => {
      let body = null; try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      go.disabled = false; bar.hidden = true;
      if (xhr.status >= 200 && xhr.status < 300) { onStarted(body); return; }
      msg.style.color = "var(--coral)";
      msg.textContent = "The file was not accepted: " + ((body && (body.detail || body.error)) || `HTTP ${xhr.status}`);
    };
    xhr.onerror = () => { go.disabled = false; msg.style.color = "var(--coral)"; msg.textContent = "The upload failed (network error)."; };
    go.disabled = true; msg.style.color = ""; msg.textContent = "Uploading, then checking and decoding the audio…";
    xhr.send(fd);
  });
  return form;
}
