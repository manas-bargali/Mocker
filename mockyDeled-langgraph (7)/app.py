"""
mockyDElEd — Uttarakhand D.El.Ed. Entrance Exam Mock Test Platform
====================================================================
Modes
-----
1. PYQ Practice   – take REAL previous-year questions (OCR-digitised from the
                    official 2022 & 2023 Uttarakhand D.El.Ed. papers you
                    supplied), section-wise or mixed. No answer key was
                    printed in the source booklets, so Gemini is asked to
                    solve the paper once per session and that answer key is
                    cached — clearly marked as AI-solved, not official.
2. Section Practice – pick 1+ sections, choose question count (10/20/30/50).
                    Fresh MCQs generated every session via the Gemini API,
                    seeded with real PYQ patterns + the official syllabus.
3. Full Mock       – complete paper simulation of the official pattern:
                    4 sections x 50 Q = 200 Q, 200 marks, 150 minutes,
                    no negative marking. Mixes PYQ-style questions with
                    Gemini's knowledge of 2026 current affairs / GK.

Uses Google's Gemini API (free tier) via the `google-genai` SDK.
Default model is the auto-updating "gemini-flash-latest" alias so the app
keeps working as Google retires dated model versions — override with the
GEMINI_MODEL env var if you want to pin a specific version.
"""

from flask import Flask, render_template, request, jsonify, session
from flask_session import Session
from google import genai
from google.genai import types
from graph_engine import generate_unique_question
import json, os, uuid, re, random

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "mockyDeled_ubse_secret")

_SESSION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".flask_session")
os.makedirs(_SESSION_DIR, exist_ok=True)
app.config["SESSION_TYPE"]      = "filesystem"
app.config["SESSION_FILE_DIR"]  = _SESSION_DIR
app.config["SESSION_PERMANENT"] = False
Session(app)

# ── Data: syllabus/pattern seed + real PYQ bank ──────────────────────────────
with open("data/deled_patterns.json") as f:
    PATTERNS = json.load(f)

with open("data/pyq_bank.json") as f:
    PYQ_BANK = json.load(f)

SECTIONS = list(PATTERNS["sections"].keys())
PYQ_YEARS = sorted(set(q["source_year"] for q in PYQ_BANK))

# ── Gemini client (free tier) ────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
# Auto-updating alias — always resolves to Google's current recommended Flash
# model, so this app doesn't break when a dated version is retired.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")

# ── Official UBSE D.El.Ed pattern constants ──────────────────────────────────
# 200 Q / 200 marks / 150 minutes / no negative marking (verified against the
# official pattern — see README). That's 45 sec/question at full-mock pace.
FULL_MOCK_TOTAL_Q     = 200
FULL_MOCK_TIME_SEC    = 150 * 60
SEC_PER_Q_EXAM_PACE   = 45
QUESTION_COUNT_CHOICES = [10, 20, 30, 50]
QUESTIONS_PER_SECTION_FULL = 50


def _timed(count: int, pace: int = SEC_PER_Q_EXAM_PACE) -> int:
    return max(count * pace, 60)


# ── Gemini call helper ────────────────────────────────────────────────────────
def _call_gemini(system: str, user_msg: str, max_tokens: int = 700, temperature: float = 0.85) -> str:
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is not set on the server")
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=user_msg,
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return (response.text or "").strip()


