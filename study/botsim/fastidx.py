"""fastidx.py - a speed patch for the SANDBOX copy of owl_chart_feed.py (2026-10-26). Live code is never touched.

Profile (6 simulated hours, after the build memo and the sliding build): `kept.index(m)` = 224 s of ~1100 s. engine() finds the
swing candle m inside `span = kept[a + 1:i]` with min()/max(), then asks `kept.index(m)` - a scan of the whole list from the
start, by equality. m is an element of span, so its index is a + 1 + its position in span. Equality-first == identity because
every candle has its own time (checked by test_fastidx.py on real candles, outputs compared exactly).
"""
import re

HELPER = '''

def _sp_pos(span, m):                      # botsim fastidx: m's position in span, by identity
    for _k, _x in enumerate(span):
        if _x is m:
            return _k
    raise ValueError("botsim fastidx: swing candle not in its span")
'''


def patch_source(src):
    lines = src.split("\n")
    out, base, n = [], None, 0
    for ln in lines:
        m1 = re.match(r"^(\s*)span = kept\[(\w+) \+ 1:i\]\s*$", ln)
        if m1:
            base = m1.group(2)
        m2 = re.match(r"^(\s*)m = (min|max)\(span, key=lambda x: x\[[23]\]\)\s*$", ln)
        out.append(ln)
        if m2:
            assert base, "fastidx: span base not found"
            out.append("%s_mi = (%s + 1) + _sp_pos(span, m)" % (m2.group(1), base))
            n += 1
    s = "\n".join(out)
    k = s.count("kept.index(m)")
    assert k == n == 4, ("fastidx: unexpected shape", k, n)
    s = s.replace("kept.index(m)", "_mi")
    i = s.index("\ndef ")
    return s[:i] + HELPER + s[i:]
