"""kino_docs.py (2026-11-08, owner: "make Kino stand out from ChatGPT and Claude" - a paid job ends with a real file to send).

Kino writes a deliverable (a CV, a letter, a plan, a document) as plain text; make() lays it out as a clean A4 page and prints it
to PDF with the server's own Edge (headless, no extra library).

Text conventions (they survive his chat clean-up, which removes "-", "*" and "•" bullets and **bold**):
  # Title / Name           the big title (a CV: the person's name)
  ## Section               a section heading
  ▸ item                   a list item
  a line right under "# ..." before the first "##"   the subtitle / contact line(s)
  an empty line            a new paragraph
"""
import html
import os
import re
import shutil
import subprocess
import tempfile
import time

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
KINDS = ("cv", "lettre", "doc")

CSS = """
@page{size:A4;margin:0}
*{box-sizing:border-box}
body{margin:0;font-family:"Segoe UI",Inter,Roboto,Arial,sans-serif;color:#1f2933;font-size:10.6pt;line-height:1.5;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.pg{padding:18mm 18mm 16mm}
h1{margin:0;font-size:25pt;letter-spacing:-.3px;color:#0f172a;line-height:1.15}
.sub{margin-top:5px;color:#475569;font-size:10pt}
h2{font-size:11.5pt;text-transform:uppercase;letter-spacing:1.4px;color:#0f766e;margin:18px 0 6px;padding-bottom:4px;border-bottom:1.5px solid #ccfbf1}
p{margin:0 0 7px}
ul{margin:2px 0 8px;padding-left:16px}li{margin:2px 0}li::marker{color:#0f766e}
.hd{border-left:5px solid #14b8a6;padding-left:14px;margin-bottom:10px}
/* letter */
.lettre .from{color:#334155;font-size:10pt;white-space:pre-line}
.lettre .date{text-align:right;color:#475569;margin:16px 0 18px}
.lettre p{margin:0 0 11px;text-align:justify}
.lettre .obj{margin:0 0 16px}.lettre{line-height:1.6}
.role{font-weight:700;color:#0f172a;margin:8px 0 2px}
/* document */
.doc .band{height:7mm;background:linear-gradient(90deg,#14b8a6,#6366f1)}
.doc h1{font-size:22pt;margin-bottom:4px}
.foot{position:fixed;bottom:8mm;left:18mm;right:18mm;font-size:8pt;color:#94a3b8;text-align:right}
"""


def _inline(s):
    s = html.escape(s)
    return re.sub(r"(https?://[^\s<]+)", r"<a href='\1' style='color:#0f766e'>\1</a>", s)


_YEARS = re.compile(r"^\s*(?:\w+\.?\s+)?(?:19|20)\d\d\s*(?:[-–—à]|to)\s*(?:(?:\w+\.?\s+)?(?:19|20)\d\d|aujourd'hui|présent|present|now)\s*$", re.I)


def normalize(kind, text):
    """2026-11-08: his chat clean-up can eat markdown, and he does not always use the markers - read the structure from plain
    text: first line = name/title, ALL-CAPS or 'Title:' lines = sections, role + dates = a job line, runs of short lines = a list"""
    L = [x.rstrip() for x in str(text or "").replace("\r", "").split("\n")]
    if any(x.strip().startswith(("# ", "## ", "▸")) for x in L):
        return "\n".join(L)
    blocks, cur = [], []
    for x in L:
        if x.strip():
            cur.append(x.strip())
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)
    out, first = [], True

    def is_head(t):
        letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
        return len(t) < 45 and bool(letters) and (t == t.upper() or (t.endswith(":") and len(t) < 40))
    for b in blocks:
        if first and kind != "lettre":
            out.append("# " + (b[0].title() if b[0] == b[0].upper() else b[0]))
            out += b[1:]
            out.append("")
            first = False
            continue
        first = False
        if kind != "lettre" and is_head(b[0]):
            out.append("## " + b[0].rstrip(":"))
            b = b[1:]
        if not b:
            continue
        short = len(b) >= 2 and all(len(x) < 100 and not x.endswith(".") for x in b)
        if kind != "lettre" and short:
            i = 0
            while i < len(b):
                if i + 1 < len(b) and _YEARS.match(b[i + 1]):
                    out.append(b[i] + " · " + b[i + 1])
                    i += 2
                    continue
                yr = re.search(r"\b(19|20)\d\d\b", b[i]) and len(b[i]) <= 60
                out.append(b[i] if yr else "▸ " + b[i])
                i += 1
        else:
            out += b
        out.append("")
    return "\n".join(out)