# ── Prompt builders ───────────────────────────────────────────────────────────
def build_section_prompt(section: str) -> str:
    sec = PATTERNS["sections"].get(section, {})
    qtypes = sec.get("question_types", [])
    pyqs   = sec.get("pyq_examples", [])

    types_text = "\n".join(
        f"  - {qt['type']}: e.g. {qt['example']}\n    Options style: {qt['options_style']}"
        for qt in qtypes
    )
    pyq_text = "\n".join(f"  * {p}" for p in pyqs[:8])

    return f"""You are an item-writer for the Uttarakhand D.El.Ed. (Diploma in Elementary
Education) Entrance Examination, conducted by UBSE. You have studied the
official exam pattern, its syllabus, and real previous-year question (PYQ)
papers. Today's date is in 2026, so for any current-affairs or "who is the
current ___" style question, use up-to-date 2026 facts.

SECTION: {section}
DESCRIPTION: {sec.get('description', '')}
TOPICS: {', '.join(sec.get('topics', []))}

REAL QUESTION TYPES SEEN IN THIS SECTION:
{types_text}

REAL PYQ EXAMPLES (for style/difficulty reference only — do NOT repeat them
verbatim, write a fresh question):
{pyq_text}

STRICT RULES:
1. Generate EXACTLY ONE question at a time, in English only.
2. Provide EXACTLY 4 options labeled (a) through (d).
3. Mark the correct answer as "ANSWER: (x)" on the LAST line — no explanation.
4. Match UBSE D.El.Ed entrance difficulty (Class 10-12 general level) — not
   too easy, not too hard.
5. Vary sub-type — do NOT repeat the same sub-type as the previous question.
6. Question must be fully self-contained as plain text (no images/figures;
   for reasoning, only use puzzle types that work purely in words).
7. No negative marking in the real exam, so plausible distractors are fine.
8. NO explanation, NO preamble. ONLY: Question + 4 options + ANSWER line.

FORMAT (follow EXACTLY):
Q. [Question text here]
(a) Option A
(b) Option B
(c) Option C
(d) Option D
ANSWER: (b)"""


def build_full_mock_prompt(q_num: int, section: str) -> str:
    sec = PATTERNS["sections"].get(section, {})
    pyqs = sec.get("pyq_examples", [])[:6]
    pyq_text = "\n".join(f"  * {p}" for p in pyqs)

    return f"""You are an item-writer for the Uttarakhand D.El.Ed. Entrance Examination
(UBSE), building question #{q_num} of a full 200-question mock paper that
follows the official pattern exactly: 4 sections x 50 marks, no negative
marking, English medium. Today's date is in 2026 — use up-to-date facts for
any current-affairs question.

SECTION FOR THIS QUESTION: {section}
TOPICS: {', '.join(sec.get('topics', []))}

REAL PYQ EXAMPLES FROM THIS SECTION (style reference only, do not repeat):
{pyq_text}

STRICT RULES:
1. EXACTLY ONE question, EXACTLY 4 options (a)-(d), English only.
2. ANSWER: (x) on the last line. No explanation.
3. Self-contained plain text (no images/figures needed to answer).
4. UBSE D.El.Ed entrance difficulty level.

FORMAT:
Q. [question]
(a) Option A
(b) Option B
(c) Option C
(d) Option D
ANSWER: (b)"""


def build_solve_prompt(items: list) -> str:
    """Ask Gemini to solve a batch of real (answer-less) PYQ questions."""
    lines = []
    for it in items:
        opts = it["options"]
        lines.append(
            f'{{"id": "{it["id"]}", "question": {json.dumps(it["question"])}, '
            f'"options": {{"a": {json.dumps(opts.get("A",""))}, "b": {json.dumps(opts.get("B",""))}, '
            f'"c": {json.dumps(opts.get("C",""))}, "d": {json.dumps(opts.get("D",""))}}}}}'
        )
    payload = "[\n" + ",\n".join(lines) + "\n]"
    return f"""You are an expert exam-solver. Below is a JSON array of real
multiple-choice questions from an Indian teacher-training entrance exam
(Uttarakhand D.El.Ed). These were digitised from scanned paper booklets via
OCR, so a few option strings may contain minor typos — infer the intended
meaning where needed.

For EACH question, determine the single best answer.

QUESTIONS:
{payload}

Respond with ONLY a JSON array, no markdown fences, no commentary, in this
exact shape:
[{{"id": "<same id>", "answer": "a"}}, ...]
The "answer" field must be one of "a", "b", "c", "d"."""


# ── Question parser (for Gemini-generated questions) ─────────────────────────
# NOTE: no longer called by /generate-next (graph_engine.py now uses Gemini's
# JSON mode + response_schema instead of parsing free-text). Left in place,
# unused, in case anything else in a future branch still wants it.
def parse_question(raw: str):
    lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
    question_lines, options, answer = [], {}, ""
    for line in lines:
        if line.upper().startswith("ANSWER:"):
            answer = line.split(":", 1)[1].strip()
        elif re.match(r"^\(([abcdABCD])\)", line):
            key = line[1].lower()
            val = line[4:].strip()
            options[key] = val
        else:
            question_lines.append(line)

    question_text = " ".join(question_lines).lstrip("Q. ").strip()
    return {
        "question": question_text,
        "options":  options,
        "answer":   re.sub(r"[^abcd]", "", answer.lower())[:1],
    }


