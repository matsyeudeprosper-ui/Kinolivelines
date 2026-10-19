/* 2026-10-19 (owner: "make Kino accessible in the app, it's really hidden"): Kino everywhere - a floating bubble (like
   chat heads) above the tab bar with an unread badge, one tap = the conversation; members without Stratégie get a card
   introducing Kino. Also Kino's takeover card (a message it wants you to see), on every page that loads this file.
   Served from disk at /<token>/kino_fab.js; data: ai_nudge {can, unread, nudge}. */
(function(){
 if(window.__kinoFab)return;window.__kinoFab=1;
 var seg=location.pathname.split('/').filter(Boolean);if(!seg.length)return;var B0='/'+seg[0]+'/';
 var here=seg[1]||'';if(here==='atelier'||here==='kino')return;
 var en=false;try{en=localStorage.getItem('owlLang')==='en'}catch(e){}
 function T(f,e){return en?e:f}
 function el(t,css,txt){var e=document.createElement(t);if(css)e.style.cssText=css;if(txt!=null)e.textContent=txt;return e;}
 var st=document.createElement('style');st.textContent=
  '#kfab{position:fixed;right:14px;bottom:calc(86px + env(safe-area-inset-bottom,0px));z-index:60;width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;'+
  'background:linear-gradient(135deg,#6d5cf6,#3b82f6);box-shadow:0 10px 28px rgba(109,92,246,.5),0 2px 6px rgba(0,0,0,.35);display:grid;place-items:center;font-size:28px;'+
  'transition:transform .2s;animation:kfin .45s cubic-bezier(.2,1.5,.4,1)}#kfab:active{transform:scale(.92)}'+
  '#kfab .kd{position:absolute;right:3px;bottom:3px;width:13px;height:13px;border-radius:50%;background:#00a884;border:2px solid #0b0f14}'+
  '#kfab .kb{position:absolute;top:-4px;right:-4px;min-width:21px;height:21px;padding:0 6px;border-radius:99px;background:#ff3b30;color:#fff;font:800 12px/21px Inter,system-ui,sans-serif;display:none;box-shadow:0 2px 6px rgba(0,0,0,.4)}'+
  '#kfab.ping{animation:kping 1.6s ease-in-out 2}'+
  '#ktip{position:fixed;right:80px;bottom:calc(96px + env(safe-area-inset-bottom,0px));z-index:60;max-width:min(260px,64vw);padding:10px 12px;border-radius:14px 14px 4px 14px;background:#1f2c34;color:#e9edef;'+
  'font:500 13px/1.4 Inter,system-ui,sans-serif;box-shadow:0 10px 26px rgba(0,0,0,.45);cursor:pointer;animation:kfin .35s both}'+
  '@keyframes kfin{0%{transform:scale(.4);opacity:0}100%{transform:none;opacity:1}}@keyframes kping{50%{transform:scale(1.12)}}'+
  '@media(min-width:1180px){#kfab{bottom:24px}#ktip{bottom:34px}}';
 document.head.appendChild(st);
 var S={can:null,unread:0,shown:0};
 function fab(){var b=document.getElementById('kfab');if(b)return b;b=el('button');b.id='kfab';b.setAttribute('aria-label','Kino');b.innerHTML='🦉<span class="kd"></span><span class="kb"></span>';
  b.onclick=function(){if(S.can)location.href=B0+'atelier';else intro();};document.body.appendChild(b);return b;}
 function badge(n){var b=fab().querySelector('.kb');b.style.display=n?'block':'none';b.textContent=n>9?'9+':String(n);if(n)fab().classList.add('ping');}
 function tip(text,cid){var t=document.getElementById('ktip');if(t)t.remove();t=el('div',null,text.length>120?text.slice(0,118)+'…':text);t.id='ktip';
  t.onclick=function(){location.href=B0+'atelier'+(cid?'?c='+encodeURIComponent(cid):'');};document.body.appendChild(t);setTimeout(function(){if(t.parentNode)t.remove();},9000);}
 function intro(){var o=el('div','position:fixed;inset:0;z-index:95;display:flex;align-items:flex-end;justify-content:center;background:rgba(3,6,10,.6);backdrop-filter:blur(4px)');
  var c=el('div','width:100%;max-width:520px;margin:0 10px calc(14px + env(safe-area-inset-bottom,0px));border-radius:26px;border:1px solid rgba(167,139,250,.45);background:linear-gradient(160deg,#1a2233,#121a25);padding:20px;color:#e8eef4;font-family:Inter,system-ui,sans-serif');
  c.appendChild(el('div','font-size:42px;margin-bottom:6px','🦉'));c.appendChild(el('b','display:block;font-size:1.15rem',T('Voici Kino','Meet Kino')));
  c.appendChild(el('p','color:#a9b8c8;font-size:.92rem;line-height:1.5;margin:8px 0 14px',T('Ton compagnon de trading IA : il construit des robots avec toi en parlant, les teste sur de vrais prix, surveille ton robot et te prévient quand il faut. Inclus dans la formule Stratégie.','Your AI trading companion: builds robots with you by talking, tests them on real prices, watches your robot and tells you when it matters. Included in the Strategy plan.')));
  var a=el('a','display:block;text-align:center;text-decoration:none;border-radius:14px;padding:13px;font-weight:800;color:#fff;background:linear-gradient(135deg,#3b82f6,#6d5cf6)',T('Découvrir Stratégie','See Strategy'));a.href=B0+'offres';
  var x=el('button','display:block;width:100%;margin-top:8px;border:1px solid #2b3a4d;border-radius:14px;padding:12px;background:#172130;color:#c6d3df;font-weight:700',T('Plus tard','Later'));
  x.onclick=function(){o.remove();};o.onclick=function(e){if(e.target===o)o.remove();};c.appendChild(a);c.appendChild(x);o.appendChild(c);document.body.appendChild(o);}
 function seen(n){try{fetch(B0+'ai_nudge_seen',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({t:n.t})});}catch(e){}}
 function card(n){if(!n||n.t===S.shown||document.getElementById('ainudge'))return;S.shown=n.t;
  var o=el('div','position:fixed;inset:0;z-index:95;display:flex;align-items:flex-end;justify-content:center;background:rgba(3,6,10,.6);backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)');o.id='ainudge';
  var c=el('div','width:100%;max-width:560px;margin:0 10px calc(14px + env(safe-area-inset-bottom,0px));border-radius:26px;border:1px solid rgba(167,139,250,.45);background:linear-gradient(160deg,#1a2233,#121a25);box-shadow:0 24px 70px rgba(0,0,0,.6);padding:18px 18px 14px;color:#e8eef4;font-family:Inter,system-ui,sans-serif;transform:translateY(40px);opacity:0;transition:all .35s cubic-bezier(.2,.8,.2,1)');
  var h=el('div','display:flex;align-items:center;gap:12px;margin-bottom:12px');
  h.appendChild(el('div','width:42px;height:42px;border-radius:50%;flex:none;display:grid;place-items:center;background:linear-gradient(135deg,#6d5cf6,#3b82f6);font-size:21px','🦉'));
  var tt=el('div','flex:1;min-width:0');tt.appendChild(el('b','display:block;font-size:.98rem','Kino'));
  tt.appendChild(el('small','display:block;color:#8a9bb0;font-size:.76rem;margin-top:2px',n.important?T('Une nouvelle pour toi','News for you'):T('Un truc que je voulais te dire','Something I wanted to tell you')));h.appendChild(tt);c.appendChild(h);
  c.appendChild(el('div','font-size:1rem;line-height:1.5;white-space:pre-wrap;max-height:40vh;overflow:auto',n.text));
  var row=el('div','display:flex;gap:8px;margin-top:14px');
  var go=el('button','flex:1;border:0;border-radius:14px;padding:13px;font-weight:800;font-size:.92rem;color:#fff;background:linear-gradient(135deg,#00a884,#0b8f72);cursor:pointer',T('Répondre','Reply'));
  var later=el('button','border:1px solid #2b3a4d;border-radius:14px;padding:13px 16px;font-weight:700;font-size:.9rem;color:#c6d3df;background:#172130;cursor:pointer',T('Plus tard','Later'));
  go.onclick=function(){seen(n);location.href=B0+'atelier?c='+encodeURIComponent(n.cid);};
  later.onclick=function(){seen(n);c.style.transform='translateY(40px)';c.style.opacity='0';setTimeout(function(){o.remove();},300);};
  o.onclick=function(e){if(e.target===o)later.onclick();};row.appendChild(go);row.appendChild(later);c.appendChild(row);o.appendChild(c);document.body.appendChild(o);
  requestAnimationFrame(function(){c.style.transform='none';c.style.opacity='1';});try{navigator.vibrate&&navigator.vibrate([60,40,60]);}catch(e){}}
 function poll(){if(document.visibilityState!=='visible')return;fetch(B0+'ai_nudge',{cache:'no-store'}).then(function(r){return r.json();}).then(function(j){
  if(!j||j.public)return;S.can=!!j.can;fab();badge(j.unread||0);if(j.nudge)card(j.nudge);
  else if(j.unread&&j.last&&j.last.t!==S.tipped){S.tipped=j.last.t;tip(j.last.text,j.last.cid);}}).catch(function(){});}
 /* 2026-10-19 (owner item 1): long-press any figure or line of the app -> "Demande à Kino" about exactly that */
 var LP=null,LPX=0,LPY=0,LPF=false;
 function pageName(){return ({'':T('l’accueil','home'),robots:T('Robots','Robots'),mesrobots:T('Mes robots','My robots'),wealth:'Patrimoine',proof:T('la Preuve','Proof'),chart:T('le graphique','the chart')})[here]||here;}
 function askPill(x,y,txt){var o=document.getElementById('kask');if(o)o.remove();o=el('button','position:fixed;z-index:96;left:'+Math.max(8,Math.min(innerWidth-190,x-90))+'px;top:'+Math.max(8,y-62)+'px;border:0;border-radius:99px;padding:10px 14px;font:800 13px Inter,system-ui,sans-serif;color:#fff;background:linear-gradient(135deg,#6d5cf6,#3b82f6);box-shadow:0 10px 26px rgba(0,0,0,.45);animation:kfin .25s both','🦉 '+T('Demande à Kino','Ask Kino'));
  o.id='kask';o.onclick=function(e){e.stopPropagation();var q=T('Explique-moi ça (sur ','Explain this (on ')+pageName()+') : « '+txt+' »';location.href=B0+'atelier?ask='+encodeURIComponent(q);};
  document.body.appendChild(o);setTimeout(function(){if(o.parentNode)o.remove();},4500);try{navigator.vibrate&&navigator.vibrate(15)}catch(e){}}
 function ctxText(t){var e=t;for(var k=0;k<4&&e&&e!==document.body;k++){var s=(e.innerText||'').replace(/\s+/g,' ').trim();if(s.length>=3&&s.length<=220)return s;e=e.parentElement;}
  var s2=(t.innerText||'').replace(/\s+/g,' ').trim();return s2.slice(0,200);}
 document.addEventListener('pointerdown',function(ev){var t=ev.target;if(!t||t.closest('input,textarea,select,#kfab,#kask,#ainudge')){return;}LPF=false;
  LPX=ev.clientX;LPY=ev.clientY;clearTimeout(LP);LP=setTimeout(function(){if(!S.can)return;var txt=ctxText(t);if(txt){LPF=true;askPill(LPX,LPY,txt);}},600);},{passive:true});
 document.addEventListener('click',function(ev){if(LPF&&!ev.target.closest('#kask')){ev.preventDefault();ev.stopPropagation();LPF=false;}},true);
 ['pointerup','pointercancel','scroll'].forEach(function(n){document.addEventListener(n,function(){clearTimeout(LP);},{passive:true,capture:true});});
 document.addEventListener('pointermove',function(ev){if(Math.abs(ev.clientX-LPX)>8||Math.abs(ev.clientY-LPY)>8)clearTimeout(LP);},{passive:true});
 setTimeout(poll,2500);setInterval(poll,45000);document.addEventListener('visibilitychange',poll);
 try{navigator.serviceWorker&&navigator.serviceWorker.addEventListener('message',function(ev){if(ev.data&&ev.data.type==='owl_nudge')poll();});}catch(e){}
})();
