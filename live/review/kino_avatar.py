"""Kino's profile picture (2026-11-05, owner: "isn't it supposed to be the consciousness presence image of him we have in the app?").

A still frame of kino_presence.js ("Synapse" - Kino has no face: a bright core with points of thought orbiting it, linked when they
meet) on the app's centre-button disc (dark radial, fine violet ring, soft violet glow). Same maths, same colours, same still frame
the app shows for reduced motion (t = 2, "rest" state), drawn at high resolution. Run: python kino_avatar.py [out_dir]
"""
import math, os, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

S = 2400                                     # supersampled canvas
C1, C2 = (124, 108, 255), (34, 211, 238)    # ST.rest: violet, cyan
SP, T = 0.35, 2.0                            # rest speed, the still frame's time
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))

yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
c = S / 2.0


def radial(cx, cy, r0, r1, stops):
    """stops: [(t, (r,g,b,a 0..1))] -> RGBA float array"""
    d = np.clip((np.hypot(xx - cx, yy - cy) - r0) / max(1e-6, r1 - r0), 0, 1)
    out = np.zeros((S, S, 4), np.float32)
    ts = [s[0] for s in stops]
    for ch in range(4):
        out[..., ch] = np.interp(d, ts, [s[1][ch] for s in stops])
    return out


def over(dst, src):
    a = src[..., 3:4]
    dst[..., :3] = src[..., :3] * a + dst[..., :3] * (1 - a)
    dst[..., 3:4] = a + dst[..., 3:4] * (1 - a)
    return dst


canvas = np.zeros((S, S, 4), np.float32)
canvas[..., :3] = (10 / 255, 14 / 255, 22 / 255)
canvas[..., 3] = 1
# the disc of the app's centre button: radial-gradient(circle at 50% 40%, #18203a 0%, #0d121e 62%, #0a0e16 100%)
canvas = over(canvas, radial(c, S * 0.40, 0, S * 0.62, [(0, (24 / 255, 32 / 255, 58 / 255, 1)), (0.62, (13 / 255, 18 / 255, 30 / 255, 1)),
                                                         (1, (10 / 255, 14 / 255, 22 / 255, 1))]))
# inset violet glow near the edge (inset 0 0 18px rgba(124,108,255,.18))
edge = np.hypot(xx - c, yy - c) / (S / 2)
glow = np.zeros((S, S, 4), np.float32)
glow[..., :3] = np.array(C1) / 255
glow[..., 3] = np.clip((edge - 0.72) / 0.28, 0, 1) ** 2 * 0.22
canvas = over(canvas, glow)

# the presence itself, drawn in a box of side w centred on the disc (the app draws it at 50/58 of the button)
w = S * 1.12                                 # bigger than in the button: an avatar is seen small (owner: same presence)
ox = oy = (S - w) / 2
cc, r, ph = w / 2, w * 0.34, T * SP
halo = radial(ox + cc, oy + cc, 0, r * 1.4, [(0, tuple(np.array(C1) / 255) + (0.42,)), (1, tuple(np.array(C1) / 255) + (0.0,))])
canvas = over(canvas, halo)

img = Image.fromarray((np.clip(canvas, 0, 1) * 255).astype(np.uint8), "RGBA")
P = []
n = 18
for i in range(n):
    a = ph * (0.4 + (i % 5) * 0.13) + i * 2.39
    rr = r * (0.45 + 0.5 * ((i * 37) % 11) / 11) * (1 + 0.06 * math.sin(ph * 2 + i))
    P.append((ox + cc + math.cos(a) * rr, oy + cc + math.sin(a) * rr * 0.92))
lines = Image.new("RGBA", (S, S), (0, 0, 0, 0))
ld = ImageDraw.Draw(lines)
lw = max(1, int(w / 180 * 1.6))              # a touch bolder than on screen, so links survive the scale-down
for i in range(n):
    for j in range(i + 1, n):
        d = math.hypot(P[i][0] - P[j][0], P[i][1] - P[j][1])
        if d < r * 0.55:
            ld.line([P[i], P[j]], fill=C2 + (int(255 * (1 - d / (r * 0.55)) * 0.5),), width=lw)
img = Image.alpha_composite(img, lines)
dots = Image.new("RGBA", (S, S), (0, 0, 0, 0))
dd = ImageDraw.Draw(dots)
pr = max(1.0, w / 90) * 1.5
for i, (x, y) in enumerate(P):
    col = C2 if i % 2 else C1
    dd.ellipse((x - pr, y - pr, x + pr, y + pr), fill=col + (242,))
# a soft bloom around each point of thought
bloom = dots.filter(ImageFilter.GaussianBlur(S * 0.006))
img = Image.alpha_composite(img, bloom)
img = Image.alpha_composite(img, dots)
# the core: white -> cyan -> transparent violet
core = radial(ox + cc, oy + cc, 0, r * 0.55, [(0, (1, 1, 1, 0.95)), (0.4, tuple(np.array(C2) / 255) + (0.7,)), (1, tuple(np.array(C1) / 255) + (0.0,))])
img = Image.alpha_composite(img, Image.fromarray((np.clip(core, 0, 1) * 255).astype(np.uint8), "RGBA"))
# the fine violet ring (border 1px rgba(157,146,255,.45)) just inside the edge
ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
rd = ImageDraw.Draw(ring)
m = S * 0.012
rd.ellipse((m, m, S - m, S - m), outline=(157, 146, 255, 115), width=int(S * 0.006))
img = Image.alpha_composite(img, ring).convert("RGB")

for size in (1000, 400):
    img.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, "kino_avatar_%d.png" % size), optimize=True)
img.resize((48, 48), Image.LANCZOS).resize((192, 192), Image.NEAREST).save(os.path.join(OUT, "kino_avatar_48preview.png"))
print("ok")
