// review/ui_states.mjs - captures the hidden states: trade sheet, info
// sheet, tour overlay, chart page. Usage: node review/ui_states.mjs <out-dir> <prefix>
// Capture the hidden states: trade sheet, info sheet, tour, chart page.
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT = process.argv[2], PFX = process.argv[3] || "s_";
const BASE = "http://127.0.0.1:8787", TOKEN = "F61w0YMMyBiH", PORT = 9334;
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run",
  "--no-default-browser-check", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${OUT}\\edgeprof4`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
let wsUrl = null;
for (let i = 0; i < 40 && !wsUrl; i++) {
  try { wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; }
  catch { await sleep(250); } }
if (!wsUrl) { console.log("no CDP"); edge.kill(); process.exit(1); }
const ws = new WebSocket(wsUrl); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); const events = [];
ws.onmessage = (m) => { const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  else if (d.method) events.push(d); };
const send = (method, params = {}, sessionId) => new Promise(res => {
  const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const waitEvent = async (name, sid, ms = 15000) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { const k = events.findIndex(e => e.method === name && e.sessionId === sid);
    if (k >= 0) { events.splice(k, 1); return true; } await sleep(50); } return false; };
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S);
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, S)).result?.result?.value;
const setViewport = (w, h) => send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 2, mobile: true }, S);
const nav = async (url) => { await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); };
const shotView = async (name) => {   // viewport only (sheets/tour are fixed-position)
  const { result } = await send("Page.captureScreenshot", { format: "png" }, S);
  writeFileSync(`${OUT}\\${PFX}${name}.png`, Buffer.from(result.data, "base64")); console.log("shot", name); };

await setViewport(390, 844);
await nav(`${BASE}/${TOKEN}/`);
await evalJs("localStorage.setItem('owlTourDone','1'); 1");
await nav(`${BASE}/${TOKEN}/`); await sleep(7000);
// trade detail sheet
await evalJs("tab('hist', document.querySelectorAll('.tb')[1]); 1"); await sleep(800);
await evalJs("window.scrollTo(0,0); tradeSheet(0); 1"); await sleep(700);
await shotView("sheet_trade");
await evalJs("document.getElementById('sheetbg').click(); 1"); await sleep(500);
// info sheet (le rattrapage)
await evalJs("tab('home', document.querySelectorAll('.tb')[0]); window.scrollTo(0,0); 1"); await sleep(500);
await evalJs("typeof ledInfo==='function' ? (ledInfo(),1) : 0"); await sleep(700);
await shotView("sheet_info");
await evalJs("document.getElementById('sheetbg').click(); 1"); await sleep(500);
// tour
await evalJs("window.scrollTo(0,0); tourStep(0); 1"); await sleep(700);
await shotView("tour");
console.log("sheet html sample:", (await evalJs("document.getElementById('sheet-c').innerHTML.slice(0,600)")));
// chart page, mobile
await nav(`${BASE}/${TOKEN}/chart`); await sleep(5000);
await shotView("chart");
ws.close(); edge.kill();
