// Settings: appearance and playback preferences (this browser), and what the server has
// configured (read from /api/health; secrets are never sent to the page).

import { h, icon, prefs, applyAppearance } from "./ui.js";

export function showSettings(root, app) {
  const seg = (key, options, fallback, after) => {
    const el = h("div", { class: "seg", role: "group" });
    const draw = () => el.replaceChildren(...options.map(([v, l]) => h("button", { type: "button", "aria-pressed": String(prefs.get(key, fallback) === v),
      onclick: () => { prefs.set(key, v); draw(); after && after(); } }, l)));
    draw();
    return el;
  };
  const row = (label, help, control) => h("div", { class: "setting-row" }, h("div", {}, h("div", { class: "label" }, label), help ? h("div", { class: "help" }, help) : null), control);
  const hl = app.health || { checks: {}, providers: [], claude: {} };
  const ok = (b) => h("span", { class: `badge ${b ? "ok" : "bad"}` }, b ? "ready" : "missing");
  const prov = (p) => h("span", { class: `badge ${p.state === "enabled" ? "ok" : "plain"}` }, p.state === "enabled" ? "enabled" : "not configured");
  root.replaceChildren(h("div", { class: "lib-head" }, h("h1", {}, "Settings")), h("div", { class: "settings" },
    h("section", { class: "panel" }, h("h3", {}, "Appearance"),
      row("Theme", "Dark is tuned for the studio; light for daylight.", seg("theme", [["dark", "Dark"], ["light", "Light"], ["system", "System"]], "dark", applyAppearance)),
      row("Motion", "Reduce turns animations off. System follows your device's setting.", seg("motion", [["system", "System"], ["reduce", "Reduce"], ["full", "Full"]], "system", applyAppearance))),
    h("section", { class: "panel" }, h("h3", {}, "Playback"),
      row("Drum sounds", app.kitInfo.samples ? "Acoustic: sampled drums from the FluidR3 GM soundfont, rendered on this server." : "The sampled kit needs fluidsynth and the FluidR3 GM soundfont on the server; the electronic kit is synthesized in the browser.",
        seg("kit", [["acoustic", "Acoustic"], ["electronic", "Electronic"]], "acoustic")),
      row("Count-in", "One bar of clicks before playback starts.", seg("countin", [[true, "On"], [false, "Off"]], false)),
      row("Metronome", "A click on every beat while playing.", seg("metronome", [[true, "On"], [false, "Off"]], false)),
      row("Follow playback", "Scroll the chart to the bar being played.", seg("follow", [[true, "On"], [false, "Off"]], true))),
    h("section", { class: "panel" }, h("h3", {}, "Server and integrations"),
      h("div", { class: "int-list" },
        h("div", { class: "int" }, icon("score"), h("div", { style: { flex: 1 } }, "LilyPond engraving", h("div", { class: "d" }, hl.checks.lilypond?.version ? `version ${hl.checks.lilypond.version}` : hl.checks.lilypond?.detail || "")), ok(hl.checks.lilypond?.ok)),
        h("div", { class: "int" }, icon("upload"), h("div", { style: { flex: 1 } }, "Audio decoding (ffmpeg)"), ok(hl.checks.ffmpeg?.ok && hl.checks.ffprobe?.ok)),
        h("div", { class: "int" }, icon("drum"), h("div", { style: { flex: 1 } }, "Drum transcription model"), ok(hl.checks.onset_classifier?.ok)),
        h("div", { class: "int" }, icon("sparkle"), h("div", { style: { flex: 1 } }, "Claude", h("div", { class: "d" }, hl.claude.configured ? "Reads beat descriptions and edit requests, and suggests section names." : `Optional. Set ${(hl.claude.missing || []).join(" and ")} on the server.`)),
          h("span", { class: `badge ${hl.claude.configured ? "ai" : "plain"}` }, hl.claude.configured ? "configured" : "not configured")),
        ...hl.providers.map((p) => h("div", { class: "int" }, icon("search"), h("div", { style: { flex: 1 } }, `${p.provider} search`, h("div", { class: "d" }, "Metadata only: identifies recordings, never supplies audio.")), prov(p))),
        h("div", { class: "int" }, icon("disc"), h("div", { style: { flex: 1 } }, "Licensed audio provider", h("div", { class: "d" }, "None is configured. Songs are transcribed from recordings you upload with a rights basis, or from the operator's authorized assets.")), h("span", { class: "badge plain" }, "none")))),
    h("section", { class: "panel" }, h("h3", {}, "Keyboard"),
      h("dl", { class: "kv" }, ...[["Space", "Play / pause"], ["Ctrl+Z / Ctrl+Shift+Z", "Undo / redo"], ["Ctrl+S", "Save version"], ["Arrow keys", "Move around the grid"], ["Enter / Space on a cell", "Add or remove a stroke"], ["Ctrl+Enter", "Generate (in the description box)"]].flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])))));
}
