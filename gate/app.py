"""
mockyGATE — GATE CS/IT mock-exam platform (same skeleton as mockyCGL: Flask + filesystem session + Gemini JSON mode + LangGraph engine,
same 4 screens: home -> loading -> exam -> result)

  full     65 Q / 100 marks / 180 min, GA 10 (5x1 + 5x2) + core 55 (25x1 + 30x2), MCQ + MSQ + NAT, official marking
  section  subject-wise mock: pick subjects + number of questions (1M/2M mix), time = 1.8 min per mark like the real paper
  pyq      real past papers: a whole paper in original order, or a fresh sample by subject (questions shown as the original images)

Every question is produced by one of three sources; the paper ALWAYS completes (see fill_slot):
  ai    Gemini, batches of BATCH_SIZE, blind-solve verified, references real PYQs of the same subject as style examples
  code  generators.py families whose answers are computed, not guessed (graphs, trees, tables, C programs...)
  pyq   real questions with an official key (fallback when the API is unavailable / out of budget)
"""
from flask import Flask, render_template, request, jsonify, session, send_from_directory
from flask_session import Session
import json, os, random, re

import generators
from engine import generate_batch, ai_ready, BUDGET, GEMINI_MODEL

BASE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "mockyGATE_dev_secret")
_SESS = os.path.join(BASE, ".flask_session"); os.makedirs(_SESS, exist_ok=True)
app.config.update(SESSION_TYPE="filesystem", SESSION_FILE_DIR=_SESS, SESSION_PERMANENT=False)
Session(app)

SY = json.load(open(os.path.join(BASE, "data", "gate_syllabus.json"), encoding="utf-8"))
SUBJ, ORDER = SY["subjects"], SY["order"]
_pb = os.path.join(BASE, "data", "pyq_bank.json")
PYQ = json.load(open(_pb, encoding="utf-8")) if os.path.exists(_pb) else []
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", 4))          # questions per Gemini call (4-5: code/figure questions are token-heavy)
MAX_LLM_Q = int(os.environ.get("MAX_LLM_Q", 40))           # cap on AI-written questions per paper (the rest come from code / PYQs)
CODE_SHARE = float(os.environ.get("CODE_SHARE", 0.35))     # share of slots served by code-computed families when the AI is on
COUNTS = [5, 10, 15, 20]
MIN_PER_MARK = 1.8                                          # 180 min / 100 marks


def paper_label(pid):
    m = re.match(r"CS(1|2)?(20\d\d)(?:_s(\d))?$", pid) or re.match(r"CS(1|2)?-?(20\d\d)(?:_s(\d))?$", pid)
    if not m: return pid
    n = pid.replace("CS", "", 1)
    yr = re.search(r"20\d\d", pid)[0]; sh = {"1": "CS1", "2": "CS2"}.get(pid[2]) if pid[2] in "12" and pid[3:5] == "20" else None
    s = f" · Set {m[3]}" if m[3] else ""
    return f"GATE {yr}" + (f" · {sh}" if sh else "") + s
PAPERS = sorted({q["paper"] for q in PYQ}, key=lambda p: (-int(re.search(r"20\d\d", p)[0]), p))


# ── planning ────────────────────────────────────────────────────────────────
def pick_type(subject, marks):
    if subject == "ga": return "mcq"
    w = (.6, .1, .3) if marks == 1 else (.45, .2, .35)
    return random.choices(["mcq", "msq", "nat"], weights=w)[0]


def slots_full():
    ga = [{"subject": "ga", "marks": 1}] * 5 + [{"subject": "ga", "marks": 2}] * 5
    one = [{"subject": k, "marks": 1} for k in ORDER if k != "ga" for _ in range(SUBJ[k]["n1"])]
    two = [{"subject": k, "marks": 2} for k in ORDER if k != "ga" for _ in range(SUBJ[k]["n2"])]
    random.shuffle(one); random.shuffle(two)
    return [dict(s) for s in ga + one + two]


def slots_subjects(keys, n):
    out = []
    for k in [x for x in ORDER if x in keys]:
        n1 = round(n * .4); out += [{"subject": k, "marks": 1}] * n1 + [{"subject": k, "marks": 2}] * (n - n1)
    return [dict(s) for s in out]


