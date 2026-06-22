import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--run-network",
        action="store_true",
        default=False,
        help="run tests marked @pytest.mark.network (live Overpass fetch)",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip_network = pytest.mark.skip(reason="network test: pass --run-network to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip_network)
