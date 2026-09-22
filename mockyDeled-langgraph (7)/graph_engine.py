"""
graph_engine.py — LangGraph question-generation engine for mockyDElEd
========================================================================
This is a MINIMAL, single-purpose graph. It is not a multi-agent system
and does not add extra LLM calls on the happy path — it replaces the old
`_call_gemini()` + `parse_question()` pair inside app.py's /generate-next
route with a small self-correcting state machine.

Why this fixes "repeated and corrupted" questions:

1. CORRUPTION — the old code asked Gemini for loosely-formatted plain
   text ("Q. ... (a) ... ANSWER: (b)") and parsed it with regex. Any
   deviation (missing option, extra line, no ANSWER line) either crashed
   parse_question() or silently produced a malformed question. This
   version asks Gemini for STRUCTURED JSON with a response_schema, so the
   shape is enforced by the API itself, then re-validates it in Python
   before it's ever shown to a user.

2. REPETITION — the old code only ever told Gemini the SECTION NAME of
   the last 2 questions ("avoid this sub-type"), and never told it what
   the actual previous questions WERE. Across a 200-question full mock
   with only ~8 topics per section, that's nowhere near enough signal —
   Gemini regenerates near-identical questions. This version keeps a
   running list of every question text served THIS SESSION and actively
   rejects + retries near-duplicates (checked locally with difflib, not
   another API call) before a question is ever added to the queue.

Cost discipline ("minimal approach"): retries are capped at MAX_ATTEMPTS
(3). On the OLD code, a malformed response just failed the whole request
with a 500 — the user's browser then called /generate-next again from
scratch, which is itself a full extra Gemini call with zero memory of
why the last one failed. So this graph's worst case (3 calls) is not
meaningfully more expensive than the old code's failure path already
was — it just spends those calls productively instead of wasting them,
and the happy path (1 call) is unchanged.

Graph shape
-----------

    START
      |
      v
  +---------+     +----------+     +--------+
  | generate| --> | validate | --> | dedup  |
  +---------+     +----------+     +--------+
       ^                                |
       |                          reject| accept
       |                                v
       +-------- retry <---- route --- (attempt < MAX?) --> finalize --> END
                                          |
                                    (attempt >= MAX)
                                          v
                                      fallback --> END
"""
from __future__ import annotations

import difflib
import json
import os
import random
import re
import time
from typing import Optional, TypedDict

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from langgraph.graph import END, StateGraph

# ── Config (same env vars app.py already uses — no new setup needed) ────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# Default model: the "lite" tier alias. Google gives its lite models
# meaningfully higher free-tier rate limits (RPM/RPD) than full Flash or
# Pro — it's the tier specifically meant for high-volume, simple tasks
# like this one (structured MCQ generation), so it buys real headroom
# against the free tier's 429 RESOURCE_EXHAUSTED cap. Override with the
# GEMINI_MODEL env var if you'd rather use a different one.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

MAX_ATTEMPTS = 3                    # hard cap on content-quality retries
DUP_SIMILARITY_THRESHOLD = 0.82     # difflib ratio; local, free, no API call

# ── Resilience against Gemini's transient errors and model retirements ─────
# Two distinct failure modes, handled differently:
#   1. TRANSIENT (429/500/503/504) — e.g. "the model is overloaded". Worth
#      retrying the SAME model with backoff first; Google's own guidance.
#   2. MODEL-SPECIFIC (404, and most other 4xx) — e.g. a model ID that no
#      longer exists because Google retired it (this happens roughly every
#      6-12 months per model — see ai.google.dev/gemini-api/docs/deprecations).
#      Retrying the same model is pointless, but a DIFFERENT model in the
#      chain may work fine, so we move on to it immediately.
# Only 401/403 (bad key / billing / permission problem) are truly fatal
# regardless of model — those abort immediately, since no model will help.
RETRYABLE_API_CODES = {429, 500, 503, 504}
FATAL_ACCOUNT_CODES = {401, 403}
_ATTEMPTS_PER_MODEL = 2
_BACKOFF_BASE = 1.0
_BACKOFF_CAP = 6.0


