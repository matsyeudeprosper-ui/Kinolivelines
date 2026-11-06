// page_states.mjs (2026-11-06): screenshots of a page's successive states, for a video made of stills (a busy server
// cannot film an animation in real time). The page exposes window.__show(k) and window.__n.
//   node live/review/page_states.mjs <outdir> <url#still> <width> <height>
import { execSync as __tk } from "node:child_process";
import { spawn } from "node:child_process"; import { writeFileSync, rmSync, mkdtempSync } from "node:fs"; import { tmpdir } from "node:os"; import { join } from "node:path";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", PORT = 9800 + Math.floor(Math.random() * 90);
const [OUT, URL_, W, H] = process.argv.slice(2);
const prof = mkdtempSync(join(tmpdir(), "pst_"));
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
let u = null; for (let i = 0; i < 120 && !u; i++) { try { u = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(250); } }
const ws = new WebSocket(u); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map();
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } };
const send = (method, params = {}, sessionId) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S);
const ev = async (e) => (await send("Runtime.evaluate", { expression: e, returnByValue: true }, S)).result?.result?.value;
await send("Emulation.setDeviceMetricsOverride", { width: +W, height: +H, deviceScaleFactor: 1, mobile: false }, S);
await send("Page.navigate", { url: URL_ }, S); await sleep(5000);
const n = await ev("window.__n||0");
for (let k = 0; k <= n; k++) {
  await ev(`window.__show(${k})`); await sleep(500);
  const shot = await send("Page.captureScreenshot", { format: "png" }, S);
  writeFileSync(`${OUT}/s_${String(k).padStart(2, "0")}.png`, Buffer.from(shot.result.data, "base64"));
}
try { edge.kill(); __tk("powershell -NoProfile -ExecutionPolicy Bypass -File C:/Projects/KinoliveLines/live/review/kill_temp_edge.ps1", { stdio: "ignore" }); } catch { }
await sleep(800); try { rmSync(prof, { recursive: true, force: true }); } catch { }
console.log("states", n + 1);
process.exit(0);
