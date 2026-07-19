import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "codex_worker.sh"


def test_codex_worker_uses_writable_private_home_and_preserves_arguments(tmp_path):
    source_home = tmp_path / "source"
    source_home.mkdir()
    (source_home / "auth.json").write_text("auth")
    (source_home / "config.toml").write_text("config")
    (source_home / "luna-high.config.toml").write_text("profile")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "capture.txt"
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        f"printf 'home=%s\\n' \"$CODEX_HOME\" > {capture}\n"
        f"printf 'args=%s\\n' \"$*\" >> {capture}\n"
    )
    fake_codex.chmod(0o755)

    worker_home = tmp_path / "worker"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CODEX_SOURCE_HOME": str(source_home),
        "CODEX_WORKER_HOME": str(worker_home),
    }
    completed = subprocess.run(
        [str(SCRIPT), "exec", "--profile", "luna-high", "task"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert capture.read_text() == (
        f"home={worker_home}\nargs=exec --profile luna-high task\n"
    )
    assert (worker_home / "auth.json").read_text() == "auth"
    assert (worker_home / "config.toml").read_text() == "config"
    assert (worker_home / "luna-high.config.toml").read_text() == "profile"
    assert worker_home.stat().st_mode & 0o777 == 0o700
    assert (worker_home / "auth.json").stat().st_mode & 0o777 == 0o600


def test_codex_worker_default_home_is_unique_and_cleaned(tmp_path):
    source_home = tmp_path / "source"
    source_home.mkdir()
    (source_home / "auth.json").write_text("auth")
    (source_home / "config.toml").write_text("config")

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "homes.txt"
    fake_codex = bin_dir / "codex"
    fake_codex.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$CODEX_HOME\" >> {capture}\n"
    )
    fake_codex.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CODEX_SOURCE_HOME": str(source_home),
        "TMPDIR": str(tmp_path / "tmp"),
    }

    for _ in range(2):
        completed = subprocess.run(
            [str(SCRIPT), "task"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr

    homes = capture.read_text().splitlines()
    assert len(homes) == 2
    assert len(set(homes)) == 2
    assert all(not Path(home).exists() for home in homes)
