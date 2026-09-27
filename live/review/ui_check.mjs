// OwlNest UI check (2026-09-27). Run any time, no deps beyond Node 22 + Edge:
//   node review/ui_check.mjs [token]
// 1. fetches the served page, the join page and the chart page and parses
//    every inline <script> (the \' trap killed the page twice this month);
// 2. loads the page headless, collects runtime exceptions, and prints the
//    key sentences in both voices (auto / manual) and both languages
//    (fr / en) so a wording regression is visible in one screen.
// Exit code 1 on any parse or runtime error.
import { spawn } from "node:child_process";
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const BASE = "http://127.0.0.1:8787", TOKEN = process.argv[2] || "F61w0YMMyBiH", PORT = 9377;
const PROF = process.env.TEMP + "\\owl_ui_check_prof";
let failures = 0;
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

// ---- 1. parse every inline script of the three pages ----
for (const [lab, url] of [["PAGE", `${BASE}/${TOKEN}/`], ["JOIN", `${BASE}/join`], ["CHART", `${BASE}/${TOKEN}/chart`]]) {
  let html = ""; try { html = await (await fetch(url)).text(); } catch (e) { console.log(lab, "FETCH FAILED", e.message); failures++; continue; }
  const re = /<script(?![^>]*src)[^>]*>([\s\S]*?)<\/script>/g; let m, n = 0, bad = 0;
  while ((m = re.exec(html))) { n++; try { new Function(m[1]); } catch (e) { bad++; failures++; console.log(lab, "SCRIPT", n, "PARSE ERROR:", e.message); } }
  console.log(`${lab}: ${n} inline scripts, ${bad} parse errors`);
}

// ---- 2. headless run: exceptions + voices + languages ----
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROF}`, "about:blank"], { stdio: "ignore" });
let wsUrl = null;
for (let i = 0; i < 40 && !wsUrl; i++) { try { wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(250); } }
if (!wsUrl) { console.log("no CDP endpoint - is Edge installed?"); edge.kill(); process.exit(1); }
const ws = new WebSocket(wsUrl); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); const events = []; const errors = [];
ws.onmessage = (m) => { const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  else if (d.method === "Runtime.exceptionThrown") errors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
  else if (d.method) events.push(d); };
const send = (method, params = {}, sessionId) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const waitEvent = async (name, sid, ms = 15000) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { const k = events.findIndex(e => e.method === name && e.sessionId === sid); if (k >= 0) { events.splice(k, 1); return true; } await sleep(50); } return false; };
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S);
const evalJs = async (expr) => { const r = await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, S);
  if (r.result?.exceptionDetails) { failures++; console.log("EVAL ERROR:", r.result.exceptionDetails.exception?.description); } return r.result?.result?.value; };
const nav = async (url) => { await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); };
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 1, mobile: true }, S);
await nav(`${BASE}/${TOKEN}/`);
await evalJs("localStorage.setItem('owlTourDone','1'); localStorage.removeItem('owlTheme'); localStorage.removeItem('owl_adm'); localStorage.removeItem('owlLang'); 1");
await nav("about:blank"); await nav(`${BASE}/${TOKEN}/`); await sleep(7000);
const report = async () => ({
  title: await evalJs("document.getElementById('mx-title').textContent.trim()"),
  line: await evalJs("document.getElementById('mx-line').textContent"),
  jcard: await evalJs("document.getElementById('jcard-lbl').textContent"),
  jmsg: await evalJs("document.getElementById('jmsg').textContent"),
  day: await evalJs("document.getElementById('day-sum').textContent"),
  st: await evalJs("document.getElementById('st').textContent.trim()") });
const setState = async (manual, lang) => { await evalJs(`clearInterval(pollT); pollT=null; localStorage.setItem('owlLang','${lang}'); (()=>{const d=JSON.parse(JSON.stringify(window._d)); d.trading_paused=${manual}; window._lastS=null; render(d); loadDay(); applyLang();})(); 1`); await sleep(2200); };
for (const [manual, lang] of [[false, "fr"], [true, "fr"], [false, "en"], [true, "en"]]) {
  await setState(manual, lang); const r = await report();
  console.log(`\n[${manual ? "MANUAL" : "AUTO"} / ${lang}]`); for (const k of Object.keys(r)) console.log(`  ${k}: ${r[k]}`);
}
// ---- guardrails (2026-09-27): every T() key in all four tables; no French left in EN ----
const keyGaps = await evalJs(`(()=>{const a=Object.keys(VOICE.auto),m=Object.keys(VOICE.manual);const out=[];
 a.forEach(k=>{if(VOICE_EN.auto[k]===undefined)out.push('en.auto:'+k);});
 m.forEach(k=>{if(VOICE_EN.manual[k]===undefined)out.push('en.manual:'+k);});return JSON.stringify(out);})()`);
const gaps = JSON.parse(keyGaps || "[]");
console.log(`\nT() keys missing in English: ${gaps.length}${gaps.length ? " -> " + gaps.slice(0, 8).join(", ") : ""}`);
failures += gaps.length;
await setState(false, "en");
const frLeft = JSON.parse(await evalJs(`(()=>{const rx=/\\b(aujourd|le robot|march\u00e9|r\u00e9glages|accueil|historique|semaine|mois|jour|depuis|aucun|trade en cours|gagn\u00e9|perdu)\\b/i;const out=[];
 for(const id of ['tab-home','tab-marche','tab-hist','tab-set']){const root=document.getElementById(id);if(!root)continue;
  const w=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);let n;while((n=w.nextNode())){const p=n.parentNode;if(!p||/^(SCRIPT|STYLE)$/.test(p.nodeName))continue;
   if(!p.offsetParent&&p.tagName!=='BODY')continue;const t=n.nodeValue.trim();if(t.length>3&&rx.test(t))out.push(id+': '+t.slice(0,60));}}
 return JSON.stringify(out.slice(0,40));})()`) || "[]");
console.log(`French left in EN mode (visible text): ${frLeft.length}${frLeft.length ? "\n  " + frLeft.slice(0, 10).join("\n  ") : ""}`);
if (frLeft.length > 8) failures++;
await evalJs("localStorage.removeItem('owlLang'); 1");
console.log(`\nruntime exceptions: ${errors.length}`); errors.slice(0, 5).forEach(e => console.log("  ", String(e).slice(0, 200)));
failures += errors.length;
ws.close(); edge.kill();
console.log(failures ? `\nUI CHECK: ${failures} problem(s)` : "\nUI CHECK: OK");
process.exit(failures ? 1 : 0);
