// tab_shot.mjs (2026-10-11): full-page capture of one app tab at 360 px, as a given account.
//   node live/review/tab_shot.mjs <outdir> <account id|demo> <tab: home|marche|hist|reglages> [marche view: market|robot|lab]
import { spawn } from "node:child_process"; import { writeFileSync, readFileSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const OUT = process.argv[2]; const BASE = "http://127.0.0.1:8787"; const WHO = process.argv[3] || "kino";
const TAB = process.argv[4] || "home", VIEW = process.argv[5] || "";
const TOKEN = WHO === "demo" ? null : JSON.parse(readFileSync("C:/Projects/KinoliveLines/live/owl_nest_users.json", "utf8")).find(u => u.id === WHO).token; /* read at run time, never printed or committed */
const PORT = 9342;
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", `--remote-debugging-port=${PORT}`, `--user-data-dir=${OUT}/tsprof_${Date.now()}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
let wsUrl = null; for (let i = 0; i < 40 && !wsUrl; i++) { try { wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(250); } }
if (!wsUrl) { console.log("no CDP"); edge.kill(); process.exit(1); }
const ws = new WebSocket(wsUrl); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); const events = [];
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else if (d.method) events.push(d); };
const send = (method, params = {}, sessionId) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const waitEvent = async (name, sid, ms = 15000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { const k = events.findIndex(e => e.method === name && e.sessionId === sid); if (k >= 0) { events.splice(k, 1); return true; } await sleep(50); } return false; };
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S);
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, S)).result?.result?.value;
const url = WHO === "demo" ? `${BASE}/demo` : `${BASE}/${TOKEN}/`;
await send("Emulation.setDeviceMetricsOverride", { width: 360, height: 800, deviceScaleFactor: 1, mobile: true }, S);
await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); await sleep(4000);
await evalJs("localStorage.setItem('owlTourDone','1');1");
await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); await sleep(6000);
const tb = { home: "tb-home", marche: "tb-marche", hist: "tb-hist", reglages: "tb-reglages" }[TAB] || "tb-home";
await evalJs(`(()=>{const b=document.getElementById('${tb}')||[...document.querySelectorAll('.tb')].find(x=>x.getAttribute('onclick')&&x.getAttribute('onclick').indexOf("'${TAB}'")>=0);tab('${TAB}',b);${VIEW ? `mxView('${VIEW}',true);` : ""}window.scrollTo(0,0);return 1})()`);
await sleep(3500);
if (process.argv[6]) { await evalJs(process.argv[6]); await sleep(1500); }   // optional: JS to run before the capture
const h = await evalJs("document.documentElement.scrollHeight");
await send("Emulation.setDeviceMetricsOverride", { width: 360, height: Math.min(h, 9000), deviceScaleFactor: 1, mobile: true }, S); await sleep(1500);
const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }, S);
writeFileSync(`${OUT}/${TAB}${VIEW ? "_" + VIEW : ""}_${WHO}${process.argv[7] ? "_" + process.argv[7] : ""}.png`, Buffer.from(shot.result.data, "base64"));
const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => (e.params.exceptionDetails.exception || {}).description || "error");
console.log(TAB, VIEW, WHO, "height", h, errs.length ? "JS ERRORS: " + errs.join(" | ") : "no JS errors");
edge.kill(); process.exit(errs.length ? 1 : 0);
