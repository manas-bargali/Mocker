"""engine.py — LangGraph question engine for mockyGATE (Gemini JSON mode).
generate -> validate -> verify -> dedup -> collect  (retry only the shortfall)

What protects the paper from API limits (see README):
  * Budget       sliding-window RPM limiter + persisted daily cap (GEMINI_RPM, GEMINI_DAILY). Exhausted -> BudgetExhausted -> caller falls back to code / real PYQs.
  * BATCH_SIZE   4 questions per call (code / table / figure questions need ~600-900 output tokens each; 8 per call truncates the JSON).
  * MAX_ATTEMPTS 2 generate attempts per batch and CALL_CAP (default 8) hard cap on real API calls per batch, so a bad batch cannot burn dozens of requests.
  * VERIFY       one blind-solve call per batch; disputed answer keys are thrown away (NAT/MCQ/MSQ aware).
"""
from __future__ import annotations
import difflib, json, math, os, random, re, threading, time
from datetime import date
from typing import Optional, TypedDict

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from langgraph.graph import END, StateGraph

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest")
FALLBACK_MODEL = os.environ.get("GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest")
_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
MAX_ATTEMPTS = int(os.environ.get("MAX_ATTEMPTS", 2))
CALL_CAP = int(os.environ.get("CALL_CAP", 8))
VERIFY = os.environ.get("VERIFY", "1") != "0"
DUP = 0.85
_MODELS = list(dict.fromkeys([GEMINI_MODEL, FALLBACK_MODEL]))
_BASE = os.path.dirname(os.path.abspath(__file__))


class BudgetExhausted(Exception): pass


class Budget:
    """Sliding-window requests/minute + persisted per-day cap. Thread-safe."""
    def __init__(self):
        self.rpm = int(os.environ.get("GEMINI_RPM", 8)); self.daily = int(os.environ.get("GEMINI_DAILY", 400))
        self.path = os.path.join(_BASE, ".budget.json"); self.win, self.lock = [], threading.Lock()
    def _load(self):
        try:
            d = json.load(open(self.path))
            if d.get("date") == str(date.today()): return d
        except Exception: pass
        return {"date": str(date.today()), "used": 0}
    def used(self): return self._load()["used"]
    def left(self): return max(self.daily - self.used(), 0)
    def take(self):
        with self.lock:
            d = self._load()
            if d["used"] >= self.daily: raise BudgetExhausted("daily API budget reached")
            now = time.time(); self.win = [t for t in self.win if now - t < 60]
            if len(self.win) >= self.rpm:
                wait = 60 - (now - self.win[0]) + .2
                if wait > 25: raise BudgetExhausted("per-minute limit; wait and retry")
                time.sleep(wait)
            self.win.append(time.time()); d["used"] += 1
            try: json.dump(d, open(self.path, "w"))
            except Exception: pass
BUDGET = Budget()
_tl = threading.local()


def ai_ready() -> bool: return _client is not None and BUDGET.left() > 0


def _call(system: str, contents: str, cfg: dict):
    if getattr(_tl, "calls", 0) >= CALL_CAP: raise BudgetExhausted("per-batch call cap")
    last = None
    for model in _MODELS:
        for attempt in range(2):
            if getattr(_tl, "calls", 0) >= CALL_CAP: raise BudgetExhausted("per-batch call cap")
            BUDGET.take(); _tl.calls = getattr(_tl, "calls", 0) + 1
            try:
                return _client.models.generate_content(model=model, contents=contents, config=types.GenerateContentConfig(system_instruction=system, **cfg))
            except genai_errors.APIError as e:
                last = e; code = getattr(e, "code", None)
                if code in (401, 403): raise
                if code in (429, 500, 503, 504): time.sleep(min(6, 1.5 * 2 ** attempt) + random.random()); continue
                break
    raise last


