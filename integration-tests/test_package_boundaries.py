import ast
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
