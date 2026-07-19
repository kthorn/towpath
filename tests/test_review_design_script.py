import os
import subprocess
import time
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "review_design.sh"


def test_review_design_uses_selected_model_and_writes_final_text(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "pi-args.txt"
    fake_pi = bin_dir / "pi"
    fake_pi.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {args_file}\n"
        "printf '%s\\n' 'CONVERGED'\n"
    )
    fake_pi.chmod(0o755)
    document = tmp_path / "design.md"
    document.write_text("# Design\n")
    output = tmp_path / "review.md"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    completed = subprocess.run(
        [
            str(SCRIPT),
            "--model",
            "opencode-go/kimi-k2.7-code",
            "--document",
            str(document),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_text() == "CONVERGED\n"
    args = args_file.read_text()
    assert "opencode-go/kimi-k2.7-code" in args
    assert f"@{document}" in args
    assert "--no-extensions" in args
    assert "--no-skills" in args
    assert "--no-context-files" in args
    assert "--no-tools" in args
    assert "read,grep,find,ls" not in args
    assert "Overpass retains parsed POIs" in args
    assert "production bulk England builds use a separate multi-pass POI accumulator" in args
    assert "GraphSpatialIndex" in args


def test_review_design_uses_random_same_directory_temp_file(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    mktemp_log = tmp_path / "mktemp.log"
    fake_mktemp = bin_dir / "mktemp"
    fake_mktemp.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$*\" >> {mktemp_log}\n"
        "exec /usr/bin/mktemp \"$@\"\n"
    )
    fake_mktemp.chmod(0o755)
    fake_pi = bin_dir / "pi"
    fake_pi.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' 'CONVERGED'\n"
    )
    fake_pi.chmod(0o755)
    document = tmp_path / "design.md"
    document.write_text("# Design\\n")
    output = tmp_path / "nested" / "review.md"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
    }

    completed = subprocess.run(
        [
            str(SCRIPT),
            "--model",
            "opencode-go/kimi-k2.7-code",
            "--document",
            str(document),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert output.read_text() == "CONVERGED\n"
    assert "review.md.tmp.XXXXXX" in mktemp_log.read_text()


def test_review_design_does_not_clobber_output_created_during_review(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    started = tmp_path / "started"
    release = tmp_path / "release"
    fake_pi = bin_dir / "pi"
    fake_pi.write_text(
        "#!/usr/bin/env bash\n"
        f"touch {started}\n"
        f"while [[ ! -f {release} ]]; do sleep 0.01; done\n"
        "printf '%s\\n' 'CONVERGED'\n"
    )
    fake_pi.chmod(0o755)
    document = tmp_path / "design.md"
    document.write_text("# Design\\n")
    output = tmp_path / "review.md"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    process = subprocess.Popen(
        [
            str(SCRIPT),
            "--model",
            "opencode-go/kimi-k2.7-code",
            "--document",
            str(document),
            "--output",
            str(output),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    deadline = time.monotonic() + 5
    while not started.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started.exists()
    output.write_text("competitor\\n")
    release.touch()
    stdout, stderr = process.communicate(timeout=5)

    assert process.returncode == 2, f"{stdout=} {stderr=}"
    assert output.read_text() == "competitor\\n"
    assert not list(output.parent.glob("review.md.tmp.*"))


def test_review_design_uses_current_completed_osm_poi_documents_by_default(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "pi-args.txt"
    fake_pi = bin_dir / "pi"
    fake_pi.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {args_file}\n"
        "printf '%s\\n' 'CONVERGED'\n"
    )
    fake_pi.chmod(0o755)
    output = tmp_path / "review.md"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    completed = subprocess.run(
        [str(SCRIPT), "--model", "opencode-go/kimi-k2.7-code", "--output", str(output)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    args = args_file.read_text()
    repo_root = Path(__file__).parents[1]
    assert f"@{repo_root}/docs/completed/2026-07-12-osm-poi-ingest-design.md" in args
    assert f"@{repo_root}/docs/completed/2026-07-14-osm-poi-multipass-memory-design.md" in args


def test_review_design_enables_repo_tools_only_when_requested(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "pi-args.txt"
    fake_pi = bin_dir / "pi"
    fake_pi.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {args_file}\n"
        "printf '%s\\n' 'CONVERGED'\n"
    )
    fake_pi.chmod(0o755)
    document = tmp_path / "design.md"
    document.write_text("# Design\n")
    output = tmp_path / "review.md"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    completed = subprocess.run(
        [
            str(SCRIPT),
            "--model",
            "opencode-go/glm-5.2",
            "--document",
            str(document),
            "--output",
            str(output),
            "--repo-tools",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    args = args_file.read_text()
    assert "read,grep,find,ls" in args
    assert "--no-tools" not in args


def test_review_design_supplies_every_selected_document(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    args_file = tmp_path / "pi-args.txt"
    fake_pi = bin_dir / "pi"
    fake_pi.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$@\" > {args_file}\n"
        "printf '%s\\n' 'CONVERGED'\n"
    )
    fake_pi.chmod(0o755)
    design = tmp_path / "design.md"
    design.write_text("# Design\n")
    implementation = tmp_path / "implementation.md"
    implementation.write_text("# Implementation\n")
    output = tmp_path / "review.md"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    completed = subprocess.run(
        [
            str(SCRIPT),
            "--model",
            "opencode-go/kimi-k2.7-code",
            "--document",
            str(design),
            "--document",
            str(implementation),
            "--output",
            str(output),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    args = args_file.read_text()
    assert f"@{design}" in args
    assert f"@{implementation}" in args


def test_review_design_times_out_stalled_model(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_pi = bin_dir / "pi"
    fake_pi.write_text("#!/usr/bin/env bash\nsleep 5\n")
    fake_pi.chmod(0o755)
    document = tmp_path / "design.md"
    document.write_text("# Design\n")
    output = tmp_path / "review.md"
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}

    completed = subprocess.run(
        [
            str(SCRIPT),
            "--model",
            "opencode-go/kimi-k2.7-code",
            "--document",
            str(document),
            "--output",
            str(output),
            "--timeout",
            "1",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=3,
    )

    assert completed.returncode == 124
    assert "timed out after 1 seconds" in completed.stderr
    assert not output.exists()
