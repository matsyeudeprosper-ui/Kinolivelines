// UI smoke test: drive the real pages and assert what they PAINT.
//
// 2026-09-30: a display switch was hung on the wrong block and silently
// took the main structure levels off the chart. Syntax was perfect, no
// runtime error, and the only thing that caught it was the owner looking
// at his phone. Screenshots do not assert; this does.
//
// The trick that found it is the trick this test is built on: wrap
// CanvasRenderingContext2D.prototype.fillText and record every string the
// chart paints. "Is the main structure still there" then has an exact
// answer instead of a squint.
//
//   node review/ui_smoke.mjs <out-dir>
//
// Exit code 1 means a check failed. Needs the app on 127.0.0.1:8787.
import { spawn } from "node:child_process";
import { writeFileSync, readFileSync, mkdirSync } from "node:fs";

const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const OUT = process.argv[2] || ".";
const BASE = "http://127.0.0.1:8787";
const PORT = 9701 + (Date.now() % 90);
mkdirSync(OUT, { recursive: true });

const users = JSON.parse(readFileSync(
  "C:/Projects/KinoliveLines/live/owl_nest_users.json", "utf8"));
const TOK = (id) => users.find(u => u.id === id).token;

const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run",
  "--no-default-browser-check", `--remote-debugging-port=${PORT}`,
  `--user-data-dir=${OUT}\\smokeprof`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

