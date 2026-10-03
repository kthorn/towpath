"""Build-time tag overrides for confirmed upstream OSM data problems.

``data/overrides.json`` (repo root) maps ``w<way_id>`` / ``n<node_id>`` keys to
``{"reason": ..., "tags": {...}}``. The tags are injected before ingest
classification so an accidental upstream tag deletion cannot silently remove a
waterway section from the graph (e.g. the Grand Union through Milton Keynes,
OSM way 4571379 v77, changeset 187488255). Remove an entry once the upstream
OSM data is fixed.
"""

import json
from pathlib import Path

DEFAULT_OVERRIDES_PATH = Path("data/overrides.json")


def load_overrides(path: Path) -> dict[str, dict[str, str]]:
    """Load tag overrides. Keys are ``w<osm_id>`` / ``n<osm_id>``; keys starting
    with ``_`` are comments. A missing file means no overrides."""
    path = Path(path)
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, dict[str, str]] = {}
    for key, value in raw.items():
        if key.startswith("_"):
            continue
        tags = value.get("tags") if isinstance(value, dict) else value
        if not isinstance(tags, dict) or not tags:
            raise ValueError(f"override {key!r} must map to a non-empty tags object")
        result[key] = {str(tag_key): str(tag_value) for tag_key, tag_value in tags.items()}
    return result
