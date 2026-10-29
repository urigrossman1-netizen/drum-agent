// Song to Chart, end to end in a real browser (run by tests/test_web_e2e.py): a stored chart,
// a failed search, a song with no source, a refused upload (no rights, corrupt file, failed
// request), and a full-song transcription of an authorized recording through to review,
// playback and the PDF.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.E2E_BASE;
const MIX = process.env.E2E_MIX;
const CORRUPT = process.env.E2E_CORRUPT;
const OUT = process.env.E2E_OUT;
const log = (...a) => console.log("[song]", ...a);
function expect(cond, what) { if (!cond) throw new Error("expectation failed: " + what); log("ok -", what); }

(async () => {
  const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 920 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const shot = (n) => page.screenshot({ path: path.join(OUT, n + ".png") });
  const search = async (q) => { await page.fill("#song-q", q); await page.press("#song-q", "Enter"); };
  try {
    // A stored chart: found first, opened with its recording.
    await page.goto(BASE + "/#/?mode=song");
    await page.waitForSelector("#song-q");
    await search("Northbound - Drum Agent");
    await page.waitForSelector("#song-results h2");
    expect(/In your chart catalog/.test(await page.textContent("#song-results")), "the catalog is searched first");
    expect(/not configured/.test(await page.textContent(".provider-states")), "each search source reports its state");
    await shot("s01-search");
    await page.locator(".result", { hasText: "Northbound" }).locator("text=Open chart").click();
    await page.waitForSelector(".page img");
    expect(/Northbound/.test(await page.textContent(".ws-head")) && /Library chart/.test(await page.textContent(".ws-head")), "the stored chart opens, labelled as a library chart");
    expect(await page.locator(".page").count() === 2 && await page.locator(".box").count() === 48, "both pages, every engraved bar mapped (48)");
    await page.locator(".side-panel summary", { hasText: "Sections" }).click();
    await page.locator(".side-panel button", { hasText: "Bar 45" }).click();
    expect(await page.locator(".box.selected").count() >= 1, "a section button selects its bar");
    await shot("s02-library-chart");

    // A failed search request is reported.
    await page.goto(BASE + "/#/?mode=song");
    await page.route("**/api/search*", (r) => r.fulfill({ status: 502, contentType: "application/json", body: '{"detail":"metadata gateway down"}' }));
    await search("Anything - Anyone");
    await page.waitForSelector(".state-line.error");
    expect(/metadata gateway down/.test(await page.textContent(".state-line")), "a failed search shows its error");
    await page.unroute("**/api/search*");

    // A song with no authorized source.
    await search("Basement Tapes - The Testers");
    await page.waitForSelector("text=Not listed? Add the song yourself");
    await page.click("text=Add song");
    await page.waitForSelector(".page-head h1");
    expect(/Needs source/.test(await page.textContent(".page-head")), "a new song needs a source");
    expect(await page.locator(".upload").count() === 1, "and offers an upload");
    await shot("s03-needs-source");

    // Uploads that must be refused.
    await page.setInputFiles("#upload-file", CORRUPT);
    await page.click("text=Upload and transcribe");
    expect(/rights basis/.test(await page.textContent(".upload")), "the rights basis is required");
    await page.selectOption("select[name=rights]", "own");
    await page.click("text=Upload and transcribe");
    await page.waitForFunction(() => /not accepted/.test(document.querySelector(".upload").textContent));
    expect(/does not start like an audio file/.test(await page.textContent(".upload")), "a corrupt file is refused with a reason");
    await page.route("**/upload", (r) => r.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"storage unavailable"}' }));
    await page.setInputFiles("#upload-file", MIX);
    await page.click("text=Upload and transcribe");
    await page.waitForFunction(() => /storage unavailable/.test(document.querySelector(".upload").textContent));
    expect(true, "a failed upload request is reported");
    await page.unroute("**/upload");

    // The real thing: a full band mix, uploaded with a rights basis, transcribed.
    await page.setInputFiles("#upload-file", MIX);
    await page.selectOption("select[name=rights]", "original");
    await page.click("text=Upload and transcribe");
    await page.waitForSelector(".progress-card", { timeout: 60000 });
    await page.waitForSelector('.stages li[data-stage="detect"].running, .stages li[data-stage="detect"].done', { timeout: 60000 });
    await shot("s04-transcribing");
    const songId = page.url().match(/#\/song\/(s_[0-9a-f]{16})/)[1];
    await page.waitForURL(/#\/chart\/ch_[0-9a-f]{16}$/, { timeout: 300000 });
    const job = (await (await page.request.get(BASE + "/api/projects/" + songId)).json()).jobs[0];
    expect(job.stages.filter((st) => st.status === "done").length === 9, "all nine real stages completed, then the chart opened by itself");
    await page.waitForSelector(".page img");
    await page.waitForFunction(() => [...document.querySelectorAll(".page img")].every((i) => i.complete && i.naturalWidth > 0));
    expect(/Transcription/.test(await page.textContent(".ws-head")), "labelled as a transcription");
    const boxes = await page.locator(".box").count();
    expect(boxes === 60, `the whole song is charted: ${boxes} bars mapped`);
    const flags = await page.locator(".box.flag").count();
    log("flagged bars:", flags);
    expect(/Needs review/.test(await page.textContent(".ws-head")) === (flags > 0), "status is Needs review exactly when bars are flagged");
    await shot("s05-transcribed");

    // Drum playback of the transcription.
    await page.click(".transport .play");
    await page.waitForFunction(() => window.__drumAgent.player.scheduledLog.length > 10, null, { timeout: 15000 });
    expect(true, "the transcribed drum part plays");
    await page.click(".transport .play");

    // Review one flagged bar and save it as a new version.
    if (flags) {
      await page.locator(".side-panel button", { hasText: "Next ›" }).click();
      const confirm = page.locator(".side-panel button", { hasText: "is right" });
      await confirm.click();
      await page.waitForFunction(() => /Unsaved changes/.test(document.querySelector(".save-state").textContent));
      await page.waitForFunction(() => document.querySelector(".engraving").hidden, null, { timeout: 60000 });
      await page.click("text=Save version");
      await page.waitForFunction(() => /Saved as version 2/.test(document.querySelector(".save-state").textContent), null, { timeout: 120000 });
      await page.waitForSelector(".page img");
      expect(await page.locator(".box.flag").count() === flags - 1, "the checked bar is no longer flagged in version 2");
    }

    // The PDF.
    await page.click(".ws-head >> text=Export");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("text=Download PDF")]);
    const pdf = path.join(OUT, "song.pdf");
    await dl.saveAs(pdf);
    expect(fs.readFileSync(pdf).subarray(0, 4).toString() === "%PDF", "the PDF downloads: " + dl.suggestedFilename());
    expect(errors.length === 0, "no script errors: " + errors.join("; "));
    log("PASS");
  } catch (e) {
    await shot("zz-song-failure").catch(() => {});
    console.error(e);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
