// chart_symbol_check.mjs (2026-10-12): the chart's market picker - open on a market, switch, split view.
//   node live/review/chart_symbol_check.mjs <outdir> [account id]
import { spawn } from "node:child_process"; import { writeFileSync, readFileSync } from "node:fs";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", BASE = "http://127.0.0.1:8787", PORT = 9355;
const OUT = process.argv[2], WHO = process.argv[3] || "kino";
const TOKEN = JSON.parse(readFileSync("C:/Projects/KinoliveLines/live/owl_nest_users.json", "utf8")).find(u => u.id === WHO).token; /* never printed */
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`, `--user-data-dir=${OUT}/csprof_${Date.now()}`, "about:blank"], { stdio: "ignore" });
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
await send("Emulation.setDeviceMetricsOverride", { width: 412, height: 860, deviceScaleFactor: 2, mobile: true }, S);
const ST = `JSON.stringify({sym:SYM,dataSym:D&&D.sym,scale:SC,digits:DG,px:document.getElementById('px').textContent,head:document.getElementById('symh').textContent.trim(),othsym:document.body.classList.contains('othsym'),candles:D&&D.candles&&D.candles.length,trades:D&&D.trades&&D.trades.length,htf:HT.on?(HT.tf+':'+(HT.data&&HT.data.candles?HT.data.candles.length:0)):'off'})`;
await send("Page.navigate", { url: `${BASE}/${TOKEN}/chart?sym=XAUUSD` }, S); await sleep(9000);
console.log("open on gold :", await ev(ST)); await shot("gold");
await ev("document.getElementById('symh').click();1"); await sleep(600);
console.log("picker       :", await ev("JSON.stringify([...document.querySelectorAll('#sympk button')].map(b=>b.dataset.s))")); await shot("picker");
await ev("document.querySelector('#sympk button[data-s=EURUSD]').click();1"); await sleep(7000);
console.log("switched EUR :", await ev(ST)); await shot("eurusd");
await ev("HT.tf='H1';HT.on=true;try{htApply()}catch(e){};htLoad(true);1"); await sleep(5000);
console.log("split H1 EUR :", await ev(ST)); await shot("eur_split");
await ev("document.getElementById('symh').click();1"); await sleep(400);
await ev("document.querySelector('#sympk button[data-s=BTCUSD]').click();1"); await sleep(7000);
console.log("back to BTC  :", await ev(ST)); await shot("btc");
const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => (e.params.exceptionDetails.exception || {}).description || "error");
console.log(errs.length ? "JS ERRORS: " + errs.slice(0, 3).join(" | ") : "no JS errors");
edge.kill(); process.exit(errs.length ? 1 : 0);
