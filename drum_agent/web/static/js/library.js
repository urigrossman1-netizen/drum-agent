// My Charts: every project (original beats and songs), searchable.

import { h, icon, api, toast, dialog, ago, statusBadge, prefs } from "./ui.js";

export async function showLibrary(root) {
  const q = h("input", { class: "input", type: "search", placeholder: "Search your charts…", "aria-label": "Search charts", value: prefs.get("lib-q", ""), style: { "max-width": "320px" } });
  let kind = prefs.get("lib-kind", "");
  const filters = h("div", { class: "seg", role: "group", "aria-label": "Show" });
  const list = h("div", { "aria-live": "polite" });
  const draw = () => filters.replaceChildren(...[["", "All"], ["beat", "Original beats"], ["song", "Song charts"]].map(([k, label]) =>
    h("button", { type: "button", "aria-pressed": String(kind === k), onclick: () => { kind = k; prefs.set("lib-kind", k); draw(); load(); } }, label)));
  draw();
  root.replaceChildren(h("div", { class: "lib-head" }, h("h1", {}, "My Charts"), q, filters,
    h("a", { class: "btn ai", href: "#/?mode=beat" }, icon("sparkle"), "New beat")), list);
  let timer = null; let seq = 0;
  q.addEventListener("input", () => { prefs.set("lib-q", q.value); clearTimeout(timer); timer = setTimeout(load, 200); });
  async function load() {
    const my = ++seq;
    list.replaceChildren(h("div", { class: "lib-grid" }, Array.from({ length: 3 }, () => h("div", { class: "skeleton", style: { height: "120px" } }))));
    let data;
    try { data = await api(`/api/projects?q=${encodeURIComponent(q.value)}&kind=${kind}`); }
    catch (e) { if (my === seq) list.replaceChildren(h("div", { class: "empty" }, h("strong", {}, "Couldn't load your charts"), e.message)); return; }
    if (my !== seq) return;
    if (!data.projects.length) {
      list.replaceChildren(h("div", { class: "empty" }, h("strong", {}, q.value || kind ? "No charts match" : "No charts yet"),
        q.value || kind ? "Try another search." : "Describe a beat or find a song to make your first chart.",
        h("div", { class: "row", style: { "justify-content": "center", "margin-top": "14px" } },
          h("a", { class: "btn ai", href: "#/?mode=beat" }, "Create a beat"), h("a", { class: "btn", href: "#/?mode=song" }, "Find a song"))));
      return;
    }
    list.replaceChildren(h("div", { class: "lib-grid" }, data.projects.map((p, i) => card(p, i, load))));
  }
  load();
}

function card(p, i, reload) {
  const href = p.chart ? `#/chart/${p.chart.id}` : p.kind === "song" ? `#/song/${p.id}` : null;
  const facts = [p.chart ? `${p.chart.bars} bars` : "no chart yet", p.chart?.tempo ? `${Math.round(p.chart.tempo)} BPM` : null, p.chart?.time_signature,
    p.versions ? `${p.versions} version${p.versions === 1 ? "" : "s"}` : null].filter(Boolean).join(" · ");
  return h("article", { class: "proj enter", style: { "--i": Math.min(i, 12) }, "aria-label": p.title },
    h("div", { class: "row" }, h("span", { class: `badge plain ${p.kind === "beat" ? "ai" : "busy"}` }, p.kind === "beat" ? "Original beat" : "Song chart"),
      statusBadge(p.status, p.kind), p.has_draft ? h("span", { class: "badge warn plain" }, "Unsaved draft") : null),
    h("div", { class: "t", title: p.title }, p.title),
    h("div", { class: "m" }, p.kind === "song" ? p.artist : (p.prompt ? `“${p.prompt.slice(0, 90)}${p.prompt.length > 90 ? "…" : ""}”` : "Original beat")),
    h("div", { class: "m" }, facts, " · updated ", ago(p.updated_at)),
    h("div", { class: "acts" },
      href ? h("a", { class: "btn sm primary", href }, "Open") : null,
      h("button", { class: "btn sm ghost", type: "button", onclick: async () => {
        const t = await dialog({ title: "Rename", confirm: "Rename", input: { value: p.title, label: "Title" } });
        if (!t) return;
        try { await api(`/api/projects/${p.id}`, { method: "PATCH", json: { title: t } }); toast("Renamed"); reload(); } catch (e) { toast(e.message, "bad"); }
      } }, icon("edit"), "Rename"),
      h("button", { class: "btn sm ghost", type: "button", onclick: async () => {
        try { const d = await api(`/api/projects/${p.id}/duplicate`, { method: "POST" }); toast(`Duplicated as “${d.title}”`); reload(); } catch (e) { toast(e.message, "bad"); }
      } }, icon("copy"), "Duplicate"),
      h("button", { class: "btn sm ghost", type: "button", "aria-label": `Delete ${p.title}`, onclick: async () => {
        const ok = await dialog({ title: `Delete “${p.title}”?`, danger: true, confirm: "Delete",
          body: `This removes ${p.versions || "its"} version${p.versions === 1 ? "" : "s"}${p.kind === "song" ? ", any uploaded recording" : ""} and the draft. It can't be undone.` });
        if (!ok) return;
        try { await api(`/api/projects/${p.id}`, { method: "DELETE" }); toast("Deleted"); reload(); } catch (e) { toast(e.message, "bad"); }
      } }, icon("trash"))));
}
