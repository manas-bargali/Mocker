# mockyGATE — GATE CS/IT live-exam mock platform

Same skeleton as mockyCGL: Flask + server-side (filesystem) session + a LangGraph/Gemini question engine,
same 4 screens (home → loading → exam → result). Adapted for GATE: one 180-minute clock, MCQ **+** MSQ **+** NAT
with official negative marking, and questions that can carry C code, data tables and SVG figures (weighted
graphs, automata, BST/heap trees, bar charts, Gantt charts) drawn client-side from a small JSON spec.

## Run

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your_key_here     # optional — see "Without an API key"
python app.py                           # http://localhost:5000
```

## Three modes
- **Full Mock** — the real GATE blueprint: 65 Q / 100 marks / 180 min, GA 10 (5×1+5×2) + core 55 across all 10
  syllabus sections (25×1 + 30×2), subject weights and MCQ/MSQ/NAT mix taken from the last two years' papers.
- **Subject-wise Mock** — pick subject(s) + a question count; timed at 1.8 min/mark like the real paper.
- **Real PYQ Mock** — an exact original paper (questions shown as cropped page images, so code/graphs/tables render
  pixel-perfect) or a fresh subject-wise sample drawn from the keyed PYQ bank — graded with the true official key.

## How every slot gets filled (this is what keeps a paper from ever failing to generate)
1. **code** — one of 27 generator families (`generators.py`) computes both the question and the answer
   (Dijkstra/MST/hashing, BST/heap traces, C-program output, paging/CPU-scheduling simulation, cache tag/AMAT
   maths, IP fragmentation/CIDR/stop-and-wait, DFA state-counting, B-tree/block-count, probability/determinant...).
   Zero API cost, zero chance of a wrong key.
2. **ai** — Gemini (LangGraph graph: generate → validate → verify → dedup → collect), batched **4 questions per
   call**, given real PYQs of the same subject as a style/difficulty reference. A second blind-solve call checks
   the model's own answer key and throws out anything disputed.
3. **pyq** — a real, officially-keyed past question for that subject/marks, used whenever the API is unavailable,
   over budget, or a batch comes back short.

## Rate/budget safety (`engine.py`)
- `Budget`: sliding-window **requests/minute** limiter (`GEMINI_RPM`, default 8) + a **daily call cap**
  (`GEMINI_DAILY`, default 400) persisted in `.budget.json`. Exhausted → `BudgetExhausted` → the caller falls back
  to code/PYQ instead of erroring.
- `CALL_CAP` (default 8) hard-caps real API calls spent on any one batch; `MAX_ATTEMPTS=2` limits generate retries.
- `BATCH_SIZE=4` (not the CGL-style 8): GATE questions carry code/tables/figures and run 600–900 output tokens
  each, so a bigger batch risks JSON truncation.
- Full Mock worst case ≈ 55 core slots ÷ 4/batch ≈ 14 generate calls + 14 verify calls ≈ **~28 calls**, well inside
  the daily budget even for several full mocks a day — and `CODE_SHARE` (default 0.35) routes a chunk of slots to
  the free code generators up front so fewer slots ever reach the API at all.

## Data pipeline (`tools/`)
- `ingest_pyq.py` — crops every question out of the original text-layer PDFs as a PNG (keeping figures/code/tables
  intact) using a two-pass "Q.n" + "carry marks" scan; **1105 questions across 18 papers** (2012–2025) ingested.
- `build_keys.py` — official transcribed keys for 2024/2025 CS1+CS2, plus keys parsed straight out of the
  embedded answer-key tables in the 2014 and 2018 PDFs, each validated by NAT-vs-MCQ agreement against the
  cropped layout. **14 of 18 papers are keyed → 520 questions in `pyq_bank.json`.** 2016's embedded table failed
  parsing (0/65 agreement) and 2012/2013/2022/2023 have no extractable key, so those stay unkeyed/unused.
- `make_syllabus.py` — the 10 GATE sections + GA from the syllabus PDF, each with a topic list and a hand-tuned
  keyword classifier, plus the official per-subject 1-mark/2-mark blueprint (30×1 + 35×2 = 65 Q).
- `classify.py` — attaches subject + type + key to every keyed PYQ (keyword scoring; `--llm` flag re-labels with
  Gemini if a key is set — unused in this build, sandbox had no key).

## Layout
```
app.py            Flask routes: /config /start /generate-next /questions /submit /result /pyq/<img>
engine.py          LangGraph engine + Budget/rate-limit safety
generators.py       27 code-computed question families (answers computed, never guessed)
data/gate_syllabus.json   sections, topics, classifier keywords, paper blueprint
data/pyq_bank.json         520 keyed real questions {img, type, answer, marks, subject, text}
data/keys/<paper>.json     official/parsed answer key per paper
data/pyq/<paper>/qN.png    cropped image of each ingested question (1105 total)
templates/index.html, static/js/app.js, static/css/style.css   4-screen UI (same visual language as mockyCGL)
tests/test_stub.py         offline engine tests (stubbed Gemini client — no key/network needed)
tests/ui_smoke.js          headless jsdom test driving a full 65-question exam through the real server
```

## Known gaps
- 2016's embedded answer key still fails to parse (0/65 agreement) — that paper isn't in the bank.
- 2012/2013/2022/2023 have no available official key, so they're excluded rather than graded against a guess.
- No live Gemini key was available in this sandbox — `engine.py` is exercised end-to-end via `tests/test_stub.py`
  (a stubbed client) rather than a real API call; wire in `GEMINI_API_KEY` to see it live.
