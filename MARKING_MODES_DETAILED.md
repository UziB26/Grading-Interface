# Marking Modes Explained (Detailed)

This document describes exactly how scoring works in the current grading engine.

It covers:
- mode resolution
- score formulas
- manifest controls
- AI fallback behavior
- known limits

## 1) Marking mode resolution

Per question, use explicit `marking_mode` whenever possible.

Supported modes:
- `output_match`
- `semantic_code`
- `semantic_text`
- `legacy_text`
- `mixed`
- `text_rubric` (reserved placeholder; use `semantic_text`)

If omitted, mode is inferred from `compare_mode`:
- `csv`, `xml`, `image` -> `output_match`
- `code` -> `semantic_code`
- `text` -> `legacy_text`
- `mixed` -> `mixed`

For `mixed`, mode is resolved per file suffix:
- `.csv`, `.xml`, `.png` -> `output_match`
- `.sql`, `.xsl`, `.xslt`, `.py` -> `semantic_code`
- otherwise -> `legacy_text`

## 2) Global scoring pipeline

For each student and expected benchmark file:
1. Find submission using benchmark filename + aliases.
2. Resolve marking mode.
3. Compute score in `[0,1]`.
4. Convert to marks: `mark = score * per_file_max_mark`.

Multi-file questions split marks evenly across files (rounding remainder is applied to last file).

Status behavior:
- `graded`: normal result
- `missing`: file not found; score `0`
- `error`: grading failure; score `0`

## 3) `output_match`

Use for deterministic artifacts where output values/structure matter.

### 3.1 CSV

Weighted score:
- 20% column compatibility
- 20% row count compatibility
- 60% value similarity

`match_rules` options:
- `numeric_tolerance_pct` (default `1.0`)
- `ignore_row_order` (default `true`)
- `require_column_names` (parsed but not currently enforced)

### 3.2 XML

- Parse and normalize structure/text
- Compare normalized representation
- Fallback to normalized text compare on parse failure

### 3.3 Image

- Exact binary match `1.0`, else `0.0`

Result shape:
- `correctness_score` populated
- `practice_score` null
- `correctness_method` often `output-match`

## 4) `semantic_code`

Use where different implementations can still be correct.

Formula:

```text
combined = correctness * correctness_weight + practice * practice_weight
```

Default weights: correctness `0.7`, practice `0.3`.
Custom weights are normalized to sum to 1.

### 4.1 Correctness component

Configured by `code_marking.correctness.method`:

#### A) `behavior_rules`
Rule source priority:
1. `question.code_marking.correctness.rules`
2. manifest-level `code_checks` for suffix (if `rules_from_code_checks=true`)
3. no rules -> correctness defaults to `1.0`

Evaluation:
- `.py` -> AST profile/rule checks
- non-`.py` -> regex-based rule checks

#### B) `output_execution`
Currently supported engines:
- `sqlite` (SQL)
- `xslt` (XSL/XSLT)
- `python` (Python scripts)

SQL execution behavior:
- Load fixtures into SQLite tables
- Execute benchmark SQL and student SQL
- Compare resulting DataFrames by columns/rows/values

XSLT execution behavior:
- Apply benchmark and student transforms to fixture XML
- Compare normalized output similarity

Python execution behavior (security note):
- Runs the benchmark `.py` and the student `.py` with the same stdin input (from `execution.input_path`, if provided)
- Compares stdout similarity to the benchmark output
- Uses a short timeout, but **does not fully sandbox** the scripts (treat submissions as trusted, or run in an isolated environment/container)

If execution config is missing/invalid, correctness becomes `0.0` with explanation in notes.

### 4.2 Practice component

Configured by `code_marking.practice.method`:

- `rules`: static checks only
- `ai`: Gemini-only quality score, fallback to rules on failure
- `hybrid`: weighted blend of rules + AI, fallback to rules on failure

Practice checks available:
- `comments`
- `no_select_star`
- `uses_aliases`
- `reasonable_length`
- `no_hardcoded_values`

Default checks by suffix:
- `.sql`: comments, no_select_star, uses_aliases, reasonable_length
- `.py`, `.xsl`, `.xslt`: comments, reasonable_length

Hybrid formula:

```text
practice = rules_score * rules_weight + ai_score * ai_weight
```

### 4.3 Result fields

- `correctness_score`: correctness component
- `practice_score`: practice component
- `similarity`: weighted combined score
- `correctness_method`: `rule-based` or `execution-based`
- `practice_method`: `rules`, `ai`, `hybrid`, or `rules-fallback`

## 5) `semantic_text`

Use for prose answers where semantic coverage is required.

Behavior:
- Build prompt with `benchmark_points` (preferred), benchmark text, and student text
- Gemini returns structured `score` + `feedback`
- Result uses `correctness_method = ai-semantic`

Fallback:
- On AI failure (missing key, auth, quota, request error), falls back to normalized text similarity
- Fallback label: `correctness_method = fallback-text`

## 6) `legacy_text`

Normalized text similarity mode.

Normalization:
- trim line whitespace
- remove empty lines
- sequence similarity on normalized content

Use as deterministic backup when semantic AI is unavailable.

## 7) `mixed`

Dispatcher mode for multi-file questions.

Each file gets its own derived mode based on suffix and is scored independently.
Per-file marks sum into the question total.

## 8) `text_rubric`

Reserved placeholder mode in schema. Use `semantic_text` for text grading.
Current `text_rubric` behavior returns zero score with explanatory notes.

## 9) Gemini integration behavior

Environment variables:
- `GEMINI_API_KEY` (required for AI paths)
- `GEMINI_MODEL` (optional; default `gemini-2.5-flash-lite`)

Runtime details:
- `.env` is loaded from project root with override enabled
- API key is read each call
- short retry on rate-limit style failures

Fallback safety guarantees:
- `semantic_text` -> `fallback-text`
- practice `ai`/`hybrid` -> `rules-fallback`

## 10) Recommended mode selection

- CSV/XML/image outputs -> `output_match`
- SQL/XSL/Python tasks -> `semantic_code`
- Prose with required key points -> `semantic_text`
- Legacy prose only -> `legacy_text`
- Transform + artifact mixed questions -> `mixed`

## 11) Known gaps

1. `text_rubric` remains a reserved placeholder mode (not an active grading pipeline).
2. `require_column_names` is parsed but not yet enforced in CSV scoring.
