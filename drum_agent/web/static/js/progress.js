// A job's real progress: the stages the server reports, in order, with timings. The pads
// animate while the job runs; the bar and the stage marks move only when the server says
// a stage finished.

import { h, api } from "./ui.js";

export function progressCard(job, { title = "Working…", onCancel, onRetry } = {}) {
  const plan = job.plan && job.plan.length ? job.plan : job.stages.map((s) => ({ name: s.name, label: s.label }));
  const byName = new Map(job.stages.map((s) => [s.name, s]));
  const done = job.stages.filter((s) => s.status === "done").length;
  const state = job.status === "failed" || job.status === "cancelled" ? "failed" : job.status === "succeeded" ? "done" : "running";
  const pct = state === "done" ? 100 : Math.round((done / Math.max(1, plan.length)) * 100);
  const items = plan.map((p) => {
    const s = byName.get(p.name);
    // A stage a finished job never reached wasn't needed (e.g. no band to separate the drums from).
    const status = s ? s.status : state === "done" ? "skipped" : "pending";
    return h("li", { class: status, "data-stage": p.name },
      h("span", { class: "mark" }, status === "running" ? h("span", { class: "spinner" }) : null),
      p.label,
      status === "skipped" ? h("span", { class: "time" }, "not needed")
        : s && s.ended_at ? h("span", { class: "time" }, `${(s.ended_at - s.started_at).toFixed(1)} s`) : null);
  });
  const heading = state === "failed" ? (job.status === "cancelled" ? "Cancelled" : "Something went wrong")
    : state === "done" ? "Done" : job.status === "queued" ? "Waiting for the worker…" : title;
  return h("div", { class: `progress-card ${state}`, role: "status", "aria-live": "polite", "data-job": job.id, "data-status": job.status },
    h("div", { class: "pads", "aria-hidden": "true" }, Array.from({ length: 8 }, (_, k) => h("div", { class: "pad", style: { "--k": k } }))),
    h("div", {},
      h("div", { class: "row" }, h("strong", {}, heading), h("span", { class: "spacer" }), h("span", { class: "small muted num" }, `${pct}%`)),
      h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: { width: `${pct}%` } })),
      h("ul", { class: "stages" }, items),
      job.error ? h("p", { class: "small", style: { color: "var(--coral)", "margin-top": "10px" } }, job.error) : null,
      h("div", { class: "row", style: { "margin-top": "12px" } },
        (job.status === "queued" || job.status === "running") && onCancel ? h("button", { class: "btn sm ghost", type: "button", onclick: onCancel }, "Cancel") : null,
        (job.status === "failed" || job.status === "cancelled") && onRetry ? h("button", { class: "btn sm", type: "button", onclick: onRetry }, "Try again") : null)));
}

/** Poll a job until it finishes, calling onUpdate with each new state. Returns a stop function. */
export function watchJob(jobId, onUpdate, interval = 600) {
  let stopped = false;
  let last = "";
  const tick = async () => {
    if (stopped) return;
    try {
      const job = await api(`/api/jobs/${jobId}`);
      const sig = JSON.stringify([job.status, job.stage, job.stages.map((s) => s.status)]);
      if (sig !== last) { last = sig; onUpdate(job); }
      if (["succeeded", "failed", "cancelled"].includes(job.status)) return;
    } catch (e) {
      onUpdate(null, e);
    }
    setTimeout(tick, interval);
  };
  tick();
  return () => { stopped = true; };
}
