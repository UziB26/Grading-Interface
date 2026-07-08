# Marking Modes Explained (Detailed)

This document explains exactly how grading works for each marking mode in the current engine implementation (`1.1-semantic`).

It describes:
- what each mode is for
- how scores are calculated
- which manifest settings control behavior
- current limitations and edge cases

---

## 1) Where Marking Mode Comes From

Each question in an assignment manifest can define:
- `marking_mode` (preferred, explicit)
- `compare_mode` (legacy comparer type)

If `marking_mode` is omitted, it is inferred from `compare_mode`:
- `csv`, `xml`, `image` -> `output_match`
- `code` -> `semantic_code`
- `text` -> `legacy_text`
- `mixed` -> `mixed`

For `mixed`, the app resolves mode per file suffix:
- `.csv`, `.xml`, `.png` -> `output_match`
- `.sql`, `.xsl`, `.xslt`, `.py` -> `semantic_code`
- anything else -> `legacy_text`

---

## 2) Scoring Pipeline (All Modes)

For each student:
1. For each question, load benchmark file(s).
2. Find matching submitted file using alias map + suffix.
3. Resolve marking mode for that file.
4. Score according to that mode.
5. Convert score to marks with:

`mark = score * per_file_max_mark`

If a question has multiple files, its question max is split evenly across files (with any rounding remainder added to the last file).

Missing file behavior:
- status = `missing`
- score = `0`
- mark = `0`

Error behavior:
- status = `error`
- score = `0`
- mark = `0`
- details in `notes`

---

## 3) Mode: `output_match`

Use this for output artifacts where values/structure matter more than wording:
- CSV data outputs
- XML outputs
- images

The system compares benchmark vs submission using file-aware logic.

### 3.1 CSV comparison

CSV score is a weighted combination:
- **20%** column compatibility
- **20%** row-count compatibility
- **60%** value similarity

Details:
- Reads both CSVs as strings (preserves values robustly).
- If columns differ, compares overlapping columns only.
- Numeric cells use tolerance:
  - tolerance = `abs(benchmark_value) * (numeric_tolerance_pct / 100)`
  - lower bounded by `1.0` in denominator logic already used by the code
- Non-numeric cells compare normalized text similarity.
- Optional row-order ignore via `match_rules.ignore_row_order` (default `true`).

Config knobs (`match_rules`):
- `numeric_tolerance_pct` (default `1.0`)
- `ignore_row_order` (default `true`)
- `require_column_names` (currently parsed, not enforced in grading logic yet)

### 3.2 XML comparison

XML is parsed and normalized into a structural text walk:
- local tag names
- sorted attributes
- trimmed node text

Then similarity is computed via sequence matching on normalized structure.

If XML parsing fails, it falls back to normalized text comparison.

### 3.3 Image comparison

Binary compare:
- exact byte match -> `1.0`
- otherwise -> `0.0`

### 3.4 Result fields for `output_match`

- `marking_mode`: `output_match`
- `correctness_score`: populated (same as combined score)
- `practice_score`: `null`
- `similarity`: combined score shown in UI
- `notes`: comparison details (e.g., row mismatch, XML compared)

---

## 4) Mode: `semantic_code`

Use this for code submissions where different implementations can still be correct.

Final semantic score:

`combined = correctness * correctness_weight + practice * practice_weight`

Default weights:
- correctness = `0.7`
- practice = `0.3`

If custom weights are provided, they are normalized to sum to 1.

### 4.1 Correctness component

Correctness is rule-based (behavior rules), not text-sim.

Rule source priority:
1. `question.code_marking.correctness.rules` (if provided)
2. manifest `code_checks` rules for that file suffix (if `rules_from_code_checks=true`)
3. no rules -> correctness defaults to `1.0`

Rule execution:
- `.py`: AST profile + AST rule evaluation
- non-`.py` code (`.sql`, `.xsl`, `.xslt`, etc.): regex rule evaluation

Score:
- `passed_rules / total_rules`

If `.py` has syntax error:
- correctness = `0.0`
- details include syntax error

