# Assignment Grading Interface

Standalone grading platform for marking student submissions against benchmark files.

**Grading engine:** `1.1-semantic` (visible in the UI header after starting the app)

For a complete, step-by-step operating guide, see:
- `GRADING_INTERFACE_GUIDE.md`

For a deep technical breakdown of every marking mode and scoring formula, see:
- `MARKING_MODES_DETAILED.md`

## Contents

- [Prerequisites](#prerequisites)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Run the app](#run-the-app)
- [Manifest-driven configuration](#manifest-driven-configuration)
- [Marking modes (semantic grading)](#marking-modes-semantic-grading)
- [Workflow](#workflow)
- [How scoring works](#how-scoring-works)
- [Reports](#reports)
- [Test data](#test-data)
- [Safety and validation](#safety-and-validation)
- [Troubleshooting](#troubleshooting)

## Prerequisites

- Python 3.10+
- pip

## Project structure

```text
Assignment Grading Interface/
├── grading_app/
│   ├── app.py                     Flask web app and routes
│   ├── templates/index.html       UI template (Tailwind)
│   ├── active_assignment.json     Active manifest pointer
│   ├── manifest.py                Manifest loader/validator + marking modes
│   ├── config.py                  Dynamic config accessors
│   ├── grader.py                  Routing, scoring, and report writing
│   ├── semantic_code.py           Semantic code grading (correctness + practice)
│   ├── code_checks.py             Generic AST/regex behaviour rules
│   ├── ast_checks.py              Safe AST rule evaluation
│   └── upload_security.py         Upload and zip safety checks
├── assignments/
│   ├── technical_assignment_2024/
│   │   └── assignment_manifest.json
│   ├── sales_ops_demo/
│   │   └── assignment_manifest.json
│   └── ...
├── test_uploads/                  Sample benchmarks and student submissions
├── GRADING_INTERFACE_GUIDE.md
├── requirements.txt
└── README.md
```

Runtime directories (benchmarks, submissions, reports) are created per assignment manifest, for example:
- `benchmark_files_sales_demo/`
- `student_submissions_sales_demo/`
- `outputs/grading_reports_sales_demo/`

## Setup

### Windows (PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### macOS/Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run the app

```powershell
python grading_app/app.py
```

Open:
- `http://127.0.0.1:5000`

Confirm you are on the semantic engine by checking the header badge:
- **Engine 1.1-semantic**

## Manifest-driven configuration

Grading behaviour is defined in:
- `assignments/<assignment_name>/assignment_manifest.json`

The active manifest is read from:
- `grading_app/active_assignment.json`

Example:
```json
{
  "manifest_path": "assignments/sales_ops_demo/assignment_manifest.json"
}
```

Each manifest controls:
- assignment metadata (`assignment_id`, `title`, `version`)
- runtime directories (`benchmark_dir`, `submissions_dir`, `reports_dir`)
- upload extension allowlist (`allowed_extensions`)
- questions (`id`, `label`, `max_mark`, `marking_mode`, `compare_mode`, files)
- per-question `match_rules` and `code_marking` settings
- submission filename aliases (`submission_aliases`)
- shared behaviour rules (`code_checks`) using AST or regex engines

## Marking modes (semantic grading)

Each question uses a **`marking_mode`** that controls how submissions are scored. The UI shows a badge per question (Configured Questions) and per result row (Detailed Results).

| Marking mode | When to use | How it scores |
|---|---|---|
| `output_match` | CSV tables, XML outputs, images | Compares values/structure against the benchmark (not wording) |
| `semantic_code` | SQL, XSL, Python | Behaviour rules (correctness) + coding practice heuristics |
| `legacy_text` | Written answers (interim) | Normalised text similarity |
| `text_rubric` | Written answers (planned) | Rubric point coverage (not yet implemented) |
| `mixed` | Multi-file questions | Per-file mode (e.g. XSL = code, XML = output match) |

If `marking_mode` is omitted, it is inferred from `compare_mode`:
- `csv` / `xml` / `image` → `output_match`
- `code` → `semantic_code`
- `text` → `legacy_text`
- `mixed` → `mixed`

### Output match (`output_match`)

Use when the answer is data, not prose.

- **CSV:** column overlap, row counts, numeric tolerance (configurable via `match_rules`)
- **XML:** structure and values compared
- **Image:** binary match

Example manifest snippet:
```json
{
  "id": "q1",
  "marking_mode": "output_match",
  "compare_mode": "csv",
  "max_mark": 30,
  "match_rules": {
    "numeric_tolerance_pct": 1.0,
    "ignore_row_order": true
  },
  "files": [{ "benchmark": "clean_leads.csv" }]
}
```

### Semantic code (`semantic_code`)

Use when students may solve the problem with different code than the benchmark.

Total mark is split into two weighted parts (default **70% correctness / 30% practice**):

```
mark = (correctness × 0.7 + practice × 0.3) × max_mark
```

**Correctness** — does the submission satisfy required behaviours?
- Rules from `code_marking.correctness.rules`, or
- Inherited from manifest `code_checks` for that file type (e.g. `.sql` regex rules)

**Practice** — static coding quality checks:
- `comments` — has explanatory comments
- `no_select_star` — SQL does not use `SELECT *`
- `uses_aliases` — SQL uses `AS` column aliases
- `reasonable_length` — file is not excessively long
- `no_hardcoded_values` — limited hardcoded string filters in SQL

Example manifest snippet:
```json
{
  "id": "q3",
  "marking_mode": "semantic_code",
  "compare_mode": "code",
  "max_mark": 25,
  "code_marking": {
    "weights": { "correctness": 0.7, "practice": 0.3 },
    "correctness": {
      "method": "behavior_rules",
      "rules_from_code_checks": true
    },
    "practice": {
      "checks": ["comments", "no_select_star", "uses_aliases", "reasonable_length"]
    }
  },
  "files": [{ "benchmark": "pipeline_metrics.sql" }]
}
```

### Multi-file questions

When a question has multiple benchmark files, `max_mark` is **split evenly** across files. For example, a 25-mark question with an XSL file and an XML file awards up to 12.5 marks per file (100 marks total across the assignment).

## Workflow

1. **Configuration**
   - Select an existing manifest, or upload/activate a new one.
   - Check **Configured Questions** for marking mode badges.
   - Optionally reset test data (benchmarks, submissions, reports).
2. **Benchmarks**
   - Upload benchmark files per question, or load from manifest `seed_from` mappings.
3. **Student submission**
   - Upload student files (or zip) under a student name.
4. **Run grading**
   - Set mark scale and execute grading.
5. **Review/export**
   - Inspect **Student Summary** (totals + avg correctness/practice).
   - Inspect **Detailed Results** (per-file marking mode, correctness, practice, notes).
   - Download CSV reports.

## How scoring works

For each expected benchmark file:

1. Find the matching student file using aliases and suffix rules.
2. Determine `marking_mode` for that file.
3. Score using the appropriate grader:
   - **output_match** → value/structure comparison
   - **semantic_code** → behaviour rules + practice heuristics
   - **legacy_text** → text similarity
4. Assign `mark = score × per_file_max_mark`.

**Student Summary** shows:
- `total_mark` / `total_max` / `percentage`
- `avg_correctness` — average correctness across graded files
- `avg_practice` — average practice score across code files
- `missing_files` — benchmark filenames not submitted

**Detailed Results** shows per file:
- Marking mode badge (`output`, `code`, etc.)
- Correctness % and Practice % (where applicable)
- Combined score % and mark awarded
- Notes (e.g. which behaviour rules passed or failed)

Missing files receive `status = missing` and score `0`.

## Reports

Written to the active manifest `reports_dir`:

| File | Contents |
|---|---|
| `summary_report.csv` | Per-student, per-file grading rows (includes `marking_mode`, `correctness_score`, `practice_score`) |
| `student_totals.csv` | Aggregate totals per student |
| `code_checks.csv` | Separate structure-check results (regex/AST rules) |
| `summary_report.json` | Full payload used to rehydrate the UI |

## Test data

Sample benchmarks and student submissions for the sales ops demo assignment live under:
- `test_uploads/sales_ops_demo/benchmarks/`
- `test_uploads/sales_ops_demo/student_perfect_100/` — high scores (~96/100)
- `test_uploads/sales_ops_demo/student_goodish/` — mixed scores (~62/100)
- `test_uploads/sales_ops_demo/student_bad_1/` — weak SQL and partial files (~51/100)

To load benchmarks: use **Load Benchmarks From Solution** in the UI, or copy student folders into the active manifest `submissions_dir`.

## Safety and validation

- Python checks are static AST inspections (no import/exec of student code)
- SQL can be executed in a controlled in-memory SQLite fixture mode when `correctness.method` is set to `output_execution`
- XSLT can be executed against a fixture XML input when `correctness.method` uses `output_execution` with engine `xslt`
- Python execution-based correctness is not enabled yet (currently behavior-rule based)
- Uploads are restricted to manifest `allowed_extensions`
- Zip files are validated for unsafe paths and disallowed extensions
- Missing files degrade gracefully (no backend crash)

## Troubleshooting

- **UI does not show Engine 1.1-semantic**
  - Stop the Flask server and restart from this repo root: `python grading_app/app.py`
- **No grading results / empty tables**
  - Ensure benchmark files are loaded for the active manifest.
- **Scores look like plain text comparison**
  - Confirm the manifest question has `marking_mode: "semantic_code"` or `output_match` (manifest version `1.1+`).
  - Re-run grading after changing the manifest.
- **Max marks show 125 instead of 100**
  - Re-run grading with engine `1.1-semantic`; multi-file marks are now split per file.
- **Student uploads not visible**
  - Check active manifest `submissions_dir` in the Manifest Details panel.
- **Upload rejected**
  - File extension not in `allowed_extensions`.
- **Many `missing` rows**
  - Filenames do not match expected benchmark names/aliases.

---

For deep operational guidance (best practices, full troubleshooting matrix, and detailed explanations), use:
- `GRADING_INTERFACE_GUIDE.md`
