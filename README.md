# Assignment Grading Interface

Manifest-driven grading platform for marking student submissions against benchmark files.

For operator workflow and UI usage, see `GRADING_INTERFACE_GUIDE.md`.
For scoring internals and formulas, see `MARKING_MODES_DETAILED.md`.
For Docker sandbox setup and troubleshooting, see `DOCKER_SANDBOX_SETUP.md`.

## What is implemented

- Explicit per-question marking modes (`output_match`, `semantic_code`, `semantic_text`, `legacy_text`, `mixed`)
- Semantic code grading with split score: correctness + practice
- Execution-based correctness for SQL (`sqlite`) and XSLT (`xslt`)
- Gemini-powered semantic text grading (`semantic_text`) with safe fallback
- Gemini-powered code practice (`ai` / `hybrid`) with safe fallback to rules
- Optional Docker sandbox execution for Python/Java/C++ correctness checks
- Per-file mark splitting for multi-file questions
- UI breakdowns: marking mode, correctness mode, practice mode, correctness %, practice %

## Requirements

- Python 3.10+
- pip

Install dependencies:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

`requirements.txt` includes:
- `flask`
- `pandas`
- `google-genai`
- `python-dotenv`
- `pydantic`
- `docker` (for optional container sandbox execution)

## Run the app

```powershell
python grading_app/app.py
```

Open `http://127.0.0.1:5000`.

## Gemini / AI setup

AI features (`semantic_text`, practice `ai`, practice `hybrid`) require a valid Google AI Studio API key.

1. Generate key at [Google AI Studio](https://aistudio.google.com/apikey)
2. Create local `.env` in repo root:

```env
GEMINI_API_KEY=AIza...your_key
GEMINI_MODEL=gemini-2.5-flash-lite
```

Notes:
- `GEMINI_MODEL` is optional. Default is `gemini-2.5-flash-lite`.
- `.env` must stay local only; never commit secrets.
- If quota is exceeded (`429 RESOURCE_EXHAUSTED`), grading safely falls back:
  - `semantic_text` -> `fallback-text`
  - practice `ai`/`hybrid` -> `rules-fallback`

## Manifest basics

Assignment behavior is defined by:
- `assignments/<assignment_name>/assignment_manifest.json`

Active manifest pointer:
- `grading_app/active_assignment.json`

Example:

```json
{
  "manifest_path": "assignments/retail_ops_ai_demo/assignment_manifest.json"
}
```

## Marking modes summary

| Mode | Typical use | Core behavior |
|---|---|---|
| `output_match` | CSV/XML/image outputs | Value/structure compare against benchmark |
| `semantic_code` | SQL/XSL/Python code files | Correctness + practice weighted score |
| `semantic_text` | Written answers with key points | Gemini semantic coverage over benchmark points |
| `legacy_text` | Legacy prose grading | Normalized text similarity |
| `mixed` | Multi-file mixed artifact questions | Per-file mode dispatch by suffix |

`text_rubric` is a reserved placeholder mode. Use `semantic_text` for text grading.

## `semantic_code` quick reference

Formula:

```text
combined = correctness * correctness_weight + practice * practice_weight
```

Defaults:
- correctness weight `0.7`
- practice weight `0.3`

Correctness methods:
- `behavior_rules`
- `output_execution` (SQL/XSLT/Python/local or Docker sandbox)

Practice methods:
- `rules`
- `ai`
- `hybrid`

Example:

```json
{
  "id": "q3",
  "marking_mode": "semantic_code",
  "compare_mode": "code",
  "code_marking": {
    "weights": { "correctness": 0.7, "practice": 0.3 },
    "correctness": {
      "method": "output_execution",
      "execution": {
        "engine": "sqlite",
        "fixtures": [
          { "table": "orders_fact", "path": "test_uploads/retail_ops_ai_demo/fixtures/orders_fact.csv" }
        ]
      }
    },
    "practice": {
      "method": "hybrid",
      "rules_weight": 0.5,
      "ai_weight": 0.5,
      "checks": ["comments", "no_select_star", "uses_aliases", "reasonable_length"]
    }
  },
  "files": [{ "benchmark": "regional_kpi.sql" }]
}
```

## `semantic_text` quick reference

Use this for text answers where meaning matters more than exact wording.

Configure:
- `marking_mode: "semantic_text"`
- `benchmark_points` (recommended): key bullets students must cover

Example:

```json
{
  "id": "q2",
  "marking_mode": "semantic_text",
  "compare_mode": "text",
  "benchmark_points": "1) Revenue trend\n2) Main root cause\n3) Recommended action",
  "files": [{ "benchmark": "executive_brief.md" }]
}
```

## Reports

Written to manifest `reports_dir`:

- `summary_report.csv` (per-student per-file rows)
- `student_totals.csv` (student aggregates)
- `code_checks.csv` (standalone structure checks)
- `summary_report.json` (UI payload)

## Security notes

- Keep `.env` out of git (`.gitignore` includes `.env`)
- If a key is ever exposed, revoke and rotate immediately
- Uploads and zip extraction are validated for unsafe content/paths
- Python student code is not executed for AST correctness checks
- Docker sandbox execution requires Docker Desktop running on host
- Docker execution is network-disabled and runs in disposable containers with resource limits

## Docker sandbox execution

Use this when you want to execute untrusted Python/Java/C++ student code in isolated containers.

Example `code_marking.correctness.execution`:

```json
{
  "method": "output_execution",
  "execution": {
    "engine": "docker",
    "language": "python",
    "image": "python:3.10-alpine",
    "timeout_seconds": 8,
    "input_path": "test_uploads/python_exec_demo/fixtures/stdin.txt"
  }
}
```

Notes:
- `language` supports `python`, `java`, `cpp`
- If `language` is omitted, it is inferred from file suffix (`.py`, `.java`, `.cpp/.cc/.cxx`)
- If Docker is unavailable, grading returns a clear execution error and does not crash the app

## Troubleshooting

- **Seeing `fallback-text` or `rules-fallback`**
  - Check `.env` key validity and model quota
  - Restart Flask after changing `.env`
- **`401 UNAUTHENTICATED` from Gemini**
  - Use a valid AI Studio key in `GEMINI_API_KEY`
- **`429 RESOURCE_EXHAUSTED`**
  - Wait for quota reset or use billing
  - Keep `GEMINI_MODEL=gemini-2.5-flash-lite` for better free-tier headroom
- **Results look legacy**
  - Confirm manifest `marking_mode` per question and rerun grading
