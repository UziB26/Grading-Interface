# Grading Interface Guide

This document is the single, end-to-end operating guide for the grading interface in this repository.

Use it as your reference for:
- first-time setup
- loading or switching assignments
- uploading benchmarks and student work
- running grading and interpreting results
- resetting test data safely
- troubleshooting common problems

---

## 1) What This Interface Does

The grading app is a local Flask web application that compares uploaded student files against benchmark files and produces scoring reports.

It is **manifest-driven**, which means:
- grading rules are defined in an assignment manifest JSON file
- the UI and backend adapt to the active manifest
- new assignments can be introduced without changing Python code

Core capabilities:
- Benchmark management per assignment
- Student file / zip uploads
- Comparison-based grading (CSV/text/XML/code)
- Code structure checks (AST and regex rules from manifest)
- Summary and detailed reports export
- Runtime manifest switching and manifest upload
- One-click reset of test data

---

## 2) Relevant Folders and Files

From repo root:

- `grading_app/app.py` - Flask routes and orchestration
- `grading_app/templates/index.html` - UI template
- `grading_app/manifest.py` - manifest loading/validation and active manifest handling
- `grading_app/grader.py` - grading engine + report writing
- `grading_app/code_checks.py` - generic code check execution
- `grading_app/ast_checks.py` - AST-based rule evaluation (safe static analysis)
- `grading_app/upload_security.py` - upload and zip safety checks
- `grading_app/active_assignment.json` - points to the active manifest
- `assignments/<assignment_name>/assignment_manifest.json` - assignment definition

Manifest-configured runtime directories (examples):
- benchmarks directory
- submissions directory
- reports directory

These are controlled by:
- `benchmark_dir`
- `submissions_dir`
- `reports_dir`
inside the active manifest.

---

## 3) Quick Start (First Run)

1. Create and activate a virtual environment.
2. Install dependencies:
   - `pip install -r requirements.txt`
3. Start app:
   - `python grading_app/app.py`
4. Open:
   - `http://127.0.0.1:5000`

You should see sections for:
- Configuration
- Benchmarks
- Student Submission
- Run Grading
- tables/reports (after grading)

---

## 4) How the Manifest System Works

The active assignment is read from:
- `grading_app/active_assignment.json`

Example:
```json
{
  "manifest_path": "assignments/technical_assignment_2024/assignment_manifest.json"
}
```

The manifest controls:
- assignment metadata (`assignment_id`, `title`, `version`)
- allowed upload extensions
- question list (id, label, max marks, compare mode, benchmark files)
- submission aliases (alternate filenames accepted)
- code checks per extension (`.py`, `.sql`, `.xsl`, etc.)

### Compare modes
- `text` - normalized text similarity
- `csv` - column/row/value-aware CSV comparison
- `xml` - structure/value-aware XML comparison
- `code` - text-based comparison for code files
- `mixed` - per-file behavior by suffix in one question
- `image` - binary compare

### Code check engines
- `ast` - static AST rules (safe; no importing or executing student code)
- `regex` - read-only pattern matching rules

---

## 5) Standard Daily Workflow

### Step A - Confirm Active Manifest
In **Configuration**:
- check the active manifest dropdown
- check the **Manifest Details** panel (version, paths, rule counts, allowed extensions)

### Step B - Load Benchmarks
You can either:
- click **Load Benchmarks From Solution** (copies files from `seed_from` entries in manifest), or
- upload benchmark files manually in the Benchmarks card

Important:
- grading cannot work if benchmark files are missing
- if no benchmark files appear in the list, load/upload them first

### Step C - Upload Student Submission
In **Student Submission**:
- enter student name
- upload one or multiple files, or a zip

Zip uploads are validated for:
- unsafe paths (zip-slip prevention)
- extension allowlist

### Step D - Run Grading
In **Run Grading**:
- choose `mark_scale` (default `1.0`)
- click **Run Grading**

The button changes to `Processing...` and is disabled during submit to prevent double runs.

### Step E - Review Output
Use on-page tables:
- Student Summary
- Detailed Results
- Code Structure Checks

Download reports:
- `summary_report.csv`
- `student_totals.csv`
- `code_checks.csv`

---

## 6) Understanding Every Section in the UI

## Configuration

### A) Switch Manifest
- Lists manifests discovered under `assignments/**/assignment_manifest.json`
- Selecting one and activating updates the app immediately

### B) Upload and Activate Manifest
- Upload a new manifest JSON directly from browser
- Provide assignment folder slug (target under `assignments/`)
- Optional benchmark zip import
- Manifest is validated before activation

### C) Reset Test Data
Reset options:
- all
- benchmarks only
- submissions only
- reports only

Use this when you need clean-room retesting.

### D) Manifest Details Panel
Shows:
- active manifest path
- assignment version
- benchmark/submission/report directories
- allowed extensions
- question count and total marks
- code-check table (suffix, engine, rule count, inheritance)

---

## Benchmarks

Uploads benchmark files into the active manifest benchmark directory.

