# Grading Interface Guide

End-to-end operator guide for setting up, running, and troubleshooting the grading interface.

## 1) First-time setup

From repo root:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python grading_app/app.py
```

Open `http://127.0.0.1:5000`.

## 2) Configure Gemini (AI features)

AI is used by:
- `semantic_text` questions
- `semantic_code` practice methods `ai` and `hybrid`

Create `.env` in repo root:

```env
GEMINI_API_KEY=AIza...your_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

Notes:
- `GEMINI_MODEL` is optional.
- Default model is `gemini-2.5-flash-lite`.
- Keep `.env` local only; do not commit.

## 3) Assignment manifests and switching

Manifests live under:
- `assignments/<name>/assignment_manifest.json`

Active manifest pointer:
- `grading_app/active_assignment.json`

Example:

```json
{
  "manifest_path": "assignments/retail_ops_ai_demo/assignment_manifest.json"
}
```

You can also set per session:

```powershell
$env:GRADING_MANIFEST_PATH = "assignments/your_assignment/assignment_manifest.json"
python grading_app/app.py
```

## 4) Daily grading workflow

1. Confirm active manifest in **Configuration**.
2. Load benchmarks (from `seed_from` or manual upload).
3. Upload student files/zip in **Student Submission**.
4. Run grading from **Run Grading**.
5. Review **Student Summary** and **Detailed Results**.
6. Export reports from `reports_dir`.

## 5) Marking modes in practice

### `output_match`
For deterministic artifacts (`csv`, `xml`, `image`).

### `semantic_code`
For code where equivalent implementations are valid.
- correctness: `behavior_rules` or `output_execution`
- practice: `rules`, `ai`, or `hybrid`

### `semantic_text`
For prose with semantic point coverage using Gemini.

### `legacy_text`
Normalized text similarity fallback/legacy path.

### `mixed`
Per-file dispatch based on suffix.

## 6) Execution-based correctness (SQL/XSLT/Python)

Use `code_marking.correctness.method = "output_execution"`.

### SQL (`engine: sqlite`)
- Load fixture tables from CSV
- Execute benchmark SQL and student SQL
- Compare output columns/rows/values

### XSLT (`engine: xslt`)
- Use fixture XML input
- Run benchmark and student transforms
- Compare normalized output

### Python (`engine: python`)
- Run benchmark and student scripts with the same stdin fixture (optional `input_path`)
- Compare stdout output similarity

Security note:
- `engine: python` executes scripts (benchmark + student). There is a timeout, but the code is not fully sandboxed. Use only for trusted code or run inside an isolated environment/container.

## 7) AI fallback behavior

The system never hard-fails grading because AI is unavailable.

Fallbacks:
- `semantic_text`: `ai-semantic` -> `fallback-text`
- practice `ai`/`hybrid`: -> `rules-fallback`

Common causes:
- missing key
- invalid key (`401`)
- quota/rate limit (`429 RESOURCE_EXHAUSTED`)

## 8) Reports and interpretation

Written to manifest `reports_dir`:
- `summary_report.csv`: per student/per file detailed rows
- `student_totals.csv`: aggregate totals
- `code_checks.csv`: raw AST/regex structure checks
- `summary_report.json`: UI data payload

Important columns in detailed rows:
- `marking_mode`
- `correctness_method`
- `practice_method`
- `correctness_score`
- `practice_score`
- `similarity` (combined score)
- `notes`

## 9) Troubleshooting quick fixes

- **Still seeing fallback after changing `.env`**
  - Restart Flask app.
- **401 Gemini auth errors**
  - Replace with valid AI Studio API key.
- **429 quota errors**
  - Wait for reset, reduce request volume, or enable billing.
- **Unexpected `missing` rows**
  - Check benchmark filenames and `submission_aliases`.
- **No visible results**
  - Verify benchmarks exist for active manifest.

## 10) Security checklist

- `.env` must be in `.gitignore`
- Never bypass secret scanning for live secrets
- Revoke and rotate any exposed key immediately
- Keep `.env.example` with placeholders only
- If you enable `code_marking.correctness.method = "output_execution"` with `execution.engine = "python"`, treat submissions as trusted (scripts are executed; only a timeout is enforced).

## 11) Creating a new assignment quickly

1. Copy existing manifest template.
2. Set unique directories (`benchmark_dir`, `submissions_dir`, `reports_dir`).
3. Define questions with explicit `marking_mode`.
4. Add `code_marking` and `match_rules` where needed.
5. Add `submission_aliases` if filename variants are expected.
6. Activate manifest and run a smoke grading pass.
