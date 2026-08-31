import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.network (live Overpass fetch)",
    )
    parser.addoption(
        "--run-bulk",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.bulk (pyosmium / osmium-tool needed)",
    )


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-network"):
        skip_network = pytest.mark.skip(reason="network test: pass --run-network to run")
        for item in items:
            if "network" in item.keywords:
                item.add_marker(skip_network)

    if not config.getoption("--run-bulk"):
        skip_bulk = pytest.mark.skip(reason="bulk test: pass --run-bulk to run")
        for item in items:
            if "bulk" in item.keywords:
                item.add_marker(skip_bulk)
    else:
        # Flag is set — still skip if pyosmium is not importable.
        pyosmium_available = True
        try:
            import osmium  # noqa: F401
        except ImportError:
            pyosmium_available = False
        if not pyosmium_available:
            skip_no_pyosmium = pytest.mark.skip(
                reason="pyosmium not installed: uv sync --extra bulk"
            )
            for item in items:
                if "bulk" in item.keywords:
                    item.add_marker(skip_no_pyosmium)
