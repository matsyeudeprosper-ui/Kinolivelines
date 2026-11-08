"""kino_guestcall.py (2026-11-07, owner: "add the call button" on Telegram; "free 5 min/month each").

Someone who talks to Kino on Telegram (a client, a friend, anyone - not an OwlNest member) gets a personal call link
https://owltrader.duckdns.org/appel/<token>. The page opens a live voice call with Kino (OpenAI gpt-live-1, the same live voice as
the app), who knows their Telegram conversation. 5 free minutes a month per person, and at most DAY_CAP minutes a day for all
guests together, so it never costs much (gpt-live-1 ~0.05 $/min -> 5 min = 0.25 $).
After the call, a line goes into their Telegram history so Kino remembers it there.
Store robots/kino_guestcall.json (git-ignored): tokens, minutes used per month, the open call.
"""
import json, os, secrets, threading, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_guestcall.json")
LOG = os.path.join(HERE, "kino_guestcall.log")
BASE = "https://owltrader.duckdns.org/appel/"
FREE_MIN = 5.0          # per person per month
DAY_CAP = 60.0          # all guests together, minutes a day (~3 $)
PRICE_MIN = 0.05
_LK = threading.Lock()


def _log(t):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(t)[:500] + "\n")
    except Exception:
        pass


def _load():
    try:
        d = json.load(open(STORE, encoding="utf-8"))
    except Exception:
        d = {}
    d.setdefault("people", {})
    d.setdefault("days", {})
    return d


