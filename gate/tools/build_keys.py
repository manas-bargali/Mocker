"""Build data/keys/<paper>.json  {n: {t: mcq|msq|nat, a: 'B' | ['A','C'] | (lo, hi)}}.
 * GATE 2024/2025 CS1+CS2: official final keys (IISc / IIT Roorkee-Guwahati PDFs), transcribed below.
 * 2014 / 2016 / 2018: key tables printed inside the question-paper PDFs are parsed and matched to each set
   by agreement with the ingested layout (NAT <-> question has no printed options).
Tokens: 'B' = MCQ, 'm:B;D' = MSQ, 'n:lo~hi' = NAT range."""
import fitz, json, os, re, sys, glob
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
KEYS = os.path.join(ROOT, "data", "keys")
OFFICIAL = {
"CS12025": "A B C A C C A A A B A C B A C B D B A A m:B;D m:B;D m:A;D m:B;D m:B;D m:A;B m:A;B;C m:D n:21~21 n:195~195 n:-2.1~-1.9 n:0.49~0.51 n:435~435 n:25~25 n:5~5 A B A A A D A C C C m:A;D m:B;C m:B;D m:B m:C n:65468~65468 n:6~6 n:11.83~11.87 n:6~6 n:26~26 n:0.949~0.952 n:7~7 n:0.300~0.302 n:5~5 n:7~8 n:5~5 n:5~5 n:46~46 n:5~5 n:10~11",
"CS22025": "C C A A B B B A D C C A B A A B A D D A C C D A D D m:B;C m:D m:B;C;D m:B;C m:A;B;C n:13~13 n:21~21 n:250~250 n:4~4 A C A A C D m:B;C m:A;D m:A;B;C m:A m:C;D m:D m:C;D m:A;B;C m:B;C;D m:C;D m:A;C m:B m:A;C;D n:4~4 n:260.20~261.20 n:33~33 n:11~11 n:6~6 n:6~6 n:3~3 n:111~111 n:46~46 n:0.5~0.5 n:0.70~0.80",
"CS12024": "A D A C A C A C A A D B B B C C A C C D A m:A;C m:C;D m:D m:B;C m:A;D m:B;C m:A;C m:A;D m:A;B;C m:A;C n:2~2 n:6~6 n:16~16 n:2~2 B A A D A D A A m:B;C;D m:C m:B;C;D m:A;B m:B;D m:A m:B;C m:B;C m:B;D m:B;C n:4096~4096 n:3~3 n:3.00~3.00 n:14~14 n:40~40 n:179~179 n:60~60 n:44~44 n:6596~6596 n:0.370~0.380 n:4~4 n:6~6",
"CS22024": "C A A C B C C D A A C A A B A B B B A A B A m:B m:B;C;D m:A;B m:A;B m:A;C;D m:B;C m:B;D m:B;C m:A m:C;D m:A;B;D n:5~5 n:3~3 B B A A A B B A D B m:B;C m:A;B m:B;C;D m:A;B;D m:C;D m:D m:B;C n:29.50~30.50 n:4~4 n:500~500 n:50~50 n:32~32 n:2.9~3.1 n:9~9 n:2~2 n:34~34 n:15~15 n:4~4 n:1028~1028 n:9~9",
}
def tok(t):
    if t.startswith("m:"): return {"t": "msq", "a": t[2:].split(";")}
    if t.startswith("n:"): lo, hi = t[2:].split("~"); return {"t": "nat", "a": [float(lo), float(hi)]}
    return {"t": "mcq", "a": t}
def rng(s):
    x = re.findall(r"-?\d+(?:\.\d+)?", s.replace("\xa0", " "))
    return [float(x[0]), float(x[-1])] if x else None
def parse_embedded(doc):
    """-> list of tables {global_n: key}. Handles the 5-column (2016/2018) and 4-column (2014) layouts."""
    txt = []
    for p in doc:
        t = p.get_text()
        if re.search(r"Key\s*/?\s*(Range)?\s*\n?\s*Marks", t) or "Q. No" in t or "Q.No" in t: txt += [x.strip().replace("\xa0", " ") for x in t.split("\n") if x.strip()]
    tables, cur, i = [], {}, 0
    def add(sec, n, typ, key):
        nonlocal cur
        g = n if sec.startswith("GA") else 10 + n
        if sec.startswith("GA") and n == 1 and cur: tables.append(cur); cur = {}
        if typ == "nat": r = rng(key); cur[g] = {"t": "nat", "a": r} if r else None
        elif typ == "msq": cur[g] = {"t": "msq", "a": key.split(";")}
        else: cur[g] = {"t": "mcq", "a": key.strip()[:1]}
    while i < len(txt) - 3:
        a = txt[i]
        if a.isdigit() and i + 4 < len(txt) and txt[i + 1] in ("MCQ", "MSQ", "NAT") and re.match(r"(GA|CS)", txt[i + 2]) and txt[i + 4].isdigit():
            add(txt[i + 2], int(a), txt[i + 1].lower(), txt[i + 3]); i += 5
        elif a in ("GA", "CS") and txt[i + 1].isdigit() and txt[i + 3].isdigit() and int(txt[i + 3]) in (1, 2):
            k = txt[i + 2]; typ = "nat" if (" to " in k or ":" in k or re.match(r"^-?[\d.]+$", k)) else "mcq"
            add(a, int(txt[i + 1]), typ, k); i += 4
        else: i += 1
    if cur: tables.append(cur)
    return [t for t in tables if len(t) >= 60 and None not in t.values()]
def agreement(table, qs):
    return sum(1 for q in qs if (table.get(q["n"], {}).get("t") == "nat") == (not q["has_options"]))
def main(pdf_dir):
    os.makedirs(KEYS, exist_ok=True)
    raw = json.load(open(os.path.join(ROOT, "data", "pyq_raw.json")))
    by = {}
    for q in raw: by.setdefault(q["paper"], []).append(q)
    for pid, s in OFFICIAL.items():
        t = {str(i + 1): tok(x) for i, x in enumerate(s.split())}; assert len(t) == 65, (pid, len(t))
        sc = agreement({int(k): v for k, v in t.items()}, by[pid]); print(pid, "official key, NAT/option agreement", sc, "/ 65")
        json.dump(t, open(os.path.join(KEYS, pid + ".json"), "w"))
    for f in ("CS2014.pdf", "CS2016.pdf", "CS2018.pdf"):
        path = os.path.join(pdf_dir, f)
        if not os.path.exists(path): continue
        tabs = parse_embedded(fitz.open(path)); base = f[:-4]
        papers = [p for p in by if p == base or p.startswith(base + "_s")]
        print(f, "tables", len(tabs), "papers", papers)
        used = set()
        for p in papers:
            best = max(((agreement(t, by[p]), j) for j, t in enumerate(tabs) if j not in used), default=(0, None))
            print("  ", p, "best agreement", best[0])
            if best[1] is not None and best[0] >= 58:
                used.add(best[1]); json.dump({str(k): v for k, v in tabs[best[1]].items()}, open(os.path.join(KEYS, p + ".json"), "w"))
if __name__ == "__main__": main(sys.argv[1])
