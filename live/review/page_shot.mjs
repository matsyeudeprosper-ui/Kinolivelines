// page_shot.mjs (2026-10-12): full-page capture of any member page at 360 px.
//   node live/review/page_shot.mjs <outdir> <account id> <path after the token, e.g. "wealth"> [js to run before] [name]
import { spawn } from "node:child_process"; import { writeFileSync, readFileSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", BASE = "http://127.0.0.1:8787", PORT = 9353;
const [OUT, WHO, PATH, JS, NAME] = process.argv.slice(2);
const TOKEN = JSON.parse(readFileSync("C:/Projects/KinoliveLines/live/owl_nest_users.json", "utf8")).find(u => u.id === WHO).token; /* never printed */
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`, `--user-data-dir=${OUT}/psprof_${Date.now()}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
let u = null; for (let i = 0; i < 40 && !u; i++) { try { u = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(250); } }
const ws = new WebSocket(u); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); const events = [];
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else if (d.method) events.push(d); };
const send = (method, params = {}, sessionId) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S);
const ev = async (e) => (await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }, S)).result?.result?.value;
await send("Emulation.setDeviceMetricsOverride", { width: 360, height: 800, deviceScaleFactor: 1, mobile: true }, S);
const url = `${BASE}/${TOKEN}/${PATH || ""}`;
await send("Page.navigate", { url }, S); await sleep(3000);
if (JS) { await ev(JS); await send("Page.reload", { ignoreCache: true }, S); }   // reload: navigating to the same URL with a #hash would not reload
await sleep(6000);
const h = await ev("document.documentElement.scrollHeight");
await send("Emulation.setDeviceMetricsOverride", { width: 360, height: Math.min(h, 9000), deviceScaleFactor: 1, mobile: true }, S); await sleep(1200);
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }, S);
writeFileSync(`${OUT}/${NAME || "page"}.png`, Buffer.from(shot.result.data, "base64"));
const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => (e.params.exceptionDetails.exception || {}).description || "error");
console.log(NAME || "page", "height", h, errs.length ? "JS ERRORS: " + errs.join(" | ") : "no JS errors");
edge.kill(); process.exit(errs.length ? 1 : 0);
