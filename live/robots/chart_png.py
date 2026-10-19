"""A chart picture for Telegram (owner 2026-10-19 item 6: "on Telegram, Kino sends real chart images").
render(demo_msg) -> PNG bytes of the first chart of a Kino "demo" message (an idea's moments, the robot's trades or the
live chart): candles, the lines (overlays), the marks / the trade (entry, stop, target, exit), a title. PIL only."""
import io

from PIL import Image, ImageDraw, ImageFont

W, H = 900, 520
BG, GRID, TXT, MUT = (11, 20, 26), (31, 44, 52), (233, 237, 239), (138, 155, 176)
UP, DN, VIO, BLU, WARN = (46, 204, 113), (255, 92, 92), (167, 139, 250), (59, 130, 246), (232, 197, 90)


def _font(n):
    for f in ("arialbd.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, n)
        except Exception:
            pass
    return ImageFont.load_default()


def render(m):
    if m.get("trades"):
        t = m["trades"][0]
        rows, ov, marks, trade = t.get("candles") or [], t.get("overlays") or [], [], t
        title = "%s · %s %s" % (m.get("market"), "Achat" if t.get("d") == 1 else "Vente", ("%+.1fR" % t["r"]) if t.get("r") is not None else "")
    elif m.get("moments"):
        x = m["moments"][0]
        rows, ov, marks, trade = x.get("candles") or [], x.get("overlays") or [], x.get("marks") or [], None
        title = ("%s · en direct" % m.get("market")) if m.get("kind") == "live" else ("%s · là où ton idée se déclenche" % m.get("market"))
    else:
        return None
    if len(rows) < 3:
        return None
    im = Image.new("RGB", (W, H), BG)
    g = ImageDraw.Draw(im)
    L, R, T, B = 16, 92, 56, 30
    lo = min(r[3] for r in rows); hi = max(r[2] for r in rows)
    for v in ([trade.get("entry"), trade.get("stop"), trade.get("target")] if trade else []) + [mk["p"] for mk in marks]:
        if v is not None:
            lo, hi = min(lo, v), max(hi, v)
    pad = (hi - lo) * 0.08 or 1
    lo -= pad; hi += pad
    n = len(rows); cw = (W - L - R) / n
    X = lambda i: L + i * cw + cw / 2
    Y = lambda v: T + (hi - v) / (hi - lo) * (H - T - B)
    f1, f2 = _font(22), _font(14)
    for q in range(4):
        v = lo + (hi - lo) * q / 3
        g.line([(L, Y(v)), (W - R, Y(v))], fill=GRID)
        g.text((W - R + 6, Y(v) - 8), ("%.5g" % v), font=f2, fill=MUT)
    for i, r in enumerate(rows):
        c = UP if r[4] >= r[1] else DN
        x = X(i)
        g.line([(x, Y(r[2])), (x, Y(r[3]))], fill=c, width=1)
        y1, y2 = Y(max(r[1], r[4])), Y(min(r[1], r[4]))
        g.rectangle([x - max(1, cw * .32), y1, x + max(1, cw * .32), max(y2, y1 + 1)], fill=c)
    for k, o in enumerate(ov[:3]):
        pts = [(X(i), Y(v)) for i, v in enumerate(o.get("pts") or []) if v is not None and i < n]
        if len(pts) > 1:
            g.line(pts, fill=VIO if k == 0 else BLU, width=2)
    idx = lambda t: max([i for i, r in enumerate(rows) if r[0] <= t] or [0])
    if trade:
        ie, ix = idx(trade["t_in"]), idx(trade["t_out"])
        for v, col in ((trade.get("entry"), BLU), (trade.get("stop"), DN), (trade.get("target"), UP)):
            if v is not None:
                g.line([(X(ie), Y(v)), (X(ix), Y(v))], fill=col, width=2)
        g.ellipse([X(ix) - 6, Y(trade["exit"]) - 6, X(ix) + 6, Y(trade["exit"]) + 6], fill=WARN)
        ye = Y(trade["entry"])
        tri = [(X(ie), ye + 4), (X(ie) - 8, ye + 18), (X(ie) + 8, ye + 18)] if trade.get("d") == 1 else [(X(ie), ye - 4), (X(ie) - 8, ye - 18), (X(ie) + 8, ye - 18)]
        g.polygon(tri, fill=UP if trade.get("d") == 1 else DN)
    for mk in marks:
        x, y = X(idx(mk["t"])), Y(mk["p"])
        if mk["k"] == "buy":
            g.polygon([(x, y + 4), (x - 8, y + 18), (x + 8, y + 18)], fill=UP)
        elif mk["k"] == "sell":
            g.polygon([(x, y - 4), (x - 8, y - 18), (x + 8, y - 18)], fill=DN)
    g.text((L, 16), title, font=f1, fill=TXT)
    g.text((W - 150, H - 24), "OwlNest · Kino", font=f2, fill=MUT)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()
