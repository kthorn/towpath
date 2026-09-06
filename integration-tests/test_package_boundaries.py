import ast
import os
import re
import subprocess
from importlib.metadata import distribution
from pathlib import Path


def imports_under(root: Path):
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                yield path, node.module
            elif isinstance(node, ast.Import):
                for name in node.names:
                    yield path, name.name


def test_core_and_web_do_not_import_build():
    for package in ("pound-core", "pound-web"):
        root = Path("packages") / package / "src"
        if not root.exists():
            continue
        imports = [(path, module) for path, module in imports_under(root)]
        assert not [(path, module) for path, module in imports if module.startswith("pound_build")]


def test_core_metadata_has_no_web_or_build_dependencies():
    dependencies = distribution("pound-core").requires or []
    dependency_names = {
        match.group(0).lower()
        for requirement in dependencies
        if (match := re.match(r"[A-Za-z0-9_.-]+", requirement))
    }

    assert dependency_names.isdisjoint({"fastapi", "flask", "requests", "uvicorn"})


def test_core_only_environment_cannot_import_web(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    dist_dir = tmp_path / "dist"
    venv_dir = tmp_path / "venv"
    build = subprocess.run(
        ["uv", "build", "--package", "pound-core", "--wheel", "--out-dir", str(dist_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr

    create_venv = subprocess.run(
        ["uv", "venv", str(venv_dir)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert create_venv.returncode == 0, create_venv.stderr

    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    core_wheel = next(dist_dir.glob("pound_core-*.whl"))
    install = subprocess.run(
        ["uv", "pip", "install", "--python", str(venv_python), "--no-deps", str(core_wheel)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    isolated_env = os.environ.copy()
    isolated_env.pop("PYTHONPATH", None)
    isolated_env.pop("PYTHONHOME", None)
    result = subprocess.run(
        [str(venv_python), "-c", "import pound_web.app"],
        cwd=repo_root,
        env=isolated_env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "No module named 'pound_web'" in result.stderr


def test_web_namespace_is_provided_by_the_web_distribution():
    assert distribution("pound-web").metadata["Name"] == "pound-web"

    import pound_web.app

    assert pound_web.app.create_app
