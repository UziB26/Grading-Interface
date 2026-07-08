# Assignments

Assignments are fully manifest-driven. Add or update `assignment_manifest.json` files under `assignments/` and activate one at runtime.

## Layout

```text
assignments/
  <assignment_name>/
    assignment_manifest.json
grading_app/
  active_assignment.json
```

## Activate assignment

### Option A: `active_assignment.json`

```json
{
  "manifest_path": "assignments/your_assignment/assignment_manifest.json"
}
```

### Option B: env var

```powershell
$env:GRADING_MANIFEST_PATH = "assignments/your_assignment/assignment_manifest.json"
python grading_app\app.py
```

## Manifest essentials

Top-level fields to define:
- `assignment_id`, `title`, `version`
- `benchmark_dir`, `submissions_dir`, `reports_dir`
- `allowed_extensions`
- `questions`
- `submission_aliases`
- `code_checks`

## Question-level fields

- `id`, `label`, `max_mark`
- `marking_mode` (recommended explicit)
- `compare_mode` (legacy/inference support)
- `files` with `benchmark` and optional `seed_from`
- optional `match_rules`
- optional `code_marking`
- optional `benchmark_points` (for `semantic_text`)

## Marking modes

- `output_match`: CSV/XML/image output comparison
- `semantic_code`: weighted correctness + practice
- `semantic_text`: Gemini semantic point coverage for prose
- `legacy_text`: deterministic text similarity
- `mixed`: per-file dispatch
- `text_rubric`: schema-only, not production-ready

## `code_marking` structure

- `weights`: correctness/practice split
- `correctness.method`: `behavior_rules` or `output_execution`
- `correctness.execution.engine`: `sqlite` or `xslt`
- `practice.method`: `rules`, `ai`, or `hybrid`
- `practice.checks`: optional explicit check list
- `practice.rules_weight` / `practice.ai_weight` for hybrid

## Minimal examples

### `semantic_text`

```json
{
  "id": "q2",
  "marking_mode": "semantic_text",
  "compare_mode": "text",
  "benchmark_points": "1) Root cause\n2) Evidence\n3) Recommendation",
  "files": [{ "benchmark": "executive_brief.md" }]
}
```

### `semantic_code` with SQL execution + hybrid practice

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
          { "table": "orders_fact", "path": "path/to/orders_fact.csv" }
        ]
      }
    },
    "practice": {
      "method": "hybrid",
      "rules_weight": 0.5,
      "ai_weight": 0.5
    }
  },
  "files": [{ "benchmark": "regional_kpi.sql" }]
}
```

## Code checks

`code_checks` define reusable suffix-level rules using:
- `engine: ast`
- `engine: regex`
- optional `inherit_from`

These can be inherited into `semantic_code` correctness when `rules_from_code_checks` is true.
