import re

# 1) worker: expose the open trades list
wp = r'C:\Projects\KinoliveLines\live\owl_nest_worker.py'
w = open(wp, encoding='utf-8').read()
old = '''    te = mt5.symbol_info_tick("EURUSDm")'''
new = '''    if BOT_ONLY:
        _shown = [p for p in open_pos
                  if (p.comment or "").startswith("OWL-")]
    else:
        _shown = list(open_pos)
    open_list = [{"d": ("A" if p.type == mt5.POSITION_TYPE_BUY else "V"),
                  "lot": p.volume,
                  "pl": round(p.profit + p.swap, 2)} for p in _shown]
    te = mt5.symbol_info_tick("EURUSDm")'''
assert old in w and w.count(old) == 1
w = w.replace(old, new)
old = '''        "open_positions": len(open_pos),'''
new = '''        "open_positions": len(open_list),
        "open_list": open_list,'''
assert old in w
w = w.replace(old, new)
open(wp, 'w', encoding='utf-8').write(w)
import ast
ast.parse(w)
print('worker upgraded')

# 2) dashboard v5
p = r'C:\Projects\KinoliveLines\live\owl_app_server.py'
s = open(p, encoding='utf-8').read()
i0 = s.index('PAGE = """')
i1 = s.index('"""\n\n\nUSERS_FILE', i0) + 3

