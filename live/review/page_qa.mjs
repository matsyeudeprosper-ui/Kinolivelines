// page_qa.mjs (2026-11-06, owner: "make sure QA catches the little things - caching and all - so the first impression is so good")
// Opens a client page in a real browser like a visitor would, on a phone (360 px) and a computer (1366 px), and reports
// what a visitor would notice. Prints one JSON object: {"issues": [...], "notes": [...]}.
//   node live/review/page_qa.mjs <url>
import { execSync as __tk } from "node:child_process";
import { spawn } from "node:child_process"; import { rmSync, mkdtempSync } from "node:fs"; import { tmpdir } from "node:os"; import { join } from "node:path";
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe", PORT = 9400 + Math.floor(Math.random() * 500);
const URL_ = process.argv[2];
const prof = mkdtempSync(join(tmpdir(), "pqa_"));
const edge = spawn(EDGE, ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${PORT}`, `--user-data-dir=${prof}`, "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise(r => setTimeout(r, ms));
const issues = [], notes = [];
const done = (code) => {
  try { edge.kill(); __tk("powershell -NoProfile -ExecutionPolicy Bypass -File C:/Projects/KinoliveLines/live/review/kill_temp_edge.ps1", { stdio: "ignore" }); } catch { }
  try { rmSync(prof, { recursive: true, force: true }); } catch { }
  console.log(JSON.stringify({ issues, notes })); process.exit(code);
};
setTimeout(() => { issues.push("the page check did not finish in 90 s (very slow page?)"); done(0); }, 90000);
let u = null; for (let i = 0; i < 120 && !u; i++) { try { u = (await (await fetch(`http://127.0.0.1:${PORT}/json/version`)).json()).webSocketDebuggerUrl; } catch { await sleep(250); } }
if (!u) { issues.push("could not start the test browser"); done(0); }
const ws = new WebSocket(u); await new Promise(r => ws.onopen = r);
let id = 0; const pending = new Map(); const events = [];
ws.onmessage = (m) => { const d = JSON.parse(m.data); if (d.id && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); } else if (d.method) events.push(d); };
const send = (method, params = {}, sessionId) => new Promise(res => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params, sessionId })); });
const { result: { targetId } } = await send("Target.createTarget", { url: "about:blank" });
const { result: { sessionId: S } } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, S); await send("Runtime.enable", {}, S); await send("Network.enable", {}, S);
await send("Network.setCacheDisabled", { cacheDisabled: true }, S);
const ev = async (e) => (await send("Runtime.evaluate", { expression: e, returnByValue: true, awaitPromise: true }, S)).result?.result?.value;

