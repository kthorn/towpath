import ast
import re
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


def test_web_namespace_is_provided_by_the_web_distribution():
    assert distribution("pound-web").metadata["Name"] == "pound-web"

    import pound_web.app

    assert pound_web.app.create_app
