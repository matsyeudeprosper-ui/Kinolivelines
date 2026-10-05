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

// 2026-10-02: this suite failed its first run after EVERY restart.ps1 and
// passed on the re-run - three times in one evening. Not a flaky product:
// a flaky test. The app answers on 8787 the moment it binds, but the chart
// feed and the day's payload land a few seconds later, so the first page
// load raced them and checks fired against half-built state.
//
// A suite that cries wolf after every restart is a suite people stop
// reading, which is exactly when it stops catching anything. So it waits
// for the server to be genuinely ready before it judges anything.
{
  const t0 = Date.now();
  let ready = false, why = "no response";
  while (Date.now() - t0 < 90000 && !ready) {
    try {
      const r = await fetch(`${BASE}/${VAL}/api?t=${Date.now()}`,
        { cache: "no-store" });
      if (r.ok) {
        const j = await r.json();
        // balance present means the worker file is loaded, not just the
        // socket open; the chart checks need the feed too
        if (j && j.balance !== undefined && !j.error) ready = true;
        else why = j && j.error ? String(j.error) : "payload incomplete";
      } else why = "http " + r.status;
    } catch (e) { why = e.message; }
    if (!ready) await sleep(1500);
  }
  console.log(ready
    ? `  (server ready after ${((Date.now() - t0) / 1000).toFixed(1)}s)`
    : `  WARNING: server not ready after 90s - ${why}; running anyway`);
}

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
// 2026-10-02: after a reload the candles can still be in flight when the
// fixed sleep ends, and draw() then paints nothing - a false "recorder is
// dead". Give the data up to ~25s to arrive before judging the recorder.
for (let k = 0; k < 12 && !((await ev("(window.__labels||[]).length")) > 0); k++)
  await paint(2000);
const rawOn = await ev("(window.__labels||[]).length") || 0;
const on = await ev(LABELS) || [];
check("the label recorder is alive", rawOn > 0, `${rawOn} paint call(s)`);

await ev("localStorage.setItem('owlIntMarks','0'); window.__labels=[]; 1");
await paint();
const off = await ev(LABELS) || [];
const isInner = (t) => /int /i.test(t) || /petite structure/i.test(t)
                    || /inner/i.test(t);
// An open trade's floating P&L is painted into its labels and ticks while
// the test runs, so comparing the raw strings reports a difference that has
// nothing to do with the switch. It did, once. Compare with the money
// blanked out: the switch must not add or remove a label, and the live
// number is not the switch's business.
const noMoney = (t) => t.replace(/[-+−]?\$[0-9.,]+/g, "$");
const mainOn = [...new Set(on.filter(t => !isInner(t)).map(noMoney))].sort();
const mainOff = [...new Set(off.filter(t => !isInner(t)).map(noMoney))].sort();
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

// 2026-10-01: "dernier BOS" showed the last MARK, and marks hold only the
// breaks that TURN the trend - so after a continuation break the glowing
// protected dot moved and the label did not. It was 27 days stale on H4.
// The invariant: if the label is painted, its number is the newest break.
//
// The annotated structure is gated on FULL, which is the owner's view, so
// the check has to ask for it - run as a plain member it finds no label at
// all and skips, which is how the first version of this check quietly
// tested nothing.
await ev("try{localStorage.setItem('owl_adm','1');}catch(e){} location.reload(); 1");
await sleep(9000);
await ev(SPY);
check("the annotated structure view is on for this check",
      (await ev("FULL")) === true);
await ev("window.__labels=[]; 1"); await paint();
const painted = (await ev(LABELS) || []).filter(t => /(dernier|last) BOS/i.test(t));
const newest = await ev(
  "(function(){var b=(D&&D.breaks||[]).slice(-1)[0];return b?b[2]:null;})()");
const lastMark = await ev("(function(){var m=(D&&D.marks||[])"
  + ".filter(function(x){return x[2]==='bos';}).slice(-1)[0];"
  + "return m?m[1]:null;})()");
const differ = newest !== null && lastMark !== null
            && Math.round(newest) !== Math.round(lastMark);
if (!painted.length || newest === null)
  skip("\"dernier BOS\" shows the newest break",
       newest === null ? "no break in the window yet"
                       : "no label in view - off-screen or merged");
else
  check("\"dernier BOS\" shows the newest break",
        painted.some(t => t.indexOf(String(Math.round(newest))) >= 0),
        `painted [${painted.join(" | ")}]  newest break ${newest}`
        + `  last mark ${lastMark}`
        + (differ ? "  (they differ now, so this check has teeth)" : ""));
await shot("smoke_chart");
// back to the member view for everything below
await ev("try{localStorage.removeItem('owl_adm');}catch(e){} location.reload(); 1");
await sleep(8000);

// two timeframes belong to Strategie only (owner 2026-10-05): a family member must not see the entry nor an empty panel
await ev("document.getElementById('tools').click(); 1"); await sleep(600);
check("two-timeframe entry is hidden for a non-Strategie member",
      (await ev("getComputedStyle(document.getElementById('htfbtn')).display==='none' && HTFOK===false && !HT.on")) === true);