def pyq_q(p):
    key = p["key"]
    q = {"src": "pyq", "img": "/pyq/" + p["img"], "type": p["type"], "marks": p["marks"], "subject": p["subject"], "question": "", "context": "", "code": "", "figure": None,
         "options": {k: k.upper() for k in "abcd"} if p["type"] != "nat" else {}, "explanation": "",
         "label": f"{paper_label(p['paper'])} · Q{p['n']}", "pid": p["id"]}
    q["answer"] = key.lower() if p["type"] == "mcq" else [x.lower() for x in key] if p["type"] == "msq" else key
    return q


def pyq_pick(subject, marks, used, typ=None):
    pool = [p for p in PYQ if p["subject"] == subject and p["id"] not in used]
    for f in (lambda p: p["marks"] == marks and (not typ or p["type"] == typ), lambda p: p["marks"] == marks, lambda p: True):
        c = [p for p in pool if f(p)]
        if c: return random.choice(c)
    c = [p for p in PYQ if p["subject"] == subject]                    # all used once: allow repeats
    return random.choice(c) if c else None


def fill_slot(i, slot, bank, used_pids, prefer="code"):
    """Deterministic fallback chain: code family -> real PYQ -> code from a neighbouring subject. Never leaves a slot empty."""
    subj, marks = slot["subject"], slot["marks"]
    order = ["code", "pyq"] if prefer == "code" else ["pyq", "code"]
    for how in order:
        if how == "code":
            q = generators.make(subj, marks)
            if q: bank[str(i)] = q; return "code"
        else:
            p = pyq_pick(subj, marks, used_pids)
            if p: used_pids.add(p["id"]); q = pyq_q(p); slot["marks"] = q["marks"]; bank[str(i)] = q; return "pyq"
    q = generators.make("pds", marks) or generators.make("algo", marks)   # last resort (e.g. no PYQ bank installed for a subject)
    q.update(subject=subj); bank[str(i)] = q; return "code"


# ── prompt (real PYQs of the subject are the style reference) ─────────────────
def refs(subject, k=3):
    pool = [p for p in PYQ if p["subject"] == subject and len(p["text"]) > 80]
    return "\n".join("  * " + re.sub(r"^Q\.\s*\d+\s*", "", p["text"])[:330] for p in random.sample(pool, min(k, len(pool)))) or "  (none available)"


FEATURES = {"pds": [("a C code snippet in `code`", .5)], "algo": [("a C-like code snippet in `code`", .2), ("a graph in figure_json (weighted or unweighted)", .2)],
            "toc": [("an automaton or a grammar (figure_json kind=graph directed=true with start/accept, or a grammar in the question)", .25)], "os": [("a data table in `context`", .3), ("a code snippet in `code`", .15)],
            "coa": [("a data table in `context`", .2)], "db": [("a data table in `context` (relation instance)", .5)], "cn": [("a data table in `context`", .15)], "math": [("a data table in `context`", .1)],
            "cd": [("a grammar or code in `code`", .4), ("a data table in `context`", .2)], "dl": [("a small data table in `context`", .2)], "ga": [("a bar-chart in figure_json kind=bar", .1)]}


def spec_for(slot, topic):
    feats = FEATURES.get(slot["subject"], []); f = "plain text"
    r = random.random(); acc = 0
    for name, w in feats:
        acc += w
        if r < acc: f = name; break
    return f"subject: {SUBJ[slot['subject']]['name']} | type={slot['type']} ({slot['marks']} mark) | topic: {topic} | features: {f}"


def build_prompt(subjects):
    blocks = "\n".join(f"- {SUBJ[k]['name']}. Topics: {'; '.join(SUBJ[k]['topics'])}\n  Real past questions of this subject (style / difficulty reference ONLY, never copy):\n{refs(k, 2)}" for k in subjects)
    return f"""You are a senior paper-setter for GATE Computer Science & Information Technology (organised by an IIT).
LEVEL: recent GATE papers (moderately hard; 2-mark questions need multi-step reasoning). Each numbered line below names its own subject, type, marks and topic.

SUBJECTS IN THIS BATCH
{blocks}

RULES
1. Output JSON matching the schema. `type`: mcq = 4 options (exactly one correct), msq = 4 options (one or more correct), nat = numerical answer, no options.
2. Options are plain strings without 'A.'/'(a)' labels. `answer`: mcq 'b'; msq 'a,c'; nat a plain number (`tol` = allowed absolute error, 0 for integers; for decimals answers are rounded as the question says).
3. Write `explanation` (max 40 words of real working) FIRST, then `answer`; compute every number carefully — the key must equal the computed value.
4. Self-contained. A table goes in `context` (first row = headers, rows separated by newlines, cells by ' | '). Program text goes in `code` (C, compact, <= 15 lines, well-defined behaviour, prints deterministic output).
5. A figure goes in `figure_json` as a JSON *string*: graph {{"kind":"graph","directed":false,"nodes":["A","B"],"edges":[["A","B","4"]]}} (automata: directed=true, edge labels = symbols, optional "start":"q0","accept":["q2"]);
   tree {{"kind":"tree","root":{{"v":"8","l":{{"v":"3","l":null,"r":null}},"r":null}}}}; bar {{"kind":"bar","labels":["2019"],"values":[40],"ylabel":"units"}}; gantt {{"kind":"gantt","segments":[["P1",0,4]]}}. Use "" when there is no figure.
   Never mention a figure/table/program that you did not supply.
6. No 'all of the above'/'none'. MSQ options must each be independently true or false. Keep questions exam-like and unambiguous. `subtopic` = 2-4 word label."""


