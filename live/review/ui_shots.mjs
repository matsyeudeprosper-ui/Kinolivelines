// review/ui_shots.mjs - headless Edge (CDP) renders of the OwlNest app at
// phone size with the first-visit tour dismissed: home / history / settings /
// landing, plus an overflow report (elements wider than the viewport).
// Usage: node review/ui_shots.mjs <output-dir> [prefix] [light]
//   prefix  -> file name prefix (default b5_);  light -> render the opt-in light theme
// Node 22+ (built-in WebSocket) + Edge; re-run after any UI change and compare PNGs.
// Drive headless Edge over CDP: dismiss the tour, screenshot each tab at
// phone size (full page), and report elements wider than the viewport.
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT = process.argv[2];
const BASE = "http://127.0.0.1:8787";
const TOKEN = "F61w0YMMyBiH";
const PORT = 9333; const PFX = process.argv[3] || "b5_"; const LIGHT = process.argv[4] === "light";

const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run",
  "--no-default-browser-check", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${OUT}\\edgeprof2`, "about:blank"], { stdio: "ignore" });

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
let wsUrl = null;
for (let i = 0; i < 40 && !wsUrl; i++) {
  try { const v = await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json();
        wsUrl = v.webSocketDebuggerUrl; } catch { await sleep(250); }
}
if (!wsUrl) { console.log("no CDP"); edge.kill(); process.exit(1); }

const ws = new WebSocket(wsUrl);
await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); const events = [];
ws.onmessage = (m) => { const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  else if (d.method) events.push(d); };
const send = (method, params = {}, sessionId) => new Promise(res => {
  const i = ++id; pending.set(i, res);
  ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const waitEvent = async (name, sid, ms = 15000) => { const t0 = Date.now();
  while (Date.now() - t0 < ms) { const k = events.findIndex(e => e.method === name && e.sessionId === sid);
    if (k >= 0) { events.splice(k, 1); return true; } await sleep(50); } return false; };

const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S);
await send("Runtime.enable", {}, S);
const evalJs = async (expr) => (await send("Runtime.evaluate",
  { expression: expr, returnByValue: true, awaitPromise: true }, S)).result?.result?.value;
const setViewport = (w, h) => send("Emulation.setDeviceMetricsOverride",
  { width: w, height: h, deviceScaleFactor: 2, mobile: true }, S);
const nav = async (url) => { await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); };
const shot = async (name, w) => {
  const h = Math.min(4000, Math.max(844, await evalJs("document.documentElement.scrollHeight")));
  await setViewport(w, h); await sleep(400);
  const { result } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }, S);
  writeFileSync(`${OUT}\\${name}.png`, Buffer.from(result.data, "base64"));
  await setViewport(w, 844);
  console.log(`shot ${name} ${w}x${h}`);
};
const overflow = async (label) => {
  const r = await evalJs(`(()=>{const W=innerWidth;const out=[];
    for(const el of document.querySelectorAll('body *')){const cs=getComputedStyle(el);
      if(cs.display==='none'||cs.position==='fixed')continue;const b=el.getBoundingClientRect();
      if(b.width>0&&b.right>W+1)out.push([el.tagName.toLowerCase()+(el.id?'#'+el.id:'')+(el.className&&typeof el.className==='string'?'.'+el.className.trim().split(/\\s+/).join('.'):''),Math.round(b.right-W),Math.round(b.width)]);}
    out.sort((a,b)=>b[1]-a[1]);return {W,scrollW:document.documentElement.scrollWidth,bodyW:document.body.scrollWidth,top:out.slice(0,12)};})()`);
  console.log(`OVERFLOW ${label}: innerWidth=${r.W} docScrollWidth=${r.scrollW} bodyScrollWidth=${r.bodyW}`);
  for (const [sel, over, w] of r.top) console.log(`   +${over}px  w=${w}  ${sel}`);
};

// ---- account page, tour dismissed
await setViewport(390, 844);
await nav(`${BASE}/${TOKEN}/`);
await evalJs("localStorage.setItem('owlTourDone','1'); " + (LIGHT ? "localStorage.setItem('owlTheme','light');" : "localStorage.removeItem('owlTheme');") + " 1");
await nav(`${BASE}/${TOKEN}/`);
await sleep(7000);   // first data poll
await overflow("account/home 390");
await shot(PFX+"home_390", 390);
for (const [t, idx, name] of [["hist", 1, PFX+"hist_390"], ["set", 3, PFX+"set_390"]]) {
  await evalJs(`tab('${t}', document.querySelectorAll('.tb')[${idx}]); 1`);
  await sleep(1200);
  await overflow(`account/${t} 390`);
  await shot(name, 390);
}
// Le Nid tab only if visible
const nidVis = await evalJs("getComputedStyle(document.getElementById('tb-nid')).display!=='none'");
console.log("nid tab visible:", nidVis);
// ---- iPhone SE width (smallest common) home
await setViewport(375, 667);
await nav(`${BASE}/${TOKEN}/`); await sleep(6000);
await overflow("account/home 375");
// ---- landing / join
await setViewport(390, 844);
await nav(`${BASE}/join`); await sleep(1500);
await overflow("join 390");
await shot(PFX+"join_390", 390);
// ---- chart page
await nav(`${BASE}/${TOKEN}/chart`); await sleep(4000);
await overflow("chart 390");
// ---- fonts actually used
console.log("font-family body(account):", await evalJs("getComputedStyle(document.body).fontFamily"));
ws.close(); edge.kill();