def to_html(kind, title, text, lang="fr"):
    kind = kind if kind in KINDS else "doc"
    lines = normalize(kind, text).split("\n")
    out, ul, para, h1_done, sub, in_sub = [], [], [], False, [], False

    def flush_ul():
        if ul:
            out.append("<ul>" + "".join("<li>%s</li>" % _inline(x) for x in ul) + "</ul>")
            ul.clear()

    def flush_p():
        if para:
            out.append("<p>%s</p>" % "<br>".join(_inline(x) for x in para))
            para.clear()
    for ln in lines:
        s = ln.strip()
        if s.startswith("# ") and kind == "lettre":
            flush_ul(); flush_p()
            out.append("__DATE__<p class='obj'><b>%s</b></p>" % _inline(s[2:].strip()))
            h1_done = True
            continue
        if s.startswith("# ") and not h1_done:
            flush_ul(); flush_p()
            out.append("<div class='hd'><h1>%s</h1>__SUB__</div>" % _inline(s[2:].strip()))
            h1_done, in_sub = True, True
            continue
        if s.startswith("## ") or s.startswith("### "):
            flush_ul(); flush_p(); in_sub = False
            out.append("<h2>%s</h2>" % _inline(s.lstrip("#").strip()))
            continue
        if in_sub and s and kind != "lettre":
            sub.append(s)
            continue
        in_sub = in_sub and bool(s)
        if s[:1] in ("▸", "►", "‣", "◦", "→") :
            flush_p()
            ul.append(s[1:].strip())
            continue
        if not s:
            flush_ul(); flush_p()
            continue
        flush_ul()
        if kind == "cv" and re.search(r"\b(19|20)\d\d\b", s) and len(s) < 110 and not para:
            out.append("<p class='role'>%s</p>" % _inline(s))
            continue
        para.append(s)
    flush_ul(); flush_p()
    body = "".join(out).replace("__SUB__", ("<div class='sub'>%s</div>" % " · ".join(_inline(x) for x in sub)) if sub else "")
    if not h1_done and kind != "lettre":
        body = "<div class='hd'><h1>%s</h1></div>" % _inline(title) + body
    if kind == "lettre":
        import datetime
        d = datetime.date.today()
        mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
        date = ("Le %d %s %d" % (d.day, mois[d.month - 1], d.year)) if lang != "en" else d.strftime("%d %B %Y")
        body = body.replace("__DATE__", "<div class='date'>%s</div>" % date, 1) if "__DATE__" in body else "<div class='date'>%s</div>" % date + body
    band = "<div class='band'></div>" if kind == "doc" else ""
    foot = "<div class='foot'>%s</div>" % html.escape(title) if kind == "doc" else ""
    return ("<!doctype html><html lang='%s'><head><meta charset='utf-8'><title>%s</title><style>%s</style></head><body class='%s'>%s"
            "<div class='pg'>%s</div>%s</body></html>" % ("en" if lang == "en" else "fr", html.escape(title), CSS, kind, band, body, foot))


def make(kind, title, text, out_pdf, lang="fr", timeout=60):
    """-> out_pdf path, or raises RuntimeError"""
    tmp = tempfile.mkdtemp(prefix="kdoc_")
    try:
        src = os.path.join(tmp, "doc.html")
        open(src, "w", encoding="utf-8").write(to_html(kind, title, text, lang))
        prof = os.path.join(tmp, "prof")
        subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--no-first-run", "--user-data-dir=" + prof,
                        "--no-pdf-header-footer", "--print-to-pdf=" + out_pdf, "file:///" + src.replace("\\", "/")],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout)
        for _ in range(20):
            if os.path.isfile(out_pdf) and os.path.getsize(out_pdf) > 800:
                return out_pdf
            time.sleep(0.25)
        raise RuntimeError("no pdf")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def split(text):
    """his message -> (the words for the chat, the document between <<< and >>>) - no markers: (text, None)"""
    m = re.search(r"<<<\s*\n?(.*?)\n?\s*>>>", str(text or ""), re.S)
    if not m:
        return text, None
    chat = re.sub(r"\n\s*\n+", "\n\n", (text[:m.start()] + text[m.end():])).strip()
    return chat, m.group(1).strip()
