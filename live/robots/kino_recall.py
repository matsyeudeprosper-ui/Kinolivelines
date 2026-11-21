"""kino_recall.py (2026-11-21, owner: "all 7, well done" - v4 step 4 part D: working memory by MEANING, any language).

A person recalls what fits the moment by meaning, not by the same words: "j'ai besoin d'un site pour ma boulangerie" brings
back "he wants a website for his bakery". kino_social.memfocus used to pick memory blocks by shared words (one language,
exact words). This gives it meaning:

  embed(texts)      -> vectors, from the local Ollama model bge-m3 (multilingual, 100+ languages, free, on this VPS);
                       if Ollama is down -> OpenAI text-embedding-3-small (paid, owner 21/11); if both are down -> None
                       and the caller falls back to word overlap. Vectors of different models are never mixed.
  scores(cue, blocks, wait_s) -> {index: similarity} for the blocks whose vector is known now; the missing ones are
                       embedded in the background for the next turn (a reply never waits for 40 embeddings).
Cache: robots/kino_embed.sqlite (key = model + hash of the block with digits blanked, so "il y a 3 min" and "il y a 5 min"
share one vector). The model stays loaded 60 min (keep_alive) so a reply does not pay the 9 s cold load.
"""
import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import threading
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "kino_embed.sqlite")
OLLAMA = "http://127.0.0.1:11434/api/embed"
OLLAMA_MODEL = "bge-m3"
OPENAI_MODEL = "text-embedding-3-small"
_LK = threading.Lock()
_BG = {"busy": False}
_DOWN = {}                     # backend -> skipped until (a failing backend is not retried for 10 min)
LOG = os.path.join(HERE, "kino_recall.log")


def _log(line):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _db():
    c = sqlite3.connect(DB, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS v (k TEXT PRIMARY KEY, model TEXT, dim INT, vec BLOB, t REAL)")
    return c


def _norm(text):
    t = re.sub(r"\d+", "#", " ".join(str(text or "").split()).lower())
    return t[:600]


def _key(model, text):
    return model + ":" + hashlib.sha1(_norm(text).encode("utf-8")).hexdigest()


def _pack(v):
    return struct.pack("%df" % len(v), *v)


def _unpack(b, dim):
    return list(struct.unpack("%df" % dim, b))


def _ollama(texts, timeout):
    # keep_alive -1: the model stays loaded (~1.2 GB RAM, owner OK 21/11) - a cold load is 9 s, longer than a reply can wait
    body = json.dumps({"model": OLLAMA_MODEL, "input": [_norm(t) for t in texts], "keep_alive": -1}).encode("utf-8")
    rq = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    out = json.loads(urllib.request.urlopen(rq, timeout=timeout).read().decode("utf-8"))
    E = out.get("embeddings") or []
    return E if len(E) == len(texts) else None


def _openai(texts, timeout):
    k = os.environ.get("OPENAI_API_KEY")
    if not k:
        return None
    body = json.dumps({"model": OPENAI_MODEL, "input": [_norm(t) for t in texts]}).encode("utf-8")
    rq = urllib.request.Request("https://api.openai.com/v1/embeddings", data=body,
                                headers={"Content-Type": "application/json", "Authorization": "Bearer " + k})
    out = json.loads(urllib.request.urlopen(rq, timeout=timeout).read().decode("utf-8"))
    D = sorted(out.get("data") or [], key=lambda x: x.get("index", 0))
    return [x["embedding"] for x in D] if len(D) == len(texts) else None


def backend():
    """the model to use now: the local one unless it is known down, then OpenAI, else None"""
    now = time.time()
    if now >= _DOWN.get("ollama", 0):
        return OLLAMA_MODEL
    if now >= _DOWN.get("openai", 0) and os.environ.get("OPENAI_API_KEY"):
        return OPENAI_MODEL
    return None


def embed(texts, model=None, timeout=60):
    """vectors for texts with ONE model (cached) -> (model, [vec...]) or (None, None)"""
    texts = [str(t or "") for t in texts]
    model = model or backend()
    if not model or not texts:
        return None, None
    keys = [_key(model, t) for t in texts]
    have = {}
    with _LK:
        c = _db()
        for k in set(keys):
            r = c.execute("SELECT dim, vec FROM v WHERE k=?", (k,)).fetchone()
            if r:
                have[k] = _unpack(r[1], r[0])
        c.close()
    miss = [i for i, k in enumerate(keys) if k not in have]
    if miss:
        try:
            fn = _ollama if model == OLLAMA_MODEL else _openai
            E = fn([texts[i] for i in miss], timeout)
            if not E:
                raise RuntimeError("no vectors")
        except Exception as e:
            # a slow answer (the model loading, a busy CPU) is not an outage: only a refused/failed call takes it out
            if "timed out" in str(e).lower() or "timeout" in type(e).__name__.lower():
                _log("SLOW %s (%ds): %s" % (model, timeout, str(e)[:120]))
            else:
                _DOWN["ollama" if model == OLLAMA_MODEL else "openai"] = time.time() + 600
                _log("DOWN %s: %s" % (model, str(e)[:160]))
            return None, None
        with _LK:
            c = _db()
            for i, v in zip(miss, E):
                have[keys[i]] = v
                c.execute("INSERT OR REPLACE INTO v VALUES (?,?,?,?,?)", (keys[i], model, len(v), _pack(v), time.time()))
            c.commit()
            c.close()
    return model, [have[k] for k in keys]


def cached(texts, model):
    """the vectors already known for these texts (no model call) -> {index: vec}"""
    out = {}
    with _LK:
        c = _db()
        for i, t in enumerate(texts):
            r = c.execute("SELECT dim, vec FROM v WHERE k=?", (_key(model, t),)).fetchone()
            if r:
                out[i] = _unpack(r[1], r[0])
        c.close()
    return out


def _cos(a, b):
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return sum(x * y for x, y in zip(a, b)) / (na * nb) if na and nb else 0.0


def _fill_bg(texts, model):
    if _BG["busy"]:
        return
    _BG["busy"] = True

    def run():
        try:
            for i in range(0, len(texts), 8):
                embed(texts[i:i + 8], model=model, timeout=120)
        except Exception:
            pass
        finally:
            _BG["busy"] = False
    threading.Thread(target=run, daemon=True).start()


def scores(cue, blocks, wait_s=3.0):
    """similarity of each memory block to the cue -> {index: 0..1} (only blocks with a known vector), or None when no
    embedding backend answers in time (the caller then uses word overlap)"""
    model = backend()
    if not model or not str(cue or "").strip():
        return None
    t0 = time.time()
    m, cv = embed([cue], model=model, timeout=wait_s)
    if not cv:
        _fill_bg(list(blocks), model)              # warm the model and learn the blocks for the next turn
        return None
    known = cached(blocks, m)
    miss = [b for i, b in enumerate(blocks) if i not in known]
    if miss:
        _fill_bg(miss, m)
    out = {i: _cos(cv[0], v) for i, v in known.items()}
    _log("SCORE %s cue %.1fs, %d/%d blocks known" % (m, time.time() - t0, len(known), len(blocks)))
    return out


def warm():
    """at app start: load the model and learn nothing else (a reply then never pays the cold load)"""
    threading.Thread(target=lambda: embed(["warm up"], timeout=120), daemon=True).start()
