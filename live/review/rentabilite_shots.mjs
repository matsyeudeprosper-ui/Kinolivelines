// review/rentabilite_shots.mjs - headless captures of the Rentabilite space (4 tabs) and its home card, as the owner. node live/review/rentabilite_shots.mjs x
// review/chart_options_check.mjs - headless Edge render of the chart page with the
// display options (swing candles on/off, pullback base, line of the last two dots),
// reporting any JS exception / console error and the candle counts.
//     node live/review/chart_options_check.mjs <outdir> [nest id, default kino = the owner, Strategie view]
import { spawn } from "node:child_process"; import { writeFileSync, readFileSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const OUT = process.argv[2]; const BASE = "http://127.0.0.1:8787"; const WHO = process.argv[3] || "kino"; const TOKEN = JSON.parse(readFileSync("C:/Projects/KinoliveLines/live/owl_nest_users.json", "utf8")).find(u => u.id === WHO).token; /* read at run time, never printed or committed */ const PORT = 9334;
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", `--remote-debugging-port=${PORT}`, `--user-data-dir=${OUT}/edgeprof3`, "about:blank"], { stdio: "ignore" });
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
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S); await send("Log.enable", {}, S);
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, S)).result?.result?.value;
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }, S);
const nav = async (url) => { await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); };
const errors = () => events.filter(e => (e.method === "Runtime.exceptionThrown") || (e.method === "Log.entryAdded" && e.params?.entry?.level === "error")).map(e => e.method === "Runtime.exceptionThrown" ? (e.params.exceptionDetails.exception?.description || e.params.exceptionDetails.text) : e.params.entry.text);

const OUTD = "C:/Users/ADMINI~1/AppData/Local/Temp/2/claude/C--Users-Administrator--local-bin/b61e52db-3e75-4c34-a894-1952c9c0ef5a/scratchpad/shots";
const full = async (name) => { const m = await send("Page.getLayoutMetrics", {}, S); const h = Math.ceil(m.result.cssContentSize.height);
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: Math.min(h, 6000), deviceScaleFactor: 2, mobile: true }, S); await sleep(700);
  const { result } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }, S); writeFileSync(`${OUTD}/${name}.png`, Buffer.from(result.data, "base64"));
  await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }, S); };
events.length = 0;
await nav(`${BASE}/${TOKEN}/rentabilite`); await sleep(3500);
for (const t of ["re", "te", "me"]) { await evalJs(`(()=>{go("${t}");return 1;})()`); await sleep(1500); await full("rent_" + t); }
await evalJs(`(()=>{go("re");tradesPanel();return 1;})()`); await sleep(1200); { const { result } = await send("Page.captureScreenshot", { format: "png" }, S); writeFileSync(`${OUTD}/rent_trades_panel.png`, Buffer.from(result.data, "base64")); }
await evalJs(`(()=>{panClose();return 1;})()`);
await evalJs(`(()=>{localStorage.setItem('owlTourDone','1');return 1;})()`); await nav(`${BASE}/${TOKEN}/`); await sleep(9000);
await sleep(12000);
const hc = await send("Runtime.evaluate", { expression: "(async()=>{window._rtT=0;await loadRent();const e=document.getElementById('rentcard');if(!e)return 'missing';e.scrollIntoView({block:'center'});return JSON.stringify({shown:e.style.display, big:document.getElementById('rc2-big').textContent, pills:document.getElementById('rc2-g3').innerText.split(String.fromCharCode(10)).join(' '), ld: typeof loadRent});})()", returnByValue: true, awaitPromise: true }, S);
console.log("home card", JSON.stringify(hc.result?.result?.value ?? hc.result?.exceptionDetails?.exception?.description).slice(0,300));
for (const w of [412, 360]) { await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 2, mobile: true }, S); await sleep(900); await send("Runtime.evaluate", { expression: "document.getElementById('rentcard').scrollIntoView({block:'center'})" }, S); await sleep(700); const { result } = await send("Page.captureScreenshot", { format: "png" }, S); writeFileSync(`${OUTD}/rent_home_${w}.png`, Buffer.from(result.data, "base64")); }
const errs = errors().map(e => String(e).split(TOKEN).join('<token>')).filter(e => !/favicon|net::ERR|404/.test(e)); console.log('errors', errs.length, errs.slice(0,3).join(' | '));
edge.kill(); process.exit(0);
