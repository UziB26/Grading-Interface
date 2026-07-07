# Assignments

Each assignment is defined by a manifest JSON file. The grading app loads the active manifest at runtime — no Python code changes are required for a new assignment.

## Layout

```text
assignments/
  technical_assignment_2024/
    assignment_manifest.json    # Questions, marks, aliases, code-check rules
grading_app/
  active_assignment.json        # Points to the manifest in use
benchmark_files/                # Solution files (path configurable in manifest)
```

## Switching assignments

**Option A — edit `grading_app/active_assignment.json`:**

```json
{
  "manifest_path": "assignments/your_new_assignment/assignment_manifest.json"
}
```

**Option B — environment variable:**

```powershell
$env:GRADING_MANIFEST_PATH = "assignments/your_new_assignment/assignment_manifest.json"
python grading_app\app.py
```

## Creating a new manifest

Copy `technical_assignment_2024/assignment_manifest.json` as a template and update:

| Section | Purpose |
|---------|---------|
| `questions` | Question id, label, max marks, compare mode, benchmark file names |
| `submission_aliases` | Alternate filenames students may submit |
| `code_checks` | Per-extension AST or regex rules |
| `allowed_extensions` | Upload whitelist |
| `benchmark_dir` | Where solution files live |

### Compare modes

`text`, `csv`, `xml`, `image`, `code`, or `mixed` (per-file suffix in mixed questions).

### Code-check rule types (AST engine)

| `type` | Manifest fields | Checks for |
|--------|-----------------|------------|
| `import_module` | `modules` | `import pandas` / `from pandas` |
| `token_match` | `tokens` | Names, attributes, strings, calls across the AST |
| `name` | `names` | Variable names |
| `function_name` | `names` | Defined functions |
| `call_name` | `names` | Function/method calls |
| `attribute` | `names` | Attribute access |
| `string_contains` | `tokens` | Substrings in string literals |

### Code-check rules (regex engine)

```json
{"label": "uses distinct count", "pattern": "COUNT\\s*\\(\\s*DISTINCT"}
```

Use `inherit_from` to share rules between extensions (e.g. `.xslt` inheriting `.xsl`).
