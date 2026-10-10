// review/chart_tap_check.mjs - headless Edge: opens the chart as the owner with the pullback panel, taps the
// next-BOS / last-BOS ring on each panel with REAL input events (CDP Input.dispatchMouseEvent) and prints the
// card that opens. Run: node live/review/chart_tap_check.mjs x  (any outdir arg; nothing is written)
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

await nav(`${BASE}/${TOKEN}/chart`); await sleep(1500);
await evalJs(`(()=>{localStorage.setItem('owl_adm','1');localStorage.setItem('owlHTF',JSON.stringify({on:true,tf:'PB',split:'v',r:0.42}));return 1;})()`);
events.length = 0; await nav(`${BASE}/${TOKEN}/chart`); await sleep(7000);
const tapTest = async (cvId, listName) => {
  const pos = await evalJs(`(()=>{draw();const list=${listName};if(!list.length)return null;const c=document.getElementById('${cvId}');const r=c.getBoundingClientRect();
   const h=list.filter(q=>q.k==='bos'||q.k==='last').slice(-1)[0]||list[0];return JSON.stringify({x:r.left+c.clientWidth-9,y:r.top+h.y,k:h.k,n:list.length});})()`);
  if (!pos) return 'no levels';
  const p = JSON.parse(pos);
  await send("Input.dispatchMouseEvent", { type: "mousePressed", x: p.x, y: p.y, button: "left", clickCount: 1, pointerType: "mouse" }, S);
  await sleep(60);
  await send("Input.dispatchMouseEvent", { type: "mouseReleased", x: p.x, y: p.y, button: "left", clickCount: 1, pointerType: "mouse" }, S);
  await sleep(300);
  const rr = await send("Runtime.evaluate", { expression: "(()=>{const sheets=[...document.querySelectorAll('div')].filter(d=>d.style.zIndex==='90'&&d.style.position==='fixed');const txt=sheets.length?sheets[sheets.length-1].innerText.slice(0,140):'';if(sheets.length)try{window._adDone(1);}catch(e){}return JSON.stringify({sheet:sheets.length,text:txt});})()", returnByValue: true }, S);
  const res = rr.result?.result?.value ?? JSON.stringify(rr.result?.exceptionDetails?.exception?.description || rr).slice(0, 200);
  return JSON.stringify(p) + ' -> ' + res;
};
console.log('MAIN ', await tapTest('cv', 'LVLHIT'));
console.log('SPLIT', await tapTest('cvh', 'LVLHIT_H'));
// the forming minute on the pullback panel: gold outline pixels must exist at the right of the last grey candle
console.log('LIVE ', await evalJs(`(()=>{draw();const c=document.getElementById('cvh');const g=c.getContext('2d');const d=g.getImageData(0,0,c.width,c.height).data;let gold=0;
 for(let i=0;i<d.length;i+=4){if(d[i]>200&&d[i+1]>170&&d[i+1]<215&&d[i+2]<120&&d[i+3]>200)gold++;}return JSON.stringify({goldPixels:gold,LT:!!(typeof LT!=='undefined'&&LT),xts:HT.xts.length});})()`));
const errs = errors().map(e => String(e).split(TOKEN).join('<token>')); console.log('errors', errs.length, errs.map(e=>e.slice(0,220)).join(' || '));
edge.kill(); process.exit(0);
