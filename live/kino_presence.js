/* kino_presence.js (2026-11-02, owner: "a consciousness-style glowing effect, reacting, alive" - chose Synapse).
   Kino has no face: a bright core with points of thought orbiting it, linking up when they meet. One shared loop draws
   every <canvas class="kpres"> on the page (sizes from CSS, added at any time). It reacts to what Kino is doing:
     KinoPresence.set("rest" | "think" | "speak" | "worry")   or   <html data-kstate="...">
   rest = slow breathing; think = faster orbits; speak = pulses like a voice; worry = amber and restless.
   Paused while the tab is hidden; one still frame when the viewer asked for reduced motion. */
(function(){
 if(window.KinoPresence)return;
 var ST={rest:{sp:.35,amp:.06,c1:[124,108,255],c2:[34,211,238]},think:{sp:1.25,amp:.13,c1:[150,130,255],c2:[34,211,238]},
  speak:{sp:.75,amp:.1,c1:[124,108,255],c2:[80,230,255],voice:1},worry:{sp:.9,amp:.16,c1:[232,177,70],c2:[255,120,90],jit:1}};
 var want='rest',cur={sp:.35,amp:.06,c1:[124,108,255],c2:[34,211,238],voice:0,jit:0};
 function R(c,a){return 'rgba('+(c[0]|0)+','+(c[1]|0)+','+(c[2]|0)+','+a+')';}
 function L(a,b,t){return a+(b-a)*t;}
 function state(){var s=document.documentElement.getAttribute('data-kstate');if(ST[s])return s;if(document.querySelector('.m.ai.typing,.m.ai.live,#livebub'))return 'speak';return want;}
 function blend(){var t=ST[state()];cur.sp=L(cur.sp,t.sp,.04);cur.amp=L(cur.amp,t.amp,.04);
  cur.c1=cur.c1.map(function(v,i){return L(v,t.c1[i],.04);});cur.c2=cur.c2.map(function(v,i){return L(v,t.c2[i],.04);});
  cur.voice=L(cur.voice,t.voice||0,.06);cur.jit=L(cur.jit,t.jit||0,.06);}
 function voice(t){return cur.voice*(.5+.5*Math.abs(Math.sin(t*7.3)*Math.sin(t*3.1+1)*Math.cos(t*11.7)));}
 function draw(x,w,t){var c=w/2,r=w*.34,ph=t*cur.sp,v=voice(t),i,j;x.clearRect(0,0,w,w);
  var halo=x.createRadialGradient(c,c,0,c,c,r*1.4);halo.addColorStop(0,R(cur.c1,.28+v*.3));halo.addColorStop(1,R(cur.c1,0));x.fillStyle=halo;x.fillRect(0,0,w,w);
  var P=[],n=w>90?18:(w>40?11:8);
  for(i=0;i<n;i++){var a=ph*(.4+(i%5)*.13)+i*2.39,rr=r*(.45+.5*((i*37)%11)/11)*(1+.06*Math.sin(ph*2+i))+cur.jit*Math.sin(t*19+i)*w*.012;P.push([c+Math.cos(a)*rr,c+Math.sin(a)*rr*.92]);}
  x.lineWidth=Math.max(.6,w/180);
  for(i=0;i<P.length;i++)for(j=i+1;j<P.length;j++){var d=Math.hypot(P[i][0]-P[j][0],P[i][1]-P[j][1]);if(d<r*.55){x.strokeStyle=R(cur.c2,(1-d/(r*.55))*.5);x.beginPath();x.moveTo(P[i][0],P[i][1]);x.lineTo(P[j][0],P[j][1]);x.stroke();}}
  for(i=0;i<P.length;i++){x.fillStyle=R(i%2?cur.c2:cur.c1,.95);x.beginPath();x.arc(P[i][0],P[i][1],Math.max(1,w/90)*(1+v*.6),0,7);x.fill();}
  var core=x.createRadialGradient(c,c,0,c,c,r*.38*(1+v*.4));core.addColorStop(0,'rgba(255,255,255,.95)');core.addColorStop(.4,R(cur.c2,.7));core.addColorStop(1,R(cur.c1,0));
  x.fillStyle=core;x.beginPath();x.arc(c,c,r*.4*(1+v*.4),0,7);x.fill();}
 var still=false;try{still=!!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches);}catch(e){}
 function frame(ms){var t=still?2:ms/1000;blend();
  var L2=document.querySelectorAll('canvas.kpres'),dpr=Math.min(2,window.devicePixelRatio||1);
  for(var k=0;k<L2.length;k++){var cv=L2[k],b=cv.getBoundingClientRect(),s=Math.round(Math.min(b.width,b.height));
   if(!s||b.bottom<0||b.top>innerHeight)continue;
   if(cv.width!==Math.round(s*dpr)){cv.width=cv.height=Math.round(s*dpr);}
   var x=cv.getContext('2d');x.setTransform(dpr,0,0,dpr,0,0);draw(x,s,t);}
  if(!still&&!document.hidden)requestAnimationFrame(frame);}
 document.addEventListener('visibilitychange',function(){if(!document.hidden&&!still)requestAnimationFrame(frame);});
 window.KinoPresence={set:function(s){if(ST[s])want=s;if(still)requestAnimationFrame(frame);},state:function(){return state();}};
 requestAnimationFrame(frame);
 if(still)new MutationObserver(function(){requestAnimationFrame(frame);}).observe(document.documentElement,{childList:true,subtree:true});
})();
