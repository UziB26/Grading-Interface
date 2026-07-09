"""Docker-backed code execution sandbox for untrusted submissions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DockerStatus:
    available: bool
    message: str


@dataclass(frozen=True)
class DockerRunResult:
    ok: bool
    output: str


_LANGUAGE_PROFILES = {
    "python": {
        "image": "python:3.10-alpine",
        "filename": "main.py",
        "run_command": "python /workspace/main.py",
    },
    "java": {
        "image": "eclipse-temurin:17-alpine",
        "filename": "Main.java",
        "run_command": "javac /workspace/Main.java && java -cp /workspace Main",
    },
    "cpp": {
        "image": "gcc:13",
        "filename": "main.cpp",
        "run_command": "g++ -O2 /workspace/main.cpp -o /workspace/main && /workspace/main",
    },
}


def get_docker_status() -> DockerStatus:
    """Return current Docker sandbox availability and a human-readable reason."""
    try:
        import docker
    except Exception as exc:  # noqa: BLE001
        return DockerStatus(
            available=False,
            message=f"Docker SDK missing: {exc}. Install with python -m pip install docker>=6.1.3",
        )

    candidates = [
        ("default-env", None),
        ("windows-pipe", "npipe:////./pipe/docker_engine"),
        ("desktop-linux-pipe", "npipe:////./pipe/dockerDesktopLinuxEngine"),
    ]
    last_error: Exception | None = None
    for label, base_url in candidates:
        try:
            client = docker.from_env() if base_url is None else docker.DockerClient(base_url=base_url)
            client.ping()
            return DockerStatus(available=True, message=f"Docker daemon reachable ({label})")
        except docker.errors.DockerException as exc:
            last_error = exc
            continue

    if last_error is not None:
        return DockerStatus(
            available=False,
            message=(
                "Docker unavailable: "
                f"{last_error}. Ensure Docker Desktop is running and Linux containers are enabled."
            ),
        )
    return DockerStatus(
        available=False,
        message="Docker unavailable: unknown error while probing daemon.",
    )


def run_code_in_sandbox(
    *,
    code: str,
    language: str,
    stdin_text: str = "",
    timeout_seconds: int = 8,
    image_override: str | None = None,
    mem_limit: str = "128m",
    cpu_quota: int = 50000,
) -> DockerRunResult:
    """Execute code inside a disposable Docker container."""
    status = get_docker_status()
    if not status.available:
        return DockerRunResult(ok=False, output=status.message)

    import docker

    profile = _LANGUAGE_PROFILES.get(language)
    if profile is None:
        return DockerRunResult(ok=False, output=f"Unsupported sandbox language: {language}")

    client = docker.from_env()
    image = image_override or profile["image"]
    filename = profile["filename"]
    run_command = profile["run_command"]
    stdin_block = ""
    stdin_redirect = ""
    if stdin_text:
        stdin_block = 'cat > /workspace/stdin.txt <<"CURSOR_STDIN"\n{stdin}\nCURSOR_STDIN\n'.format(
            stdin=stdin_text
        )
        stdin_redirect = " < /workspace/stdin.txt"
    command = (
        "sh -c 'cat > /workspace/{fname} <<\"CURSOR_EOF\"\n{code}\nCURSOR_EOF\n"
        "{stdin_block}{run_cmd}{stdin_redirect}'"
    ).format(
        fname=filename,
        code=code,
        stdin_block=stdin_block,
        run_cmd=run_command,
        stdin_redirect=stdin_redirect,
    )

    container = None
    try:
        container = client.containers.run(
            image=image,
            command=command,
            remove=False,
            detach=True,
            network_disabled=True,
            mem_limit=mem_limit,
            cpu_quota=cpu_quota,
            environment={"PYTHONUNBUFFERED": "1"},
            working_dir="/workspace",
            stdin_open=False,
            tty=False,
            user="nobody",
            tmpfs={"/workspace": "rw,noexec,nosuid,size=64m"},
            nano_cpus=None,
        )
        try:
            result = container.wait(timeout=timeout_seconds)
        except Exception:
            container.kill()
            return DockerRunResult(
                ok=False,
                output=f"Execution Error: timed out after {timeout_seconds}s",
            )

        exit_code = int(result.get("StatusCode", 1))
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="ignore").strip()
        if exit_code != 0:
            return DockerRunResult(ok=False, output=f"Execution Error: {logs or f'exit code {exit_code}'}")
        return DockerRunResult(ok=True, output=logs)
    except docker.errors.ImageNotFound:
        return DockerRunResult(
            ok=False,
            output=f"Sandbox image '{image}' not found locally. Pull it first with Docker.",
        )
    except docker.errors.DockerException as exc:
        return DockerRunResult(
            ok=False,
            output=f"Docker unavailable: {exc}. Ensure Docker Desktop is running.",
        )
    except Exception as exc:  # noqa: BLE001
        return DockerRunResult(ok=False, output=f"System Error: {exc}")
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except Exception:
                pass


def run_python_in_sandbox(
    script_code: str,
    *,
    timeout_seconds: int = 8,
    image_override: str | None = None,
) -> DockerRunResult:
    """Backwards-compatible helper for python-only sandboxes."""
    return run_code_in_sandbox(
        code=script_code,
        language="python",
        timeout_seconds=timeout_seconds,
        image_override=image_override,
    )