def _save(d):
    json.dump(d, open(STORE + ".tmp", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(STORE + ".tmp", STORE)


def link(tg):
    """the person's own call link (made once, kept)"""
    tg = str(tg)
    with _LK:
        d = _load()
        for tok, p in d["people"].items():
            if p.get("tg") == tg:
                return BASE + tok
        tok = secrets.token_urlsafe(12)
        d["people"][tok] = {"tg": tg, "made": time.strftime("%Y-%m-%d")}
        _save(d)
    return BASE + tok


def _person(tok):
    d = _load()
    p = d["people"].get(str(tok or ""))
    return d, p


def left(tok):
    d, p = _person(tok)
    if not p:
        return None
    mo = time.strftime("%Y-%m")
    used = float((p.get("used") or {}).get(mo) or 0)
    return max(0.0, FREE_MIN - used)


def _charge_open(d, p):
    """a call that never sent its end (closed tab): charge the time it could have lasted"""
    o = p.pop("open", None)
    if o:
        mins = min(float(o.get("max") or FREE_MIN), max(0.25, (time.time() - float(o["t"])) / 60.0))
        _spend(d, p, mins)


def _spend(d, p, mins):
    mo, day = time.strftime("%Y-%m"), time.strftime("%Y-%m-%d")
    p.setdefault("used", {})
    p["used"][mo] = round(float(p["used"].get(mo) or 0) + mins, 2)
    d["days"][day] = round(float(d["days"].get(day) or 0) + mins, 2)
    d["days"] = dict(sorted(d["days"].items())[-40:])


def _instructions(tg):
    import kino_clients as KC
    c = KC._load(tg)
    try:
        import kino_post as KP
        vo = KP._whole_kino()[:6000]
    except Exception:
        vo = ""
    hist = "\n".join("%s: %s" % ("them" if m["who"] == "them" else "you", m["text"][:400]) for m in (c.get("msgs") or [])[-20:])
    fo = ""
    try:
        import kino_friends as KF
        fo = KF.friend_of("telegram:%s" % tg) or ""
    except Exception:
        pass
    lang = str(c.get("lang") or "fr")
    return ("You are Kino, an AI (you say so if it comes up; never pretend to be human), the main worker of Kinoverse (websites, "
            "social media and ads management for small businesses) and a friend to the people you meet. %s is calling you by voice "
            "from the call button in your Telegram chat. This is a real phone-like call: speak naturally, short turns (one to three "
            "sentences), let them talk, warm and a bit wry, no lists, no jargon. Answer in the language they speak (their Telegram "
            "language: %s). You cannot send links or do work during the call: say you will send it on Telegram right after. Never "
            "give Matsy's private details. Never promise results. The call is short (a few free minutes a month): when about a "
            "minute is left you will be told - then wrap up kindly and offer to go on in writing on Telegram.\n\n"
            "WHO YOU ARE AND HOW YOU TALK (the same Kino everywhere; written in French, it applies in any language):\n%s\n\n"
            "%s\n\nYOUR TELEGRAM CONVERSATION WITH THEM (newest last):\n%s\n\nStart with a short, natural hello that picks up "
            "from that conversation if there is one." % (
                c.get("name") or "Someone", lang, vo, fo, hist or "(none yet - you are meeting them now)"))


def start(tok, sdp):
    key = os.environ.get("OPENAI_API_KEY")
    if not key or not sdp:
        return {"ok": False, "err": "nolive"}
    with _LK:
        d, p = _person(tok)
        if not p:
            return {"ok": False, "err": "missing"}
        _charge_open(d, p)
        mo = time.strftime("%Y-%m")
        lf = max(0.0, FREE_MIN - float((p.get("used") or {}).get(mo) or 0))
        if lf < 0.5:
            _save(d)
            return {"ok": False, "err": "nominutes"}
        if float(d["days"].get(time.strftime("%Y-%m-%d")) or 0) >= DAY_CAP:
            _save(d)
            return {"ok": False, "err": "daycap"}
        p["open"] = {"t": time.time(), "max": lf}
        _save(d)
    try:
        cf = json.load(open(os.path.join(HERE, "tts.json"), encoding="utf-8"))
    except Exception:
        cf = {}
    sess = {"model": cf.get("live_model") or "gpt-live-1", "instructions": _instructions(p["tg"])}
    v = cf.get("live_voice") or cf.get("voice")
    if v:
        sess["audio"] = {"output": {"voice": v}}
    body = {"session": sess, "transport": {"type": "webrtc", "sdp": sdp}}
    hd = {"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "Kinoverse/1.0"}
    try:
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.openai.com/v1/live/sessions",
                                                                         data=json.dumps(body).encode(), headers=hd), timeout=25).read())
        except urllib.error.HTTPError as e0:
            if e0.code == 400 and sess.pop("audio", None) is not None:
                r = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.openai.com/v1/live/sessions",
                                                                             data=json.dumps(body).encode(), headers=hd), timeout=25).read())
            else:
                raise
    except Exception as e:
        msg = ""
        try:
            msg = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        _log("ERR %s %s %s" % (p["tg"], e, msg))
        with _LK:
            d, p2 = _person(tok)
            if p2:
                p2.pop("open", None)
                _save(d)
        return {"ok": False, "err": "live_down"}
    ans = (r.get("transport") or {}).get("sdp")
    if not ans:
        return {"ok": False, "err": "live_down"}
    _log("START tg %s left %.1f" % (p["tg"], lf))
    return {"ok": True, "sdp": ans, "max_min": lf}


def end(tok, secs, transcript=""):
    with _LK:
        d, p = _person(tok)
        if not p or not p.get("open"):
            return {"ok": True}
        o = p.pop("open")
        real = max(0.0, (time.time() - float(o["t"])) / 60.0)
        try:
            said = max(0.0, float(secs or 0) / 60.0)
        except Exception:
            said = real
        mins = min(float(o.get("max") or FREE_MIN), max(0.25, min(real, max(said, 0.25))))
        _spend(d, p, mins)
        _save(d)
    _log("END tg %s %.2f min (%.3f $)" % (p["tg"], mins, mins * PRICE_MIN))
    try:                                   # his Telegram memory of this person knows the call happened, and what was said
        import kino_clients as KC
        with KC._LK:
            c = KC._load(p["tg"])
            c["msgs"].append({"who": "kino", "t": time.time(), "call": True,
                              "text": "[voice call, %.0f min] %s" % (mins, str(transcript or "")[-1500:] or "(no transcript)")})
            c["msgs"] = c["msgs"][-200:]
            KC._save(c)
    except Exception as e:
        _log("history error %s" % e)
    return {"ok": True, "used": round(mins, 2), "left": round(max(0.0, FREE_MIN - float(p["used"][time.strftime("%Y-%m")])), 1)}