await ev("document.getElementById('tools').click(); 1"); await sleep(300);
check("header chips still reachable",
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
const readChartWx = () => ev(`(function(){
  var w=(typeof wxState==='function')?wxState():null;
  return w?{k:w.k,mv:w.mv,nb:w.nb,intRule:w.intRule,mvOk:w.mvOk}:null;})()`);
let chartWx = await readChartWx();
check("the chart can state a weather verdict", !!chartWx,
      chartWx ? `${chartWx.k} (mv ${chartWx.mv}, nb ${chartWx.nb})` : "none");
const readCard = async () => {
  await nav("about:blank"); await nav(`${BASE}/${VAL}/#marche`); await sleep(11000);
  return await ev("(document.getElementById('mx-title')||{}).textContent");
};
let cardTitle = await readCard();
// compare the DECISION, not the wording: both compute mvOk the same way, so
// a disagreement shows up as one saying "nothing to do" and the other not.
const isSleep = (t) => /Rien .{0,3} faire|Nothing to do/i.test(t || "");
let cardSleep = isSleep(cardTitle);
let chartSleep = chartWx ? (chartWx.k === "none") : null;
// 2026-10-02: the two reads are ~20s apart and the movement count is a
// rolling 2h window, so a mark landing between them is a real change, not a
// disagreement (it failed 1 run in 3). Only two paired reads in a row that
// still differ count as a fail.
if (chartWx !== null && cardSleep !== chartSleep) {
  await nav("about:blank"); await nav(`${BASE}/${VAL}/chart`); await sleep(9000);
  const again = await readChartWx();
  if (again) { chartWx = again; chartSleep = again.k === "none"; }
  cardTitle = await readCard(); cardSleep = isSleep(cardTitle);
}
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
// 2026-10-02: proofPage() returns silently while window._proof is still in
// flight (1 run in 3 failed here for that reason alone) - retry until the
// deck exists instead of judging a page that had not loaded yet.
for (let k = 0; k < 10; k++) {
  await ev("if(typeof proofPage==='function')proofPage(); 1"); await sleep(2500);
  if ((await ev("!!(window._pv&&window._pv.S&&window._pv.S.length)")) === true) break;
}
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

// ---------- the lab, the night, the nest (2026-10-03) ------------------
// The three screens that changed most this week, and that only hand-made
// probes covered. kino = Strategie access + admin, so every block renders.
console.log("");
console.log("labo");
{
  const KIN = TOK("kino");
  await nav("about:blank"); await nav(`${BASE}/${KIN}/`);
  await ev("try{localStorage.setItem('owlTourDone','1');localStorage.setItem('owl_adm','1');localStorage.setItem('owlLabIntro','1');}catch(e){}1");
  await nav(`${BASE}/${KIN}/`); await sleep(12000);
  await ev("(function(){var b=document.getElementById('tb-marche');if(b)b.click();return 1;})()"); await sleep(1500);
  await ev("(function(){var b=document.getElementById('mxs-lab');if(b)b.click();return 1;})()"); await sleep(5000);
  const order = await ev("Array.from(document.getElementById('lab-body').children).map(function(e){return e.className||e.id;}).join(' > ')");
  // 2026-10-03: the week card (Sunday's digest) may sit between hero and board; the lab's robot card sits after the board
  check("labo landing is hero > (week) > board > robot > clues row", /labhero > (panel labweek > )?panel jboard > panel lablabo/.test(order) && /labseedrow/.test(order), order);
  check("the board has four columns", (await ev("document.querySelectorAll('.jrail .jn').length")) === 4);
  check("a card renders in the open column", (await ev("document.querySelectorAll('#jcards .lc').length")) >= 1);
  const lt = await ev("document.getElementById('lab-body').innerText");
  check("no bare A/B/C verdict badge", !/(^|,)[ABC](,|$)/.test(await ev("Array.from(document.querySelectorAll('.lcb')).map(function(e){return e.innerText.trim();}).filter(Boolean).join(',')")));
  check("no NaN/undefined on the landing", !/NaN|undefined/.test(lt));
  await ev("(function(){var h=document.querySelector('.labhero');if(h)h.click();return 1;})()"); await sleep(1500);
  const navTxt = await ev("Array.from(document.querySelectorAll('.nt-nav button')).map(function(b){return b.innerText;}).join(' | ')");
  check("the night report opens with its sections", (await ev("document.querySelectorAll('.nt-sec').length")) >= 3, navTxt);
  check("the report has no bare verdict letter", !/(?<=[\s(:])[ABC](?=[\s,.;:)])/.test(await ev("(function(){var c=document.getElementById('sheet-c').cloneNode(true);c.querySelectorAll('.nt-chip').forEach(function(e){e.remove();});return c.innerText;})()")));
  await shot("smoke_labo");
  await ev("window._shDone&&_shDone(1);1"); await sleep(500);
  await ev("(function(){var b=document.getElementById('tb-nid');if(b){b.style.display='';b.click();}return !!b;})()"); await sleep(3500);
  check("le Nid lists the accounts", (await ev("document.querySelectorAll('#nest .nrow').length")) >= 3);
  check("le Nid rows carry no emoji", !/[\u{1F300}-\u{1FAFF}]/u.test(await ev("document.getElementById('nest').innerText")));
  check("no runtime errors on the lab screens", (await ev("(window.__errs||[]).length")) === 0,
        await ev("(window.__errs||[]).slice(0,3).join(' | ')"));
}

console.log("");
console.log(fails ? `UI SMOKE: ${fails} CHECK(S) FAILED`
      : (skips ? `UI SMOKE: OK (${skips} skipped, nothing to compare)`
               : "UI SMOKE: OK"));
ws.close(); edge.kill();
process.exit(fails ? 1 : 0);
