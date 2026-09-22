# What changed, and why

## Root causes of "repeated and corrupted" questions in the original build

1. **Corruption** — `app.py` asked Gemini for loosely-formatted plain text
   (`Q. ... (a) ... ANSWER: (b)`) and parsed it with a regex (`parse_question`
   in the original `app.py`). Any small deviation — a missing option, an
   extra blank line, a missing `ANSWER:` line — either crashed the parser or
   silently produced a malformed question that still got added to the queue.
2. **Repetition** — the generator only ever told Gemini the *section name*
   of the last 2 questions (`history[-2:]`), never the actual text of
   previous questions. With ~8 topics per section and 50+ questions needed
   per section in a full mock, that's nowhere near enough signal to stay
   unique — Gemini regenerates near-identical questions.

Neither of these is a "wrong model" problem — it's a missing feedback loop:
nothing ever checked the output against what had already been shown, and
nothing ever told the model *why* a draft was bad so it could correct
itself.

## What changed

Two files, minimal diff:

- **`graph_engine.py`** (new) — a small LangGraph `StateGraph` with 5 nodes:
  `generate → validate → dedup → finalize`, with a retry loop back to
  `generate` (capped at 3 attempts) and a `fallback` exit if it keeps
  failing. See the diagram.
- **`app.py`** — same file, ~15 lines touched:
  - `+1` import line
  - `/start`: two new session keys (`used_texts`, `used_subtopics`) —
    plain lists, no new storage system
  - `/generate-next`: the old `_call_gemini()` + `parse_question()` call is
    replaced with one call to `generate_unique_question(...)` from
    `graph_engine.py`. Everything else in the route (session/queue/bank
    handling, the `/questions`, `/submit`, `/result` routes, the HTML/CSS/JS,
    the PYQ bank, the answer-key solver) is **untouched**.

Nothing else in the repo needed to change. `requirements.txt` gets one new
line (`langgraph>=0.2.0`).

## Why this is still a "minimal" (cheap) rebuild

- **Same 1 Gemini call per question on the happy path.** The graph doesn't
  add a planning step or a second model call — `generate` is still the only
  node that touches the API.
- **Retries are capped at 3**, same order of magnitude as what already
  happened implicitly before: in the old code, a malformed response just
  returned a `500` and the frontend's loop called `/generate-next` again
  from scratch — a full extra Gemini call with *zero* memory of what went
  wrong. This version spends that same worst-case budget productively
  instead of wastefully, by telling the model exactly why the last draft
  was rejected.
- **Dedup is local and free.** It's a `difflib` text-similarity check
  against the session's own question list — no embeddings API, no second
  LLM call, no vector DB.
- **Validation is local and free.** Pure Python checks on the parsed JSON
  (4 distinct non-empty options, valid answer key, minimum length) — no
  extra API call either.
- Gemini's JSON mode (`response_schema`) is used instead of free-text +
  regex, which *reduces* first-try failures compared to before, so on
  average this should cost the **same or fewer** tokens than the original,
  not more.

## How to apply

1. Drop `graph_engine.py` into the repo root (next to `app.py`).
2. Replace your `app.py` with the one here (or apply the same ~15-line
   change by hand — see the diff logic above).
3. `pip install -r requirements.txt` (adds `langgraph`).
4. Nothing else changes — `data/`, `static/`, `templates/` stay as they are.

---

## Update: fixed a real bug — "503 The model is overloaded" was crashing out raw

If you saw the app get stuck on "Retrying… (503 UNAVAILABLE. {'error':
{'code': 503, 'message': 'This model is cur…")" — that was a genuine bug
in the first version of `graph_engine.py` I shipped, not your API key.

**What was wrong:** the Gemini API call itself (`_client.models.generate_content(...)`)
was not wrapped in any `try/except`. Only the JSON-parsing step *after* it
was. So when Google's servers returned a 503 ("the model is overloaded" —
a well-documented, transient, Google-side capacity issue tracked per
model, unrelated to your key or quota), that exception skipped every node
in the graph — validate, dedup, retry, all of it — and fell straight out
to Flask's outer error handler, which just dumped the raw exception text.
That's exactly the garbled message you saw.

