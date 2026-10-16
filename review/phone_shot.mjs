// phone_shot.mjs - screenshot pages at a real phone viewport (390 x 844 CSS px, scale 2) through Edge's
// DevTools protocol, the way review/ui_smoke.mjs drives the browser. Plain `msedge --screenshot` ignores the
// window size in headless mode, so its captures lie about phone layouts (2026-10-16).
//   node review/phone_shot.mjs <out_dir> <url-or-file> [...]      -> <out_dir>/<basename>.png
import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync, rmSync } from "node:fs";
import { basename, join } from "node:path";
import { tmpdir } from "node:os";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
// --run "<js>" runs that JavaScript on each page after it loads (e.g. open a sheet: "pick('family')")
const argv = process.argv.slice(2);
let RUN = ""; const ri = argv.indexOf("--run"); if (ri >= 0) { RUN = argv[ri + 1] || ""; argv.splice(ri, 2); }
const [outDir, ...targets] = argv;
if (!outDir || !targets.length) { console.error("usage: node review/phone_shot.mjs [--run <js>] <out_dir> <url|file> ..."); process.exit(2); }
mkdirSync(outDir, { recursive: true });
const PORT = 9333 + Math.floor(Math.random() * 300);
const prof = join(tmpdir(), "owl_phone_shot_" + PORT);
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", "--hide-scrollbars",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ws, id = 0; const pending = new Map();
function send(method, params = {}) {
  return new Promise((res, rej) => { const i = ++id; pending.set(i, { res, rej }); ws.send(JSON.stringify({ id: i, method, params })); });
}
try {
  let list = null;
  for (let i = 0; i < 40 && !list; i++) { await sleep(250); try { list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json(); } catch { } }
  const page = list.find(t => t.type === "page");
  ws = new WebSocket(page.webSocketDebuggerUrl); await new Promise(r => ws.onopen = r);
  ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { const p = pending.get(m.id); pending.delete(m.id); m.error ? p.rej(new Error(m.error.message)) : p.res(m.result); } };
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
  await send("Page.enable");
  for (const t of targets) {
    const url = /^[a-z]+:\/\//i.test(t) ? t : "file:///" + t.replace(/\\/g, "/");
    await send("Page.navigate", { url }); await sleep(1200);
    if (RUN) { await send("Runtime.evaluate", { expression: RUN, awaitPromise: true }); await sleep(700); }
    const { cssContentSize } = await send("Page.getLayoutMetrics");
    const h = Math.min(Math.ceil(cssContentSize.height), 3000);
    await send("Emulation.setDeviceMetricsOverride", { width: 390, height: h, deviceScaleFactor: 2, mobile: true });
    await sleep(200);
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
    const name = basename(t).replace(/\.html?$/i, "").replace(/[^A-Za-z0-9_-]/g, "_") || "page";
    writeFileSync(join(outDir, name + ".png"), Buffer.from(shot.data, "base64"));
    const over = cssContentSize.width > 390 ? `  OVERFLOW: content ${cssContentSize.width}px wide` : "";
    console.log(`${name}.png  ${Math.ceil(cssContentSize.width)}x${h} css px${over}`);
  }
} finally {
  try { ws && ws.close(); } catch { }
  edge.kill(); await sleep(500);
  try { rmSync(prof, { recursive: true, force: true }); } catch { }
}
