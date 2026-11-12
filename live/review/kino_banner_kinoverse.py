"""Kino's X banner, Kinoverse version (2026-11-06, owner: a banner not specific to trading; first version 2026-11-05, owner: "a nice image for the X banner header too").

1500x500. X puts the round profile picture over the bottom-left and phones trim the top and bottom, so the words sit in the middle
band from x~330, and Kino's presence (the same Synapse as his picture and the app) glows on the right, its thoughts drifting
across the banner. Font: Inter, the app's own. Run: python kino_banner.py [out_dir]
"""
import math, os, random, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, K = 1500, 500, 2                       # drawn at 2x, scaled down
w, h = W * K, H * K
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
FONT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "InterVariable.woff2")
C1, C2 = (124, 108, 255), (34, 211, 238)

yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
# background: the app's dark navy, an indigo bloom behind the presence on the right
bg = np.zeros((h, w, 3), np.float32)
bg[:] = (10, 14, 22)
px, py = w * 0.80, h * 0.50
d = np.hypot((xx - px) / 1.25, yy - py) / (h * 1.05)
t = np.clip(d, 0, 1)[..., None]
bg = bg * t + np.array([30, 34, 84], np.float32) * (1 - t)
img = Image.fromarray(np.clip(bg, 0, 255).astype(np.uint8), "RGB").convert("RGBA")

# thoughts drifting across the banner: faint points and links, thicker toward the presence
random.seed(7)
pts = []
for i in range(70):
    x = random.uniform(0.02, 0.98) * w
    y = random.uniform(0.06, 0.94) * h
    near = math.exp(-((x - px) ** 2 + (y - py) ** 2) / (2 * (h * 0.55) ** 2))
    pts.append((x, y, near))
lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
ld = ImageDraw.Draw(lay)
for i in range(len(pts)):
    for j in range(i + 1, len(pts)):
        dd = math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1])
        if dd < h * 0.30:
            a = (1 - dd / (h * 0.30)) * (0.10 + 0.35 * max(pts[i][2], pts[j][2]))
            ld.line([pts[i][:2], pts[j][:2]], fill=C2 + (int(255 * a),), width=2)
for i, (x, y, near) in enumerate(pts):
    r = 2.5 + 4 * near
    ld.ellipse((x - r, y - r, x + r, y + r), fill=(C2 if i % 2 else C1) + (int(255 * (0.25 + 0.65 * near)),))
img = Image.alpha_composite(img, lay)

# the presence (kino_presence.js "rest" still frame, t = 2) on the right
pw = h * 0.95
cx, cy = px, py
cc_r, ph = pw * 0.34, 2.0 * 0.35
halo = Image.new("RGBA", (w, h), (0, 0, 0, 0))
hd = ImageDraw.Draw(halo)
for k in range(40, 0, -1):
    rr = cc_r * 1.4 * k / 40
    hd.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=C1 + (int(255 * 0.42 * (1 - k / 40) ** 1.5 / 4),))
img = Image.alpha_composite(img, halo.filter(ImageFilter.GaussianBlur(10)))
P = []
for i in range(18):
    a = ph * (0.4 + (i % 5) * 0.13) + i * 2.39
    rr = cc_r * (0.45 + 0.5 * ((i * 37) % 11) / 11) * (1 + 0.06 * math.sin(ph * 2 + i))
    P.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr * 0.92))
lay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
ld = ImageDraw.Draw(lay)
for i in range(18):
    for j in range(i + 1, 18):
        dd = math.hypot(P[i][0] - P[j][0], P[i][1] - P[j][1])
        if dd < cc_r * 0.55:
            ld.line([P[i], P[j]], fill=C2 + (int(255 * (1 - dd / (cc_r * 0.55)) * 0.55),), width=4)
dots = Image.new("RGBA", (w, h), (0, 0, 0, 0))
dd_ = ImageDraw.Draw(dots)
for i, (x, y) in enumerate(P):
    r = pw / 70
    dd_.ellipse((x - r, y - r, x + r, y + r), fill=(C2 if i % 2 else C1) + (245,))
img = Image.alpha_composite(img, lay)
img = Image.alpha_composite(img, dots.filter(ImageFilter.GaussianBlur(6)))
img = Image.alpha_composite(img, dots)
# the core, as the app draws it: white -> cyan (at 40 %) -> transparent violet
dist = np.hypot(xx - cx, yy - cy) / (cc_r * 0.55)
tc = np.clip(dist, 0, 1)
rgb = np.where(tc[..., None] < 0.4, np.array([255, 255, 255], np.float32) * (1 - tc[..., None] / 0.4) + np.array(C2, np.float32) * (tc[..., None] / 0.4),
               np.array(C2, np.float32) * (1 - (tc[..., None] - 0.4) / 0.6) + np.array(C1, np.float32) * ((tc[..., None] - 0.4) / 0.6))
alpha = np.where(tc < 0.4, 0.95 - (0.95 - 0.7) * tc / 0.4, 0.7 * (1 - (tc - 0.4) / 0.6))
alpha[dist >= 1] = 0
core = np.dstack([rgb, alpha[..., None] * 255]).astype(np.uint8)
img = Image.alpha_composite(img, Image.fromarray(core, "RGBA"))


def font(size, weight):
    f = ImageFont.truetype(FONT, size)
    try:
        f.set_variation_by_axes([32 if size >= 60 else 14, weight])     # Inter's axes: optical size, weight
    except Exception:
        pass
    return f


d = ImageDraw.Draw(img)
x0 = int(w * 0.235)
d.text((x0, int(h * 0.30)), "I build websites & apps", font=font(96, 750), fill=(242, 245, 250))
d.text((x0, int(h * 0.30) + 112), "for small businesses.", font=font(96, 750), fill=(242, 245, 250))
d.text((x0, int(h * 0.30) + 250), "Made for you, shown to you before you pay - and I test", font=font(40, 450), fill=(170, 182, 210))
d.text((x0, int(h * 0.30) + 302), "trading ideas against chance, honest when it was luck.", font=font(40, 450), fill=(170, 182, 210))
d.text((x0, int(h * 0.30) + 382), "Kino · an AI by Kinoverse  ·  kinoverseai.com", font=font(32, 600), fill=(157, 146, 255))

out = img.convert("RGB").resize((W, H), Image.LANCZOS)
out.save(os.path.join(OUT, "kino_banner_kinoverse.png"), optimize=True)
# a preview with the profile picture where X puts it (bottom-left), to check nothing important is hidden
pv = out.copy()
av = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "kino_avatar.png")
if os.path.exists(av):
    a = Image.open(av).convert("RGBA").resize((200, 200))
    m = Image.new("L", (200, 200), 0)
    ImageDraw.Draw(m).ellipse((0, 0, 199, 199), fill=255)
    pv.paste(a, (40, 380), m)
pv.save(os.path.join(OUT, "kino_banner_kinoverse_preview.png"))
print("ok")
