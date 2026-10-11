// review/rentabilite_shots.mjs - headless captures of the Rentabilite space (4 tabs) and its home card, as the owner. node live/review/rentabilite_shots.mjs x
// review/chart_options_check.mjs - headless Edge render of the chart page with the
// display options (swing candles on/off, pullback base, line of the last two dots),
// reporting any JS exception / console error and the candle counts.
//     node live/review/chart_options_check.mjs <outdir> [nest id, default kino = the owner, Strategie view]
import { spawn } from "node:child_process"; import { writeFileSync, readFileSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const OUT = process.argv[2]; const BASE = "http://127.0.0.1:8787"; const WHO = process.argv[3] || "kino"; const EL = process.argv[4] || "aicard"; const TOKEN = WHO === "demo" ? null : JSON.parse(readFileSync("C:/Projects/KinoliveLines/live/owl_nest_users.json", "utf8")).find(u => u.id === WHO).token; /* read at run time, never printed or committed */ const PORT = 9336;
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", `--remote-debugging-port=${PORT}`, `--user-data-dir=${OUT}/hcprof_${Date.now()}`, "about:blank"], { stdio: "ignore" });
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

// home_card_shot.mjs (2026-10-11): one home card, as the given account sees it, at 412 and 360 px
//   node live/review/home_card_shot.mjs <outdir> [account id|demo] [element id]
const url = WHO === "demo" ? `${BASE}/demo` : `${BASE}/${TOKEN}/`;
let bad = 0;
for (const w of [412, 360]) {
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: 900, deviceScaleFactor: 2, mobile: true }, S);
  await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); await sleep(6000);
  await evalJs("localStorage.setItem('owlTourDone','1');1");
  const r = await evalJs(`(()=>{const e=document.getElementById('${EL}');if(!e)return {missing:true};e.scrollIntoView({block:'center'});const b=e.getBoundingClientRect();return {shown:getComputedStyle(e).display!=='none',w:Math.round(b.width),h:Math.round(b.height),sw:document.documentElement.scrollWidth,iw:innerWidth,txt:e.innerText.replace(/\\s+/g,' ').slice(0,400)}})()`);
  const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => e.params.exceptionDetails.exception?.description?.split("\n")[0]); events.length = 0;
  console.log(w, JSON.stringify(r), errs.length ? "JS ERRORS: " + errs.join(" | ") : "no JS errors");
  if (!r || !r.shown || r.sw > r.iw || errs.length) bad++;
  await sleep(700);
  if (process.env.FULL) { await evalJs("window.scrollTo(0,0);1"); const h = await evalJs("document.documentElement.scrollHeight"); await send("Emulation.setDeviceMetricsOverride", { width: w, height: Math.min(h, 9000), deviceScaleFactor: 1, mobile: true }, S); await sleep(1500); }
  const { result } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: !!process.env.FULL }, S); writeFileSync(`${OUT}/${EL}_${WHO}_${w}.png`, Buffer.from(result.data, "base64"));
}
edge.kill(); process.exit(bad ? 1 : 0);
