// Landing screenshots (2026-09-27): three real renders of the public demo -
// home, market, history - written to static/shot_*.webp and served at
// /shots/<name>.webp for the landing carousel and the Open Graph preview.
//   node review/landing_shots.mjs
// Node 22 + Edge, no deps. Re-run whenever the design changes (boot_all can
// call it daily; the landing hides a figure whose image is missing).
import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "static");
mkdirSync(OUT, { recursive: true });
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const BASE = "http://127.0.0.1:8787", PORT = 9378;
const PROF = process.env.TEMP + "\\owl_landing_shots_prof";
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const tok = await fetch(`${BASE}/demo`, { redirect: "manual" }).then(r => (r.headers.get("location") || "").split("/").filter(x => x)[0]).catch(() => null);
if (!tok) { console.log("no public demo account"); process.exit(1); }
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROF}`, "about:blank"], { stdio: "ignore" });
let wsUrl = null;
for (let i = 0; i < 40 && !wsUrl; i++) { try { wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(250); } }
if (!wsUrl) { console.log("no CDP"); edge.kill(); process.exit(1); }
const ws = new WebSocket(wsUrl); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); const events = [];
let paused = async () => {};
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else if (d.method === "Fetch.requestPaused") { paused(d.params, d.sessionId); } else if (d.method) events.push(d); };
const send = (method, params = {}, sessionId) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const waitEvent = async (name, sid, ms = 15000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { const k = events.findIndex(e => e.method === name && e.sessionId === sid); if (k >= 0) { events.splice(k, 1); return true; } await sleep(50); } return false; };
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S);
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, S)).result?.result?.value;
const nav = async (url) => { await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); };
// 2026-10-04 (owner): a red day is not a shop window. The three renders are
// taken into memory and written together only when the day and the week
// are green; otherwise the previous ones stay (unless none exist yet).
const taken = {};
const shot = async (name) => { const { result } = await send("Page.captureScreenshot", { format: "webp", quality: 82 }, S); taken[name] = Buffer.from(result.data, "base64"); };
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 780, deviceScaleFactor: 2, mobile: true }, S);
await nav(`${BASE}/${tok}/`);
await evalJs("localStorage.setItem('owlTourDone','1'); localStorage.removeItem('owlTheme'); localStorage.removeItem('owlBig'); localStorage.removeItem('owl_adm'); localStorage.removeItem('owlLang'); 1");
await nav("about:blank"); await nav(`${BASE}/${tok}/`); await sleep(7500);
// the running-trade pill is a moment, not a result: not in the shop window
await evalJs("(function(){['tradepill','nudge','apkcard','expcard'].forEach(function(i){var p=document.getElementById(i);if(p)p.style.display='none';});})(); window.scrollTo(0,0); 1"); await shot("shot_home.webp");
await evalJs("tab('marche', document.querySelectorAll('.tb')[1]); window.scrollTo(0,0); 1"); await sleep(800); await shot("shot_marche.webp");
await evalJs("tab('hist', document.querySelectorAll('.tb')[2]); window.scrollTo(0,0); 1"); await sleep(800); await shot("shot_hist.webp");
// 2026-10-06 (owner): the chart with its structure marks (BOS / CHoCH) and the lab. Both are
// paid views, so the public demo page is opened with the full view switched on in the page
// itself (nothing changes on the server); the lab text is the shared lab, read once with the
// owner's link. A shot whose text names a member is dropped.
const NAMES = /(mike|dad|kino|val[eè]re|guilet|lolo|lololo)/i;
let labJson = null, structKeys = null;
try {
  const U = JSON.parse(readFileSync(join(HERE, "..", "owl_nest_users.json"), "utf8").replace(/^﻿/, ""));
  const mt = (Array.isArray(U) ? U : U.users || []).find(u => u.name === "Mike")?.token;
  const lj = mt ? await fetch(`${BASE}/${mt}/lab`).then(r => r.text()) : null;
  if (lj && !JSON.parse(lj).err) labJson = lj;
  // Same file for everyone: only the server hides the structure from the demo link.
  const cj = mt ? JSON.parse(await fetch(`${BASE}/${mt}/chart_data`).then(r => r.text())) : null;
  if (cj && cj.marks) { structKeys = {}; for (const k of ["dots", "marks", "breaks", "int_dots", "int_marks"]) structKeys[k] = cj[k]; }
} catch {}
paused = async (p, sid) => {
  if (process.env.SHOT_DEBUG) console.log("paused", p.request.url, p.responseStatusCode);
  const u = p.request.url;
  try {
    if (/\/lab\?/.test(u) && labJson) {
      await send("Fetch.fulfillRequest", { requestId: p.requestId, responseCode: 200, responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from(labJson).toString("base64") }, sid); return;
    }
    if (/\/chart_data/.test(u) && structKeys && p.responseStatusCode) {
      const b = (await send("Fetch.getResponseBody", { requestId: p.requestId }, sid)).result;
      const j = JSON.parse(b.base64Encoded ? Buffer.from(b.body, "base64").toString("utf8") : b.body);
      Object.assign(j, structKeys);
      await send("Fetch.fulfillRequest", { requestId: p.requestId, responseCode: 200, responseHeaders: [{ name: "Content-Type", value: "application/json" }], body: Buffer.from(JSON.stringify(j)).toString("base64") }, sid); return;
    }
    if (/\/chart(\?|$)/.test(u) && p.responseStatusCode) {
      const b = (await send("Fetch.getResponseBody", { requestId: p.requestId }, sid)).result;
      let html = b.base64Encoded ? Buffer.from(b.body, "base64").toString("utf8") : b.body;
      html = html.replace(/const FULL=(true|false);/, "const FULL=true;").replace(/const TIER='[a-z]*';/, "const TIER='strategy';");
      await send("Fetch.fulfillRequest", { requestId: p.requestId, responseCode: 200, responseHeaders: [{ name: "Content-Type", value: "text/html; charset=utf-8" }], body: Buffer.from(html).toString("base64") }, sid); return;
    }
  } catch {}
  await send("Fetch.continueRequest", { requestId: p.requestId }, sid);
};
await send("Network.enable", {}, S); await send("Network.setBypassServiceWorker", { bypass: true }, S);
await send("Fetch.enable", { patterns: [{ urlPattern: `*/${tok}/chart*`, requestStage: "Response" }, { urlPattern: `*/${tok}/lab?*`, requestStage: "Request" }] }, S);
await nav(`${BASE}/${tok}/chart`); await sleep(8000);
const chartTxt = await evalJs("document.body.innerText"), chartFull = await evalJs("typeof FULL!=='undefined'&&FULL===true");
const chartMarks = await evalJs("(typeof D!=='undefined'&&D&&D.marks&&D.dots)?D.marks.length*1000+D.dots.length:0");
if (chartTxt && chartFull && chartMarks >= 3003 && !NAMES.test(chartTxt)) await shot("shot_chart.webp"); else console.log("chart shot skipped (kept previous)", { full: chartFull, marks: chartMarks, len: (chartTxt || "").length, name: (chartTxt || "").match(NAMES)?.[0] || null });
if (labJson) {
  await nav(`${BASE}/${tok}/`);
  await evalJs("localStorage.setItem('owlLabIntro','1'); 1"); await nav("about:blank"); await nav(`${BASE}/${tok}/`); await sleep(7500);
  await evalJs("(function(){['tradepill','nudge','apkcard','expcard'].forEach(function(i){var p=document.getElementById(i);if(p)p.style.display='none';});window.labVisible=function(){return true;};window.labAllowed=function(){return true;};tab('marche',document.getElementById('tb-marche'));mxView('lab',true);})(); 1"); await sleep(3500);
  // the day's money is a moment, not a result: scroll the lab title to the top so the header leaves the frame
  await evalJs("(function(){var best=null;document.querySelectorAll('div,span,h2,h3,p').forEach(function(e){var t=(e.innerText||'').trim();if(/^LE LABO/i.test(t)&&(!best||t.length<best.t.length))best={e:e,t:t};});if(best)window.scrollTo(0,best.e.getBoundingClientRect().top+window.scrollY-18);})(); 1"); await sleep(800);
  const labTxt = await evalJs("document.body.innerText");
  if (labTxt && !NAMES.test(labTxt) && /testé|idées|IDÉES/i.test(labTxt)) await shot("shot_labo.webp"); else console.log("lab shot skipped (not rendered, or a name on screen)");
}
await send("Fetch.disable", {}, S);
const red = await evalJs("(function(){var d=window._d||{};return (typeof d.today==='number'&&d.today<0)||(typeof d.week==='number'&&d.week<0);})()");
const missing = ["shot_home.webp", "shot_marche.webp", "shot_hist.webp", "shot_chart.webp", "shot_labo.webp"].some(n => !existsSync(join(OUT, n)));
const only = process.env.SHOT_ONLY ? process.env.SHOT_ONLY.split(",") : null;
if (only) { for (const [n, b] of Object.entries(taken)) if (only.includes(n)) { writeFileSync(join(OUT, n), b); console.log("wrote static/" + n); } }
else if (red && !missing) { console.log("red day/week: landing shots kept as they were"); }
else { for (const [n, b] of Object.entries(taken)) { writeFileSync(join(OUT, n), b); console.log("wrote static/" + n); } }
ws.close(); edge.kill();
