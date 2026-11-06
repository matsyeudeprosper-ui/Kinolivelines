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
