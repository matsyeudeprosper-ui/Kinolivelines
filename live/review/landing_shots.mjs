// Landing screenshots (2026-09-27): three real renders of the public demo -
// home, market, history - written to static/shot_*.png and served at
// /shots/<name>.png for the landing carousel and the Open Graph preview.
//   node review/landing_shots.mjs
// Node 22 + Edge, no deps. Re-run whenever the design changes (boot_all can
// call it daily; the landing hides a figure whose image is missing).
import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
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
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else if (d.method) events.push(d); };
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
const shot = async (name) => { const { result } = await send("Page.captureScreenshot", { format: "png" }, S); taken[name] = Buffer.from(result.data, "base64"); };
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 780, deviceScaleFactor: 2, mobile: true }, S);
await nav(`${BASE}/${tok}/`);
await evalJs("localStorage.setItem('owlTourDone','1'); localStorage.removeItem('owlTheme'); localStorage.removeItem('owlBig'); localStorage.removeItem('owl_adm'); localStorage.removeItem('owlLang'); 1");
await nav("about:blank"); await nav(`${BASE}/${tok}/`); await sleep(7500);
await evalJs("window.scrollTo(0,0); 1"); await shot("shot_home.png");
await evalJs("tab('marche', document.querySelectorAll('.tb')[1]); window.scrollTo(0,0); 1"); await sleep(800); await shot("shot_marche.png");
await evalJs("tab('hist', document.querySelectorAll('.tb')[2]); window.scrollTo(0,0); 1"); await sleep(800); await shot("shot_hist.png");
const red = await evalJs("(function(){var d=window._d||{};var h=(document.querySelector('.hero')||{}).innerText||'';var w=(document.getElementById('tab-hist')||{}).innerText||'';return (typeof d.today==='number'&&d.today<0)||/-\\$\\d/.test(h)||/Cette semaine : -\\$|This week: -\\$/.test(w);})()");
const { existsSync } = await import("node:fs");
const missing = ["shot_home.png", "shot_marche.png", "shot_hist.png"].some(n => !existsSync(join(OUT, n)));
if (red && !missing) { console.log("red day/week: landing shots kept as they were"); }
else { for (const [n, b] of Object.entries(taken)) { writeFileSync(join(OUT, n), b); console.log("wrote static/" + n); } }
ws.close(); edge.kill();
