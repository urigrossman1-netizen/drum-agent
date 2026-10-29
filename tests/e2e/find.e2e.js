// A song from its name, end to end in a real browser (run by tests/test_web_e2e.py): the
// personal app with a stand-in for yt-dlp. Type the song, add it, confirm it's for your own
// practice, watch it being found on YouTube, downloaded and charted, land on the chart, and
// check it is marked as a personal-practice chart and says which video it came from.
const { chromium } = require("playwright");
const path = require("path");

const BASE = process.env.E2E_BASE;
const OUT = process.env.E2E_OUT;
const log = (...a) => console.log("[find]", ...a);
function expect(cond, what) { if (!cond) throw new Error("expectation failed: " + what); log("ok -", what); }

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 920 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  const shot = (n) => page.screenshot({ path: path.join(OUT, n + ".png") });
  try {
    const health = await (await page.request.get(BASE + "/api/health")).json();
    expect(health.mode === "personal" && health.online.available, "the personal app, with yt-dlp available");
    expect("personal" in health.rights_options, "\"for my own practice\" is a rights basis here");

    await page.goto(BASE + "/");
    await page.waitForSelector("#song-q");
    expect(await page.getAttribute("#mode-song", "aria-selected") === "true", "the personal app opens on Song to Chart");
    expect(/finds it on YouTube/.test(await page.textContent("#mode-panel")), "the hint says the song is found on YouTube");
    await page.fill("#song-q", "Test Groove - The Placeholders");
    await page.press("#song-q", "Enter");
    await page.waitForSelector("#song-results form");
    await shot("f01-search");
    await page.locator("#song-results form button[type=submit]").click();  // "Add song": title and artist prefilled

    await page.waitForSelector(".find");
    expect(/\?go=1$/.test(page.url()), "adding the song goes straight to charting it");
    const go = page.locator(".find button.primary");
    expect(await go.isDisabled(), "nothing starts before the personal-practice confirmation");
    await shot("f02-confirm");
    await page.check("#personal-ack");
    await go.click();
    await page.waitForSelector(".progress-card");
    const labels = await page.locator(".progress-card .stages li").allTextContents();
    expect(/Finding the song on YouTube/.test(labels[0]) && /Downloading the audio/.test(labels[1]), "the first stages: find it, download it");
    await shot("f03-progress");

    await page.waitForURL(/#\/chart\/ch_[0-9a-f]{16}$/, { timeout: 300000 });
    await page.waitForSelector(".page img");
    const head = await page.textContent(".ws-head");
    expect(/Test Groove/.test(head) && /Transcription/.test(head), "the chart opens by itself when it's ready");
    expect(/Personal practice/.test(head), "it is marked as a personal-practice chart");
    expect(await page.locator(".box").count() >= 8, "every engraved bar is mapped (8 bars or more)");
    await shot("f04-chart");

    await page.locator(".ws-head a[aria-label=Back]").click();
    await page.waitForSelector(".page-head");
    const source = await page.textContent(".grid-2");
    expect(/From YouTube: The Placeholders - Test Groove \(Official Audio\)/.test(source), "the song says which video it was charted from");
    expect(/personal/.test(source), "its chart version is listed as personal");
    await page.locator("button", { hasText: "Chart another version" }).click();
    await page.waitForSelector(".video-list .video");
    const videos = await page.locator(".video-list .video .title").allTextContents();
    expect(videos.length === 3 && videos[0] === "The Placeholders - Test Groove (Official Audio)", "other uploads are listed, the official one first");
    await shot("f05-versions");

    await page.goto(BASE + "/#/?mode=song");
    await page.fill("#song-q", "Test Groove - The Placeholders");
    await page.press("#song-q", "Enter");
    await page.waitForSelector("#song-results .result");
    expect(/In your chart catalog/.test(await page.textContent("#song-results")), "next time the song is in the catalog");

    expect(errors.length === 0, "no page errors: " + errors.join(" | "));
    log("PASS");
  } catch (e) {
    console.error(e);
    await shot("f99-failure").catch(() => {});
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