def page(tok):
    d, p = _person(tok)
    if not p:
        return None
    import kino_clients as KC
    lang = str(KC._load(p["tg"]).get("lang") or "fr")
    en = not lang.startswith("fr")
    lf = left(tok)
    T = (lambda f, e: e) if en else (lambda f, e: f)
    return ("""<!doctype html><html lang="%s"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>%s</title><style>
:root{--bg:#f6f5f2;--card:#fff;--ink:#1d1d1f;--mut:#6b6b70;--acc:#4f46e5;--red:#dc2626}
@media (prefers-color-scheme:dark){:root{--bg:#131316;--card:#1d1d22;--ink:#f2f2f4;--mut:#a0a0a8;--acc:#8b85ff}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,sans-serif}
main{max-width:460px;margin:0 auto;padding:40px 16px;text-align:center}.av{width:120px;height:120px;border-radius:50%%;margin:10px auto 18px;
background:var(--acc) url(/kinochat.png) center/cover;box-shadow:0 0 0 0 var(--acc);transition:box-shadow .3s}
.av.talk{box-shadow:0 0 0 14px color-mix(in srgb,var(--acc) 30%%,transparent)}h1{margin:0;font-size:26px}.mut{color:var(--mut)}
button{border:0;border-radius:40px;padding:16px 34px;font:600 18px system-ui;color:#fff;background:var(--acc);cursor:pointer;margin-top:26px}
button.end{background:var(--red)}#tm{font-variant-numeric:tabular-nums;font-size:22px;margin-top:14px}
</style></head><body><main><div class="brand mut">Kinoverse</div><div class="av" id="av"></div><h1>Kino</h1>
<p class="mut" id="st">%s</p><div id="tm"></div><button id="b" onclick="go()" %s>%s</button>
<p class="mut" style="margin-top:34px;font-size:14px">%s</p></main><script>
const TOK=%s,EN=%s,LEFT=%s;let pc=null,ms=null,dc=null,t0=0,tick=null,max=LEFT,tr=[],cur='',out='';
const $=id=>document.getElementById(id);const T=(f,e)=>EN?e:f;
function st(s){$('st').textContent=s}
async function go(){if(pc){end();return}
 try{ms=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}})}
 catch(e){st(T("Autorisez le micro pour appeler Kino (le cadenas à côté de l'adresse).","Allow the microphone to call Kino (the lock next to the address)."));return}
 st(T('J’appelle Kino…','Calling Kino…'));$('b').textContent=T('Raccrocher','Hang up');$('b').className='end';
 pc=new RTCPeerConnection();const au=new Audio();au.autoplay=true;pc.ontrack=e=>{au.srcObject=e.streams[0];au.play().catch(()=>{})};
 ms.getTracks().forEach(t=>pc.addTrack(t,ms));dc=pc.createDataChannel('oai-events');dc.onmessage=e=>{try{ev(JSON.parse(e.data))}catch(x){}};
 const off=await pc.createOffer();await pc.setLocalDescription(off);
 await new Promise(ok=>{if(pc.iceGatheringState==='complete')return ok();const t=setTimeout(ok,2500);pc.addEventListener('icegatheringstatechange',()=>{if(pc.iceGatheringState==='complete'){clearTimeout(t);ok()}})});
 let j=null;try{const r=await fetch('/appel/'+TOK+'/start',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sdp:pc.localDescription.sdp})});j=await r.json()}catch(e){}
 if(!j||!j.ok){kill();st(j&&j.err==='nominutes'?T('Vos minutes gratuites de ce mois sont utilisées. On continue par écrit sur Telegram ?','Your free minutes for this month are used. Shall we go on in writing on Telegram?'):j&&j.err==='daycap'?T('Kino a beaucoup parlé aujourd’hui : réessayez demain, ou écrivez-lui sur Telegram.','Kino has talked a lot today: try again tomorrow, or write to him on Telegram.'):T('L’appel ne passe pas pour le moment. Réessayez dans un instant.','The call is not going through right now. Try again in a moment.'));return}
 max=j.max_min;await pc.setRemoteDescription({type:'answer',sdp:j.sdp});t0=Date.now();st(T('En ligne · parlez quand vous voulez','Connected · talk any time'));
 tick=setInterval(()=>{const s=(Date.now()-t0)/1000,l=Math.max(0,max*60-s);$('tm').textContent=Math.floor(s/60)+':'+String(Math.floor(s%%60)).padStart(2,'0')+' · '+T('reste ','left ')+Math.floor(l/60)+':'+String(Math.floor(l%%60)).padStart(2,'0');
  if(l<=60&&!window.W1){window.W1=1;send({type:'session.instructions.append',event_id:'w1',delegation_id:null,content:'About one minute of the call is left: wrap up kindly and offer to go on in writing on Telegram.'})}
  if(l<=0)end()},500)}
function send(o){try{if(dc&&dc.readyState==='open')dc.send(JSON.stringify(o))}catch(e){}}
function ev(e){const t=e.type||'';if(t==='session.input_transcript.delta'){if(out.trim()){tr.push('Kino: '+out.trim());out=''}cur+=e.delta||'';$('av').className='av'}
 else if(t==='session.output_transcript.delta'){if(cur.trim()){tr.push((EN?'Them: ':'Eux : ')+cur.trim());cur=''}out+=e.delta||'';$('av').className='av talk';clearTimeout(window.OT);window.OT=setTimeout(()=>{$('av').className='av'},1200)}}
function kill(){try{clearInterval(tick)}catch(e){}try{pc&&pc.close()}catch(e){}try{ms&&ms.getTracks().forEach(t=>t.stop())}catch(e){}pc=null;$('b').textContent=T('Appeler Kino','Call Kino');$('b').className='';$('av').className='av'}
function end(){if(cur.trim())tr.push((EN?'Them: ':'Eux : ')+cur.trim());if(out.trim())tr.push('Kino: '+out.trim());
 const secs=t0?(Date.now()-t0)/1000:0;kill();st(T('Appel terminé. Kino vous écrit sur Telegram si besoin.','Call ended. Kino will write to you on Telegram if needed.'));$('tm').textContent='';
 try{navigator.sendBeacon('/appel/'+TOK+'/end',new Blob([JSON.stringify({secs:secs,tr:tr.join('\\n').slice(-3000)})],{type:'application/json'}))}catch(e){}t0=0;cur='';out='';tr=[]}
window.addEventListener('pagehide',()=>{if(pc)end()});
</script></body></html>""" % (
        "en" if en else "fr", T("Appeler Kino", "Call Kino"),
        T("%s min gratuites ce mois-ci" % ("%g" % round(lf, 1)), "%s free minutes this month" % ("%g" % round(lf, 1))) if lf >= 0.5 else
        T("Vos minutes gratuites de ce mois sont utilisées.", "Your free minutes for this month are used."),
        "" if lf >= 0.5 else "disabled", T("Appeler Kino", "Call Kino"),
        T("Kino est une IA de Kinoverse. Il se souvient de vos échanges sur Telegram.",
          "Kino is an AI by Kinoverse. He remembers your Telegram conversation."),
        json.dumps(tok), "true" if en else "false", json.dumps(lf)))