# ── schemas (explanation BEFORE answer: the model works the problem first) ─────────────────
_QP = ["type", "question", "context", "code", "figure_json", "options", "explanation", "answer", "tol", "subtopic"]
_Q = {"type": "object", "properties": {"type": {"type": "string", "enum": ["mcq", "msq", "nat"]}, "question": {"type": "string"}, "context": {"type": "string"},
      "code": {"type": "string"}, "figure_json": {"type": "string"}, "options": {"type": "array", "items": {"type": "string"}},
      "explanation": {"type": "string"}, "answer": {"type": "string"}, "tol": {"type": "number"}, "subtopic": {"type": "string"}},
      "required": ["type", "question", "explanation", "answer", "subtopic"], "propertyOrdering": _QP}
_GEN = {"type": "object", "properties": {"questions": {"type": "array", "items": _Q}}, "required": ["questions"]}
_SOLVE = {"type": "object", "properties": {"solutions": {"type": "array", "items": {"type": "object", "properties": {
    "n": {"type": "integer"}, "working": {"type": "string"}, "answer": {"type": "string"}}, "required": ["n", "working", "answer"], "propertyOrdering": ["n", "working", "answer"]}}}, "required": ["solutions"]}


# ── figure validation ────────────────────────────────────────────────────────────────────
def _circle(nodes):
    return {n: [round(50 + 40 * math.cos(2 * math.pi * i / len(nodes) - 1.2), 1), round(50 + 40 * math.sin(2 * math.pi * i / len(nodes) - 1.2), 1)] for i, n in enumerate(nodes)}
def clean_figure(txt: str) -> Optional[dict]:
    if not txt or not txt.strip(): return None
    try: f = json.loads(txt)
    except Exception: return None
    k = f.get("kind")
    try:
        if k == "graph":
            nodes = [str(n) for n in f["nodes"]][:10]; edges = []
            for e in f["edges"][:24]:
                if str(e[0]) in nodes and str(e[1]) in nodes: edges.append([str(e[0]), str(e[1]), str(e[2]) if len(e) > 2 else ""])
            if len(nodes) < 2 or not edges: return None
            out = {"kind": "graph", "directed": bool(f.get("directed")), "nodes": nodes, "edges": edges, "pos": _circle(nodes)}
            if f.get("accept"): out["accept"] = [str(a) for a in f["accept"] if str(a) in nodes]
            if f.get("start") and str(f["start"]) in nodes: out["start"] = str(f["start"])
            return out
        if k == "tree":
            def walk(t, d=0):
                if not t or d > 5: return None
                return {"v": str(t["v"]), "l": walk(t.get("l"), d + 1), "r": walk(t.get("r"), d + 1)}
            r = walk(f["root"]); return {"kind": "tree", "root": r} if r else None
        if k == "bar":
            lab, val = [str(x) for x in f["labels"]][:12], [float(x) for x in f["values"]][:12]
            return {"kind": "bar", "labels": lab, "values": val, "ylabel": str(f.get("ylabel", ""))} if len(lab) == len(val) >= 2 else None
        if k == "gantt":
            seg = [[str(s[0]), float(s[1]), float(s[2])] for s in f["segments"][:30]]
            return {"kind": "gantt", "segments": seg} if seg else None
    except Exception: return None
    return None
_FIGREF = re.compile(r"\b(figure|diagram|chart|graph (?:shown|given|below)|shown below|shown in|table (?:below|given|shown))\b", re.I)


def _norm(t): return re.sub(r"[^a-z0-9 ]", "", (t or "").lower()).strip()
def _is_dup(k, used): k = _norm(k)[:200]; return any(difflib.SequenceMatcher(None, k, _norm(u)[:200]).ratio() >= DUP for u in used)
def _nat_close(a, b, tol): return abs(a - b) <= max(tol, 0.02 * abs(b), 0.011)


