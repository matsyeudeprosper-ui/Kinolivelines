// home_robot_check.mjs (2026-10-11): the home card "Le robot en ce moment" and the robot tab it opens.
// Captures both at 360 px, reports JS errors and whether the tap lands on the robot tab.
//   node live/review/home_robot_check.mjs <outdir> [account id|demo]
import { spawn } from "node:child_process"; import { writeFileSync, readFileSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const OUT = process.argv[2]; const BASE = "http://127.0.0.1:8787"; const WHO = process.argv[3] || "kino";
const TOKEN = WHO === "demo" ? null : JSON.parse(readFileSync("C:/Projects/KinoliveLines/live/owl_nest_users.json", "utf8")).find(u => u.id === WHO).token; /* read at run time, never printed or committed */
const PORT = 9338;
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", `--remote-debugging-port=${PORT}`, `--user-data-dir=${OUT}/hrprof_${Date.now()}`, "about:blank"], { stdio: "ignore" });
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
await send("Emulation.setDeviceMetricsOverride", { width: 360, height: 800, deviceScaleFactor: 2, mobile: true }, S);
await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); await sleep(4000);
await evalJs("localStorage.setItem('owlTourDone','1');localStorage.setItem('owlMxView:'+B,'market');1");
await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); await sleep(6000);
await evalJs("document.getElementById('rbnow').scrollIntoView({block:'center'});1"); await sleep(600);
let shot = await send("Page.captureScreenshot", { format: "png" }, S); writeFileSync(`${OUT}/home_${WHO}.png`, Buffer.from(shot.result.data, "base64"));
const home = await evalJs("document.getElementById('rbnow').innerText.split('\\n').join(' ').slice(0,220)");
await evalJs("document.getElementById('rbnow').click();1"); await sleep(1500);
const r = await evalJs("(()=>({robotShown:getComputedStyle(document.getElementById('mx-robot')).display!=='none',jcard:document.getElementById('jcard').innerText.split('\\n').join(' ').slice(0,200)}))()");
shot = await send("Page.captureScreenshot", { format: "png" }, S); writeFileSync(`${OUT}/robot_${WHO}.png`, Buffer.from(shot.result.data, "base64"));
const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => (e.params.exceptionDetails.exception || {}).description || "error");
console.log(WHO, "HOME:", home, "| TAP:", JSON.stringify(r), errs.length ? "JS ERRORS: " + errs.join(" | ") : "no JS errors");
edge.kill(); process.exit(errs.length || !r.robotShown ? 1 : 0);
