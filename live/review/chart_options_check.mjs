// review/chart_options_check.mjs - headless Edge render of the chart page with the
// display options (swing candles on/off, pullback base, line of the last two dots),
// reporting any JS exception / console error and the candle counts.
//     node live/review/chart_options_check.mjs <outdir>
import { spawn } from "node:child_process"; import { writeFileSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const OUT = process.argv[2]; const BASE = "http://127.0.0.1:8787"; const TOKEN = "F61w0YMMyBiH"; const PORT = 9334;
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
let fails = 0;
const shot = async (name) => { const { result } = await send("Page.captureScreenshot", { format: "png" }, S); writeFileSync(`${OUT}/${name}.png`, Buffer.from(result.data, "base64")); };
for (const [label, store] of [["default", {}], ["swing on", { owlSwing: "1" }], ["swing on + pullback", { owlSwing: "1", owlChartType: "pb" }], ["line off", { owlTl2: "0" }]]) {
  await nav(`${BASE}/${TOKEN}/chart`); await sleep(1500);
  await evalJs(`(()=>{localStorage.removeItem('owlSwing');localStorage.removeItem('owlChartType');localStorage.removeItem('owlTl2');localStorage.setItem('owl_adm','1');${Object.entries(store).map(([k, v]) => `localStorage.setItem('${k}','${v}');`).join("")}return 1;})()`);
  events.length = 0; await nav(`${BASE}/${TOKEN}/chart`); await sleep(7000);
  const info = await evalJs(`(()=>{const D=window.D||null;return D?{n:(D.candles||[]).length,swing:!!D.swing,dots:(D.dots||[]).length,trend:D.trend,runs:(()=>{let r=0,p=null;for(const c of (D.candles||[])){if(c[5]!==p){r++;p=c[5];}}return r;})()}:null;})()`);
  const errs = errors(); const bad = errs.filter(e => !/favicon|net::ERR|404/.test(e));
  if (bad.length) fails++;
  console.log(`${bad.length ? "FAIL" : "ok  "}  ${label}: ${JSON.stringify(info)} errors=${bad.length} ${bad.slice(0, 2).join(" | ")}`);
  await shot(`chart_${label.replace(/[^a-z]+/g, "_")}`);
}
edge.kill(); console.log(fails ? "CHART OPTIONS: FAIL" : "CHART OPTIONS: OK"); process.exit(fails ? 1 : 0);
