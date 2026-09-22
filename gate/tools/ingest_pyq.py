"""Crop every question of a GATE text-layer PDF into a PNG (keeps code, figures, tables, maths intact)
and record its text for classification / prompt reference.
   python tools/ingest_pyq.py <pdf-dir> [--only CS12024.pdf]      needs: pymupdf pillow"""
import fitz, re, os, sys, json, glob, io
from PIL import Image, ImageChops
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
QRE = re.compile(r"^Q\.?\s*(\d{1,2})\b")
CARRY = re.compile(r"Q\.?\s*(\d+)\s*[–\-−]+\s*Q\.?\s*(\d+)\s+carry\s+(one|two|1|2)\s+mark", re.I)
HDR = re.compile(r"Organizing Institute|^Page \d+ of|Set \d|\(CS\d?\)|Computer Science and Information|^CS\s*\d*\s*[-/]\s*\d+|GATE 20\d\d|^\s*CS\s*$", re.I)
END = re.compile(r"END OF THE QUESTION PAPER|END OF QUESTION PAPER", re.I)

def lines_of(page):
    out = []
    for b in page.get_text("dict")["blocks"]:
        for l in b.get("lines", []):
            t = "".join(s["text"] for s in l["spans"]).strip()
            if t: out.append((t, fitz.Rect(l["bbox"])))
    return sorted(out, key=lambda x: (round(x[1].y0), x[1].x0))

def scan(doc):
    ev = []
    for pi, page in enumerate(doc):
        for t, r in lines_of(page):
            c, m = CARRY.search(t), QRE.match(t)
            if c: ev.append((pi, r.y0, "carry", (int(c[1]), int(c[2]), 1 if c[3].lower() in ("one", "1") else 2)))
            elif m and r.x0 < 120: ev.append((pi, r.y0, "q", int(m[1])))
            elif END.search(t): ev.append((pi, r.y0, "end", 0))
    return ev

def build(events):
    """Sequential Q.n markers -> global index. GA-first papers (2014+) restart numbering at the CS section."""
    papers, cur, loc, off = [], None, 1, 0
    new = lambda: {"q": {}, "stops": []}
    for pi, y, kind, val in events:
        if kind == "q":
            tot = len(cur["q"]) if cur else 0
            if val == 1 and tot >= 55: papers.append(cur); cur, loc, off = None, 1, 0
            elif val == 1 and 1 < tot <= 51 and off == 0 and loc == tot + 1: off, loc = tot, 1
            if val == loc:
                cur = cur or new(); cur["q"][off + val] = (pi, y); loc += 1
        elif kind in ("carry", "end"):
            cur = cur or new(); cur["stops"].append((pi, y))
    if cur and cur["q"]: papers.append(cur)
    return papers

def marks_for(year, n):
    if year >= 2014: return 1 if (n <= 5 or 11 <= n <= 35) else 2          # GA first, then CS
    return 1 if (n <= 25 or 56 <= n <= 60) else 2                            # 2012-13: CS then GA

def page_bounds(page):
    h, top, bot = page.rect.height, 36, page.rect.height - 30
    for t, r in lines_of(page):
        if r.y1 < 95 and HDR.search(t): top = max(top, r.y1 + 2)
        if r.y0 > h - 75 and (HDR.search(t) or re.match(r"^\d+$", t)): bot = min(bot, r.y0 - 1)
    return top, bot

def crop_question(doc, p, n, zoom=2.0):
    p0, y0 = p["q"][n]
    cands = [p["q"][n + 1]] if (n + 1) in p["q"] else []
    cands += sorted(s for s in p["stops"] if s > (p0, y0))[:1]
    end = min(cands, default=(len(doc) - 1, 10**6))
    pieces, text = [], []
    for pi in range(p0, min(end[0], len(doc) - 1) + 1):
        pg = doc[pi]; top, bot = page_bounds(pg)
        a = max(top, y0 - 2) if pi == p0 else top
        b = min(bot, end[1] - 2) if pi == end[0] else bot
        if b - a < 8: continue
        rect = fitz.Rect(0, a, pg.rect.width, b)
        text.append(pg.get_text("text", clip=rect))
        pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        pieces.append(Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB"))
    if not pieces: return None, ""
    W, H = max(i.width for i in pieces), sum(i.height for i in pieces)
    img, y = Image.new("RGB", (W, H), "white"), 0
    for i in pieces: img.paste(i, (0, y)); y += i.height
    bb = ImageChops.difference(img, Image.new("RGB", img.size, "white")).getbbox()
    if bb: img = img.crop((max(bb[0] - 8, 0), max(bb[1] - 6, 0), min(bb[2] + 8, W), min(bb[3] + 6, H)))
    return img, " ".join(" ".join(text).split())

def main(src, only=None):
    bank = []
    for f in sorted(glob.glob(os.path.join(src, "*.pdf"))):
        if only and os.path.basename(f) != only: continue
        doc = fitz.open(f)
        m = re.search(r"(20\d\d)", os.path.basename(f)); yr = int(m[1]) if m else 0
        papers = build(scan(doc))
        for k, p in enumerate(papers, 1):
            name = re.sub(r"\.pdf$", "", os.path.basename(f)); pid = name + (f"_s{k}" if len(papers) > 1 else "")
            print(f"{os.path.basename(f)} -> {pid}: {len(p['q'])} questions")
            if len(p["q"]) < 55: continue
            os.makedirs(os.path.join(OUT, "pyq", pid), exist_ok=True)
            for n in sorted(p["q"]):
                img, txt = crop_question(doc, p, n)
                if img is None: continue
                rel = f"{pid}/q{n}.png"
                img.convert("L").save(os.path.join(OUT, "pyq", rel), optimize=True)
                bank.append({"id": f"{pid}-{n}", "paper": pid, "year": yr, "n": n, "marks": marks_for(yr, n),
                             "img": rel, "text": txt[:1200], "has_options": bool(re.search(r"\(A\).*\(B\)", txt))})
    json.dump(bank, open(os.path.join(OUT, "pyq_raw.json"), "w"))
    print("total", len(bank))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[sys.argv.index("--only") + 1] if "--only" in sys.argv else None)