def pick_topic(subject, recent):
    t = [x for x in SUBJ[subject]["topics"] if x not in recent[-10:]] or SUBJ[subject]["topics"]
    return random.choice(t)


# ── routes ──────────────────────────────────────────────────────────────────
@app.route("/")
def index(): session.clear(); return render_template("index.html")


@app.route("/pyq/<path:p>")
def pyq_img(p): return send_from_directory(os.path.join(BASE, "data", "pyq"), p, max_age=86400)


@app.route("/config")
def get_config():
    subs = [{"key": k, "name": SUBJ[k]["name"], "n1": SUBJ[k]["n1"], "n2": SUBJ[k]["n2"], "marks": SUBJ[k]["n1"] + 2 * SUBJ[k]["n2"],
             "pyq": sum(1 for p in PYQ if p["subject"] == k), "code": len(generators.FAMILIES.get(k, []))} for k in ORDER]
    return jsonify({"subjects": subs, "counts": COUNTS, "ai_ready": ai_ready(), "model": GEMINI_MODEL, "batch": BATCH_SIZE,
                    "budget": {"used": BUDGET.used(), "cap": BUDGET.daily, "rpm": BUDGET.rpm},
                    "papers": [{"id": p, "label": paper_label(p), "n": sum(1 for q in PYQ if q["paper"] == p)} for p in PAPERS], "pyq_total": len(PYQ),
                    "paper": SY["paper"]})


@app.route("/start", methods=["POST"])
def start_exam():
    d = request.json or {}; mode = d.get("mode", "section"); keys = [k for k in d.get("subjects") or [] if k in SUBJ]
    n = int(d.get("count") or 10); paper = d.get("paper") or ""
    session.clear(); bank, used_pids = {}, set(); ai = ai_ready()
    if mode == "pyq":
        if not PYQ: return jsonify({"status": "error", "error": "No PYQ bank installed (run tools/ingest_pyq.py, build_keys.py, classify.py)."}), 400
        if paper:
            qs = sorted([p for p in PYQ if p["paper"] == paper], key=lambda p: p["n"]); slots = [{"subject": p["subject"], "marks": p["marks"]} for p in qs]
            for i, p in enumerate(qs): bank[str(i)] = pyq_q(p)
            label, full = paper_label(paper), True
        else:
            if not keys: return jsonify({"status": "error", "error": "Pick at least one subject."}), 400
            slots = slots_subjects(keys, n); label, full = "PYQ · by subject", False
            for i, s in enumerate(slots):
                p = pyq_pick(s["subject"], s["marks"], used_pids)
                if p: used_pids.add(p["id"]); bank[str(i)] = pyq_q(p); s["marks"] = bank[str(i)]["marks"]
            slots = [s for i, s in enumerate(slots) if str(i) in bank]; bank = {str(i): bank[k] for i, k in enumerate(sorted(bank, key=int))}
            if not slots: return jsonify({"status": "error", "error": "No PYQs for that selection."}), 400
    else:
        if mode == "full": slots, label, full = slots_full(), "Full Mock", True
        else:
            if not keys: return jsonify({"status": "error", "error": "Pick at least one subject."}), 400
            slots, label, full = slots_subjects(keys, n), "Subject Mock", False
        for s in slots: s["type"] = pick_type(s["subject"], s["marks"])
        allow = MAX_LLM_Q if ai else 0
        for i in random.sample(range(len(slots)), len(slots)):           # random order so the AI cap is spread over subjects
            s = slots[i]
            if generators.FAMILIES.get(s["subject"]) and (not ai or random.random() < (CODE_SHARE if s["subject"] != "ga" else .5)): fill_slot(i, s, bank, used_pids, "code" if (ai or random.random() > .4) else "pyq")
            elif allow > 0: allow -= 1                                    # left pending -> written by Gemini in /generate-next
            else: fill_slot(i, s, bank, used_pids, "pyq" if random.random() < .5 else "code")   # no API: mix real PYQs (more MCQ/MSQ) with code families
    tm = sum(s["marks"] for s in slots)
    t = 180 * 60 if (full and len(slots) == 65) else max(300, round(tm * MIN_PER_MARK * 60))
    plan = {"mode": mode, "label": label, "slots": slots, "time_sec": t, "full": full, "total": len(slots)}
    session.update(plan=plan, bank=bank, used_pids=list(used_pids), used_texts=[], submitted=False, ai_calls=0)
    pending = len(slots) - len(bank)
    return jsonify({"status": "ok", "plan": {k: plan[k] for k in ("mode", "label", "time_sec", "total")}, "pending": pending})