If `correctness.method = "output_execution"`:
- SQL can be executed against SQLite fixtures and compared to benchmark-query output
- XSLT can be executed against a fixture XML input and compared to benchmark-transform output
- currently supported engines: `sqlite`, `xslt`
- output is compared by columns + rows + values (SQL) or normalized XML similarity (XSLT)
- if execution profile is missing/unsupported, correctness is `0.0` with explanatory notes

### 4.2 Practice component

Practice checks are static heuristics.

Default checks by suffix:
- `.sql`: `comments`, `no_select_star`, `uses_aliases`, `reasonable_length`
- `.py`, `.xsl`, `.xslt`: `comments`, `reasonable_length`

Available practice checks:
- `comments`
- `no_select_star`
- `uses_aliases`
- `reasonable_length`
- `no_hardcoded_values` (SQL-focused heuristic)

Practice score:
- `passed_checks / total_checks`

### 4.3 Result fields for `semantic_code`

- `marking_mode`: `semantic_code`
- `correctness_score`: behavior/rule score
- `practice_score`: practice heuristic score
- `similarity`: weighted combined score
- `notes`: concatenated correctness and practice details

---

## 5) Mode: `legacy_text`

Use this for current text-based marking where no rubric mode is set yet.

Normalization:
- strip whitespace per line
- drop empty lines
- compare normalized text with sequence matching

Score:
- similarity in `[0.0, 1.0]`

Result fields:
- `correctness_score` = similarity
- `practice_score` = `null`

This mode is sensitive to wording and ordering (even if meaning is close).

---

## 6) Mode: `text_rubric`

This mode exists in manifest/schema but is **not implemented yet** in grader logic.

Current behavior:
- status is marked `graded`
- score = `0.0`
- mark = `0.0`
- notes indicate rubric grading is not implemented

Do not enable this mode for production grading until rubric evaluator is added.

---

## 7) Mode: `mixed`

`mixed` is a dispatcher, not a scorer itself.

For each file in the question:
- resolve file suffix
- map to one of:
  - `output_match`
  - `semantic_code`
  - `legacy_text`

Marks are computed per file and summed into question/student totals.

---

## 8) Student Summary Metrics

After all file-level results are computed:
- `total_mark` = sum of awarded marks
- `total_max` = sum of file max marks
- `percentage` = `(total_mark / total_max) * 100`
- `avg_correctness` = average of non-null `correctness_score`
- `avg_practice` = average of non-null `practice_score`
- `missing_files` = comma-separated benchmark names with status `missing`

`code_structure_avg` is also reported separately from `code_checks.csv` and is independent of the semantic combined score.

---

## 9) Recommended Usage by Question Type

- Data tables / deterministic outputs -> `output_match`
- SQL/XSL/Python where equivalent solutions are valid -> `semantic_code`
- Written prose currently -> `legacy_text`
- Hybrid question with transform + output artifacts -> `mixed`

Avoid `text_rubric` until implemented.

---

## 10) Example Question Configs

### Output match (CSV)

```json
{
  "id": "q1",
  "label": "Clean Lead File",
  "max_mark": 30,
  "marking_mode": "output_match",
  "compare_mode": "csv",
  "match_rules": {
    "numeric_tolerance_pct": 1.0,
    "ignore_row_order": true
  },
  "files": [{ "benchmark": "clean_leads.csv" }]
}
```

### Semantic code (SQL)

```json
{
  "id": "q3",
  "label": "Pipeline SQL",
  "max_mark": 25,
  "marking_mode": "semantic_code",
  "compare_mode": "code",
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

### Mixed multi-file

```json
{
  "id": "q4",
  "label": "Lead XML Transform",
  "max_mark": 25,
  "marking_mode": "mixed",
  "compare_mode": "mixed",
  "files": [
    { "benchmark": "lead_transform.xsl" },
    { "benchmark": "leads_output.xml" }
  ]
}
```

---

## 11) Current Gaps / Future Work

1. `text_rubric` evaluator is not implemented yet.
2. `output_execution` is implemented for SQL (`sqlite`) and XSLT (`xslt`) execution profiles; Python runtime execution is still pending.
3. `require_column_names` is parsed in manifest but not enforced in CSV logic.

These are good candidates for the next grading-engine phase.
