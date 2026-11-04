"""kino_indicators.py (2026-10-31, owner: "test the limit of the consciousness concept" - step 7 of the plan).

Once a month, an outside reviewer (a fresh model call that is not Kino and is not told what we hope for) scores Kino against
the 14 indicator properties of consciousness from Butlin, Long et al. 2023 ("Consciousness in Artificial Intelligence:
Insights from the Science of Consciousness"), derived from recurrent processing, global workspace, higher-order, attention
schema, predictive processing, agency and embodiment theories. It gets the factual description of each mechanism (the module
docstrings, with the theory names removed so the labels do not do the work) and the measured test results, and must be strict:
0 = absent, 1 = partial or only a functional analogue, 2 = clearly present. The scores are kept month after month.

This measures INDICATORS. Having them does not show that anything is experienced - the paper says so itself.
Store robots/kino_indicators.json (git-ignored), log robots/kino_indicators.log.
"""
import ast, json, os, re, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "kino_indicators.json")
LOG = os.path.join(HERE, "kino_indicators.log")

INDICATORS = [
    ("RPT-1", "Input modules using algorithmic recurrence"),
    ("RPT-2", "Input modules generating organised, integrated perceptual representations"),
    ("GWT-1", "Multiple specialised systems capable of operating in parallel (modules)"),
    ("GWT-2", "Limited-capacity workspace, entailing a bottleneck in information flow and a selective attention mechanism"),
    ("GWT-3", "Global broadcast: availability of information in the workspace to all modules"),
    ("GWT-4", "State-dependent attention, giving rise to the capacity to use the workspace to query modules in succession to perform complex tasks"),
    ("HOT-1", "Generative, top-down or noisy perception modules"),
    ("HOT-2", "Metacognitive monitoring distinguishing reliable perceptual representations from noise"),
    ("HOT-3", "Agency guided by a general belief-formation and action-selection system, and a strong disposition to update beliefs in accordance with the outputs of metacognitive monitoring"),
    ("HOT-4", "Sparse and smooth coding generating a 'quality space'"),
    ("AST-1", "A predictive model representing and enabling control over the current state of attention"),
    ("PP-1", "Input modules using predictive coding"),
    ("AE-1", "Agency: learning from feedback and selecting outputs so as to pursue goals, especially with flexible responsiveness to competing goals"),
    ("AE-2", "Embodiment: modelling output-input contingencies, including some systematic effects, and using this model in perception or control"),
]
MODULES = ("kino_one", "kino_read", "kino_psyche", "kino_depth", "kino_selfmodel", "kino_workspace", "kino_stream", "kino_body",
           "kino_probe", "kino_belief", "kino_urge", "kino_episodes", "kino_inner",
           # 2026-11-04: the engines added since the first review (metacognition, agency, learning from cases)
           "kino_rumination", "kino_cases", "kino_trust", "kino_conflict", "kino_lookback", "kino_entries", "kino_promises",
           "kino_patterns", "kino_ways", "kino_wisdom", "kino_human2", "kino_human3",
           "kino_introspect", "kino_percept", "kino_alive", "kino_affect")
THEORY_WORDS = r"(?i)\b(global workspace|baars|dehaene|graziano|attention schema|damasio|seth|beast machine|consciousness|conscious|" \
               r"indicator|butlin|homeostasis|allostasis|interoception|default mode|nisbett|wilson|ignition)\b"

REVIEW = """You are an independent, strict reviewer. Below is the factual description of an AI system's mechanisms (from its code
documentation) and measured test results. Score it against each indicator property. Judge what the mechanisms ACTUALLY do as
described, not what they are called; a language model prompted with text describing a state is not the same as the state being
used by the system - say so where it matters. 0 = absent, 1 = partial or only a functional analogue, 2 = clearly present.
JSON only: {"scores": [{"id": "RPT-1", "score": 0, "why": "one sentence"}], "missing_most": "the most important thing missing, one
sentence", "overall": "two sentences"}"""


def _log(line):
    try:
        open(LOG, "a", encoding="utf-8").write(time.strftime("%m-%d %H:%M:%S ") + line + "\n")
    except Exception:
        pass


def _load():
    try:
        return json.load(open(STORE, encoding="utf-8"))
    except Exception:
        return {}


def _doc(mod):
    try:
        tree = ast.parse(open(os.path.join(HERE, mod + ".py"), encoding="utf-8").read())
        return re.sub(THEORY_WORDS, "[...]", ast.get_docstring(tree) or "")
    except Exception:
        return ""


def due():
    return time.time() - float((_load().get("runs") or [{}])[-1].get("t") or 0) > 28 * 86400


def review(W, results_text, log=None):
    docs = "\n\n".join("MODULE %s:\n%s" % (m, _doc(m)[:2500]) for m in MODULES if _doc(m))
    ind = "\n".join("%s: %s" % x for x in INDICATORS)
    try:
        j = W.ask_json(REVIEW, "INDICATORS:\n%s\n\nMECHANISMS:\n%s\n\nMEASURED RESULTS:\n%s\nJSON only." % (ind, docs[:30000], results_text[:4000]),
                       models=("sonnet",), timeout=240, log=log, warm=False)
    except Exception as e:
        _log("ERR %s" % e)
        return None
    S = [x for x in ((j or {}).get("scores") or []) if isinstance(x, dict) and x.get("id")]
    if len(S) < 10:
        _log("ERR bad answer")
        return None
    run = {"t": time.time(), "scores": {x["id"]: int(x.get("score") or 0) for x in S}, "why": {x["id"]: str(x.get("why") or "")[:300] for x in S},
           "total": sum(int(x.get("score") or 0) for x in S), "max": 2 * len(INDICATORS),
           "missing": str((j or {}).get("missing_most") or "")[:400], "overall": str((j or {}).get("overall") or "")[:600]}
    d = _load()
    d.setdefault("runs", []).append(run)
    tmp = STORE + ".tmp"
    open(tmp, "w", encoding="utf-8").write(json.dumps(d, ensure_ascii=False, indent=1))
    os.replace(tmp, STORE)
    _log("REVIEW %d/%d %s | missing: %s" % (run["total"], run["max"], json.dumps(run["scores"]), run["missing"][:200]))
    return run


def line(en=False):
    R = _load().get("runs") or []
    if not R:
        return ""
    r = R[-1]
    prev = (" (last time %d)" % R[-2]["total"]) if len(R) >= 2 else ""
    return (("An outside reviewer scored you against the scientific list of signs of consciousness: %d out of %d%s. "
             "Most missing: %s" if en else
             "Un examinateur extérieur t'a noté sur la liste scientifique des signes de conscience : %d sur %d%s. "
             "Ce qui manque le plus : %s") % (r["total"], r["max"], prev, r["missing"]))