def _model_fallback_chain() -> list:
    # Deliberately alias-based, not pinned to dated model IDs. Google
    # retires concrete model versions (gemini-2.0-flash, gemini-2.5-flash,
    # etc.) on a rolling ~6-12 month schedule, which is exactly what broke
    # this fallback chain once already. The "-latest" aliases are Google's
    # own mechanism for never going stale — they get silently repointed to
    # whatever the current model is, so this list should not need updating
    # again as models come and go.
    chain = [GEMINI_MODEL]
    for extra in ("gemini-flash-latest", "gemini-pro-latest"):
        if extra not in chain:
            chain.append(extra)
    return chain


_MODEL_CHAIN = _model_fallback_chain()


def _call_gemini_resilient(system_instruction: str, contents: str, gen_config: dict):
    """Try each model in _MODEL_CHAIN in turn. Retryable errors (429/500/
    503/504) get backoff + retry on the SAME model first. A model-specific
    error (404 = retired/unknown model ID, or any other 4xx) moves straight
    to the NEXT model instead of retrying something that can't succeed.
    Only a genuine account-level error (401/403) aborts immediately, since
    no model in the chain would fix a bad key."""
    last_err = None
    for model in _MODEL_CHAIN:
        for attempt in range(_ATTEMPTS_PER_MODEL):
            try:
                return _client.models.generate_content(
                    model=model,
                    contents=contents,
                    config=types.GenerateContentConfig(system_instruction=system_instruction, **gen_config),
                )
            except genai_errors.APIError as e:
                last_err = e
                code = getattr(e, "code", None)
                if code in FATAL_ACCOUNT_CODES:
                    raise  # no model will fix a bad key/billing problem
                if code in RETRYABLE_API_CODES:
                    delay = min(_BACKOFF_CAP, _BACKOFF_BASE * (2 ** attempt)) + random.uniform(0, 1)
                    time.sleep(delay)
                    continue
                # Model-specific problem (404 etc.) — stop retrying THIS
                # model and move on to the next one in the chain.
                break
    raise last_err

_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "question": {"type": "string"},
        "options": {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"type": "string"},
                "c": {"type": "string"},
                "d": {"type": "string"},
            },
            "required": ["a", "b", "c", "d"],
        },
        "answer": {"type": "string", "enum": ["a", "b", "c", "d"]},
        "subtopic": {"type": "string"},
    },
    "required": ["question", "options", "answer", "subtopic"],
}


class QGenState(TypedDict, total=False):
    section: str
    prompt_base: str          # system prompt built by app.py's existing
                               # build_section_prompt()/build_full_mock_prompt()
                               # — unchanged, just routed through this graph now
    used_questions: list       # every question TEXT served this session so far
    recent_subtopics: list     # subtopics of the last few questions
    attempt: int
    reject_reason: Optional[str]
    fatal: bool                 # True = don't bother retrying (bad key/request)
    raw: Optional[dict]
    question: Optional[dict]
    status: str                # "ok" | "fallback"


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _is_near_duplicate(candidate: str, used: list) -> bool:
    c = _norm(candidate)
    return any(
        difflib.SequenceMatcher(None, c, _norm(prev)).ratio() >= DUP_SIMILARITY_THRESHOLD
        for prev in used
    )


# ── Nodes ─────────────────────────────────────────────────────────────────
def generate_node(state: QGenState) -> QGenState:
    if _client is None:
        raise RuntimeError("GEMINI_API_KEY is not set on the server")

    attempt = state.get("attempt", 0) + 1

    feedback = ""
    if state.get("reject_reason"):
        feedback = (
            f"\n\nYour previous draft was REJECTED — reason: {state['reject_reason']}. "
            "Produce a genuinely different question: different numbers/names, a "
            "different sub-type, different phrasing. Do not lightly edit the "
            "rejected draft."
        )

    subtopics = state.get("recent_subtopics", [])
    variety_note = (
        f"\n\nDo not reuse these recent sub-types: {', '.join(subtopics[-5:])}."
        if subtopics else ""
    )

    try:
        response = _call_gemini_resilient(
            state["prompt_base"],
            f"Generate one fresh {state['section']} question now.{feedback}{variety_note}",
            dict(
                temperature=0.9 if attempt == 1 else 1.05,   # nudge harder on retries
                max_output_tokens=400,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
            ),
        )
        raw = json.loads(response.text)
        return {**state, "attempt": attempt, "raw": raw, "reject_reason": None, "fatal": False}

    except genai_errors.APIError as e:
        # Every retryable attempt across the whole model chain failed, OR
        # this was a non-retryable error (bad key/request) raised immediately.
        code = getattr(e, "code", None)
        fatal = code in FATAL_ACCOUNT_CODES
        reason = f"Gemini API error {code} {getattr(e, 'status', '') or ''}".strip()
        return {**state, "attempt": attempt, "raw": None, "reject_reason": reason, "fatal": fatal}

    except Exception:
        # Malformed JSON etc. — treat like any other bad draft, worth a
        # normal content retry (not a fatal/API-level problem).
        return {**state, "attempt": attempt, "raw": None,
                "reject_reason": "empty or non-JSON response", "fatal": False}


