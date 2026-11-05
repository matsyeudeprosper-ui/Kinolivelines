"""Kino's profile picture: the OwlNest owl (amber eyes, orange beak, dark navy) in Kino's indigo, drawn large and scaled down
so it stays crisp; built to read inside X's circle crop and at 48 px."""
from PIL import Image, ImageDraw, ImageFilter
import math, os

S = 2000                                   # draw big, scale down
OUT = os.path.dirname(os.path.abspath(__file__))
img = Image.new("RGB", (S, S), (11, 15, 20))
px = img.load()
cx = cy = S / 2
# background: indigo glow in the middle (Kino's colour) fading to the app's dark navy
for y in range(S):
    for x in range(0, S, 1):
        d = math.hypot(x - cx, y - cy * 0.92) / (S * 0.72)
        t = max(0.0, min(1.0, d))
        r = int(44 * (1 - t) + 11 * t)
        g = int(56 * (1 - t) + 15 * t)
        b = int(138 * (1 - t) + 26 * t)
        px[x, y] = (r, g, b)
d = ImageDraw.Draw(img)

# head: a soft rounded shape with two ear tufts
head = (int(S * 0.20), int(S * 0.24), int(S * 0.80), int(S * 0.86))
d.ellipse(head, fill=(20, 27, 40))
for side in (-1, 1):                       # symmetric owl tufts, leaning out
    d.polygon([(cx + side * S * 0.27, S * 0.43), (cx + side * S * 0.235, S * 0.175), (cx + side * S * 0.10, S * 0.30)], fill=(20, 27, 40))
# a lighter face disc so the eyes pop
d.ellipse((int(S * 0.25), int(S * 0.33), int(S * 0.75), int(S * 0.83)), fill=(28, 37, 56))

# eyes: amber discs with a darker ring, pupils, and a highlight - looking slightly up-right (curious)
for side in (-1, 1):
    ex, ey, R = cx + side * S * 0.125, S * 0.50, S * 0.115
    d.ellipse((ex - R * 1.12, ey - R * 1.12, ex + R * 1.12, ey + R * 1.12), fill=(186, 118, 36))
    d.ellipse((ex - R, ey - R, ex + R, ey + R), fill=(242, 182, 62))
    pr = R * 0.50
    pxo, pyo = ex + R * 0.10, ey - R * 0.06
    d.ellipse((pxo - pr, pyo - pr, pxo + pr, pyo + pr), fill=(14, 16, 22))
    hr = R * 0.17
    d.ellipse((pxo + pr * 0.25 - hr, pyo - pr * 0.45 - hr, pxo + pr * 0.25 + hr, pyo - pr * 0.45 + hr), fill=(255, 255, 255))

# beak
d.polygon([(cx - S * 0.045, S * 0.615), (cx + S * 0.045, S * 0.615), (cx, S * 0.70)], fill=(214, 128, 44))

# a small spark at the top right: the "AI" in him, quietly
sx, sy, sr = S * 0.84, S * 0.29, S * 0.045
glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse((sx - sr * 2.2, sy - sr * 2.2, sx + sr * 2.2, sy + sr * 2.2), fill=(140, 170, 255, 70))
glow = glow.filter(ImageFilter.GaussianBlur(S * 0.02))
img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
d = ImageDraw.Draw(img)
pts = []
for i in range(8):
    a = math.pi / 4 * i - math.pi / 2
    rr = sr if i % 2 == 0 else sr * 0.32
    pts.append((sx + rr * math.cos(a), sy + rr * math.sin(a)))
d.polygon(pts, fill=(214, 226, 255))

for size in (1000, 400):
    img.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, "kino_avatar_%d.png" % size), optimize=True)
img.resize((48, 48), Image.LANCZOS).resize((192, 192), Image.NEAREST).save(os.path.join(OUT, "kino_avatar_48preview.png"))
print("ok")
