from __future__ import annotations

import os
import shlex
import shutil
import signal
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SCRIPT = ROOT / "scripts" / "dev.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def _fake_server(label: str) -> str:
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail
label={shlex.quote(label)}
printf '%s %s\n' "$label" "$*" >> "$DEV_LOG"
printf '%s\n' "$BASHPID" > "$DEV_PID_DIR/$label.pid"
trap 'exit 0' TERM INT
while :; do sleep 0.05; done
"""


def _prepare_launcher(
    tmp_path: Path, uv_script: str, npm_script: str
) -> tuple[Path, Path, Path, dict[str, str]]:
    assert os.access(SOURCE_SCRIPT, os.X_OK)
    assert "set -Eeuo pipefail" in SOURCE_SCRIPT.read_text()

    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "dev.sh"
    shutil.copy2(SOURCE_SCRIPT, script)
    script.chmod(0o755)

    (tmp_path / "web").mkdir()
    artifact = tmp_path / "artifact.pkl"
    artifact.touch()
    enrichment = tmp_path / "boat-hire.csv"
    enrichment.write_text("record_type\n", encoding="utf-8")
    (tmp_path / ".env.sh").write_text(
        "\n".join(
            [
                f"export POUND_ARTIFACT_PATH={shlex.quote(str(artifact))}",
                f"export POUND_BOAT_HIRE_ENRICHMENT_PATH={shlex.quote(str(enrichment))}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uv", uv_script)
    _write_executable(fake_bin / "npm", npm_script)

    log = tmp_path / "commands.log"
    pid_dir = tmp_path / "pids"
    pid_dir.mkdir()
    environment = os.environ.copy()
    environment.pop("POUND_ARTIFACT_PATH", None)
    environment.pop("POUND_BOAT_HIRE_ENRICHMENT_PATH", None)
    environment.update(
        PATH=f"{fake_bin}{os.pathsep}{environment['PATH']}",
        DEV_LOG=str(log),
        DEV_PID_DIR=str(pid_dir),
    )
    return script, log, pid_dir, environment


def _coordinated_server(label: str) -> str:
    completion = (
        'touch "$DEV_UV_DONE"\nexit 0'
        if label == "uv"
        else 'while [[ ! -f "$DEV_UV_DONE" ]]; do sleep 0.01; done\ntouch "$DEV_NPM_DONE"\nexit 7'
    )
    return f"""#!/usr/bin/env bash
set -Eeuo pipefail
label={shlex.quote(label)}
printf '%s\n' "$label" >> "$DEV_LOG"
printf '%s\n' "$BASHPID" > "$DEV_PID_DIR/$label.pid"
while [[ ! -f "$DEV_RELEASE" ]]; do sleep 0.01; done
{completion}
"""


def _wait_for_file(path: Path) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {path}")


def _wait_for_commands(log: Path, expected: set[str], process: subprocess.Popen[str]) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if process.poll() is not None:
            output = process.stdout.read() if process.stdout is not None else ""
            raise AssertionError(f"launcher exited early with output:\n{output}")
        if log.exists() and expected <= set(log.read_text().splitlines()):
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for commands in {log}")


def _wait_for_exit(pid: int) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    raise AssertionError(f"process {pid} is still alive")


def test_dev_script_requires_enrichment_path_before_launching_servers(tmp_path: Path) -> None:
    server = """#!/usr/bin/env bash
set -Eeuo pipefail
printf 'started\\n' >> "$DEV_LOG"
"""
    script, log, _, environment = _prepare_launcher(tmp_path, server, server)
    env_file = tmp_path / ".env.sh"
    env_file.write_text(
        "\n".join(
            line
            for line in env_file.read_text().splitlines()
            if not line.startswith("export POUND_BOAT_HIRE_ENRICHMENT_PATH=")
        )
        + "\n",
        encoding="utf-8",
    )
    process = subprocess.run(
        [str(script)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    assert process.returncode == 1
    assert process.stdout == "dev: POUND_BOAT_HIRE_ENRICHMENT_PATH is not set\n"
    assert not log.exists()


def test_dev_script_requires_existing_enrichment_file_before_launching_servers(
    tmp_path: Path,
) -> None:
    server = """#!/usr/bin/env bash
set -Eeuo pipefail
printf 'started\\n' >> "$DEV_LOG"
"""
    script, log, _, environment = _prepare_launcher(tmp_path, server, server)
    enrichment = tmp_path / "missing.csv"
    env_file = tmp_path / ".env.sh"
    env_file.write_text(
        "\n".join(
            (
                f"export POUND_BOAT_HIRE_ENRICHMENT_PATH={shlex.quote(str(enrichment))}"
                if line.startswith("export POUND_BOAT_HIRE_ENRICHMENT_PATH=")
                else line
            )
            for line in env_file.read_text().splitlines()
        )
        + "\n",
        encoding="utf-8",
    )
    process = subprocess.run(
        [str(script)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )

    assert process.returncode == 1
    assert process.stdout == f"dev: boat-hire enrichment not found: {enrichment}\n"
    assert not log.exists()


def test_dev_script_starts_and_stops_both_servers(tmp_path: Path) -> None:
    script, log, pid_dir, environment = _prepare_launcher(
        tmp_path, _fake_server("uv"), _fake_server("npm")
    )
    process = subprocess.Popen(
        [str(script)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_commands(
            log,
            {
                "uv run uvicorn pound_web.app:app --host 127.0.0.1 --port 8000 --reload",
                "npm run dev -- --host 127.0.0.1 --port 5173",
            },
            process,
        )
        child_pids = [int((pid_dir / f"{label}.pid").read_text()) for label in ("uv", "npm")]

        process.send_signal(signal.SIGTERM)
        assert process.wait(timeout=5) == 143
        for child_pid in child_pids:
            _wait_for_exit(child_pid)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)


def test_dev_script_propagates_child_failure(tmp_path: Path) -> None:
    script, log, pid_dir, environment = _prepare_launcher(
        tmp_path, _coordinated_server("uv"), _coordinated_server("npm")
    )
    release = tmp_path / "release"
    uv_done = tmp_path / "uv.done"
    npm_done = tmp_path / "npm.done"
    environment.update(
        DEV_RELEASE=str(release),
        DEV_UV_DONE=str(uv_done),
        DEV_NPM_DONE=str(npm_done),
    )
    process = subprocess.Popen(
        [str(script)],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        _wait_for_commands(log, {"uv", "npm"}, process)
        process.send_signal(signal.SIGSTOP)
        release.touch()
        _wait_for_file(uv_done)
        _wait_for_file(npm_done)
        process.send_signal(signal.SIGCONT)
        assert process.wait(timeout=5) == 7
    finally:
        if process.poll() is None:
            process.send_signal(signal.SIGCONT)
            process.terminate()
            process.wait(timeout=5)
