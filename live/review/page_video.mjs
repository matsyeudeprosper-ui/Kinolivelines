// page_video.mjs (2026-11-06, owner: a short demo video of the AI staff member): films a page as it animates.
//   node live/review/page_video.mjs <outdir> <url> <width> <height> <seconds>
// writes <outdir>/f_00000.jpg ... (10 frames a second) - ffmpeg makes the video
import { execSync as __tk } from "node:child_process";
import { spawn } from "node:child_process"; import { writeFileSync, rmSync, mkdtempSync } from "node:fs"; import { tmpdir } from "node:os"; import { join } from "node:path";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", PORT = 9900 + Math.floor(Math.random() * 90);
const [OUT, URL_, W, H, SEC] = process.argv.slice(2);
const prof = mkdtempSync(join(tmpdir(), "pvid_"));
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
let u = null; for (let i = 0; i < 120 && !u; i++) { try { u = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(250); } }
const ws = new WebSocket(u); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); let vt = null;
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else if (d.method === "Emulation.virtualTimeBudgetExpired" && vt) { const r = vt; vt = null; r(); } };
const send = (method, params = {}, sessionId) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S);
await send("Emulation.setDeviceMetricsOverride", { width: +W, height: +H, deviceScaleFactor: 1, mobile: false }, S);
// the page's own clock is advanced 100 ms per frame: smooth whatever the server's load (06/11: real time gave 0.8 frame/s)
await send("Emulation.setVirtualTimePolicy", { policy: "pause" }, S);
await send("Page.navigate", { url: URL_ }, S); await sleep(1500);
const n = Math.round(+SEC * 10); const t0 = Date.now();
for (let f = 0; f < n; f++) {
  const p = new Promise(r => vt = r);
  await send("Emulation.setVirtualTimePolicy", { policy: "advance", budget: 100 }, S);
  await Promise.race([p, sleep(5000)]);
  const shot = await send("Page.captureScreenshot", { format: "jpeg", quality: 88 }, S);
  writeFileSync(`${OUT}/f_${String(f).padStart(5, "0")}.jpg`, Buffer.from(shot.result.data, "base64"));
}
try { edge.kill(); __tk("powershell -NoProfile -ExecutionPolicy Bypass -File C:/Projects/KinoliveLines/live/review/kill_temp_edge.ps1", { stdio: "ignore" }); } catch { }
await sleep(800); try { rmSync(prof, { recursive: true, force: true }); } catch { }
console.log("frames", n, "in", Math.round((Date.now() - t0) / 1000), "s");
process.exit(0);
