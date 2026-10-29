// Create a Beat, end to end in a real browser (run by tests/test_web_e2e.py):
// describe -> generate -> real events -> notation -> play -> grid edit -> notation follows ->
// tempo -> save -> reload -> reopen from My Charts -> PDF, plus drafts, words, mobile, motion.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const { execFileSync } = require("child_process");

const BASE = process.env.E2E_BASE;
const OUT = process.env.E2E_OUT;
const log = (...a) => console.log("[beat]", ...a);
function expect(cond, what) { if (!cond) throw new Error("expectation failed: " + what); log("ok -", what); }

(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 920 }, acceptDownloads: true });
  // The API as the page sees it: with its cookie (each browser is its own visitor on a shared server).
  const api = async (p) => (await ctx.request.get(BASE + p)).json();
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const shot = (n) => page.screenshot({ path: path.join(OUT, n + ".png") });
  try {
    // 1-2. Open the app, choose Create a Beat.
    await page.goto(BASE + "/");
    await page.waitForFunction(() => /Engine ready/.test(document.querySelector("#health").textContent));
    await page.click("#mode-beat");
    expect(await page.getAttribute("#mode-beat", "aria-selected") === "true", "Create a Beat is selected");
    // 3. A specific prompt: tempo, meter, groove, instruments, a fill.
    const prompt = "Create a powerful pop-punk beat at 165 BPM in 4/4 with fast eighth-note hi-hats, a driving kick, " +
      "strong snare hits and a two-bar tom fill every eight bars. 16 bars, intermediate.";
    await page.fill("#beat-prompt", prompt);
    await page.waitForFunction(() => /Tempo:\s*165/.test(document.querySelector(".understood").textContent));
    expect(/Pop-Punk/.test(await page.textContent(".understood")), "the description is understood (style, tempo shown)");
    await shot("b01-prompt");
    // 4. Generate: the stages come from the job.
    await page.click("#generate");
    await page.waitForSelector(".progress-card");
    await shot("b02-progress");
    await page.waitForURL(/#\/chart\/ch_/, { timeout: 120000 });
    const chartId = page.url().split("/chart/")[1];
    await page.waitForSelector(".page img");
    await page.waitForFunction(() => [...document.querySelectorAll(".page img")].every((i) => i.complete && i.naturalWidth > 0));
    // 5-6. Real structured events in valid measures.
    const score = await api(`/api/charts/${chartId}/files/chart.json`);
    const chart = await api(`/api/charts/${chartId}`);
    const hits = score.measures.reduce((a, m) => a + m.hits.length, 0);
    expect(score.measures.length === 16 && hits > 150, `16 bars with ${hits} real strokes`);
    expect(score.measures[0].tempo === 165 && score.measures.every((m) => m.time === "4/4"), "165 BPM, 4/4 throughout");
    expect(chart.validation.ok && chart.status === "COMPLETE", "every bar validates (structure, grid, playability)");
    const toms = score.measures.slice(6, 8).flatMap((m) => m.hits).filter((h) => /tom/.test(h.inst)).length;
    expect(toms > 0, "the two-bar fill is on the toms in bars 7-8");
    const boxes = await page.locator(".box").count();
    expect(boxes === chart.view.bars.length && boxes >= 8, `the notation shows ${boxes} mapped bars`);
    expect(/Validated/.test(await page.textContent(".ws-head")) && /Original beat/.test(await page.textContent(".ws-head")), "labelled as a validated original beat");
    await shot("b03-workspace");
    // 7. Play: the scheduled strokes are the chart's strokes at the chart's tempo.
    await page.click(".transport .play");
    await page.waitForFunction(() => window.__drumAgent.player.scheduledLog.length > 20, null, { timeout: 15000 });
    const played = await page.evaluate(() => window.__drumAgent.player.scheduledLog.filter((e) => e.bar === 0 && !e.grace));
    const bar1 = new Set(score.measures[0].hits.map((x) => `${x.pos}|${x.inst}`));
    const heard = new Set(played.map((e) => `${e.pos}|${e.inst}`));
    expect([...bar1].every((k) => heard.has(k)) && heard.size === bar1.size, `bar 1 plays exactly its ${bar1.size} strokes`);
    const eighth = played.find((e) => e.pos === "1/8");
    expect(eighth && Math.abs(eighth.t - 60 / 165 / 2) < 0.002, `an 8th note sounds ${eighth && eighth.t}s in (60/165/2)`);
    await page.waitForFunction(() => /Bar 2/.test(document.querySelector(".position").textContent), null, { timeout: 8000 });
    expect(await page.locator(".box.current").count() === 1, "the playing bar is highlighted in the notation");
    await shot("b04-playing");
    await page.click(".transport .play");
    // 8-9. Edit a hit in the grid; the notation is re-engraved with it.
    const before = await page.$eval(".page img", (i) => i.src);
    const cell = page.locator('.cell[data-bar="0"][data-pos="1/8"][data-inst="tom1"]');
    expect(await cell.getAttribute("aria-pressed") === "false", "bar 1 has no tom on the & of 1");
    await cell.click();
    expect(await cell.getAttribute("aria-pressed") === "true", "clicking the grid adds the tom");
    await page.waitForFunction((b) => document.querySelector(".page img").src !== b && /previews/.test(document.querySelector(".page img").src), before, { timeout: 30000 });
    const working = await page.evaluate(() => window.__drumAgent.score);
    expect(working.measures[0].hits.some((x) => x.inst === "tom1" && x.pos === "1/8"), "the working score has the tom");
    const svg = await (await ctx.request.get(await page.$eval(".page img", (i) => i.src))).text();
    const oldSvg = await (await ctx.request.get(before)).text();
    const count = (s) => (s.match(/class="nh" data-bar="1" data-pos="1\/8"/g) || []).length;
    expect(count(svg) === count(oldSvg) + 1, `the notation shows one more note at bar 1, & of 1 (${count(oldSvg)} -> ${count(svg)})`);
    expect(/Unsaved changes/.test(await page.textContent(".save-state")), "the edit is marked unsaved");
    await shot("b05-grid-edit");
    // 10. Change the tempo: playback follows it.
    await page.fill(".bpm", "120");
    await page.press(".bpm", "Enter");
    await page.click(".transport .play");
    await page.waitForFunction(() => window.__drumAgent.player.scheduledLog.length > 5, null, { timeout: 15000 });
    const at120 = await page.evaluate(() => window.__drumAgent.player.scheduledLog.find((e) => e.bar === 0 && e.pos === "1/4"));
    expect(at120 && Math.abs(at120.t - 0.5) < 0.002, `at 120 BPM beat 2 sounds at ${at120 && at120.t}s`);
    await page.click(".transport .play");
    // Undo and redo really edit the chart.
    await page.click('button[aria-label="Undo"]');
    expect((await page.evaluate(() => window.__drumAgent.score.measures[0].tempo)) === 165, "undo restores the tempo");
    await page.click('button[aria-label="Redo"]');
    expect((await page.evaluate(() => window.__drumAgent.score.measures[0].tempo)) === 120, "redo applies it again");
    // A plain-language edit.
    await page.fill(".side-panel textarea", "Replace the final bar with a tom fill");
    await page.click(".side-panel >> text=Apply");
    await page.waitForFunction(() => /Fill in bar 16/.test(document.querySelector(".cmd-log").textContent), null, { timeout: 10000 });
    const last = await page.evaluate(() => window.__drumAgent.score.measures[15].hits.filter((x) => /tom/.test(x.inst)).length);
    expect(last > 0, "“Replace the final bar with a tom fill” put toms in bar 16");
    await page.fill(".side-panel textarea", "make it sound like a famous band");
    await page.click(".side-panel >> text=Apply");
    await page.waitForSelector(".cmd-log .entry.bad");
    expect(/Things I can do/.test(await page.textContent(".cmd-log .entry.bad")), "an unsupported request is explained, not ignored");
    // 11. Save a version.
    await page.waitForFunction(() => document.querySelector(".engraving").hidden, null, { timeout: 30000 });
    await page.click("text=Save version");
    await page.waitForFunction(() => /Saved as version 2/.test(document.querySelector(".save-state").textContent), null, { timeout: 60000 });
    const v2 = page.url().split("/chart/")[1];
    expect(v2 !== chartId, "saving made version 2");
    // 12. Reload: the saved chart comes back.
    await page.reload();
    await page.waitForSelector(".page img");
    await page.waitForFunction(() => window.__drumAgent.score);
    const reloaded = await page.evaluate(() => window.__drumAgent.score);
    expect(reloaded.measures[0].tempo === 120 && reloaded.measures[0].hits.some((x) => x.inst === "tom1" && x.pos === "1/8"), "after a reload the chart has the edits");
    // Drafts: an unsaved edit survives a reload.
    await page.locator('.cell[data-bar="0"][data-pos="3/8"][data-inst="tom2"]').click();
    await page.waitForFunction(() => /draft kept/.test(document.querySelector(".save-state").textContent));
    await page.waitForTimeout(1800);
    await page.reload();
    await page.waitForSelector(".banner");
    expect(/Restored your unsaved changes/.test(await page.textContent(".banner")), "an unsaved edit is restored after a reload");
    expect(await page.locator('.cell[data-bar="0"][data-pos="3/8"][data-inst="tom2"]').getAttribute("aria-pressed") === "true", "the restored draft has the edit");
    await page.click(".banner >> text=Discard changes");
    await page.click("dialog button[value=ok]");
    await page.waitForFunction(() => /Saved as version 2/.test(document.querySelector(".save-state").textContent));
    await page.waitForTimeout(1500);
    // 13. My Charts: find it and reopen it.
    await page.click("nav >> text=My Charts");
    await page.waitForSelector(".proj");
    const card = page.locator(".proj", { hasText: "Pop-Punk Beat" }).first(); // the most recently updated
    expect(await card.count() === 1, "My Charts lists the beat");
    expect(/2 versions/.test(await card.textContent()), "with its 2 versions");
    await shot("b06-library");
    await card.locator("text=Open").click();
    await page.waitForSelector(".page img");
    expect(/v2/.test(await page.textContent(".ws-head")), "reopened at version 2");
    // 14-15. Download the PDF and check it holds the chart.
    await page.click(".ws-head >> text=Export");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("text=Download PDF")]);
    const pdf = path.join(OUT, "beat.pdf");
    await dl.saveAs(pdf);
    expect(fs.readFileSync(pdf).subarray(0, 4).toString() === "%PDF", "the PDF downloads: " + dl.suggestedFilename());
    const text = execFileSync("pdftotext", [pdf, "-"]).toString();
    expect(/Pop-Punk Beat/.test(text) && /Original Beat/.test(text) && /120/.test(text), "the PDF has the title, the chart type and the new tempo");
    execFileSync("pdftoppm", ["-r", "60", "-png", pdf, path.join(OUT, "beat-pdf")]);
    // Print: the print stylesheet shows only the engraved pages.
    await page.emulateMedia({ media: "print" });
    const printed = path.join(OUT, "beat-print.pdf");
    await page.pdf({ path: printed, format: "Letter" });
    await page.emulateMedia({ media: "screen" });
    const pages = (fs.readFileSync(printed, "latin1").match(/\/Type\s*\/Page[^s]/g) || []).length;
    expect(pages === chart.view.pages.length, `printing gives the chart's ${pages} page(s)`);
    // Keyboard: the mode tabs move with the arrow keys.
    await page.goto(BASE + "/#/?mode=song");
    await page.focus("#mode-song");
    await page.keyboard.press("ArrowRight");
    expect(await page.getAttribute("#mode-beat", "aria-selected") === "true", "arrow keys switch the mode");
    // Reduced motion.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.reload();
    await page.waitForSelector(".hero h1");
    const dur = await page.$eval(".hero h1", (el) => getComputedStyle(el).animationDuration);
    expect(parseFloat(dur) < 0.01, `animations are off with reduced motion (${dur})`);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    // Mobile: no sideways scrolling; the workspace is usable.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(BASE + "/#/?mode=beat");
    await page.waitForSelector("#beat-prompt");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "the create page fits a phone");
    await shot("b07-mobile-create");
    await page.goto(BASE + `/#/chart/${v2}`);
    await page.waitForSelector(".page img");
    await page.waitForTimeout(500);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "the workspace fits a phone");
    await shot("b08-mobile-workspace");
    expect(errors.length === 0, "no script errors: " + errors.join("; "));
    log("PASS");
  } catch (e) {
    await shot("zz-beat-failure").catch(() => {});
    console.error(e);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
