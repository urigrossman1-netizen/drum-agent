// Drum Agent studio: routes (in the URL hash, so a refresh keeps your place) and shared state.

import { h, icon, api, applyAppearance, toast } from "./ui.js";
import { showCreate } from "./create.js";
import { showWorkspace, closeWorkspace, leaveGuard } from "./workspace.js";
import { showLibrary } from "./library.js";
import { showSettings } from "./settings.js";
import { showSong } from "./song.js";

const app = { health: null, kitInfo: { instruments: [], samples: false }, styles: [], editExamples: [] };
const main = document.getElementById("main");

async function boot() {
  applyAppearance();
  document.getElementById("logo").append(icon("drum"));
  const [health, kit, styles] = await Promise.allSettled([
    fetch("/api/health").then((r) => r.json()), api("/api/kit"), api("/api/beats/styles")]);
  if (health.status === "fulfilled") app.health = health.value;
  if (kit.status === "fulfilled") app.kitInfo = kit.value;
  if (styles.status === "fulfilled") { app.styles = styles.value.styles; app.editExamples = styles.value.edit_examples; }
  renderHealth();
  window.addEventListener("hashchange", route);
  window.addEventListener("beforeunload", (e) => { const msg = leaveGuard(); if (msg) { e.preventDefault(); e.returnValue = msg; } });
  route();
}

function renderHealth() {
  const el = document.getElementById("health");
  const hl = app.health;
  if (!hl) { el.className = "health bad"; el.querySelector(".label").textContent = "Server unreachable"; return; }
  const missing = Object.entries(hl.checks).filter(([, c]) => !c.ok).map(([k]) => k);
  el.className = `health ${hl.ok ? "ok" : "bad"}`;
  el.title = hl.ok ? `Engine ready · LilyPond ${hl.checks.lilypond.version}${hl.claude.configured ? " · Claude configured" : ""}` : `Missing: ${missing.join(", ")}`;
  el.querySelector(".label").textContent = hl.ok ? "Engine ready" : `Not ready: ${missing.join(", ")}`;
}

function setNav(name) {
  for (const a of document.querySelectorAll("[data-nav]")) {
    if (a.dataset.nav === name) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
}

function route() {
  const [path, query] = (location.hash.slice(1) || "/").split("?");
  const params = new URLSearchParams(query || "");
  const view = h("div", { class: "view" });
  let m;
  if (!(m = path.match(/^\/chart\/(ch_[0-9a-f]{16})$/))) closeWorkspace();
  main.replaceChildren(view);
  if (m) { setNav(null); document.title = "Chart · Drum Agent"; return showWorkspace(view, m[1], app); }
  if ((m = path.match(/^\/song\/(s_[0-9a-f]{16})$/))) { setNav("create"); document.title = "Song · Drum Agent"; return showSong(view, m[1], app, params); }
  if (path === "/library") { setNav("library"); document.title = "My Charts · Drum Agent"; return showLibrary(view); }
  if (path === "/settings") { setNav("settings"); document.title = "Settings · Drum Agent"; return showSettings(view, app); }
  setNav("create");
  document.title = "Drum Agent Studio";
  view.id = "create-view";
  showCreate(view, app, params);
}

window.addEventListener("unhandledrejection", (e) => { if (e.reason && e.reason.name !== "AbortError") toast(String(e.reason.message || e.reason), "bad"); });
boot();
