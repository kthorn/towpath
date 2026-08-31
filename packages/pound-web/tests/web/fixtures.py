"""Shared test payload writers for the web package."""

import pickle
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import networkx as nx
from pound.artifact import ROUTING_ARTIFACT_SCHEMA_VERSION
from pound.catalog.artifact import CATALOG_SCHEMA_VERSION, OSM_ATTRIBUTION


def write_runtime_artifact(
    graph: nx.Graph,
    pois: Iterable[object],
    path: Path,
    metadata: dict[str, object],
) -> Path:
    payload_metadata = dict(metadata)
    payload_metadata.setdefault("artifact_schema_version", ROUTING_ARTIFACT_SCHEMA_VERSION)
    with Path(path).open("wb") as stream:
        pickle.dump(
            {
                "graph": graph,
                "pois": list(pois),
                "gazetteer": {},
                "metadata": payload_metadata,
            },
            stream,
        )
    return Path(path)


def write_catalog_payload(places: Iterable[object], path: Path, metadata: dict[str, Any]) -> Path:
    payload_metadata = dict(metadata)
    payload_metadata.setdefault("catalog_schema_version", CATALOG_SCHEMA_VERSION)
    payload_metadata.setdefault("catalog_revision", "test-catalog")
    payload_metadata.setdefault("attribution", OSM_ATTRIBUTION)
    with Path(path).open("wb") as stream:
        pickle.dump({"places": list(places), "metadata": payload_metadata}, stream)
    return Path(path)