Tips:
- Use question selector that matches manifest question IDs
- Upload exact benchmark filenames where possible
- For new assignments, prefer loading from `seed_from` if available

---

## Student Submission

Stores files under active manifest submissions directory.

Behavior:
- student name maps to one folder
- re-upload with same student name replaces previous folder
- zip extraction keeps nested structure

---

## Run Grading

Runs grading for all student directories in active submissions directory.

`mark_scale`:
- `1.0` = full manifest max marks
- `0.5` = half marks globally
- `2.0` = doubles max marks globally

---

## 7) How Scoring Is Calculated

For each benchmark file:
1. find matching student file using filename aliases and suffix constraints
2. run compare-mode logic
3. compute similarity score `[0.0, 1.0]`
4. mark = `similarity * max_mark_for_that_item`

Question totals roll into student totals.

### Student Summary fields
- `total_mark` - sum of all awarded marks
- `total_max` - sum of all max marks attempted in run
- `percentage` - `(total_mark / total_max) * 100`
- `missing_files` - comma-separated missing benchmark filenames
- `code_structure_avg` - average structure check score (if checks exist)

### Detailed Results fields
- `status`:
  - `graded` - compared successfully
  - `missing` - expected file not submitted / unavailable
  - `error` - comparison failed for technical reason

---

## 8) Code Checks Explained

Code checks are separate from raw file similarity and come from manifest.

Examples:
- SQL: verify `COUNT(DISTINCT ...)`, `GROUP BY`, domain filters
- XSL: verify templates, expected mapping tokens
- Python: AST rules on imports/tokens/functions (static only)

These checks appear in `code_checks.csv` and in the UI table.

---

## 9) Report Files

Written to active manifest `reports_dir`:

1. `summary_report.csv`
   - one row per student+benchmark comparison
2. `student_totals.csv`
   - one row per student aggregate
3. `code_checks.csv`
   - one row per checked code file
4. `summary_report.json`
   - full structured payload for UI reload

---

## 10) Testing from Scratch (Recommended Procedure)

1. Go to Configuration -> **Reset Test Data**
2. Select `all` and confirm
3. Verify active manifest in details panel
4. Load/upload benchmarks
5. Upload student samples
6. Run grading
7. Download CSV reports for validation

---

## 11) Common Problems and Fixes

### Problem: “Not grading” or blank results
Cause:
- benchmark directory is empty for active manifest
Fix:
- load benchmarks from solution or upload benchmark files first

### Problem: Student uploads not visible
Cause:
- active manifest points to a different submissions directory
Fix:
- check Manifest Details -> `submissions_dir`

### Problem: Upload rejected
Cause:
- file extension not in manifest `allowed_extensions`
Fix:
- update manifest allowlist or upload allowed types only

### Problem: Zip upload fails
Cause:
- disallowed extension in zip, or unsafe path inside zip
Fix:
- clean zip contents and retry

### Problem: “Missing” statuses
Cause:
- required benchmark filename not found in student submission
Fix:
- use expected filenames or configure aliases in manifest

### Problem: Manifest activation fails
Cause:
- invalid JSON or invalid manifest schema fields
Fix:
- validate manifest structure against working examples

---

## 12) Creating a New Assignment (No Code Changes)

1. Copy an existing manifest as template:
   - `assignments/technical_assignment_2024/assignment_manifest.json`
2. Update:
   - assignment metadata
   - runtime directories
   - questions/files/max marks
   - aliases
   - code checks
3. Place manifest in:
   - `assignments/<new_name>/assignment_manifest.json`
4. Activate via UI Configuration or `active_assignment.json`
5. Upload/load benchmarks
6. Start grading

---

## 13) Safety Model (Important)

- No execution of student scripts for grading logic
- Python checks are static AST inspections
- Uploads are extension-restricted
- Zip extraction validates paths and file types
- Missing files degrade gracefully (no hard crash)

---

## 14) Operational Best Practices

- Keep one manifest per assignment under `assignments/`
- Use dedicated dirs per assignment (`benchmark_dir`, `submissions_dir`, `reports_dir`)
- Version manifests (`version` field) and keep change notes
- Maintain stable benchmark filenames
- Keep aliases minimal and explicit
- Reset data before formal grading cycles
- Export reports after each run for audit trail

---

## 15) Command-Line Reference

Run app:
```powershell
python grading_app/app.py
```

Set manifest via env var (session-scoped):
```powershell
$env:GRADING_MANIFEST_PATH = "assignments/your_assignment/assignment_manifest.json"
python grading_app/app.py
```

---

## 16) Where to Look in Code

- Manifest model/validation: `grading_app/manifest.py`
- Grading and reports: `grading_app/grader.py`
- Code checks: `grading_app/code_checks.py`, `grading_app/ast_checks.py`
- Upload security: `grading_app/upload_security.py`
- UI routes: `grading_app/app.py`
- UI layout: `grading_app/templates/index.html`

---

If you want a shorter “operator quick card” version of this guide (1–2 pages), you can keep this as the master doc and generate a condensed companion file.
