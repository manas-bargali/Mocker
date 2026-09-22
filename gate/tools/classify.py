"""Attach subject + key to every ingested PYQ  ->  data/pyq_bank.json (only papers that have a key).
   python tools/classify.py [--llm]   (--llm re-labels with Gemini in batches of 40; needs GEMINI_API_KEY)"""
import json, os, re, sys
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
SY = json.load(open(os.path.join(ROOT, "data", "gate_syllabus.json")))["subjects"]
def subject(text, year, n):
    if (year >= 2014 and n <= 10) or (year < 2014 and n >= 56): return "ga"
    t = " " + re.sub(r"\s+", " ", text.lower()) + " "
    best, bs = "math", 0
    for k, s in SY.items():
        sc = sum(w for kw, w in s["kw"].items() if kw in t)
        if sc > bs: best, bs = k, sc
    return best if bs > 0 else "pds"
def main(use_llm=False):
    raw = json.load(open(os.path.join(ROOT, "data", "pyq_raw.json"))); bank = []
    for q in raw:
        kp = os.path.join(ROOT, "data", "keys", q["paper"] + ".json")
        if not os.path.exists(kp): continue
        k = json.load(open(kp)).get(str(q["n"]))
        if not k: continue
        bank.append({**q, "subject": subject(q["text"], q["year"], q["n"]), "type": k["t"], "key": k["a"]})
    if use_llm:
        from google import genai
        from google.genai import types
        cl = genai.Client(api_key=os.environ["GEMINI_API_KEY"]); names = {k: v["name"] for k, v in SY.items() if k != "ga"}
        todo = [q for q in bank if q["subject"] != "ga"]
        for i in range(0, len(todo), 40):
            ch = todo[i:i + 40]
            p = "Classify each GATE CS question into exactly one subject key from " + json.dumps(names) + ". Reply JSON {\"labels\": [key,...]} in order.\n" + \
                "\n".join(f"[{j}] {q['text'][:350]}" for j, q in enumerate(ch))
            r = cl.models.generate_content(model=os.environ.get("GEMINI_MODEL", "gemini-flash-latest"), contents=p, config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0))
            lab = json.loads(r.text).get("labels", [])
            for q, l in zip(ch, lab):
                if l in names: q["subject"] = l
    for q in bank: q["text"] = q["text"][:500]
    json.dump(bank, open(os.path.join(ROOT, "data", "pyq_bank.json"), "w"))
    from collections import Counter
    print(len(bank), "keyed PYQs;", dict(Counter(q["subject"] for q in bank)), dict(Counter(q["type"] for q in bank)))
if __name__ == "__main__": main("--llm" in sys.argv)