@app.route("/generate-next", methods=["POST"])
def generate_next():
    """Write the next batch (<= BATCH_SIZE, one subject). Always fills every slot it touched: shortfalls fall back to code / real PYQs."""
    plan, bank = session.get("plan"), session.get("bank", {})
    if not plan or plan["mode"] == "pyq": return jsonify({"error": "No generation session active"}), 400
    pend = [i for i in range(plan["total"]) if str(i) not in bank]
    if not pend: return jsonify({"done": True, "generated": plan["total"], "total": plan["total"]})
    slots = plan["slots"]; so = {k: n for n, k in enumerate(ORDER)}
    pend.sort(key=lambda i: (so[slots[i]["subject"]], i)); grp = pend[:BATCH_SIZE]          # subject-sorted, but batches are always filled to BATCH_SIZE (fewest calls)
    used_texts, used_pids, topics = session.get("used_texts", []), set(session.get("used_pids", [])), session.get("topics", [])
    tops = []
    for i in grp: tp = pick_topic(slots[i]["subject"], topics); topics.append(tp); tops.append(tp)
    specs = [spec_for(slots[i], tp) for i, tp in zip(grp, tops)]; subjects = list(dict.fromkeys(slots[i]["subject"] for i in grp))
    res = generate_batch(build_prompt(subjects), specs, len(grp), used_texts)
    got = res["questions"]; ai_n = 0
    for i, q in zip(grp, got):
        q.update(subject=slots[i]["subject"], marks=slots[i]["marks"], src="ai"); bank[str(i)] = q; used_texts.append(q["question"]); ai_n += 1
    for i in grp[len(got):]: fill_slot(i, slots[i], bank, used_pids, "code")
    session.update(bank=bank, plan=plan, topics=topics[-30:], used_texts=used_texts[-200:], used_pids=list(used_pids), ai_calls=session.get("ai_calls", 0) + res["calls"])
    left = plan["total"] - len(bank)
    return jsonify({"done": left == 0, "generated": len(bank), "total": plan["total"], "ai": ai_n, "fallback": len(grp) - ai_n,
                    "calls": res["calls"], "note": res["reason"] if len(got) < len(grp) else "", "budget_used": BUDGET.used()})


def _pub(q, i):
    fig = q.get("figure"); fig = None if (fig and fig.get("hidden")) else fig
    src = q.get("label") or {"ai": "AI-generated", "code": "Code-verified"}.get(q["src"], "")
    return {"id": str(i), "q_num": i + 1, "type": q["type"], "marks": q["marks"], "subject": q["subject"], "question": q.get("question", ""), "context": q.get("context", ""),
            "code": q.get("code", ""), "figure": fig, "options": q.get("options", {}), "img": q.get("img", ""), "src": q["src"], "label": src}


@app.route("/questions")
def get_questions():
    plan, bank = session.get("plan"), session.get("bank", {})
    if not plan: return jsonify({"error": "no session"}), 400
    qs = [_pub(bank[str(i)], i) for i in range(plan["total"]) if str(i) in bank]
    key = (lambda q: "ga" if q["subject"] == "ga" else "cs") if plan["full"] else (lambda q: q["subject"])
    nm = {"ga": "General Aptitude", "cs": "Computer Science & IT", **{k: v["name"] for k, v in SUBJ.items()}}
    subs, s0 = [], 0
    for i in range(1, len(qs) + 1):
        if i == len(qs) or key(qs[i]) != key(qs[s0]): subs.append({"name": nm[key(qs[s0])], "start": s0, "end": i}); s0 = i
    return jsonify({"label": plan["label"], "mode": plan["mode"], "time_sec": plan["time_sec"], "total": len(qs), "subjects": subs, "questions": qs,
                    "max_marks": sum(q["marks"] for q in qs)})


