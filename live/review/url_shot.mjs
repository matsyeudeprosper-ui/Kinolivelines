// url_shot.mjs (2026-11-06): full-page capture of any public URL (client previews), phone or desktop.
//   node live/review/url_shot.mjs <outdir> <url> <width> <name>
import { execSync as __tk } from "node:child_process";
import { spawn } from "node:child_process"; import { writeFileSync, rmSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", PORT = 9354;
const [OUT, URL_, W, NAME] = process.argv.slice(2);
const width = parseInt(W || "390"), mobile = width < 700;
const prof = `${OUT}/usprof_${Date.now()}`;
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
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
await send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile }, S);
await send("Page.navigate", { url: URL_ }, S); await sleep(5000);
// reveal-on-scroll pages stay blank in a still capture: scroll through, then force everything visible
await ev("(async()=>{for(let y=0;y<document.documentElement.scrollHeight;y+=600){scrollTo(0,y);await new Promise(r=>setTimeout(r,120))}scrollTo(0,0);document.querySelectorAll('*').forEach(e=>{const s=getComputedStyle(e);if(s.opacity==='0')e.style.opacity='1'})})()");
await sleep(1500);
const h = await ev("document.documentElement.scrollHeight");
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true, clip: { x: 0, y: 0, width, height: Math.min(h, 9000), scale: 1 } }, S);
writeFileSync(`${OUT}/${NAME}.png`, Buffer.from(shot.result.data, "base64"));
const broken = await ev("[...document.images].filter(i=>!i.complete||i.naturalWidth===0).map(i=>i.src)");
const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => (e.params.exceptionDetails.exception || {}).description || "error");
console.log(NAME, "height", h, "broken images", JSON.stringify(broken), errs.length ? "JS ERRORS: " + errs.join(" | ") : "no JS errors");
try { edge.kill(); __tk("powershell -NoProfile -ExecutionPolicy Bypass -File C:/Projects/KinoliveLines/live/review/kill_temp_edge.ps1", { stdio: "ignore" }); } catch { }
await sleep(800); try { rmSync(prof, { recursive: true, force: true }); } catch { }
process.exit(0);