def _pyq_options_lower(options: dict) -> dict:
    """Real bank stores options as A/B/C/D — normalise to a/b/c/d for the UI."""
    return {k.lower(): v for k, v in options.items()}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    session.clear()
    return render_template("index.html")


@app.route("/config")
def get_config():
    pyq_counts = {}
    for year in PYQ_YEARS:
        pyq_counts[year] = len([q for q in PYQ_BANK if q["source_year"] == year])
    pyq_counts["mixed"] = len(PYQ_BANK)

    return jsonify({
        "sections":        SECTIONS,
        "question_counts": QUESTION_COUNT_CHOICES,
        "gemini_configured": client is not None,
        "gemini_model":    GEMINI_MODEL,
        "full_mock": {
            "total_marks": FULL_MOCK_TOTAL_Q,
            "total_questions": FULL_MOCK_TOTAL_Q,
            "time_sec":    FULL_MOCK_TIME_SEC,
            "description": "4 sections x 50 Q each — official UBSE D.El.Ed pattern, 150 minutes, no negative marking",
        },
        "pyq": {
            "years": PYQ_YEARS,
            "counts": pyq_counts,
            "sec_per_q": SEC_PER_Q_EXAM_PACE,
        },
    })


@app.route("/start", methods=["POST"])
def start_exam():
    data = request.json or {}
    mode = data.get("mode", "section")

    session.clear()
    session["mode"]      = mode
    session["bank"]      = {}
    session["queue"]     = []
    session["history"]   = []
    session["submitted"] = False
    session["pyq_solved"] = False
    session["used_texts"] = []       # question texts served this session (dedup memory)
    session["used_subtopics"] = []   # subtopics served this session (variety hint)

    if mode == "full":
        plan = {
            "mode":     "full",
            "time_sec": FULL_MOCK_TIME_SEC,
            "count":    FULL_MOCK_TOTAL_Q,
        }

    elif mode == "pyq":
        year = data.get("year", "mixed")
        sections = data.get("sections") or SECTIONS
        pool = [q for q in PYQ_BANK if (year == "mixed" or q["source_year"] == year)
                and q["section"] in sections]
        random.shuffle(pool)
        requested = int(data.get("count", len(pool)))
        pool = pool[:max(1, min(requested, len(pool)))]

        bank = {}
        queue = []
        for q in pool:
            qid = uuid.uuid4().hex[:8]
            bank[qid] = {
                "question": q["question"],
                "options":  _pyq_options_lower(q["options"]),
                "answer":   "",          # unknown until Gemini solves it
                "marks":    1,
                "type":     "objective",
                "section":  q["section"],
                "pyq_id":   q["id"],
                "source_year": q["source_year"],
            }
            queue.append(qid)
        session["bank"]  = bank
        session["queue"] = queue

        plan = {
            "mode":     "pyq",
            "year":     year,
            "time_sec": _timed(len(queue)),
            "count":    len(queue),
        }

    else:  # section practice
        sections = data.get("sections") or [SECTIONS[0]]
        count    = int(data.get("count", 20))
        if count not in QUESTION_COUNT_CHOICES:
            count = 20
        plan = {
            "mode":     "section",
            "sections": sections,
            "count":    count,
            "time_sec": _timed(count),
        }

    session["plan"] = plan
    return jsonify({"status": "ok", "plan": plan})


