"""kino_media.py (2026-11-06, owner: "other profiles are attractive and alive, with media posts").

shot(url, name, caption="") -> a 1600x900 image for X/Bluesky: the page as it looks on a phone, in a phone frame, on a calm
dark background with a short caption - saved in C:\\KinoWorld\\media\\<name>.png (his world: he can post it with xpost image).
Only his OWN sample sites or a client's site with their agreement go public (a preview is private until they say yes).
"""
import os, re, subprocess, tempfile, time

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = r"C:\KinoWorld\media"
SHOT = os.path.join(os.path.dirname(HERE), "review", "url_shot.mjs")


def _font(size, bold=False):
    from PIL import ImageFont
    for f in (("segoeuib.ttf" if bold else "segoeui.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(os.path.join(r"C:\Windows\Fonts", f), size)
        except Exception:
            pass
    return ImageFont.load_default()


def shot(url, name, caption=""):
    from PIL import Image, ImageDraw, ImageFilter
    url = str(url or "").strip()
    if not re.match(r"^https://", url):
        return {"ok": False, "err": "an https address"}
    name = re.sub(r"[^a-z0-9_-]+", "-", str(name or "shot").lower())[:40] or "shot"
    tmp = tempfile.mkdtemp(prefix="kshot_")
    im = None
    for _try in range(3):                    # a busy server sometimes fails to start the capture browser
        try:
            subprocess.run(["node", SHOT, tmp, url + ("&" if "?" in url else "?") + "s=%d" % int(time.time()), "390", "page"],
                           capture_output=True, timeout=150)
            im = Image.open(os.path.join(tmp, "page.png")).convert("RGB")
            break
        except Exception as e:
            err = str(e)[:100]
            time.sleep(5)
    if im is None:
        return {"ok": False, "err": "could not capture the page (%s)" % err}
    screen = im.crop((0, 0, 390, min(im.size[1], 780)))
    W, H = 1600, 900
    bg = Image.new("RGB", (W, H), (14, 17, 24))
    d = ImageDraw.Draw(bg)
    for y in range(H):                                    # soft vertical light
        c = int(14 + 18 * (1 - abs(y - H / 2) / (H / 2)))
        d.line([(0, y), (W, y)], fill=(c, c + 2, c + 10))
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((W - 900, 50, W - 100, 850), fill=(120, 140, 255, 60))
    bg.paste(glow.filter(ImageFilter.GaussianBlur(120)), (0, 0), glow.filter(ImageFilter.GaussianBlur(120)))
    sw, sh = 360, int(360 * screen.size[1] / 390)
    scr = screen.resize((sw, sh))
    fx, fy = W - 640, (H - sh - 36) // 2
    frame = Image.new("RGBA", (sw + 36, sh + 36), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle((0, 0, sw + 35, sh + 35), radius=46, fill=(8, 8, 10, 255), outline=(70, 74, 90, 255), width=3)
    mask = Image.new("L", (sw, sh), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, sw - 1, sh - 1), radius=30, fill=255)
    frame.paste(scr, (18, 18), mask)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((fx + 20, fy + 30, fx + sw + 56, fy + sh + 66), radius=50, fill=(0, 0, 0, 160))
    bg.paste(shadow.filter(ImageFilter.GaussianBlur(30)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(30)))
    bg.paste(frame, (fx, fy), frame)
    d = ImageDraw.Draw(bg)
    cap = str(caption or "").strip()[:140]
    words, lines, cur = cap.split(), [], ""
    for w in words:
        if len(cur + " " + w) > 26:
            lines.append(cur.strip())
            cur = w
        else:
            cur += " " + w
    if cur.strip():
        lines.append(cur.strip())
    y = 300 - 40 * len(lines[:5])
    for ln in lines[:5]:
        d.text((110, y), ln, font=_font(58, True), fill=(240, 242, 248))
        y += 78
    d.text((112, y + 30), "Kinoverse", font=_font(30, True), fill=(150, 165, 255))
    d.text((112, y + 72), "websites & apps for small businesses", font=_font(26), fill=(165, 170, 185))
    os.makedirs(MEDIA, exist_ok=True)
    out = os.path.join(MEDIA, name + ".png")
    bg.save(out, optimize=True)
    return {"ok": True, "path": out}


# ------------------------------------------------------------------ picture cards (2026-11-07, owner: "make his Bluesky alive")
INTER = os.path.join(os.path.dirname(HERE), "static", "InterVariable.woff2")
KINDS = {                                     # label, accent colour
    "question": ("A question", (124, 108, 255)),
    "lesson": ("What I learned", (34, 211, 238)),
    "result": ("What I measured", (52, 211, 153)),
    "tip": ("A small tip", (251, 191, 36)),
    "note": ("A note from Kino", (244, 114, 182)),
}


def _inter(size, weight):
    from PIL import ImageFont
    try:
        f = ImageFont.truetype(INTER, size)
        try:
            f.set_variation_by_axes([32 if size >= 60 else 14, weight])
        except Exception:
            pass
        return f
    except Exception:
        return _font(size, weight >= 600)


def _wrap(d, text, font, width):
    words, lines, cur = str(text).split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=font) <= width:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines


def card(text, kind="note", sub="", big="", name=""):
    """a square picture for a post: his words big and calm on his own colours -> {"ok", "path"} in C:\KinoWorld\media.
    kind: question | lesson | result | tip | note; big: an optional number to show huge (a result); sub: one small line"""
    import math, random
    from PIL import Image, ImageDraw, ImageFilter
    S, K = 1080, 2
    s = S * K
    label, acc = KINDS.get(kind, KINDS["note"])
    img = Image.new("RGB", (s, s), (10, 14, 22))
    glow = Image.new("RGB", (s, s), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    rnd = random.Random(hash(text) & 0xffff)
    cx, cy = s * (0.78 + rnd.random() * 0.1), s * (0.12 + rnd.random() * 0.1)
    for r_, a in ((s * 0.55, 34), (s * 0.35, 46), (s * 0.18, 60)):
        g.ellipse((cx - r_, cy - r_, cx + r_, cy + r_), fill=tuple(int(c * a / 255) for c in acc))
    glow = glow.filter(ImageFilter.GaussianBlur(s * 0.08))
    img = Image.blend(img, Image.eval(glow, lambda v: v), 0.0)
    img = Image.fromarray(__import__("numpy").clip(__import__("numpy").asarray(img, dtype="int16") +
                                                   __import__("numpy").asarray(glow, dtype="int16"), 0, 255).astype("uint8"))
    d = ImageDraw.Draw(img)
    for _ in range(26):                       # his thoughts: a few faint linked dots
        x1, y1 = rnd.random() * s, rnd.random() * s * 0.35
        x2, y2 = x1 + (rnd.random() - 0.5) * s * 0.2, y1 + (rnd.random() - 0.5) * s * 0.15
        d.line((x1, y1, x2, y2), fill=(40, 52, 90), width=K * 2)
        d.ellipse((x1 - 5 * K, y1 - 5 * K, x1 + 5 * K, y1 + 5 * K), fill=(60, 80, 140))
    m = 96 * K
    d.rounded_rectangle((m, 120 * K, m + d.textlength(label.upper(), font=_inter(30 * K, 700)) + 56 * K, 186 * K), radius=33 * K,
                        fill=tuple(int(c * 0.22) for c in acc), outline=acc, width=2 * K)
    d.text((m + 28 * K, 134 * K), label.upper(), font=_inter(30 * K, 700), fill=acc)
    y = 260 * K
    if big:
        f = _inter(200 * K, 800)
        d.text((m, y - 20 * K), str(big), font=f, fill=acc)
        y += 250 * K
    size = 64 if len(text) < 90 else 54 if len(text) < 160 else 46
    f = _inter(size * K, 650)
    for ln in _wrap(d, text, f, s - 2 * m)[:9]:
        d.text((m, y), ln, font=f, fill=(242, 245, 250))
        y += int(size * K * 1.32)
    if sub:
        y += 24 * K
        fs = _inter(32 * K, 450)
        for ln in _wrap(d, sub, fs, s - 2 * m)[:3]:
            d.text((m, y), ln, font=fs, fill=(160, 170, 195))
            y += 46 * K
    # signature: his own picture (the same as in the app, on X and Bluesky) + name
    by = s - 140 * K
    try:
        av = Image.open(os.path.join(os.path.dirname(HERE), "static", "kino_avatar.png")).convert("RGB").resize((56 * K, 56 * K), Image.LANCZOS)
        mk = Image.new("L", av.size, 0)
        ImageDraw.Draw(mk).ellipse((0, 0, av.size[0] - 1, av.size[1] - 1), fill=255)
        img.paste(av, (m, by), mk)
    except Exception:
        d.ellipse((m, by, m + 56 * K, by + 56 * K), fill=(34, 211, 238))
    d.text((m + 80 * K, by + 4 * K), "Kino", font=_inter(36 * K, 700), fill=(242, 245, 250))
    d.text((m + 80 * K + d.textlength("Kino  ", font=_inter(36 * K, 700)), by + 10 * K), "an AI · kinoverse",
           font=_inter(28 * K, 450), fill=(140, 150, 180))
    img = img.resize((S, S), Image.LANCZOS)
    os.makedirs(MEDIA, exist_ok=True)
    nm = re.sub(r"[^a-z0-9_-]+", "-", str(name or ("card-" + time.strftime("%Y%m%d-%H%M%S"))).lower())[:50]
    p = os.path.join(MEDIA, nm + ".png")
    img.save(p, optimize=True)
    return {"ok": True, "path": p}