def grade(q, u):
    """-> (is_correct | None if unattempted, score)"""
    m, t = q["marks"], q["type"]
    if t == "mcq":
        if not u: return None, 0.0
        return (True, float(m)) if u == q["answer"] else (False, -m / 3.0)
    if t == "msq":
        if not u: return None, 0.0
        return (True, float(m)) if sorted(u) == sorted(q["answer"]) else (False, 0.0)
    try: v = float(str(u).replace(",", "").strip())
    except Exception: return None, 0.0
    lo, hi = q["answer"]; ok = lo - 1e-9 <= v <= hi + 1e-9
    return (True, float(m)) if ok else (False, 0.0)


def show_key(q):
    if q["type"] == "nat":
        lo, hi = q["answer"]; f = lambda x: str(int(x)) if float(x).is_integer() else str(x)
        return f(lo) if lo == hi else f"{f(lo)} to {f(hi)}"
    return ", ".join(x.upper() for x in ([q["answer"]] if q["type"] == "mcq" else q["answer"]))


@app.route("/submit", methods=["POST"])
def submit():
    if session.get("submitted"): return jsonify({"error": "Already submitted"}), 400
    d = request.json or {}; answers, tt = d.get("answers", {}), d.get("time_taken_sec", 0)
    plan, bank = session.get("plan"), session.get("bank", {}); per, items, tot = {}, [], 0.0
    for i in range(plan["total"]):
        q = bank.get(str(i))
        if not q: continue
        u = answers.get(str(i)); u = u if u not in ("", [], None) else None
        ok, sc = grade(q, u); ss = per.setdefault(q["subject"], {"key": q["subject"], "section": SUBJ[q["subject"]]["name"], "total": 0, "attempted": 0, "correct": 0, "wrong": 0, "score": 0.0, "max": 0})
        ss["total"] += 1; ss["max"] += q["marks"]; ss["score"] += sc
        if u is not None: ss["attempted"] += 1
        if ok is True: ss["correct"] += 1
        elif ok is False: ss["wrong"] += 1
        tot += q["marks"]
        items.append({"q_num": i + 1, "type": q["type"], "marks": q["marks"], "subject": SUBJ[q["subject"]]["name"], "question": q.get("question", ""), "context": q.get("context", ""), "code": q.get("code", ""),
                      "figure": q.get("figure"), "options": q.get("options", {}), "img": q.get("img", ""), "key": show_key(q), "user": ("" if u is None else (", ".join(x.upper() for x in u) if isinstance(u, list) else (u.upper() if q["type"] == "mcq" else str(u)))),
                      "is_correct": ok, "score": round(sc, 2), "explanation": q.get("explanation", ""), "src": q["src"], "label": q.get("label", "")})
    summ = []
    for s in per.values():
        s["score"] = round(s["score"], 2); s["accuracy"] = round(s["correct"] / s["attempted"] * 100, 1) if s["attempted"] else 0.0; summ.append(s)
    score = round(sum(s["score"] for s in summ), 2); pct = round(score / tot * 100, 1) if tot else 0.0
    corr, wr, att = sum(s["correct"] for s in summ), sum(s["wrong"] for s in summ), sum(s["attempted"] for s in summ)
    src = {k: sum(1 for b in bank.values() if b["src"] == k) for k in ("ai", "code", "pyq")}
    res = {"label": plan["label"], "score": score, "total_marks": tot, "percent": pct, "correct": corr, "wrong": wr, "attempted": att, "unattempted": len(items) - att,
           "accuracy": round(corr / att * 100, 1) if att else 0.0, "time_taken_sec": tt, "section_summary": summ, "sources": src,
           "weak": [s["section"] for s in sorted(summ, key=lambda x: x["accuracy"]) if s["attempted"] and s["accuracy"] < 50][:3],
           "grade": "Excellent — qualifying-cutoff territory 🏆" if pct >= 60 else "Good — keep polishing weak subjects 📚" if pct >= 40 else "Average — revise the basics, then retry ⚠️" if pct >= 25 else "Needs work — go subject by subject first 📖", "review": items}
    session["result"], session["submitted"] = res, True
    return jsonify(res)


@app.route("/result")
def get_result():
    r = session.get("result"); return (jsonify(r), 200) if r else (jsonify({"error": "No result yet"}), 404)


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
