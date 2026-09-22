"""Offline tests: the Gemini client is replaced by a stub, so no key / network is needed.  python tests/test_stub.py"""
import json, os, sys, types
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ["GEMINI_API_KEY"] = ""
import engine, app as A
from collections import Counter

import random
WORDS = "alpha bravo canyon delta ember fjord gamma harbor island jungle kernel lantern meadow nebula orchid prairie quartz ripple summit tundra umbra valley willow xenon yonder zephyr".split()
STATE = {"dispute": False, "fail": None, "calls": 0, "last": []}
def fake_call(system, contents, cfg):
    STATE["calls"] += 1; engine.BUDGET.take = lambda: None
    if STATE["fail"]: raise engine.BudgetExhausted("stub budget exhausted")
    if "solver" in system:
        sols = [{"n": i + 1, "working": "w", "answer": ("d" if STATE["dispute"] and a in "abc" else a)} for i, a in enumerate(STATE["last"])]
        return types.SimpleNamespace(text=json.dumps({"solutions": sols}))
    n = int(contents.split("exactly ")[1].split()[0]); qs, STATE["last"] = [], []
    for i in range(n):
        k = (STATE["calls"] * 10 + i)
        kind = ["mcq", "msq", "nat", "mcq"][i % 4]
        q = {"type": kind, "question": "Consider " + " ".join(random.choice(WORDS) for _ in range(9)) + f" with parameter {k}?", "explanation": "because", "subtopic": "stub", "context": "", "code": "", "figure_json": ""}
        if kind == "mcq": q.update(options=[f"opt{k}a", f"opt{k}b", f"opt{k}c", f"opt{k}d"], answer="b"); STATE["last"].append("b")
        elif kind == "msq": q.update(options=[f"opt{k}a", f"opt{k}b", f"opt{k}c", f"opt{k}d"], answer="a,c"); STATE["last"].append("a,c")
        else: q.update(answer="12.5", tol=0.1); STATE["last"].append("12.5")
        if i == 0: q["figure_json"] = json.dumps({"kind": "graph", "directed": True, "nodes": ["q0", "q1"], "edges": [["q0", "q1", "a"], ["q1", "q0", "b"]], "start": "q0", "accept": ["q1"]}); q["question"] = "For the automaton shown in the figure, " + " ".join(random.choice(WORDS) for _ in range(8)) + f" {k} is"
        qs.append(q)
    return types.SimpleNamespace(text=json.dumps({"questions": qs}))

engine._call = fake_call; engine._client = object(); A.ai_ready = lambda: True
c = A.app.test_client()

def run(mode, **kw):
    r = c.post("/start", json={"mode": mode, **kw}).get_json(); assert r["status"] == "ok", r
    guard, tot_calls = 0, 0
    while r["pending"] and guard < 30:
        g = c.post("/generate-next").get_json(); tot_calls += g.get("calls", 0); guard += 1
        if g.get("note"): print("   note:", g["note"][:100])
        if g.get("done"): break
    d = c.get("/questions").get_json(); assert d["total"] == r["plan"]["total"], (d["total"], r); return d, tot_calls

# 1) healthy API: batches of <= 4, verified, every slot filled
STATE.update(fail=None, dispute=False, calls=0); d, calls = run("full")
print("healthy  :", d["total"], "Q", Counter(q["src"] for q in d["questions"]), "api calls this paper:", STATE["calls"])
assert Counter(q["src"] for q in d["questions"])["ai"] > 0 and STATE["calls"] <= 30
fig = [q for q in d["questions"] if q["figure"]]; assert fig and fig[0]["figure"]["kind"] in ("graph", "tree", "bar", "gantt")
# 2) solver disputes every key -> nothing verified -> fallback fills the shortfall, call count stays bounded
STATE.update(fail=None, dispute=True, calls=0); d, calls = run("section", subjects=["os"], count=10)
print("disputed :", d["total"], "Q", Counter(q["src"] for q in d["questions"]), "api calls:", STATE["calls"]); assert d["total"] == 10 and STATE["calls"] <= 8 * 3
# 3) budget exhausted mid-paper
STATE.update(fail=True, dispute=False, calls=0); d, calls = run("full")
print("no budget:", d["total"], "Q", Counter(q["src"] for q in d["questions"])); assert d["total"] == 65 and "ai" not in {q["src"] for q in d["questions"]}
# 4) scoring rules
d, _ = run("section", subjects=["algo"], count=5)
bank = A.session if False else None
with c.session_transaction() as s: bank = s["bank"]
ans = {}
for q in d["questions"]:
    b = bank[q["id"]]
    ans[q["id"]] = b["answer"] if b["type"] == "mcq" else b["answer"] if b["type"] == "msq" else str(sum(b["answer"]) / 2)
res = c.post("/submit", json={"answers": ans, "time_taken_sec": 5}).get_json(); assert res["score"] == res["total_marks"], res
print("scoring  : perfect answers ->", res["score"], "/", res["total_marks"])
print("ALL STUB TESTS PASSED")