for (const [label, width, mobile] of [["phone", 360, true], ["computer", 1366, false]]) {
  await send("Emulation.setDeviceMetricsOverride", { width, height: mobile ? 760 : 900, deviceScaleFactor: mobile ? 2 : 1, mobile }, S);
  const t0 = Date.now();
  await send("Page.navigate", { url: URL_ }, S); await sleep(4500);
  const r = await ev(`(async()=>{
    const W=innerWidth, out={};
    // what only shows on some phones (the Android "install the app" button): shown, so the layout is tested with it
    document.querySelectorAll('header button, header a, nav button').forEach(b=>{ if(getComputedStyle(b).display==='none' && /install|installer|l'app|the app|app|instalar/i.test((b.id||'')+' '+(b.innerText||b.textContent||''))){ b.style.display='inline-flex'; b.dataset.qaShown='1'; } });
    await new Promise(r=>setTimeout(r,300));
    for(let y=0;y<document.documentElement.scrollHeight;y+=500){scrollTo(0,y);await new Promise(r=>setTimeout(r,60))} scrollTo(0,0);
    await new Promise(r=>setTimeout(r,500));
    out.sw=document.documentElement.scrollWidth; out.W=W;
    const name=e=>(e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+((e.className&&typeof e.className==='string')?'.'+e.className.trim().split(/\\s+/)[0]:'')+' "'+(e.innerText||e.alt||'').trim().slice(0,30)+'"');
    out.over=[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect(); const s=getComputedStyle(e);
      return r.width>0 && r.right>W+2 && s.position!=='fixed' && !e.closest('[aria-hidden=true]') && (e.innerText||'').trim().length>0 && e.children.length===0;}).slice(0,6).map(name);
    out.hiddenButtons=[...document.querySelectorAll('[data-qa-shown]')].map(name);
    out.headerOver=[...document.querySelectorAll('header *')].filter(e=>{const r=e.getBoundingClientRect(); return r.width>0 && (r.right>W+1 || r.left< -1);}).slice(0,4).map(name);
    out.broken=[...document.images].filter(i=>i.complete && i.naturalWidth===0).map(i=>i.getAttribute('src'));
    out.small=[...document.images].filter(i=>i.naturalWidth>0 && i.getBoundingClientRect().width>0 && i.naturalWidth < i.getBoundingClientRect().width*1.2 && i.getBoundingClientRect().width>200).map(i=>i.getAttribute('src')+' ('+i.naturalWidth+'px shown at '+Math.round(i.getBoundingClientRect().width)+'px)').slice(0,4);
    out.unversioned=[...new Set([...document.images].map(i=>i.getAttribute('src')||'').filter(s=>s && !/^(https?:|data:)/.test(s) && !/[?]v=/.test(s)))].slice(0,5);
    const res=performance.getEntriesByType('resource'); out.kb=Math.round((res.reduce((a,r)=>a+(r.transferSize||r.encodedBodySize||0),0)+(performance.getEntriesByType('navigation')[0]?.transferSize||0))/1024);
    out.big=res.filter(r=>(r.encodedBodySize||0)>500000).map(r=>r.name.split('/').pop()+' '+Math.round(r.encodedBodySize/1024)+'KB').slice(0,4);
    out.lang=document.documentElement.lang||''; out.title=document.title||'';
    out.tel=document.querySelectorAll('a[href^="tel:"]').length;
    out.deadLinks=[...document.querySelectorAll('a[href^="#"]')].map(a=>a.getAttribute('href')).filter(h=>h.length>1 && !document.getElementById(decodeURIComponent(h.slice(1)))).slice(0,5);
    out.tiny=[...document.querySelectorAll('p, li, a, span, small')].filter(e=>{const s=parseFloat(getComputedStyle(e).fontSize); const r=e.getBoundingClientRect(); return r.width>0 && (e.innerText||'').trim().length>3 && s<11;}).length;
    out.lowContrastText=[...document.querySelectorAll('h1,h2,h3,p')].filter(e=>{const c=getComputedStyle(e).color.match(/\\d+(\\.\\d+)?/g); return c && c.length===4 && parseFloat(c[3])<0.45;}).length;
    return out;})()`);
  const ms = Date.now() - t0;
  if (!r) { issues.push(`${label}: the page did not load`); continue; }
  if (r.sw > r.W + 2) issues.push(`${label}: the page scrolls sideways (${r.sw}px wide on a ${r.W}px screen)${r.over.length ? " - sticking out: " + r.over.join(", ") : ""}`);
  if (r.headerOver.length) issues.push(`${label}: the top bar does not fit${r.hiddenButtons.length ? " once the button(s) some phones show appear (" + r.hiddenButtons.join(", ") + ")" : ""} - cut off: ${r.headerOver.join(", ")}`);
  if (r.broken.length) issues.push(`${label}: broken images: ${r.broken.join(", ")}`);
  if (r.small.length && label === "computer") notes.push(`photos smaller than shown, may look soft on a computer: ${r.small.join("; ")}`);
  if (r.big.length) issues.push(`${label}: heavy files that make a phone wait: ${r.big.join(", ")}`);
  if (label === "phone" && r.kb > 3000) issues.push(`phone: the page weighs ${r.kb} KB - too heavy for a first visit on mobile data`);
  if (label === "phone" && r.unversioned.length) issues.push(`images without a version in their address (a rebuilt page would show OLD cached photos to someone who already opened it): ${r.unversioned.join(", ")} - use img/x.jpg?v=2`);
  if (r.deadLinks.length && label === "phone") issues.push(`links that go nowhere: ${r.deadLinks.join(", ")}`);
  if (label === "phone" && r.tiny > 0) notes.push(`${r.tiny} bits of text under 11px on a phone (hard to read)`);
  if (r.lowContrastText && label === "phone") notes.push(`${r.lowContrastText} headings/paragraphs very faint`);
  if (!r.lang) issues.push("no language set on the page (<html lang=...>)");
  if (label === "phone") notes.push(`phone: ${r.kb} KB, loaded in about ${Math.round(ms / 1000)} s, language "${r.lang}", ${r.tel} call link(s)`);
}
const errs = events.filter(e => e.method === "Runtime.exceptionThrown").map(e => (e.params.exceptionDetails.exception || {}).description || "error");
if (errs.length) issues.push("JavaScript errors: " + [...new Set(errs)].slice(0, 3).join(" | ").slice(0, 300));
const failed = events.filter(e => e.method === "Network.loadingFailed" && !e.params.canceled).length;
if (failed) issues.push(`${failed} file(s) failed to load`);
done(0);
