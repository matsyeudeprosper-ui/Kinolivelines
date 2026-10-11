// landing_check.mjs (2026-10-11): the logged-out landing as a NEW visitor sees it
// (fresh profile, phone emulation). Captures top-to-bottom slices at 390 and 360 px,
// reports horizontal overflow, JS errors, and which acquisition blocks rendered.
//   node live/review/landing_check.mjs <outdir>
import { spawn } from "node:child_process";
import { writeFileSync, mkdirSync } from "node:fs";
const OUT = process.argv[2] || "."; mkdirSync(OUT, { recursive: true });
const EDGE = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe", PORT = 9341, PROF = `${OUT}/lcprof_${Date.now()}`; // fresh visitor every run
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROF}`, "about:blank"], { stdio: "ignore" });
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
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S);
// never count this check in the owner's visitor numbers (fn() skips events already in sessionStorage)
await send("Page.addScriptToEvaluateOnNewDocument", { source: "try{['landing','offers','choose','proof_seen','proof_switch','proof_open','demo_open','tg_open','faq_more'].forEach(e=>sessionStorage.setItem('fn_'+e,'1'))}catch(e){}" }, S);
const evalJs = async (expr) => (await send("Runtime.evaluate", { expression: expr, returnByValue: true, awaitPromise: true }, S)).result?.result?.value;
let bad = 0;
for (const w of [390, 360]) {
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: 844, deviceScaleFactor: 2, mobile: true }, S);
  await send("Page.navigate", { url: "http://127.0.0.1:8787/join" }, S); await waitEvent("Page.loadEventFired", S); await sleep(5000);
  const r = await evalJs(`(()=>{const de=document.documentElement,q=id=>{const e=document.getElementById(id);return !!e&&!e.hidden&&e.offsetHeight>0};
    const wide=[...document.querySelectorAll('body *')].filter(e=>{const b=e.getBoundingClientRect();return b.width>0&&b.right>innerWidth+1&&getComputedStyle(e).position!=='fixed'&&!e.closest('.shots,.carousel,[class*=scroll]')}).slice(0,6).map(e=>e.tagName+'.'+e.className+'#'+e.id+' r='+Math.round(e.getBoundingClientRect().right));
    return {sw:de.scrollWidth,iw:innerWidth,h:de.scrollHeight,proof:q('pf2'),worst:q('pw'),trust:q('trust'),calc:q('calc'),shots:document.querySelectorAll('#shots-sec figure:not([style*=none])').length,tg:q('tgc'),tgHref:(document.getElementById('tg-go')||{}).href,
     faqOpen:document.querySelectorAll('details.fq:not(details.fqall details.fq)').length,faqMore:document.querySelectorAll('details.fqall details.fq').length,wide}})()`);
  const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => e.params.exceptionDetails.exception?.description?.split("\n")[0]); events.length = 0;
  console.log(w, JSON.stringify(r), errs.length ? "JS ERRORS: " + errs.join(" | ") : "no JS errors");
  if (!r || r.sw > r.iw || errs.length || !r.proof || !r.worst || !r.trust || !r.calc || !r.tg) bad++;
  await send("Emulation.setDeviceMetricsOverride", { width: w, height: Math.min(r.h, 7000), deviceScaleFactor: 1, mobile: true }, S); await sleep(800);
  const { result } = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true }, S);
  writeFileSync(`${OUT}/landing_${w}.png`, Buffer.from(result.data, "base64"));
}
// English: the new blocks must not keep French text
await send("Emulation.setDeviceMetricsOverride", { width: 390, height: 844, deviceScaleFactor: 2, mobile: true }, S);
await evalJs(`(()=>{const b=[...document.querySelectorAll('button,a')].find(x=>x.textContent.trim()==='EN');if(b)b.click();return !!b})()`); await sleep(1500);
const en = await evalJs(`(()=>['pf2','pw','trust','calc','tgc'].map(id=>{const e=document.getElementById(id);return id+': '+(e?e.innerText.replace(/\\s+/g,' ').slice(0,260):'-')}).concat(['FAQ more: '+(document.querySelector('details.fqall>summary')||{}).textContent, 'tag: '+(document.querySelector('.tag')||{}).innerText]))()`);
console.log("EN\n" + (en || []).join("\n"));
edge.kill(); process.exit(bad ? 1 : 0);
