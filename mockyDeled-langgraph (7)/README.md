# mockyDElEd — Uttarakhand D.El.Ed Entrance Mock Test Platform

Built on the same architecture as **mockyX** (the CBSE AI 417 mock platform),
adapted for the **Uttarakhand D.El.Ed. (Diploma in Elementary Education)
Entrance Examination**, conducted by UBSE. English-medium only.

---

## Official exam pattern (verified, see Sources below)

| | |
|---|---|
| Total questions | 200 (objective, MCQ) |
| Total marks | 200 (1 mark each) |
| Duration | **2 hours 30 minutes** (150 minutes) |
| Negative marking | None |
| Sections | 4 × 50 questions each |

**Sections:**
1. General Knowledge & Comprehension
2. General Intelligence & Reasoning
3. Quantitative Aptitude
4. Teaching Aptitude

## Modes

### 1. Real PYQ Practice
Takes the **actual previous-year questions** — digitised via OCR from the
official 2022 and 2023 Uttarakhand D.El.Ed. question papers. 131 real,
manually-verified questions are bundled in `data/pyq_bank.json`, tagged by
section and year. Two of the four papers you originally supplied
(`Questionbooklet2019.pdf` and `Questionbooklet2020.pdf`) turned out to be a
Hindi-only paper and a duplicate re-scan of the 2022 paper respectively, so
they weren't included as separate sets — you can re-run the OCR pipeline
(see `EXTRACTION.md`-style notes at the bottom of this file) on more papers
later and merge them into the same JSON format.

**Important honesty note:** the source booklets did not print an answer key.
This app asks Gemini to solve the whole paper once, the first time you start
a PYQ test, and caches that AI-built answer key for grading. It's a genuine
best-effort key, not an official one — please double-check anything you're
unsure about. If no `GEMINI_API_KEY` is configured, the test is still fully
playable; you just won't get auto-grading, only self-review.

### 2. Section Practice
Pick one or more sections and a question count (10/20/30/50). Fresh
MCQs are generated every session via the Gemini API, seeded with the real
PYQ patterns above plus the official syllabus (`data/deled_patterns.json`).
Paced at the exam's own rate (45 sec/question).

### 3. Full Mock
A complete 200-question paper following the official pattern exactly:
50 questions from each of the 4 sections, 150 minutes, no negative marking.
Blends PYQ-style phrasing with Gemini's knowledge of 2026 current affairs
for the General Knowledge section.

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Get a free Gemini API key
- Go to https://aistudio.google.com/apikey
- Sign in with a Google account → Create API key
- The free tier is generous enough for casual mock-test use (check current
  limits in your AI Studio dashboard — Google's free-tier quotas change
  over time)

### 3. Set environment variables
```bash
# Linux / Mac
export GEMINI_API_KEY="your_key_here"

# Windows
set GEMINI_API_KEY=your_key_here
```

Optional — pin a specific model instead of the auto-updating default:
```bash
export GEMINI_MODEL="gemini-2.5-flash"   # or any current model ID
```
By default this app uses `gemini-flash-latest`, Google's auto-updating
alias that always resolves to their current recommended Flash model. That
means the app keeps working as Google retires older dated model versions,
without you having to edit code. If you'd rather pin a specific version for
stability/reproducibility, set `GEMINI_MODEL` explicitly — just check
https://ai.google.dev/gemini-api/docs/models for what's currently available,
since Google retires dated versions on a rolling basis.

### 4. Run
```bash
python app.py
```
Open http://localhost:5000 in your browser.

---

## Project structure

```
mockyDeled/
├── app.py                      Flask backend (Gemini-powered)
├── requirements.txt
├── data/
│   ├── deled_patterns.json     Syllabus + question-type + PYQ-style seed data per section
│   └── pyq_bank.json           131 real, OCR-digitised PYQ questions (2022 & 2023 papers)
├── static/
│   ├── css/style.css
│   └── js/app.js
└── templates/
    └── index.html
```

## How the real PYQ data was built

The two usable source PDFs (`Uttarakhand_D_El_Ed._Official_Paper_2021-22`,
60 pages, and `Uttarakhand_D_El.Ed__Official_Paper__Held_On__20_May__2023_`,
20 pages) are bilingual scans (Hindi | English side by side). The pipeline:

1. Rendered every page to an image (`pdftoppm`).
2. Cropped the English-language half of each page.
3. Ran Tesseract OCR on each cropped image.
4. Parsed the raw OCR text into `{question, options}` objects with a regex
   parser tuned to the papers' numbering/option format.
5. Filtered out OCR-garbled entries (broken option text, stray symbols).
6. Classified each surviving question into one of the 4 official sections
   using keyword heuristics (similar in spirit to mockyX's chapter
   detector).

This is genuine exam content, not AI-fabricated — but since it went through
OCR rather than manual transcription, expect the occasional typo in a
handful of entries. Diagram-based reasoning questions (mirror images,
cubes, figure series) were mostly filtered out during cleanup since they
can't be faithfully represented as plain text without the original image.

## Sources for the exam pattern

- Careers360, Physics Wallah, and AglaSem coverage of the UBSE Uttarakhand
  D.El.Ed entrance exam pattern (200 Q / 200 marks / 2h30m / 4 sections of
  50, no negative marking) — cross-checked across multiple independent
  sources as of September 2026. Always confirm against the current UBSE
  notification at ubse.uk.gov.in before a real attempt, since patterns can
  change year to year.
