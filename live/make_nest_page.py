p = r'C:\Projects\KinoliveLines\live\owl_app_server.py'
s = open(p, encoding='utf-8').read()

old = '''        data = {
            "balance": round(ai.balance, 2),'''
new = '''        _te = mt5.symbol_info_tick("EURUSDm")
        _eur = round(_te.bid, 5) if _te and _te.bid > 0 else None
        data = {
            "eurusd": _eur,
            "balance": round(ai.balance, 2),'''
if old in s:
    s = s.replace(old, new)
else:
    assert '"eurusd": _eur' in s, "eur patch missing and anchor not found"

i0 = s.index('PAGE = """')
i1 = s.index('"""\n\n\nclass H(', i0) + 3

new_page = 'PAGE = """' + '''<!doctype html><html lang="fr"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="theme-color" content="#0b0f14">
<title>OwlNest</title>
<style>
*{box-sizing:border-box}
body{background:#0b0f14;color:#eef2f6;margin:0;padding:28px 20px;
 font-family:-apple-system,'Segoe UI',Roboto,sans-serif;text-align:center}
.wrap{max-width:430px;margin:0 auto}
.top{display:flex;align-items:center;justify-content:center;gap:10px;
 color:#9aa7b4;font-weight:600;font-size:1.05rem}
.dot{width:9px;height:9px;border-radius:50%;background:#2ecc71;
 animation:p 1.6s infinite}
@keyframes p{0%,100%{opacity:1}50%{opacity:.25}}
.money{font-size:3.4rem;font-weight:800;margin:18px 0 2px;letter-spacing:-1px}
.eur{color:#9aa7b4;font-size:1.15rem;margin-bottom:14px}
.status{background:#121924;border:1px solid #1f2a38;border-radius:14px;
 padding:13px;margin:16px 0 20px;font-size:1rem;color:#c9d4de}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.card{background:#121924;border:1px solid #1f2a38;border-radius:16px;
 padding:18px 8px 15px}
.lbl{font-size:.72rem;color:#9aa7b4;text-transform:uppercase;
 letter-spacing:.06em}
.val{font-size:1.55rem;font-weight:800;margin-top:7px}
.sub{font-size:.68rem;color:#5d6b79;margin-top:5px}
.pos{color:#2ecc71}.neg{color:#ff5c5c}.neu{color:#eef2f6}
#inst{display:none;margin:22px auto 0;background:#2563eb;color:#fff;
 border:0;border-radius:12px;padding:13px 26px;font-size:1rem;font-weight:700}
.foot{margin-top:18px;font-size:.75rem;color:#5d6b79}
</style></head><body><div class="wrap">
<div class="top"><span>&#129417; OwlNest</span><span class="dot"></span>
<span style="font-size:.75rem;color:#2ecc71">EN DIRECT</span></div>
<div class="money" id="eq">--</div>
<div class="eur" id="eqe">&nbsp;</div>
<div class="status" id="st">Connexion...</div>
<div class="grid">
<div class="card"><div class="lbl">Aujourd&#8217;hui</div>
<div class="val" id="today">--</div><div class="sub">gains du jour</div></div>
<div class="card"><div class="lbl">Cette semaine</div>
<div class="val" id="week">--</div><div class="sub">depuis lundi</div></div>
<div class="card"><div class="lbl">Pire creux</div>
<div class="val neg" id="dd">--</div><div class="sub">7 derniers jours</div></div>
<div class="card"><div class="lbl">Trades en cours</div>
<div class="val neu" id="open">--</div>
<div class="sub">g&#233;r&#233;s par le robot</div></div>
</div>
<button id="inst" onclick="inst()">Installer l&#8217;application</button>
<div class="foot" id="upd">chargement...</div>
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
  if(d.error){document.getElementById('st').innerHTML=
   'Petit souci technique, r&eacute;essai...';return}
  const f=(x)=>(x>=0?'+':'-')+Math.abs(x).toFixed(2)+' $';
  document.getElementById('eq').textContent=d.equity.toFixed(2)+' $';
  if(d.eurusd){document.getElementById('eqe').innerHTML=
   '&asymp; '+(d.equity/d.eurusd).toFixed(0)+' &euro;';}
  const n=d.open_positions;
  document.getElementById('st').innerHTML = n>0
   ? '&#129302; Le robot travaille : <b>'+n+' trade'+(n>1?'s':'')+
     ' en cours</b>'
   : '&#128564; March&eacute; surveill&eacute;, aucun trade en ce moment';
  const t=document.getElementById('today');
  t.innerHTML=(d.today>=0?'&#9650; ':'&#9660; ')+f(d.today);
  t.className='val '+(d.today>=0?'pos':'neg');
  const w=document.getElementById('week');
  w.innerHTML=(d.week>=0?'&#9650; ':'&#9660; ')+f(d.week);
  w.className='val '+(d.week>=0?'pos':'neg');
  document.getElementById('dd').textContent='-'+d.max_dd_7d.toFixed(0)+' $';
  document.getElementById('open').textContent=n;
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
 document.getElementById('inst').style.display='inline-block';
});
function inst(){if(dp){dp.prompt();dp=null;
 document.getElementById('inst').style.display='none';}}
window.addEventListener('appinstalled',()=>{
 document.getElementById('inst').style.display='none';});
</script></body></html>''' + '"""'

s = s[:i0] + new_page + s[i1:]
open(p, 'w', encoding='utf-8').write(s)
import ast
ast.parse(s)
print("grandma-pro page installed, syntax OK")
