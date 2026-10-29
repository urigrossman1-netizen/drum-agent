// Every page on a phone (run by tests/test_web_e2e.py): a 390 x 844 touch screen. Each page
// must fit the screen's width (nothing pushing the page sideways; wide content such as the
// grid scrolls inside its own box) and show its main control, with no script errors.
const { chromium } = require("playwright");
const path = require("path");

const BASE = process.env.E2E_BASE;
const OUT = process.env.E2E_OUT;
const log = (...a) => console.log("[phone]", ...a);
function expect(cond, what) { if (!cond) throw new Error("expectation failed: " + what); log("ok -", what); }

// elements reaching past the right edge of the screen, outside any box that scrolls them
const overflowing = (page) => page.evaluate(() => {
  const vw = document.documentElement.clientWidth;
  const scrolled = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (/(auto|scroll|hidden)/.test(s.overflowX) && p.scrollWidth > p.clientWidth) return true;
    }
    return false;
  };
  return [...document.querySelectorAll("body *")]
    .filter((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.right > vw + 1 && !scrolled(el); })
    .slice(0, 5).map((el) => `${el.tagName.toLowerCase()}.${[...el.classList].join(".")}`);
});

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  try {
    await page.goto(BASE + "/");
    await page.waitForSelector("#create-view");
    const made = await (await page.request.post(BASE + "/api/songs", { data: { title: "Phone Song", artist: "Nobody" } })).json();
    const songs = (await (await page.request.get(BASE + "/api/songs")).json()).songs;
    const example = songs.find((s) => s.chart && s.chart.id);
    expect(!!example, "the example song has a chart");
    const pages = [
      ["create", "/#/", "#create-view .composer"],
      ["my-charts", "/#/library", "main h1"],
      ["settings", "/#/settings", ".int-list"],
      ["song-needing-a-recording", `/#/song/${made.song.id}`, "input[type=file]"],
      ["song-with-a-chart", `/#/song/${example.id}`, "main h1"],
      ["workspace", `/#/chart/${example.chart.id}`, ".transport"],
    ];
    for (const [name, where, control] of pages) {
      await page.goto(BASE + where);
      await page.waitForSelector(control, { state: "attached", timeout: 30000 });
      await page.waitForTimeout(800);
      const wide = await overflowing(page);
      await page.screenshot({ path: path.join(OUT, `phone-${name}.png`) });
      expect(wide.length === 0, `${name} fits a 390 px screen${wide.length ? " (too wide: " + wide.join(", ") + ")" : ""}`);
    }
    expect(errors.length === 0, "no script errors" + (errors.length ? ": " + errors.join(" | ") : ""));
  } finally {
    await browser.close();
  }
})().catch((e) => { console.error(e); process.exit(1); });