def solve_items(items: list) -> list:
    """Blind-solve. Returns raw answer strings ('' if none). Raises on API failure/budget."""
    blocks = []
    for i, q in enumerate(items, 1):
        parts = [f"[{i}] TYPE: {q['type'].upper()}"]
        if q.get("context"): parts.append("TABLE:\n" + q["context"])
        if q.get("code"): parts.append("CODE:\n" + q["code"])
        if q.get("figure"): parts.append("FIGURE (JSON spec): " + json.dumps(q["figure"])[:700])
        parts.append("QUESTION: " + q["question"])
        if q["type"] != "nat": parts += [f"({k}) {q['options'][k]}" for k in "abcd"]
        blocks.append("\n".join(parts))
    r = _call("You are a meticulous GATE Computer Science solver. Solve every question independently. MCQ: one option letter a-d. MSQ: all correct letters comma-separated (e.g. a,c). NAT: a single number. Give working in max 30 words.",
              "\n\n".join(blocks), dict(temperature=0.0, max_output_tokens=300 + 220 * len(items), response_mime_type="application/json", response_schema=_SOLVE))
    out = [""] * len(items)
    for s in json.loads(r.text).get("solutions", []):
        n = s.get("n")
        if isinstance(n, int) and 1 <= n <= len(items): out[n - 1] = str(s.get("answer", "")).strip().lower()
    return out
def _agree(q, got):
    if not got: return True                      # solver produced nothing -> do not punish the question
    if q["type"] == "mcq": return got[:1] == q["answer"]
    if q["type"] == "msq": return set(re.findall(r"[a-d]", got)) == set(q["answer"])
    try: return _nat_close(float(re.findall(r"-?\d+(?:\.\d+)?", got)[0]), sum(q["answer"]) / 2, q["answer"][1] - q["answer"][0])
    except Exception: return True


class S(TypedDict, total=False):
    prompt_base: str; specs: list; n: int; used: list; attempt: int; notes: list; fatal: bool; raw: Optional[dict]; cands: list; accepted: list; reason: str


def generate_node(s: S) -> S:
    att = s.get("attempt", 0) + 1; need = s["n"] - len(s.get("accepted", [])); done = len(s.get("accepted", []))
    lines = "\n".join(f"{i+1}. {s['specs'][(done+i) % len(s['specs'])]}" for i in range(need))
    task = f"Write exactly {need} DIFFERENT questions, one per line below, in this order:\n{lines}\nUse different numbers, names and scenarios in every question."
    if s.get("notes"): task += "\n\nProblems in the previous draft (avoid): " + "; ".join(s["notes"][-3:])
    try:
        r = _call(s["prompt_base"], task, dict(temperature=.8 if att == 1 else .95, max_output_tokens=min(900 + 620 * need, 6000), response_mime_type="application/json", response_schema=_GEN))
        return {**s, "attempt": att, "raw": json.loads(r.text), "fatal": False, "reason": ""}
    except BudgetExhausted as e: return {**s, "attempt": att, "raw": None, "fatal": True, "reason": str(e)}
    except genai_errors.APIError as e: return {**s, "attempt": att, "raw": None, "fatal": getattr(e, "code", 0) in (401, 403), "reason": f"API error {getattr(e, 'code', '')}"}
    except Exception: return {**s, "attempt": att, "raw": None, "fatal": False, "reason": "empty or non-JSON response (likely truncated)"}


