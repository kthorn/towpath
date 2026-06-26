"""Serialize/load the built graph artifact (design §4.4).

Pickle for the NetworkX first cut (design says pickle or PostGIS). The artifact
is gitignored (like pound/data/); tests build it into a tmp path. Not a long-
term portable format — revisit at the scale scope. No network.
"""

import pickle
from datetime import UTC, datetime
from pathlib import Path


def save_artifact(graph, path: Path, metadata: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        **metadata,
        "built_at": metadata.get("built_at", datetime.now(UTC).isoformat()),
    }
    with open(path, "wb") as f:
        pickle.dump({"graph": graph, "metadata": meta}, f)


def load_artifact(path: Path) -> tuple:
    with open(path, "rb") as f:
        blob = pickle.load(f)
    return blob["graph"], blob["metadata"]
