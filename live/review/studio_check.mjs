// studio_check.mjs (2026-10-12): the chart studio end to end - replay, trades with stops, save, observations.
//   node live/review/studio_check.mjs <outdir> [account id]
import { spawn } from "node:child_process"; import { writeFileSync, readFileSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", BASE = "http://127.0.0.1:8787", PORT = 9363;
const OUT = process.argv[2], WHO = process.argv[3] || "kino";
const TOKEN = JSON.parse(readFileSync("C:/Projects/KinoliveLines/live/owl_nest_users.json", "utf8")).find(u => u.id === WHO).token; /* never printed */
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`, `--user-data-dir=${OUT}/stprof_${Date.now()}`, "about:blank"], { stdio: "ignore" });
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
const shot = async (n) => { const r = await send("Page.captureScreenshot", { format: "png" }, S); writeFileSync(`${OUT}/${n}.png`, Buffer.from(r.result.data, "base64")); };
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }, S);
await send("Page.navigate", { url: `${BASE}/${TOKEN}/chart?studio=1` }, S); await sleep(7000);
await shot("st_setup");
await ev("ST.view='silence';document.getElementById('stud').value='2026-10-09';stuStart();1"); await sleep(2500);
console.log("start:", await ev("JSON.stringify({cur:ST.cur,cands:D.candles.length,marks:(D.marks||[]).length,last:ST.last&&ST.last[0]})"));
await shot("st_replay");
let made = 0;
for (let k = 0; k < 4; k++) {
  await ev("stuFetch(15)"); await sleep(1200);
  await ev(`stuOpen(${k % 2 ? -1 : 1});1`); await sleep(300);
  await ev("(function(){const p=ST.pos;const dd=(D.dots||[]).filter(x=>x[2]===(p.d===1?1:-1)&&x[0]<=p.te);if(dd.length&&((p.d===1&&dd[dd.length-1][1]<p.e)||(p.d===-1&&dd[dd.length-1][1]>p.e)))stuProtected();else stuSetStop(p.e-p.d*150);return 1;})()"); await sleep(300);
  if (k === 0) await shot("st_open");
  for (let j = 0; j < 6 && (await ev("!!ST.pos")); j++) { await ev("stuFetch(5)"); await sleep(900); }
  if (await ev("!!ST.pos")) { await ev("stuExit();1"); }
  made++;
}
console.log("trades:", await ev("JSON.stringify(ST.trades.map(t=>({d:t.d,why:t.why,r:+(t.d*(t.x-t.e)/Math.abs(t.e-t.sl)).toFixed(2)})))"));
await shot("st_done");
await ev("stuSave()"); await sleep(6000);
console.log("landed on:", (await ev("location.pathname.split('/').pop()+location.hash.replace(/=.*/,'=…')")));
await shot("st_obs");
console.log("observations:", await ev("JSON.stringify((STU&&STU.summary||[]).map(s=>s.id+' '+s.k+'/'+s.n))"));
await ev("studioConfirm()"); await sleep(1500);
console.log("parts:", await ev("JSON.stringify(STU&&STU.parts)"));
const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => (e.params.exceptionDetails.exception || {}).description || "error");
console.log(errs.length ? "JS ERRORS: " + errs.slice(0, 3).join(" | ") : "no JS errors");
edge.kill(); process.exit(errs.length ? 1 : 0);
