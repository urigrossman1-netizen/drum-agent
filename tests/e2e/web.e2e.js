// Browser end-to-end test of the web app (run by tests/test_web_e2e.py, which starts the
// server and prepares the files). Exits non-zero on the first failed expectation.
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = process.env.E2E_BASE;
const MIX = process.env.E2E_MIX;          // a full-song band mix we have the rights to (original)
const CORRUPT = process.env.E2E_CORRUPT;  // a file that claims to be an MP3
const OUT = process.env.E2E_OUT;          // screenshots and downloads
const log = (...a) => console.log("[e2e]", ...a);
function expect(cond, what) { if (!cond) throw new Error("expectation failed: " + what); log("ok -", what); }

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const shot = (name) => page.screenshot({ path: path.join(OUT, name + ".png") });
  try {
    // 1. Health and the existing chart in the catalog.
    await page.goto(BASE + "/");
    await page.waitForFunction(() => /LilyPond/.test(document.querySelector("#health").textContent));
    await page.fill("#q", "Northbound - Drum Agent");
    await page.press("#q", "Enter");
    await page.waitForSelector("#results h2:text('In the chart catalog')");
    expect(await page.locator("#results .card", { hasText: "Northbound" }).count() >= 1, "search finds the stored chart");
    expect(await page.locator(".providers").textContent().then((t) => /not configured/.test(t)), "provider states are shown");
    await shot("01-search");
    await page.locator("#results .card", { hasText: "Complete" }).locator("text=Open chart").click();
    await page.waitForSelector(".page img");
    await page.waitForFunction(() => [...document.querySelectorAll(".page img")].every((i) => i.complete && i.naturalWidth > 0));
    expect(await page.locator(".page").count() === 2, "the written song chart has two pages");
    expect(await page.locator(".box").count() === 48, "every engraved bar of the written chart is mapped (48)");
    await page.locator(".sections button", { hasText: "Bridge" }).click();
    expect(await page.locator(".box.current").getAttribute("title") === "Bar 37", "the Bridge button jumps to bar 37");
    await page.fill('input[aria-label="Go to bar"]', "30");
    await page.press('input[aria-label="Go to bar"]', "Enter");
    expect(await page.locator(".box.current").getAttribute("title") === "Bar 30", "go to bar 30");
    await shot("02-written-chart");
    await page.emulateMedia({ media: "print" });
    const printed = path.join(OUT, "print.pdf");
    await page.pdf({ path: printed, format: "Letter", printBackground: false });
    await page.emulateMedia({ media: "screen" });
    const pages = (fs.readFileSync(printed, "latin1").match(/\/Type\s*\/Page[^s]/g) || []).length;
    expect(pages === 2, `printing gives the chart's two pages (got ${pages})`);

    // 2. A failed search request is reported.
    await page.route("**/api/search*", (r) => r.fulfill({ status: 502, contentType: "application/json", body: '{"detail":"metadata gateway down"}' }));
    await page.goto(BASE + "/#/search?q=" + encodeURIComponent("Anything - Anyone"));
    await page.waitForSelector("#search-state.error");
    expect(/metadata gateway down/.test(await page.textContent("#search-state")), "a failed search shows its error");
    await page.unroute("**/api/search*");

    // 3. A song with no authorized source.
    await page.goto(BASE + "/#/search?q=" + encodeURIComponent("Basement Tapes - The Testers"));
    await page.waitForSelector("text=Not listed? Add the song yourself");
    await page.click("text=Add song");
    await page.waitForSelector("#song-view .badge");
    expect(/Needs a recording/.test(await page.textContent("#song-view h2")), "a new song needs a source");
    expect(await page.locator("h3", { hasText: "Upload a recording" }).count() === 1, "the upload action is offered");
    await shot("03-needs-source");

    // 4. Upload without a rights basis, then a corrupt file, then a failing request.
    await page.setInputFiles('input[type=file]', CORRUPT);
    await page.click("text=Upload and transcribe");
    expect(/rights basis/.test(await page.textContent(".upload")), "the rights basis is required");
    await page.selectOption("select[name=rights]", "own");
    await page.click("text=Upload and transcribe");
    await page.waitForSelector(".upload .error-text");
    expect(/does not start like an audio file/.test(await page.textContent(".upload .error-text")), "a corrupt file is refused with a reason");
    await shot("04-corrupt");
    await page.route("**/upload", (r) => r.fulfill({ status: 500, contentType: "application/json", body: '{"detail":"storage unavailable"}' }));
    await page.setInputFiles('input[type=file]', MIX);
    await page.click("text=Upload and transcribe");
    await page.waitForSelector(".upload .error-text");
    expect(/storage unavailable/.test(await page.textContent(".upload .error-text")), "a failed upload request is reported");
    await page.unroute("**/upload");

    // 5. The real thing: upload the full band mix and watch the stages.
    await page.setInputFiles('input[type=file]', MIX);
    await page.selectOption("select[name=rights]", "original");
    await page.click("text=Upload and transcribe");
    await page.waitForSelector("#job .stages li", { timeout: 60000 });
    await page.waitForSelector("text=Detecting drum strokes", { timeout: 60000 });
    await shot("05-progress");
    await page.waitForSelector("text=Open the chart", { timeout: 300000 });
    const stages = await page.locator("#job .stages li.done").count();
    expect(stages === 9, `all nine stages completed (${stages})`);
    await page.click("text=Open the chart");
    await page.waitForSelector(".page img");
    await page.waitForFunction(() => [...document.querySelectorAll(".page img")].every((i) => i.complete && i.naturalWidth > 0));
    const boxes = await page.locator(".box").count();
    expect(boxes === 60, `the transcription maps all 60 bars of the song (${boxes})`);
    const flags = await page.locator(".box.flag").count();
    log("flagged bars:", flags);
    await shot("06-transcribed-chart");

    // 6. Playback follow: the bar under the audio position is highlighted.
    await page.evaluate(() => new Promise((res) => {
      const a = document.querySelector("audio");
      a.preload = "auto";
      a.addEventListener("loadedmetadata", () => { a.currentTime = 60; a.addEventListener("seeked", () => { a.dispatchEvent(new Event("timeupdate")); res(); }, { once: true }); }, { once: true });
      a.load();
    }));
    const followed = await page.locator(".box.current").getAttribute("title");
    const bar = parseInt(followed.replace(/\D+/g, " ").trim().split(" ")[0], 10);
    expect(bar >= 20 && bar <= 24, `at 60 s (84 BPM) the highlighted bar is about bar 22 (got ${bar})`);

    // 7. Download the PDF.
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click('#chart-bar a:has-text("PDF")')]);
    const saved = path.join(OUT, await dl.suggestedFilename());
    await dl.saveAs(saved);
    expect(fs.readFileSync(saved).subarray(0, 4).toString() === "%PDF", "the PDF downloads: " + path.basename(saved));

    // 8. Review a flagged bar: a new version.
    if (flags) {
      await page.click("text=Next ›");
      await page.click("#confirm-bar");
      await page.waitForFunction(() => /v2/.test(document.querySelector("#chart-bar").textContent), null, { timeout: 120000 });
      await page.waitForSelector(".box");
      expect(await page.locator(".box.flag").count() === flags - 1, "confirming a bar clears its flag in version 2");
    }

    // 9. Refresh keeps the place.
    await page.reload();
    await page.waitForSelector(".page img");
    expect(/v2|v1/.test(await page.textContent("#chart-bar")), "a refresh reopens the same chart");
    expect(errors.length === 0, "no script errors: " + errors.join("; "));
    log("PASS");
  } catch (e) {
    await shot("zz-failure").catch(() => {});
    console.error(e);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
