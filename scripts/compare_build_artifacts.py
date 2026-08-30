"""Compare two Pound graph artifacts while ignoring build-specific identifiers."""

import argparse
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pound.graph.artifact import GraphArtifact, load_artifact

_IGNORED_METADATA_FIELDS = {"artifact_revision", "built_at"}


def _normalized(value: Any) -> Any:
    if isinstance(value, Mapping):
        return tuple(sorted((key, _normalized(item)) for key, item in value.items()))
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(_normalized(item) for item in value))
    if isinstance(value, (list, tuple)):
        return tuple(_normalized(item) for item in value)
    return value


def _nodes(artifact: GraphArtifact) -> dict:
    return {
        node_id: _normalized(attributes) for node_id, attributes in artifact.graph.nodes(data=True)
    }


def _edges(artifact: GraphArtifact) -> dict:
    return {
        (min(u, v), max(u, v)): _normalized(attributes)
        for u, v, attributes in artifact.graph.edges(data=True)
    }


def _pois(artifact: GraphArtifact) -> tuple:
    return tuple(_normalized(poi.model_dump(mode="json")) for poi in artifact.pois)


def _metadata(artifact: GraphArtifact) -> Any:
    retained = {
        key: value
        for key, value in artifact.metadata.items()
        if key not in _IGNORED_METADATA_FIELDS
    }
    return _normalized(retained)


def compare_artifacts(before: GraphArtifact, after: GraphArtifact) -> list[str]:
    """Return the artifact sections that differ, in stable reporting order."""
    sections = (
        ("graph nodes", _nodes(before), _nodes(after)),
        ("graph edges", _edges(before), _edges(after)),
        ("pois", _pois(before), _pois(after)),
        ("metadata", _metadata(before), _metadata(after)),
    )
    return [
        f"{name} differ"
        for name, before_value, after_value in sections
        if before_value != after_value
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    args = parser.parse_args(argv)

    mismatches = compare_artifacts(load_artifact(args.before), load_artifact(args.after))
    for mismatch in mismatches:
        print(mismatch, file=sys.stderr)
    return 1 if mismatches else 0


if __name__ == "__main__":
    raise SystemExit(main())