def validate_node(state: QGenState) -> QGenState:
    if state.get("reject_reason"):
        return state   # generate_node already flagged an API-level failure

    raw = state.get("raw")
    if not raw:
        return {**state, "reject_reason": "empty or non-JSON response"}

    q = (raw.get("question") or "").strip()
    opts = raw.get("options") or {}
    ans = (raw.get("answer") or "").lower().strip()

    if len(q) < 12:
        return {**state, "reject_reason": "question text too short / likely corrupted"}
    if sorted(opts.keys()) != ["a", "b", "c", "d"]:
        return {**state, "reject_reason": "did not return exactly 4 labeled options"}
    if any(len((opts.get(k) or "").strip()) < 1 for k in "abcd"):
        return {**state, "reject_reason": "one or more options were empty"}
    if len({(opts.get(k) or "").strip().lower() for k in "abcd"}) < 4:
        return {**state, "reject_reason": "two or more options were identical"}
    if ans not in "abcd":
        return {**state, "reject_reason": "answer was not a/b/c/d"}

    return {**state, "reject_reason": None}


def dedup_node(state: QGenState) -> QGenState:
    if state.get("reject_reason"):
        return state  # already rejected on validation — skip dedup work
    q = state["raw"]["question"]
    if _is_near_duplicate(q, state.get("used_questions", [])):
        return {**state, "reject_reason": "near-duplicate of a question already used this session"}
    return state


def finalize_node(state: QGenState) -> QGenState:
    raw = state["raw"]
    question = {
        "question": raw["question"].strip(),
        "options": {k: raw["options"][k].strip() for k in "abcd"},
        "answer": raw["answer"].lower(),
        "subtopic": raw.get("subtopic", ""),
    }
    return {**state, "question": question, "status": "ok"}


def fallback_node(state: QGenState) -> QGenState:
    # Ran out of attempts (or hit a fatal/non-retryable error). Surface a
    # clear, human-readable reason via reject_reason instead of a raw
    # exception dump — app.py's route reads it straight off the result.
    return {**state, "status": "fallback", "question": None}


def _route_after_dedup(state: QGenState) -> str:
    if not state.get("reject_reason"):
        return "finalize"
    if state.get("fatal") or state.get("attempt", 0) >= MAX_ATTEMPTS:
        return "fallback"
    return "generate"


# ── Build graph once at import time ─────────────────────────────────────────
_graph = StateGraph(QGenState)
_graph.add_node("generate", generate_node)
_graph.add_node("validate", validate_node)
_graph.add_node("dedup", dedup_node)
_graph.add_node("finalize", finalize_node)
_graph.add_node("fallback", fallback_node)

_graph.set_entry_point("generate")
_graph.add_edge("generate", "validate")
_graph.add_edge("validate", "dedup")
_graph.add_conditional_edges(
    "dedup",
    _route_after_dedup,
    {"finalize": "finalize", "generate": "generate", "fallback": "fallback"},
)
_graph.add_edge("finalize", END)
_graph.add_edge("fallback", END)

compiled_graph = _graph.compile()


def generate_unique_question(
    section: str, prompt_base: str, used_questions: list, recent_subtopics: list
) -> dict:
    """Drop-in replacement for the old _call_gemini()+parse_question() pair.

    Returns a dict with:
      - status: "ok" or "fallback"
      - question: {"question","options","answer","subtopic"} or None
      - attempt: how many Gemini calls this took (1 on the happy path)
    """
    return compiled_graph.invoke(
        {
            "section": section,
            "prompt_base": prompt_base,
            "used_questions": used_questions,
            "recent_subtopics": recent_subtopics,
            "attempt": 0,
        }
    )
