// Small UI toolkit: element builder, icons, API client, toasts, dialogs, preferences.

export function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "dataset") Object.assign(el.dataset, v);
    else if (k === "style") for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
    else if (v === true) el.setAttribute(k, "");
    else el.setAttribute(k, v);
  }
  append(el, kids);
  return el;
}

function append(el, kids) {
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
}

const PATHS = {
  play: '<polygon points="7 4 20 12 7 20 7 4"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  loop: '<path d="M17 2l4 4-4 4"/><path d="M3 11v-1a4 4 0 0 1 4-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 13v1a4 4 0 0 1-4 4H3"/>',
  metronome: '<path d="M8 21h8l-2-17h-4z"/><path d="M12 15l5-9"/>',
  count: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  redo: '<path d="M15 14l5-5-5-5"/><path d="M20 9H9a5 5 0 0 0 0 10h3"/>',
  save: '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v5h7V3"/><rect x="8" y="13" width="8" height="6" rx="1"/>',
  download: '<path d="M12 3v12"/><path d="M7 10l5 5 5-5"/><path d="M5 21h14"/>',
  print: '<path d="M6 9V3h12v6"/><rect x="3" y="9" width="18" height="8" rx="2"/><path d="M7 14h10v7H7z"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/>',
  sparkle: '<path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/><path d="M19 15l.8 2.2L22 18l-2.2.8L19 21l-.8-2.2L16 18l2.2-.8z"/>',
  disc: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="2.5"/>',
  drum: '<ellipse cx="12" cy="7" rx="8" ry="3"/><path d="M4 7v9c0 1.7 3.6 3 8 3s8-1.3 8-3V7"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  sticks: '<path d="M4 20L16 6"/><path d="M8 20L20 6"/><circle cx="16.5" cy="5.5" r="1.5"/><circle cx="20.5" cy="5.5" r="1.5"/>',
  grid: '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
  score: '<path d="M3 6h18M3 10h18M3 14h18M3 18h18"/><circle cx="9" cy="10" r="2" fill="currentColor"/><path d="M11 10V3"/>',
  split: '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 12h18"/>',
  chevron: '<path d="M9 6l6 6-6 6"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  alert: '<path d="M12 3l10 18H2z"/><path d="M12 10v5"/><circle cx="12" cy="18" r="0.6" fill="currentColor"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  minus: '<path d="M5 12h14"/>',
  trash: '<path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M6 6l1 15h10l1-15"/>',
  copy: '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
  edit: '<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13 7l4 4"/>',
  wand: '<path d="M15 4V2M15 10V8M11 6h2M17 6h2"/><path d="M3 21L14 10"/>',
  library: '<path d="M4 4h4v16H4zM10 4h4v16h-4z"/><path d="M16 5l4 1-3 15-4-1z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  upload: '<path d="M12 21V9"/><path d="M7 14l5-5 5 5"/><path d="M5 3h14"/>',
  volume: '<path d="M11 5L6 9H2v6h4l5 4z"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/><path d="M19 5a10 10 0 0 1 0 14"/>',
  refresh: '<path d="M21 12a9 9 0 1 1-3-6.7L21 8"/><path d="M21 3v5h-5"/>',
  layers: '<path d="M12 2l10 6-10 6L2 8z"/><path d="M2 16l10 6 10-6"/>',
  arrowLeft: '<path d="M19 12H5"/><path d="M11 18l-6-6 6-6"/>',
  zoomIn: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M11 8v6M8 11h6"/>',
  zoomOut: '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3M8 11h6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r="0.6" fill="currentColor"/>',
};

export function icon(name, cls = "") {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", "icon " + cls);
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = PATHS[name] || "";
  return svg;
}

export class ApiError extends Error {
  constructor(message, status, body) { super(message); this.status = status; this.body = body; }
}

export async function api(path, opts = {}) {
  const init = { method: opts.method || (opts.json !== undefined ? "POST" : "GET"), headers: { Accept: "application/json" } };
  if (opts.json !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(opts.json); }
  if (opts.signal) init.signal = opts.signal;
  let res;
  try {
    res = await fetch(path, init);
  } catch (e) {
    if (e.name === "AbortError") throw e;
    throw new ApiError("The server can't be reached. Check that Drum Agent is running.", 0, null);
  }
  let body = null;
  try { body = await res.json(); } catch { body = null; }
  if (!res.ok) {
    const d = body && (body.detail || body.error);
    const msg = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg || JSON.stringify(x)).join("; ") : `Request failed (HTTP ${res.status})`;
    throw new ApiError(msg, res.status, body);
  }
  return body;
}