let ws = null, wsUrl = null;
for (let i = 0; i < 40 && !wsUrl; i++) {
  try {
    wsUrl = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`))
      .json()).webSocketDebuggerUrl;
  } catch { await sleep(250); }
}
if (!wsUrl) { console.log("no CDP - is Edge installed?"); edge.kill(); process.exit(1); }
ws = new WebSocket(wsUrl); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); const events = [];
ws.onmessage = (m) => {
  const d = JSON.parse(m.data);
  if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
  else if (d.method) events.push(d);
};
const send = (method, params = {}, sessionId) => new Promise(res => {
  const i = ++id; pending.set(i, res);
  ws.send(JSON.stringify({ id: i, method, params, sessionId }));
});
const waitEvent = async (name, sid, ms = 15000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < ms) {
    const k = events.findIndex(e => e.method === name && e.sessionId === sid);
    if (k >= 0) { events.splice(k, 1); return true; }
    await sleep(50);
  }
  return false;
};
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S);
const ev = async (expr) => {
  const r = await send("Runtime.evaluate",
    { expression: expr, returnByValue: true, awaitPromise: true }, S);
  if (r.result?.exceptionDetails)
    console.log("  JS ERR", r.result.exceptionDetails.exception?.description);
  return r.result?.result?.value;
};
const nav = async (url) => { await send("Page.navigate", { url }, S); await waitEvent("Page.loadEventFired", S); };
const shot = async (n) => {
  const { result } = await send("Page.captureScreenshot", { format: "png" }, S);
  writeFileSync(`${OUT}\\${n}.png`, Buffer.from(result.data, "base64"));
};

let fails = 0, skips = 0;
const check = (name, ok, detail) => {
  console.log(`  ${ok ? "ok  " : "FAIL"}  ${name}${detail ? "  -> " + detail : ""}`);
  if (!ok) fails++;
};
// A check with nothing to compare must say SKIP, not ok. A suite that
// reports green because it looked at an empty list is worse than no suite.
const skip = (name, why) => { console.log(`  SKIP  ${name}  -> ${why}`); skips++; };
await send("Emulation.setDeviceMetricsOverride",
  { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }, S);

// the recorder
const SPY = `(function(){var g=document.getElementById('cv').getContext('2d');
 var p=Object.getPrototypeOf(g);
 if(!window.__spy){window.__spy=p.fillText;
  p.fillText=function(t){try{window.__labels.push(String(t));}catch(e){}
   return window.__spy.apply(this,arguments);};}
 window.__labels=[];return 1;})()`;
const LABELS = `(function(){var u=[];(window.__labels||[]).forEach(function(s){
 if(s&&s.length>1&&!/^[0-9]+$/.test(s)&&u.indexOf(s)<0)u.push(s);});return u;})()`;

const VAL = TOK("u224016179");
console.log("UI SMOKE");
console.log("");

// ---------- the chart -------------------------------------------------
console.log("chart");
await nav(`${BASE}/${VAL}/chart`); await sleep(9000);
await ev("try{localStorage.setItem('owlIntMarks','1');localStorage.removeItem('owlHTF');}catch(e){} location.reload(); 1");
await sleep(9000);
check("no runtime errors on load", (await ev("(window.__errs||[]).length")) === 0,
      await ev("(window.__errs||[]).slice(0,2).join(' | ')"));
// force redraws rather than waiting on requestAnimationFrame: a headless
// background page may never schedule one, and a test that depends on the
// browser feeling like animating is a flaky test.
const paint = async (ms = 900) => {
  await ev("try{for(var i=0;i<3;i++)draw();}catch(e){} 1");
  await sleep(ms);
};
// NOTE on what is asserted here. "A BOS label is painted" is NOT a safe
// check: whether any level is labelled depends on where price is right now,
// so that assertion fails on a perfectly good chart in a quiet market. It
// did, on the first run. The market-independent invariant - and the one the
// 2026-09-30 bug actually broke - is that flipping the inner-marks switch
// changes ONLY inner labels and leaves every other label untouched.
await ev(SPY); await paint();
const rawOn = await ev("(window.__labels||[]).length") || 0;
const on = await ev(LABELS) || [];
check("the label recorder is alive", rawOn > 0, `${rawOn} paint call(s)`);

await ev("localStorage.setItem('owlIntMarks','0'); window.__labels=[]; 1");
await paint();
const off = await ev(LABELS) || [];
const isInner = (t) => /int /i.test(t) || /petite structure/i.test(t)
                    || /inner/i.test(t);
const mainOn = on.filter(t => !isInner(t)).sort();
const mainOff = off.filter(t => !isInner(t)).sort();
if (mainOn.length === 0 && mainOff.length === 0)
  skip("the switch leaves every non-inner label alone",
       "no level labels in view right now - quiet market, nothing to compare");
else
  check("the switch leaves every non-inner label alone",
        JSON.stringify(mainOn) === JSON.stringify(mainOff),
        `on: [${mainOn.join(" | ")}]  off: [${mainOff.join(" | ")}]`);
check("the switch does remove the inner labels when there are any",
      on.some(isInner) ? !off.some(isInner) : true,
      on.some(isInner) ? off.filter(isInner).join(" | ")
                       : "none in view right now");
await ev("localStorage.setItem('owlIntMarks','1'); 1");
await shot("smoke_chart");

// the two-timeframe panel still opens from the menu
await ev("document.getElementById('tools').click(); 1"); await sleep(600);
check("tools menu lists the two-timeframe entry",
      /Deux temps|Two timeframes/.test(await ev(
        "[...document.querySelectorAll('#toolsmenu .tb')].map(b=>b.textContent).join(' ')") || ""));
await ev("document.getElementById('htfbtn').click(); 1"); await sleep(900);
await ev("(()=>{const b=[...document.querySelectorAll('button')].find(x=>x.textContent.trim()==='H1'); if(b)b.click(); return 1;})()");
await sleep(4500);
check("higher panel opens and has candles",
      (await ev("HT.on && (HT.data&&HT.data.candles||[]).length>50")) === true,
      await ev("'on='+HT.on+' candles='+((HT.data&&HT.data.candles)||[]).length"));
check("header chips still reachable with the panel open",
      (await ev("(()=>{const e=document.getElementById('meteo');const b=e.getBoundingClientRect();const t=document.elementFromPoint(b.x+b.width/2,b.y+b.height/2);return !!(t&&(t.id==='meteo'||e.contains(t)));})()")) === true);
await shot("smoke_htf");
await ev("try{localStorage.removeItem('owlHTF');}catch(e){} 1");

// ---------- the two weather verdicts must agree -----------------------
// This has broken TWICE in two days: the card and the chart each chose the
// movement rule on "does an inner structure exist", which stopped being the
// bot's rule the moment inner entries were switched off. They are two
// renderings of ONE rule and the member can see both within two taps.
console.log("");
console.log("weather agreement");
const chartWx = await ev(`(function(){
  var w=(typeof wxState==='function')?wxState():null;
  return w?{k:w.k,mv:w.mv,nb:w.nb,intRule:w.intRule,mvOk:w.mvOk}:null;})()`);
check("the chart can state a weather verdict", !!chartWx,
      chartWx ? `${chartWx.k} (mv ${chartWx.mv}, nb ${chartWx.nb})` : "none");
await nav("about:blank"); await nav(`${BASE}/${VAL}/#marche`); await sleep(11000);
const cardTitle = await ev("(document.getElementById('mx-title')||{}).textContent");
const chartTitle = chartWx ? null : null;
// compare the DECISION, not the wording: both compute mvOk the same way, so
// a disagreement shows up as one saying "nothing to do" and the other not.
const cardSleep = /Rien .{0,3} faire|Nothing to do/i.test(cardTitle || "");
const chartSleep = chartWx ? (chartWx.k === "none") : null;
if (chartWx === null)
  skip("chart and card agree on movement", "the chart gave no verdict");
else
  check("chart and card agree on movement", cardSleep === chartSleep,
        `chart "${chartWx.k}" (sleep=${chartSleep}) vs card "${cardTitle}" (sleep=${cardSleep})`);
check("the chart uses the rule the bot runs",
      chartWx ? (chartWx.intRule === false) : true,
      chartWx ? `intRule=${chartWx.intRule} - inner entries are off, so the big rule must decide` : "");

// ---------- settings --------------------------------------------------
console.log("");
console.log("settings");
await nav("about:blank"); await nav(`${BASE}/${VAL}/#set`); await sleep(10000);
check("inner-marks row exists",
      (await ev("!!document.getElementById('intmkrow')")) === true);
check("its switch reflects the stored value",
      (await ev("document.getElementById('intmk-sw').classList.contains('on')")) === true);

// ---------- the proof -------------------------------------------------
console.log("");
console.log("proof");
await nav("about:blank"); await nav(`${BASE}/${VAL}/`); await sleep(11000);
await ev("if(typeof proofPage==='function')proofPage(); 1"); await sleep(2500);
check("proof deck opens", (await ev("!!(window._pv&&window._pv.S&&window._pv.S.length)")) === true);
let seen = false;
for (let k = 0; k < 8 && !seen; k++) {
  seen = (await ev("document.body.innerText.indexOf('ources')>=0")) === true;
  if (!seen) { await ev("if(window._pv&&window._pv.i<window._pv.S.length-1){window._pv.i++;pvPaint();} 1"); await sleep(600); }
}
check("the sources slide renders", seen);
check("the honest note about the retired rule is on it",
      (await ev("document.body.innerText.indexOf('Note honn')>=0 || document.body.innerText.indexOf('Honest note')>=0")) === true);
await shot("smoke_proof");
check("no runtime errors anywhere", (await ev("(window.__errs||[]).length")) === 0,
      await ev("(window.__errs||[]).slice(0,3).join(' | ')"));

console.log("");
console.log(fails ? `UI SMOKE: ${fails} CHECK(S) FAILED`
      : (skips ? `UI SMOKE: OK (${skips} skipped, nothing to compare)`
               : "UI SMOKE: OK"));
ws.close(); edge.kill();
process.exit(fails ? 1 : 0);
