# Docker Sandbox Setup and Usage

This guide explains how to enable and use Docker-based execution sandboxing in the Assignment Grading Interface.

## What Docker Sandbox Does

When configured in a question's manifest:
- student code is executed in an isolated, disposable container
- benchmark code is executed in the same isolated environment
- outputs are compared for correctness scoring

Current supported languages in Docker sandbox:
- `python`
- `java`
- `cpp`

If Docker is unavailable, the app remains usable. Only Docker-based execution checks are affected.

---

## 1) Prerequisites

## Required
- Docker Desktop installed
- Docker daemon running
- Python dependency installed:
  - `docker>=6.1.3` (already in `requirements.txt`)

Install/update dependencies:

```powershell
python -m pip install -r requirements.txt
```

---

## 2) Windows Host Requirements

Docker Desktop needs host virtualization support and Windows virtualization features.

### A) Check CPU virtualization
- Open Task Manager -> Performance -> CPU
- Confirm `Virtualization: Enabled`

### B) Enable Windows features (Admin terminal required)

```powershell
bcdedit /set hypervisorlaunchtype auto
dism /online /enable-feature /featurename:VirtualMachinePlatform /all /norestart
dism /online /enable-feature /featurename:HypervisorPlatform /all /norestart
dism /online /enable-feature /featurename:Microsoft-Windows-Subsystem-Linux /all /norestart
```

Then reboot.

### C) Docker Desktop settings
- Use WSL2 engine
- Linux containers mode enabled

If your machine is managed (school/work), IT/admin may need to enable these settings.

---

## 3) Verify Docker Outside the App

Run these in terminal:

```powershell
docker version
docker info
```

If these fail, fix Docker Desktop first before app-level testing.

---

## 4) Verify Docker Inside the App

The UI shows:
- header badge: `Docker sandbox: available/unavailable`
- button: `Check Docker Sandbox Status`

Use the button to get detailed diagnostics.

---

## 5) Manifest Configuration (Docker Engine)

Use Docker sandbox under `code_marking.correctness.execution` with:
- `method: "output_execution"`
- `execution.engine: "docker"`

Example (Python):

```json
{
  "id": "q_python",
  "label": "Python Program",
  "max_mark": 20,
  "marking_mode": "semantic_code",
  "compare_mode": "code",
  "code_marking": {
    "weights": { "correctness": 0.8, "practice": 0.2 },
    "correctness": {
      "method": "output_execution",
      "execution": {
        "engine": "docker",
        "language": "python",
        "image": "python:3.10-alpine",
        "timeout_seconds": 8,
        "input_path": "test_uploads/python_exec_demo/fixtures/stdin.txt"
      }
    },
    "practice": {
      "method": "rules",
      "checks": ["comments", "reasonable_length"]
    }
  },
  "files": [
    { "benchmark": "sum_numbers.py" }
  ]
}
```

Notes:
- `language` can be omitted for known suffixes (`.py`, `.java`, `.cpp/.cc/.cxx`)
- `image` is optional (defaults are built in)
- `timeout_seconds` defaults to `8`
- `input_path` is optional

---

## 6) Pull Runtime Images (Recommended)

Pull once to avoid first-run delays:

```powershell
docker pull python:3.10-alpine
docker pull eclipse-temurin:17-alpine
docker pull gcc:13
```

---

## 7) Security Model in This Implementation

Containers are launched with:
- network disabled (`network_disabled=True`)
- memory limit (`mem_limit`)
- CPU quota (`cpu_quota`)
- non-root user (`user="nobody"`)
- disposable cleanup (`remove(force=True)` in teardown)
- execution timeout with forced kill

This is suitable for controlled assignment execution, but still review policies for high-risk environments.

---

## 8) Troubleshooting

## `Docker sandbox: unavailable` in UI
- Click `Check Docker Sandbox Status` and read the full message.

Common causes:
- Docker daemon not running
- virtualization/WSL2 not enabled
- Docker Desktop engine unhealthy
- user lacks permission/admin setup

## `ModuleNotFoundError: docker`
- Install dependency in the same Python environment:

```powershell
python -m pip install "docker>=6.1.3"
```

## `500 Server Error for http+docker://localhostpipe/version`
- Docker SDK found, daemon endpoint unhealthy
- Restart Docker Desktop
- ensure Linux containers + WSL2 engine
- verify `docker version` and `docker info`

## Image not found
- Pull the image listed in the error.

## Execution timeout
- Increase `timeout_seconds` in manifest for that question.

---

## 9) Operational Recommendation

Keep Docker execution optional per assignment/question:
- use Docker for untrusted full programs (Python/Java/C++)
- keep existing local engines (`sqlite`, `xslt`, local python execution) for lightweight workflows

This lets grading continue even when Docker is unavailable on restricted machines.