export function toast(message, kind = "ok", ms = 4200) {
  const box = document.getElementById("toasts");
  const el = h("div", { class: `toast ${kind}`, role: kind === "bad" ? "alert" : "status" },
    icon(kind === "bad" ? "alert" : kind === "info" ? "info" : "check"), h("div", {}, message));
  box.append(el);
  setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 260); }, ms);
}

export function dialog({ title, body, confirm = "OK", cancel = "Cancel", danger = false, input = null }) {
  return new Promise((resolve) => {
    const field = input ? h("input", { class: "input", value: input.value || "", maxlength: input.maxlength || 120, "aria-label": input.label || title }) : null;
    const ok = h("button", { class: `btn ${danger ? "danger" : "primary"}`, value: "ok" }, confirm);
    const dlg = h("dialog", { class: "modal", "aria-labelledby": "dlg-title" },
      h("form", { method: "dialog" },
        h("h2", { id: "dlg-title" }, title),
        body ? h("div", { class: "muted" }, body) : null,
        field ? h("div", { style: { "margin-top": "12px" } }, field) : null,
        h("div", { class: "actions" }, h("button", { class: "btn ghost", value: "cancel" }, cancel), ok)));
    document.body.append(dlg);
    dlg.addEventListener("close", () => {
      const v = dlg.returnValue === "ok" ? (field ? field.value.trim() : true) : null;
      dlg.remove();
      resolve(v);
    });
    dlg.showModal();
    (field || ok).focus();
    if (field) field.select();
  });
}

export const prefs = {
  get(key, fallback) {
    try { const v = localStorage.getItem("drum-agent:" + key); return v === null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("drum-agent:" + key, JSON.stringify(value)); } catch { /* private mode: not remembered */ }
  },
  remove(key) { try { localStorage.removeItem("drum-agent:" + key); } catch { /* ignore */ } },
};

export function applyAppearance() {
  const theme = prefs.get("theme", "dark");
  const sys = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.dataset.theme = theme === "system" ? sys : theme;
  const motion = prefs.get("motion", "system");
  if (motion === "system") delete document.documentElement.dataset.motion; else document.documentElement.dataset.motion = motion;
}

export function reducedMotion() {
  const m = document.documentElement.dataset.motion;
  if (m === "reduce") return true;
  if (m === "full") return false;
  return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export const fmtDur = (s) => (s ? `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, "0")}` : "");

export function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  if (s < 86400 * 7) return `${Math.floor(s / 86400)} d ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

export const STATUS = {
  COMPLETE: ["Complete", "ok"], NEEDS_CORRECTION: ["Needs review", "warn"], NEEDS_SOURCE: ["Needs source", "bad"],
  NOT_STARTED: ["Source ready", "plain"], ANALYZING: ["Analyzing audio", "busy"], TRANSCRIBING: ["Transcribing", "busy"],
  VERIFYING: ["Validating chart", "busy"], GENERATING: ["Generating", "busy"], FAILED: ["Generation failed", "bad"],
};

export function statusBadge(status, kind) {
  let [label, cls] = STATUS[status] || [status, "plain"];
  if (kind === "beat" && status === "COMPLETE") label = "Validated";
  if (kind === "beat" && status === "FAILED") label = "Generation failed";
  if (kind === "song" && status === "FAILED") label = "Transcription failed";
  return h("span", { class: `badge ${cls}` }, label);
}

export function menu(button, items) {
  let list = null;
  const close = () => { if (list) { list.remove(); list = null; button.setAttribute("aria-expanded", "false"); document.removeEventListener("click", outside, true); } };
  const outside = (e) => { if (list && !list.contains(e.target) && e.target !== button && !button.contains(e.target)) close(); };
  button.setAttribute("aria-haspopup", "menu");
  button.setAttribute("aria-expanded", "false");
  button.addEventListener("click", () => {
    if (list) return close();
    list = h("div", { class: "menu-list", role: "menu" }, items().map((it) => {
      const el = it.href ? h("a", { href: it.href, role: "menuitem", download: it.download ? "" : null }, it.icon ? icon(it.icon) : null, it.label)
        : h("button", { role: "menuitem", type: "button" }, it.icon ? icon(it.icon) : null, it.label);
      el.addEventListener("click", () => { close(); if (it.onClick) it.onClick(); });
      return el;
    }));
    button.parentElement.append(list);
    button.setAttribute("aria-expanded", "true");
    setTimeout(() => document.addEventListener("click", outside, true));
    list.querySelector("a,button")?.focus();
    list.addEventListener("keydown", (e) => { if (e.key === "Escape") { close(); button.focus(); } });
  });
  return { close };
}