def _get_full_mock_section(idx: int) -> str:
    """200 Qs = 50 per section, in official order."""
    return SECTIONS[idx // QUESTIONS_PER_SECTION_FULL]


@app.route("/generate-next", methods=["POST"])
def generate_next():
    """Generate ONE more AI question. Called in a loop by the frontend.
    (PYQ mode doesn't need this — its questions are already real; see
    /pyq-solve for its one-shot answer-key step.)"""
    plan  = session.get("plan")
    queue = session.get("queue", [])
    bank  = session.get("bank", {})

    if not plan:
        return jsonify({"error": "No active session"}), 400

    mode = plan.get("mode", "section")

    if mode == "full":
        target = plan["count"]
        if len(queue) >= target:
            return jsonify({"done": True, "generated": len(queue), "total": target})
        idx = len(queue)
        section = _get_full_mock_section(idx)
        system = build_full_mock_prompt(idx + 1, section)
        user_msg = f"Generate question #{idx + 1} for section '{section}' of the D.El.Ed full mock."
    elif mode == "section":
        target   = plan["count"]
        sections = plan.get("sections", [SECTIONS[0]])
        if len(queue) >= target:
            return jsonify({"done": True, "generated": len(queue), "total": target})
        section = sections[len(queue) % len(sections)]
        system = build_section_prompt(section)
        user_msg = f"Generate 1 fresh question for the '{section}' section."
    else:
        return jsonify({"error": f"Unsupported mode for generation: {mode}"}), 400

    history   = session.get("history", [])
    used_texts     = session.get("used_texts", [])
    used_subtopics = session.get("used_subtopics", [])

    try:
        # `system` here is the exact same prompt build_section_prompt()/
        # build_full_mock_prompt() always produced — unchanged. Only the
        # call-and-parse step is now routed through the LangGraph engine,
        # which enforces JSON schema validity AND rejects near-duplicates
        # of every question already served this session (not just the
        # last 2 section names, which is all the old code tracked).
        result = generate_unique_question(section, system, used_texts, used_subtopics)

        if result["status"] != "ok":
            reason = result.get("reject_reason") or "unknown error"
            return jsonify({
                "error": f"Gemini is temporarily unavailable ({reason}). "
                         "This is usually a transient issue on Google's side — "
                         "please try again in a moment.",
            }), 503

        q = result["question"]
        qid = uuid.uuid4().hex[:8]
        bank[qid] = {
            "question": q["question"],
            "options":  q["options"],
            "answer":   q["answer"],
            "marks":    1,
            "type":     "objective",
            "section":  section,
        }
        session["bank"] = bank
        queue.append(qid)
        session["queue"] = queue

        used_texts.append(q["question"])
        session["used_texts"] = used_texts[-210:]   # cap: full mock is 200 Q max
        used_subtopics.append(q.get("subtopic") or section)
        session["used_subtopics"] = used_subtopics[-10:]

        history.append(section)
        session["history"] = history[-8:]

        total_target = plan["count"]
        done_now = len(queue) >= total_target
        return jsonify({"done": done_now, "generated": len(queue), "total": total_target})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/pyq-solve", methods=["POST"])
def pyq_solve():
    """One-shot: ask Gemini to solve every question in a PYQ-mode paper and
    cache the answer key server-side. Called once by the frontend before the
    exam screen shows. Gracefully degrades if no API key is configured —
    the paper is still fully playable, just self-review at the end instead
    of auto-graded."""
    plan  = session.get("plan", {})
    queue = session.get("queue", [])
    bank  = session.get("bank", {})

    if plan.get("mode") != "pyq":
        return jsonify({"error": "Not a PYQ session"}), 400

    if session.get("pyq_solved"):
        return jsonify({"status": "already_solved"})

    if client is None:
        session["pyq_solved"] = True  # nothing more we can do without a key
        return jsonify({"status": "no_api_key", "note": "Gemini API key not configured — answers will be shown for self-review without auto-grading."})

    items = [{"id": qid, "question": bank[qid]["question"], "options": {k.upper(): v for k, v in bank[qid]["options"].items()}}
             for qid in queue]

    BATCH = 20
    solved = 0
    try:
        for i in range(0, len(items), BATCH):
            chunk = items[i:i + BATCH]
            prompt = build_solve_prompt(chunk)
            raw = _call_gemini(
                "You are a meticulous exam-solving assistant. Reply with ONLY valid JSON, nothing else.",
                prompt, max_tokens=BATCH * 20 + 200, temperature=0.1,
            )
            raw_clean = re.sub(r"^```(json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
            parsed = json.loads(raw_clean)
            for item in parsed:
                qid = item.get("id")
                ans = re.sub(r"[^abcd]", "", str(item.get("answer", "")).lower())[:1]
                if qid in bank and ans in "abcd":
                    bank[qid]["answer"] = ans
                    solved += 1
        session["bank"] = bank
        session["pyq_solved"] = True
        return jsonify({"status": "solved", "solved": solved, "total": len(items)})
    except Exception as e:
        session["pyq_solved"] = True
        return jsonify({"status": "solve_failed", "error": str(e),
                         "note": "Could not build an AI answer key — the paper is still playable for self-review."})


@app.route("/questions")
def get_questions():
    queue = session.get("queue", [])
    bank  = session.get("bank", {})
    plan  = session.get("plan", {})

    questions = []
    for i, qid in enumerate(queue):
        b = bank[qid]
        questions.append({
            "id":       qid,
            "q_num":    i + 1,
            "question": b["question"],
            "options":  b["options"],
            "marks":    b["marks"],
            "section":  b.get("section", "General"),
            "source_year": b.get("source_year"),
        })

    return jsonify({
        "mode":      plan.get("mode"),
        "total":     len(queue),
        "time_sec":  plan.get("time_sec", FULL_MOCK_TIME_SEC),
        "questions": questions,
    })


@app.route("/submit", methods=["POST"])
def submit():
    if session.get("submitted"):
        return jsonify({"error": "Already submitted"}), 400

    data       = request.json or {}
    answers    = data.get("answers", {})
    time_taken = data.get("time_taken_sec", 0)

    queue = session.get("queue", [])
    bank  = session.get("bank", {})
    plan  = session.get("plan", {})

    total_marks, scored_marks, attempted = 0, 0, 0
    section_stats = {}
    items = []
    ungraded = 0

    for i, qid in enumerate(queue):
        b = bank[qid]
        raw_user = answers.get(qid, "")
        marks_avail = b["marks"]

        correct_ans = (b.get("answer") or "").lower().strip("() ")[:1]
        user_ans = (raw_user or "").lower().strip("() ")[:1]

        if not correct_ans:
            is_correct = None   # no answer key available (ungraded PYQ item)
            marks_got  = 0
            ungraded  += 1
        else:
            is_correct = bool(user_ans) and user_ans == correct_ans
            marks_got  = marks_avail if is_correct else 0

        if raw_user:
            attempted += 1
        total_marks  += marks_avail
        scored_marks += marks_got

        sec = b.get("section", "General")
        cs = section_stats.setdefault(sec, {"correct": 0, "attempted": 0, "total": 0, "marks": 0})
        cs["total"] += 1
        cs["marks"] += marks_avail
        if raw_user:
            cs["attempted"] += 1
        if is_correct:
            cs["correct"] += 1

        items.append({
            "qid": qid, "q_num": i + 1, "question": b["question"], "options": b["options"],
            "answer": correct_ans, "user_ans": user_ans, "is_correct": is_correct,
            "marks_avail": marks_avail, "marks_got": marks_got, "section": sec,
            "source_year": b.get("source_year"),
        })

    gradable = max(len(queue) - ungraded, 0)
    graded_correct = sum(1 for it in items if it["is_correct"])
    pct = round((graded_correct / max(gradable, 1)) * 100, 1) if gradable else 0.0

    section_summary = []
    for sec, cs in section_stats.items():
        acc = round((cs["correct"] / cs["attempted"] * 100) if cs["attempted"] else 0, 1)
        section_summary.append({"section": sec, "accuracy": acc, **cs})
    section_summary.sort(key=lambda x: x["accuracy"])

    weak = [c["section"] for c in section_summary if c["attempted"] > 0 and c["accuracy"] < 60][:4]

    result = {
        "mode":            plan.get("mode"),
        "score":           scored_marks,
        "total_marks":     total_marks,
        "attempted":       attempted,
        "percent":         pct,
        "grade":           _grade(pct),
        "time_taken_sec":  time_taken,
        "section_summary": section_summary,
        "weak_sections":   weak,
        "review":          items,
        "ungraded_note": (
            f"{ungraded} question(s) had no confirmed answer key (Gemini could not solve them or no API key was set) "
            "and are excluded from scoring — review them yourself below."
        ) if ungraded else "",
    }

    session["result"]    = result
    session["submitted"] = True
    return jsonify(result)


@app.route("/result")
def get_result():
    result = session.get("result")
    if not result:
        return jsonify({"error": "No result yet"}), 404
    return jsonify(result)


def _grade(pct):
    if pct >= 90: return "Outstanding — Entrance Ready! 🏆"
    if pct >= 75: return "Very Good — Keep Practicing! 📚"
    if pct >= 60: return "Good — Revise Weak Sections 💡"
    if pct >= 40: return "Average — Need More Practice ⚠️"
    return "Below Average — Revise Basics First 📖"


if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
