# Assignment Grading Interface

Standalone grading platform extracted from the main assignment repository.

For a complete, step-by-step operating guide, see:
- `GRADING_INTERFACE_GUIDE.md`

## Contents

- [Prerequisites](#prerequisites)
- [Project structure](#project-structure)
- [Setup](#setup)
- [Run the app](#run-the-app)
- [Manifest-driven configuration](#manifest-driven-configuration)
- [Workflow](#workflow)
- [How grading works](#how-grading-works)
- [Reports](#reports)
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
│   ├── manifest.py                Manifest loader/validator
│   ├── config.py                  Dynamic config accessors
│   ├── grader.py                  Comparison + scoring + reports
│   ├── code_checks.py             Generic AST/regex code checks
│   ├── ast_checks.py              Safe AST rule evaluation
│   └── upload_security.py         Upload and zip safety checks
├── assignments/
│   ├── technical_assignment_2024/
│   │   └── assignment_manifest.json
│   ├── sales_ops_demo/
│   │   └── assignment_manifest.json
│   └── ...
├── GRADING_INTERFACE_GUIDE.md
├── requirements.txt
└── README.md
```

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

## Manifest-driven configuration

This interface is fully manifest-driven. Grading behavior comes from:
- `assignments/<assignment_name>/assignment_manifest.json`

Active manifest is read from:
- `grading_app/active_assignment.json`

Example:
```json
{
  "manifest_path": "assignments/technical_assignment_2024/assignment_manifest.json"
}
```

Each manifest controls:
- assignment metadata (`assignment_id`, `title`, `version`)
- runtime directories (`benchmark_dir`, `submissions_dir`, `reports_dir`)
- upload extension allowlist (`allowed_extensions`)
- questions (`id`, `label`, `max_mark`, `compare_mode`, files)
- submission filename aliases (`submission_aliases`)
- code checks (`code_checks`) using AST or regex engines

## Workflow

1. **Configuration**
   - Select an existing manifest, or upload/activate a new one.
   - Optionally reset test data (benchmarks, submissions, reports).
2. **Benchmarks**
   - Upload benchmark files per question, or load from manifest `seed_from` mappings.
3. **Student submission**
   - Upload student files (or zip) under a student name.
4. **Run grading**
   - Set mark scale and execute grading.
5. **Review/export**
   - Inspect summary tables and download CSV reports.

## How grading works

### Compare modes

- `text`: normalized text similarity
- `csv`: CSV structure/value comparison
- `xml`: XML structure/value comparison
- `code`: text similarity for code artifacts
- `mixed`: per-file mode in same question
- `image`: binary comparison

### Scoring

For each expected benchmark file:
1. match student file using aliases and suffix
2. compute similarity in `[0, 1]`
3. assign `mark = similarity * max_mark`

`Student Summary` percentage is:

`(total_mark / total_max) * 100`

Missing files are marked with `status = missing` and score `0`.

## Reports

Written to active manifest `reports_dir`:

- `summary_report.csv` - per-student, per-file grading rows
- `student_totals.csv` - total marks per student
- `code_checks.csv` - code structure checks
- `summary_report.json` - full payload used to rehydrate UI

## Safety and validation

- Python checks are static AST inspections (no import/exec of student code)
- Uploads are restricted to manifest `allowed_extensions`
- Zip files are validated for unsafe paths and disallowed extensions
- Missing files degrade gracefully (no backend crash)

## Troubleshooting

- **No grading results / empty tables**
  - Ensure active manifest has benchmark files loaded.
- **Student uploads not visible**
  - Check active manifest `submissions_dir` in Manifest Details panel.
- **Upload rejected**
  - File extension not in `allowed_extensions`.
- **Many `missing` rows**
  - Filenames do not match expected benchmark names/aliases.
- **Manifest activation fails**
  - Validate JSON schema/fields in uploaded manifest.

---

For deep operational guidance (best practices, full troubleshooting matrix, and detailed explanations), use:
- `GRADING_INTERFACE_GUIDE.md`