**The fix**, entirely inside `graph_engine.py` (`app.py`'s only change is a
friendlier error message):
- `generate_node` now wraps the actual API call, not just the JSON parse.
- On a retryable error (429/500/503/504), it retries with **exponential
  backoff + jitter**, then falls back across a short chain of models
  (`GEMINI_MODEL` → `gemini-2.5-flash` → `gemini-2.0-flash`) — since
  overload capacity is tracked per model, a different model often
  succeeds immediately even while the first one is saturated.
- On a non-retryable error (400/401/403 — an actually bad key or request),
  it fails fast instead of burning through retries on something that can
  never succeed.
- The final error message shown to you is now a clean sentence (e.g.
  "Gemini is temporarily unavailable (Gemini API error 503 UNAVAILABLE)")
  instead of a raw stack-trace fragment.

I verified all three paths — overload-then-recovers, fast-fail on a bad
key, and total-outage-exhausts-gracefully — with simulated API responses
before shipping this update.

---

## Update 2: fixed "404 NOT_FOUND" — a second real bug, plus stale model names

After the fix above, a new error showed up: `Gemini API error 404
NOT_FOUND`. Two separate problems, both mine, now both fixed:

**Bug 1 — the fallback chain never actually got used on a 404.** My
`_call_gemini_resilient` treated *any* non-retryable error (400/401/403/404
alike) as "give up entirely," using a bare `raise` that exited the whole
function — not just the current model. So the very fallback mechanism I'd
built to survive exactly this kind of failure was accidentally being
skipped every time it was needed. Fixed: only a genuine account-level
error (401/403 — bad key, billing/permission problem) aborts immediately
now, since no model fixes that. A model-specific error like 404 now
correctly moves on to the *next* model in the chain instead.

**Bug 2 — the fallback models themselves were retired.** The two concrete
model names I'd hardcoded as fallbacks, `gemini-2.5-flash` and
`gemini-2.0-flash`, have since been shut down by Google (Google retires
specific dated model versions on a rolling ~6-12 month schedule). Calling
either now returns exactly the 404 you saw. Fixed by switching the
fallback chain to Google's own `-latest` aliases (`gemini-flash-latest`,
`gemini-pro-latest`), which Google itself keeps silently repointed at
whatever the current model is — so this list shouldn't need updating again
as models come and go, unlike hardcoded version-pinned IDs.

I verified both fixes directly: simulated a 404 on the primary model and
confirmed the call now succeeds via the fallback model within the same
attempt, and confirmed a genuine 401 still aborts immediately without
wasting time on fallbacks.

---

## Update 3: switched the default model to the "lite" tier

To help with `429 RESOURCE_EXHAUSTED` (free-tier quota exhaustion — a real
usage cap, not a bug), `GEMINI_MODEL` now defaults to
`gemini-flash-lite-latest` instead of `gemini-flash-latest`. Google gives
its lite-tier models meaningfully higher free-tier rate limits (both
requests-per-minute and requests-per-day) than full Flash or Pro — it's
the tier specifically meant for high-volume, simple tasks like structured
MCQ generation, so this buys real headroom against the free tier's cap,
at no cost.

Like the other fallback entries, this is an alias (`-latest`), not a
pinned dated model ID — Google keeps it silently repointed at whatever
the current lite model is, so it shouldn't need updating as models are
retired, the same reasoning as the fallback-chain fix in Update 2.

The fallback chain is now: `gemini-flash-lite-latest` (primary, highest
free quota) → `gemini-flash-latest` → `gemini-pro-latest`. Re-ran the
full test suite (happy path, in-model retry-with-backoff, cross-model
fallback on a model-specific error, fast-fail on a bad key) against this
new chain — all four paths confirmed still correct.

If you'd rather keep using full Flash for slightly higher answer quality
and are fine with the lower free-tier ceiling, set the `GEMINI_MODEL`
environment variable to `gemini-flash-latest` before running `app.py` and
it'll override this default.

