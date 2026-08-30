import pickle
from dataclasses import dataclass
from pathlib import Path

import networkx as nx

from pound.models import RuntimePoi

ROUTING_ARTIFACT_SCHEMA_VERSION = 1
_PAYLOAD_FIELDS = {"graph", "pois", "gazetteer", "metadata"}


class InvalidArtifactError(ValueError):
    """An artifact does not satisfy the runtime compatibility contract."""


@dataclass(frozen=True, slots=True)
class RuntimeArtifact:
    graph: nx.Graph
    pois: tuple[RuntimePoi, ...]
    gazetteer: dict[str, tuple[float, float] | list[tuple[float, float]]]
    metadata: dict[str, object]


def load_artifact(path: Path) -> RuntimeArtifact:
    with Path(path).open("rb") as stream:
        payload = pickle.load(stream)  # pi-lens-ignore: python-pickle
    if not isinstance(payload, dict) or set(payload) != _PAYLOAD_FIELDS:
        raise InvalidArtifactError("invalid top-level artifact shape")
    metadata = payload["metadata"]
    version = metadata.get("artifact_schema_version") if isinstance(metadata, dict) else None
    if type(version) is not int or version != ROUTING_ARTIFACT_SCHEMA_VERSION:
        raise InvalidArtifactError("unsupported artifact schema version")
    if not isinstance(metadata.get("artifact_revision"), str) or not metadata["artifact_revision"]:
        raise InvalidArtifactError("artifact revision is required")
    if not isinstance(payload["graph"], nx.Graph) or not isinstance(payload["pois"], (list, tuple)):
        raise InvalidArtifactError("invalid artifact section type")
    if not isinstance(payload["gazetteer"], dict):
        raise InvalidArtifactError("invalid gazetteer section type")
    return RuntimeArtifact(payload["graph"], tuple(payload["pois"]), payload["gazetteer"], metadata)