def validate_node(s: S) -> S:
    if not s.get("raw"): return {**s, "cands": []}
    notes, cands = list(s.get("notes", [])), []
    for q in (s["raw"].get("questions") or [])[: s["n"]]:
        t, text, ans = q.get("type"), (q.get("question") or "").strip(), (q.get("answer") or "").strip().lower()
        opts = [str(o).strip() for o in (q.get("options") or [])]; fig = clean_figure(q.get("figure_json", "")); ctx = (q.get("context") or "").strip(); code = (q.get("code") or "").strip()
        if t not in ("mcq", "msq", "nat") or len(text) < 15: notes.append("bad type/short question"); continue
        if _FIGREF.search(text) and not (fig or ctx): notes.append("refers to a figure/table that was not supplied"); continue
        d = {"type": t, "question": text, "context": ctx, "code": code, "figure": fig, "options": {}, "explanation": (q.get("explanation") or "").strip(), "subtopic": (q.get("subtopic") or "").strip()}
        if t in ("mcq", "msq"):
            if len(opts) != 4 or len({o.lower() for o in opts}) < 4 or not all(opts): notes.append("options must be 4 distinct non-empty strings"); continue
            d["options"] = dict(zip("abcd", opts)); ks = sorted(set(re.findall(r"[a-d]", ans)))
            if t == "mcq" and len(ks) != 1: notes.append("mcq needs exactly one answer letter"); continue
            if t == "msq" and not (1 <= len(ks) <= 3): notes.append("msq needs 1-3 answer letters"); continue
            d["answer"] = ks[0] if t == "mcq" else ks
        else:
            try: v = float(re.findall(r"-?\d+(?:\.\d+)?", ans.replace(",", ""))[0])
            except Exception: notes.append("nat answer not numeric"); continue
            tol = abs(float(q.get("tol") or 0)); d["answer"] = [round(v - tol, 4), round(v + tol, 4)]
        cands.append(d)
    return {**s, "cands": cands, "notes": notes}


def verify_node(s: S) -> S:
    c = s.get("cands", [])
    if not (VERIFY and c) or BUDGET.left() < 5: return s
    try: got = solve_items(c)
    except Exception: return s                   # verifier unavailable -> keep unverified rather than fail the paper
    keep, notes = [], list(s.get("notes", []))
    for q, g in zip(c, got):
        if _agree(q, g): keep.append(q)
        else: notes.append(f"answer disputed: {q['question'][:40]}")
    return {**s, "cands": keep, "notes": notes}


def dedup_node(s: S) -> S:
    used, keep, notes = list(s.get("used", [])) + [q["question"] for q in s.get("accepted", [])], [], list(s.get("notes", []))
    for q in s.get("cands", []):
        if _is_dup(q["question"] + q["code"][:80], used): notes.append("near-duplicate"); continue
        keep.append(q); used.append(q["question"] + q["code"][:80])
    return {**s, "cands": keep, "notes": notes}


def collect_node(s: S) -> S: return {**s, "accepted": s.get("accepted", []) + s.get("cands", [])}
def _route(s: S) -> str: return "end" if s.get("fatal") or len(s.get("accepted", [])) >= s["n"] or s.get("attempt", 0) >= MAX_ATTEMPTS else "generate"

_g = StateGraph(S)
for nm, fn in (("generate", generate_node), ("validate", validate_node), ("verify", verify_node), ("dedup", dedup_node), ("collect", collect_node)): _g.add_node(nm, fn)
_g.set_entry_point("generate")
for a, b in (("generate", "validate"), ("validate", "verify"), ("verify", "dedup"), ("dedup", "collect")): _g.add_edge(a, b)
_g.add_conditional_edges("collect", _route, {"generate": "generate", "end": END})
_graph = _g.compile()


def generate_batch(prompt_base: str, specs: list, n: int, used: list) -> dict:
    """-> {"questions": [...valid, verified...], "calls": int, "reason": str}. Never raises for budget/API trouble: a shortfall is the caller's job to fill."""
    _tl.calls = 0
    if _client is None: return {"questions": [], "calls": 0, "reason": "no GEMINI_API_KEY"}
    try:
        out = _graph.invoke({"prompt_base": prompt_base, "specs": specs, "n": n, "used": used, "attempt": 0, "notes": [], "accepted": []})
    except Exception as e:
        return {"questions": [], "calls": getattr(_tl, "calls", 0), "reason": f"engine error: {type(e).__name__}"}
    return {"questions": out.get("accepted", [])[:n], "calls": getattr(_tl, "calls", 0), "reason": out.get("reason") or "; ".join(out.get("notes", [])[-2:])}