new_page = 'PAGE = """' + '''<!doctype html><html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0f2740">
<title>OwlNest</title>
<style>
*{box-sizing:border-box;margin:0}
body{background:#0b0f14;color:#e8eef4;padding:0 0 44px;
 font-family:-apple-system,'Segoe UI',Roboto,sans-serif}
.hero{background:linear-gradient(165deg,#0f2740 0%,#14406b 100%);
 color:#fff;padding:22px 22px 38px;border-radius:0 0 30px 30px;
 text-align:center;box-shadow:0 8px 24px rgba(0,0,0,.35)}
.topline{display:flex;justify-content:space-between;align-items:center}
.brand{font-weight:700;color:#cfe3f5;font-size:1.02rem}
.live{display:inline-flex;align-items:center;gap:6px;
 background:rgba(46,204,113,.16);color:#8df0bb;font-size:.7rem;
 font-weight:700;padding:4px 11px;border-radius:999px;
 letter-spacing:.06em}
.dot{width:8px;height:8px;border-radius:50%;background:#2ecc71;
 animation:p 1.8s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
.hello{color:#9fc2de;font-size:.95rem;margin-top:16px}
.money{font-size:3.5rem;font-weight:800;margin-top:6px;
 letter-spacing:-1px}
.eur{color:#9fc2de;font-size:1.2rem;margin-top:2px}
.bankline{color:#7d9cb8;font-size:.85rem;margin-top:9px}
.wrap{max-width:440px;margin:-20px auto 0;padding:0 16px}
.status{background:#151d29;border-radius:18px;padding:16px;
 text-align:center;font-size:1.04rem;color:#c6d3df;
 box-shadow:0 6px 18px rgba(0,0,0,.35)}
.panel{background:#151d29;border-radius:18px;padding:16px;
 box-shadow:0 6px 18px rgba(0,0,0,.35)}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
.card{background:#151d29;border-radius:18px;padding:18px 10px 15px;
 text-align:center;box-shadow:0 6px 18px rgba(0,0,0,.35)}
.lbl{font-size:.74rem;color:#8fa1b3;text-transform:uppercase;
 letter-spacing:.06em;font-weight:600}
.val{font-size:1.6rem;font-weight:800;margin-top:8px}
.sub{font-size:.72rem;color:#5f7185;margin-top:6px}
.pos{color:#2ecc71}.neg{color:#ff5c5c}.neu{color:#e8eef4}
.sec{margin:24px 6px 10px;color:#b9c7d4;font-weight:700;font-size:.96rem;
 text-align:left}
.row{display:flex;justify-content:space-between;align-items:center;
 padding:11px 4px;border-bottom:1px solid #1e2937;font-size:1rem}
.row:last-child{border-bottom:0}
.rowt{color:#8fa1b3;font-size:.92rem}
.bd{display:inline-block;width:8px;height:8px;border-radius:50%;
 margin-right:8px;animation:p 1.8s infinite}
#inst{display:none;width:100%;margin-top:24px;background:#2563eb;
 color:#fff;border:0;border-radius:14px;padding:16px;font-size:1.06rem;
 font-weight:700}
.foot{margin-top:20px;text-align:center;font-size:.8rem;color:#5f7185}
.exit{display:block;margin-top:14px;text-align:center;color:#5f7185;
 font-size:.82rem;text-decoration:none}
</style></head><body>
<div class="hero">
<div class="topline"><span class="brand">&#129417; OwlNest</span>
<span class="live"><span class="dot"></span>EN DIRECT</span></div>
<div class="hello">Bonjour %%NAME%% &#128075;</div>
<div class="money" id="eq">--</div>
<div class="eur" id="eqe">&nbsp;</div>
<div class="bankline" id="bank">&nbsp;</div>
</div>
<div class="wrap">
<div class="status" id="st" style="margin-top:26px">Connexion...</div>
<div id="trial" style="display:none;margin-top:10px;text-align:center;
 background:#251d07;border:1px solid #4a3c12;border-radius:14px;
 padding:10px;color:#e8c55a;font-size:.9rem"></div>
<div id="battles-sec" style="display:none">
<div class="sec">Combats en cours</div>
<div class="panel" id="battles"></div>
</div>
<div class="grid">
<div class="card"><div class="lbl">Aujourd&#8217;hui</div>
<div class="val" id="today">--</div><div class="sub">gains du jour</div></div>
<div class="card"><div class="lbl">Cette semaine</div>
<div class="val" id="week">--</div><div class="sub">depuis lundi</div></div>
<div class="card"><div class="lbl">Pire creux</div>
<div class="val neg" id="dd">--</div><div class="sub">7 derniers jours</div></div>
<div class="card"><div class="lbl">Trades en cours</div>
<div class="val neu" id="open">--</div><div class="sub">g&#233;r&#233;s
 par le robot</div></div>
</div>
<div class="sec">Progression &middot; 7 jours</div>
<div class="panel"><svg id="spark" viewBox="0 0 300 70"
 style="width:100%;height:70px"></svg></div>
<div class="sec">Derniers trades</div>
<div class="panel" id="hist"><div class="rowt"
 style="padding:8px">chargement...</div></div>
<button id="inst" onclick="inst()">Installer l&#8217;application</button>
<div class="foot" id="upd">chargement...</div>
<a class="exit" href="../">&#8618; Changer de compte &middot;
 cr&eacute;er un nouveau nid</a>
</div><script>
const B=location.pathname.endsWith('/')?location.pathname:location.pathname+'/';
(function(){
 const m=document.createElement('link');m.rel='manifest';
 m.href=B+'manifest.json';document.head.appendChild(m);
 const i=document.createElement('link');i.rel='icon';
 i.href=B+'icon192.png';document.head.appendChild(i);
})();
let lastOk=0;
function ago(){
 if(!lastOk){return}
 const s=Math.max(0,Math.round((Date.now()-lastOk)/1000));
 document.getElementById('upd').innerHTML='Mis &agrave; jour il y a '+s+' s';
}
async function load(){
 try{
  const r=await fetch(B+'api',{cache:'no-store'});
  const d=await r.json();
  if(d.expired){document.getElementById('st').innerHTML=
   '&#9203; <b>Essai termin&eacute;.</b> Contactez Kino pour passer au '+
   'Premium et continuer.';return}
  if(d.error){document.getElementById('st').innerHTML=
   '&#9203; '+(d.error.includes('patientez')?d.error:
   'Petit souci technique, r&eacute;essai automatique...');return}
  if(d.trial_days_left!==undefined){
   const tb=document.getElementById('trial');tb.style.display='block';
   tb.innerHTML='&#127873; Essai gratuit &mdash; <b>'+d.trial_days_left+
    ' jour'+(d.trial_days_left>1?'s':'')+' restant'+
    (d.trial_days_left>1?'s':'')+'</b>';}
  const f=(x)=>(x>=0?'+':'-')+Math.abs(x).toFixed(2)+' $';
  document.getElementById('eq').textContent=d.equity.toFixed(2)+' $';
  if(d.eurusd){document.getElementById('eqe').innerHTML=
   '&asymp; '+(d.equity/d.eurusd).toFixed(0)+' &euro;';}
  document.getElementById('bank').innerHTML=
   'Solde des trades termin&eacute;s : '+d.balance.toFixed(2)+' $';
  const n=d.open_positions;
  document.getElementById('st').innerHTML = n>0
   ? '&#129302; Le robot travaille &mdash; <b>'+n+' trade'+(n>1?'s':'')+
     ' en cours</b>'
   : '&#127747; March&eacute; sous surveillance &mdash; aucun trade ouvert';
  const bs=document.getElementById('battles-sec');
  if(d.open_list&&d.open_list.length){
   bs.style.display='block';
   document.getElementById('battles').innerHTML=d.open_list.map(x=>
    '<div class="row"><span class="rowt"><span class="bd" style="background:'+
    (x.pl>=0?'#2ecc71':'#ff5c5c')+'"></span>'+
    (x.d=='A'?'Achat':'Vente')+' &middot; '+x.lot.toFixed(2)+
    '</span><b class="'+(x.pl>=0?'pos':'neg')+'">'+
    (x.pl>=0?'+':'-')+Math.abs(x.pl).toFixed(2)+' $</b></div>').join('');
  }else{bs.style.display='none'}
  const t=document.getElementById('today');
  t.innerHTML=(d.today>=0?'&#9650; ':'&#9660; ')+f(d.today);
  t.className='val '+(d.today>=0?'pos':'neg');
  const w=document.getElementById('week');
  w.innerHTML=(d.week>=0?'&#9650; ':'&#9660; ')+f(d.week);
  w.className='val '+(d.week>=0?'pos':'neg');
  document.getElementById('dd').textContent='-'+d.max_dd_7d.toFixed(0)+' $';
  document.getElementById('open').textContent=n;
  if(d.curve&&d.curve.length>1){
   const c=d.curve,mn=Math.min(...c,0),mx=Math.max(...c,0),sp=(mx-mn)||1;
   const P=(v,i)=>((i/(c.length-1))*300).toFixed(1)+','+
     (62-((v-mn)/sp*54)).toFixed(1);
   const pts=c.map((v,i)=>P(v,i)).join(' ');
   const up=c[c.length-1]>=0;
   const col=up?'#2ecc71':'#ff5c5c';
   document.getElementById('spark').innerHTML=
    '<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'+
    '<stop offset="0%" stop-color="'+col+'" stop-opacity=".35"/>'+
    '<stop offset="100%" stop-color="'+col+'" stop-opacity="0"/>'+
    '</linearGradient></defs>'+
    '<polygon points="0,70 '+pts+' 300,70" fill="url(#g)"/>'+
    '<polyline points="'+pts+'" fill="none" stroke="'+col+
    '" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>';
  }
  if(d.trades&&d.trades.length){
   document.getElementById('hist').innerHTML=d.trades.map(x=>
    '<div class="row"><span class="rowt">'+x.w+'</span><b class="'+
    (x.p>=0?'pos':'neg')+'">'+(x.p>=0?'+':'-')+Math.abs(x.p).toFixed(2)+
    ' $</b></div>').join('');
  }
  lastOk=Date.now();ago();
 }catch(e){document.getElementById('upd').textContent=
  'hors ligne - nouvel essai...'}
}
load();setInterval(load,5000);setInterval(ago,1000);
if('serviceWorker' in navigator){
 navigator.serviceWorker.register(B+'sw.js',{scope:B}).catch(()=>{});}
let dp=null;
window.addEventListener('beforeinstallprompt',(e)=>{
 e.preventDefault();dp=e;
 document.getElementById('inst').style.display='block';
});
function inst(){if(dp){dp.prompt();dp=null;
 document.getElementById('inst').style.display='none';}}
window.addEventListener('appinstalled',()=>{
 document.getElementById('inst').style.display='none';});
</script></body></html>''' + '"""'

s = s[:i0] + new_page + s[i1:]
open(p, 'w', encoding='utf-8').write(s)
ast.parse(s)
print("dashboard v5 applied, syntax OK")
