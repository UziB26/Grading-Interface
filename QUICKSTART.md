# Quickstart

Fast setup and first grading run.

## 1) Install

From repo root:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2) Configure Gemini (for AI features)

Create `.env` in repo root:

```env
GEMINI_API_KEY=AIza...your_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

Notes:
- `GEMINI_MODEL` is optional (default is `gemini-2.5-flash-lite`).
- Keep `.env` local only. Never commit it.

## 3) Start app

```powershell
python grading_app/app.py
```

Open:
- `http://127.0.0.1:5000`

## 4) Select manifest

In **Configuration**:
- choose the assignment manifest
- confirm benchmark/submission/report directories in Manifest Details

Examples:
- `assignments/sales_ops_demo/assignment_manifest.json`
- `assignments/retail_ops_ai_demo/assignment_manifest.json`

## 5) Load benchmarks

Use either:
- **Load Benchmarks From Solution** (recommended), or
- manual benchmark uploads per question

## 6) Upload student submissions

In **Student Submission**:
- enter student name
- upload files or zip

## 7) Run grading

In **Run Grading**:
- keep `mark_scale = 1.0` for normal scoring
- click **Run Grading**

Review:
- **Student Summary**
- **Detailed Results**

## 8) Understand result modes quickly

- `output_match`: CSV/XML/image output comparison
- `semantic_code`: correctness + practice weighted score
- `semantic_text`: Gemini semantic grading for prose
- `legacy_text`: deterministic text similarity
- `mixed`: per-file dispatch

## 9) Download reports

Saved to active manifest `reports_dir`:
- `summary_report.csv`
- `student_totals.csv`
- `code_checks.csv`
- `summary_report.json`

## 10) If something looks wrong

- Seeing `fallback-text` or `rules-fallback`:
  - check `.env` key
  - restart app after changing `.env`
  - check Gemini quota (`429 RESOURCE_EXHAUSTED`)
- Seeing many `missing` files:
  - verify benchmark filenames and submission aliases
- No results:
  - ensure benchmarks are loaded for the active manifest

## 11) Security checklist

- `.env` is ignored by git
- if a key is exposed, revoke and rotate immediately
- keep only placeholders in `.env.example`
- If you enable `output_execution` with `execution.engine = "python"`, scripts are executed (timeout only). Use this only for trusted submissions or inside an isolated environment.

## 12) Next docs

- Full operator guide: `GRADING_INTERFACE_GUIDE.md`
- Scoring internals: `MARKING_MODES_DETAILED.md`
- Manifest authoring: `assignments/README.md`
