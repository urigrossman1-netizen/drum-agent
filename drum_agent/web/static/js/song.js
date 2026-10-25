// A song: which recording it is, whether there is a chart or an authorized source, the
// upload (with the rights basis) and the transcription job.

import { h, icon, api, toast, fmtDur, statusBadge } from "./ui.js";
import { progressCard, watchJob } from "./progress.js";

const CASE = {
  EXISTING_CHART: ["A chart for this recording is stored.", "ok"],
  AUTHORIZED_ASSET: ["An authorized recording is available on the server.", "ok"],
  USER_UPLOAD: ["You uploaded a recording for this song.", "ok"],
  LICENSED_SOURCE: ["A licensed audio source is available.", "ok"],
  NEEDS_SOURCE: ["Needs source: the recording is identified, but no authorized audio is available to transcribe.", "bad"],
};

let stopWatch = null;

export async function showSong(root, id, app) {
  if (stopWatch) { stopWatch(); stopWatch = null; }
  let d;
  try { d = await api(`/api/projects/${id}`); }
  catch (e) { root.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "This song could not be loaded"), e.message)); return; }
  if (d.kind === "beat") { if (d.chart) location.hash = `#/chart/${d.chart.id}`; else location.hash = "#/library"; return; }
  const meta = [d.album, d.year, d.version, d.chart?.time_signature].filter(Boolean).join(" · ");
  const [text, cls] = CASE[d.resolution.case] || [d.resolution.case, "plain"];
  const job = d.jobs[0];
  const running = job && (job.status === "queued" || job.status === "running");
  const jobHost = h("div", {});
  const left = h("div", { class: "stack" },
    h("div", { class: "panel" }, h("h3", {}, "Source"),
      h("div", { class: "row" }, h("span", { class: `badge ${cls}` }, d.resolution.case.replace(/_/g, " ").toLowerCase()), h("strong", {}, text)),
      h("p", { class: "small muted", style: { "margin-top": "8px" } }, d.resolution.detail)),
    jobHost);
  const right = h("div", { class: "stack" });
  if (d.charts.length) {
    right.append(h("div", { class: "panel" }, h("h3", {}, "Charts"), h("div", { class: "versions" }, d.charts.map((c) =>
      h("div", { class: "v" }, h("strong", { class: "num" }, `v${c.version}`), statusBadge(c.status, "song"),
        h("span", { class: "muted small", style: { flex: 1 } }, `${c.bars} bars · ${c.note || c.origin.replace("_", " ")}`),
        h("a", { class: "btn sm primary", href: `#/chart/${c.id}` }, "Open"))))));
  }
  if (!running) {
    if (d.resolution.case === "AUTHORIZED_ASSET" && !d.resolution.source_id) {
      right.append(h("div", { class: "panel" }, h("h3", {}, "Authorized recording"), h("button", { class: "btn primary", type: "button", onclick: async () => {
        try { const r = await api(`/api/songs/${id}/use-asset`, { method: "POST" }); watch(r.job); } catch (e) { toast(e.message, "bad"); }
      } }, "Transcribe the authorized recording")));
    }
    right.append(uploadPanel(id, app, d.charts.length > 0 || d.resolution.case === "USER_UPLOAD", (r) => watch(r.job)));
  }
  root.replaceChildren(
    h("div", { class: "page-head" },
      h("a", { class: "btn icon-only ghost", href: "#/?mode=song", "aria-label": "Back to search" }, icon("arrowLeft")),
      h("div", { style: { flex: 1, "min-width": "240px" } }, h("h1", {}, `${d.title} — ${d.artist}`), h("p", { class: "muted small" }, meta || "Song")),
      statusBadge(d.status, "song")),
    h("div", { class: "grid-2" }, left, right));
  function watch(j) {
    const draw = (x) => jobHost.replaceChildren(progressCard(x, { title: "Transcribing the recording",
      onCancel: async () => { try { await api(`/api/jobs/${x.id}/cancel`, { method: "POST" }); } catch (e) { toast(e.message, "bad"); } },
      onRetry: async () => { try { const n = await api(`/api/jobs/${x.id}/retry`, { method: "POST" }); watch(n); } catch (e) { toast(e.message, "bad"); } } }));
    draw(j);
    if (stopWatch) stopWatch();
    stopWatch = watchJob(j.id, (x, err) => {
      if (err) return;
      draw(x);
      if (x.status === "succeeded" && x.chart_id) {
        jobHost.querySelector(".progress-card")?.append(h("a", { class: "btn primary", href: `#/chart/${x.chart_id}`, style: { "margin-top": "12px" } }, "Open the chart"));
      }
    });
  }
  if (job) watch(job);
}

function uploadPanel(id, app, again, onStarted) {
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
    h("h3", {}, again ? "Upload another recording" : "Upload a recording"),
    h("p", { class: "small muted" }, `WAV, MP3, FLAC, M4A, AAC or OGG, up to ${app.health?.limits?.max_upload_mb || 200} MB. Full transcription needs a rights basis: a recording you made or own, the rights holder's permission, a licence, public-domain material, or your own composition.`),
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
      if (xhr.status >= 200 && xhr.status < 300) { msg.style.color = "var(--mint)"; msg.textContent = body.created ? "Accepted. Transcribing…" : "This recording was already analyzed; showing that job."; onStarted(body); form.remove(); return; }
      msg.style.color = "var(--coral)";
      msg.textContent = "The file was not accepted: " + ((body && (body.detail || body.error)) || `HTTP ${xhr.status}`);
    };
    xhr.onerror = () => { go.disabled = false; msg.style.color = "var(--coral)"; msg.textContent = "The upload failed (network error)."; };
    go.disabled = true; msg.style.color = ""; msg.textContent = "Uploading, then checking and decoding the audio…";
    xhr.send(fd);
  });
  return form;
}
