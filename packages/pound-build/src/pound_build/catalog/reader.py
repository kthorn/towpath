"""Read the independent place catalog from an original OSM extract."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Literal, cast

from pound.catalog.metadata import NormalizedLink, normalize_metadata
from pound.catalog.models import CatalogPlace
from pound.models import OsmElementType

from pound_build.catalog.geometry import normalize_catalog_geometry
from pound_build.catalog.inventory import (
    _candidate_kind,
    _is_artwork,
    _is_inactive,
    _is_pedestrian_access,
    _is_transport,
)
from pound_build.ingest.profile import BuildProfiler

GeometrySource = Literal["point", "line", "area"]


class _CatalogPlaces(tuple[CatalogPlace, ...]):
    """Tuple-compatible places carrying the reader report for the build CLI."""

    report: dict[str, Any]

    def __new__(cls, places, report: dict[str, Any]):
        result = super().__new__(cls, places)
        result.report = report
        return result


def _create_wkt(factory, method: str, obj) -> str | None:
    try:
        return getattr(factory, method)(obj)
    except (RuntimeError, ValueError):
        return None


def _read_report(counts: dict[str, Any]) -> dict[str, Any]:
    return {
        **counts,
        "excluded_by_reason": dict(sorted(counts["excluded_by_reason"].items())),
    }


def read_catalog(path: Path, *, profiler: BuildProfiler | None = None) -> _CatalogPlaces:
    """Read named, active manifest records from an original OSM PBF or XML file."""
    import osmium

    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    profiler = profiler or BuildProfiler()
    counts: dict[str, Any] = {
        "scanned": 0,
        "classified": 0,
        "emitted": 0,
        "duplicate": 0,
        "malformed": 0,
        "inactive": 0,
        "excluded": 0,
        "excluded_by_reason": Counter(),
    }
    places: dict[tuple[OsmElementType, int, str], CatalogPlace] = {}
    pending: dict[tuple[OsmElementType, int, str], dict[str, str]] = {}
    seen_source: set[tuple[OsmElementType, int]] = set()
    factory = cast(Any, osmium).geom.WKTFactory()

    def exclude(reason: str) -> None:
        counts["excluded"] += 1
        counts["excluded_by_reason"][reason] += 1
        if reason == "inactive":
            counts["inactive"] += 1

    def classify(tags: dict[str, str]) -> str | None:
        if _is_inactive(tags):
            exclude("inactive")
            return None
        if _is_artwork(tags):
            exclude("artwork")
            return None
        if _is_transport(tags):
            exclude("transport")
            return None
        if _is_pedestrian_access(tags):
            exclude("pedestrian_access")
            return None
        kind = _candidate_kind(tags)
        if kind is None:
            exclude("unclassified")
            return None
        counts["classified"] += 1
        if not tags.get("name", "").strip():
            exclude("unnamed")
            return None
        return kind

    def emit(
        osm_type: OsmElementType,
        osm_id: int,
        kind: str,
        tags: dict[str, str],
        geometry_wkt: str | None,
        geometry_source: GeometrySource,
    ) -> None:
        identity = (osm_type, osm_id, kind)
        if identity in places:
            counts["duplicate"] += 1
            return
        if geometry_wkt is None:
            counts["malformed"] += 1
            return
        try:
            metadata = normalize_metadata(tags, kind=kind)
            if metadata.name is None:
                raise ValueError("normalized name is empty")
            metadata = metadata.model_copy(
                update={
                    "links": [
                        *metadata.links,
                        NormalizedLink(
                            label="OpenStreetMap",
                            url=f"https://www.openstreetmap.org/{osm_type.value}/{osm_id}",
                        ),
                    ]
                }
            )
            geometry_wkb, coordinate = normalize_catalog_geometry(
                geometry_wkt,
                source=geometry_source,
            )
            places[identity] = CatalogPlace(
                osm_type=osm_type,
                osm_id=osm_id,
                kind=kind,
                name=metadata.name,
                lat=coordinate.lat,
                lon=coordinate.lon,
                metadata=metadata,
                geometry_wkb=geometry_wkb,
                geometry_source=geometry_source,
            )
        except Exception:
            counts["malformed"] += 1
            return
        counts["emitted"] += 1

    with profiler.phase("catalog_read", counts=lambda: _read_report(counts)):
        processor = osmium.FileProcessor(str(path)).with_locations().with_areas()
        for obj in processor:
            obj = cast(Any, obj)
            object_name = type(obj).__name__
            if object_name == "Area":
                osm_type = OsmElementType.WAY if obj.from_way() else OsmElementType.RELATION
                identity_source = (osm_type, obj.orig_id())
                area_tags = {tag.k: tag.v for tag in obj.tags}
                kind = _candidate_kind(area_tags)
                if kind is None:
                    continue
                identity = (*identity_source, kind)
                tags = pending.pop(identity, None)
                if tags is None:
                    continue
                geometry_wkt = _create_wkt(factory, "create_multipolygon", obj)
                emit(osm_type, obj.orig_id(), kind, tags, geometry_wkt, "area")
                continue

            if object_name not in {"Node", "Way", "Relation"}:
                continue
            counts["scanned"] += 1
            osm_type = OsmElementType(object_name.lower())
            source_identity = (osm_type, obj.id)
            if source_identity in seen_source:
                counts["duplicate"] += 1
                continue
            seen_source.add(source_identity)
            tags = {tag.k: tag.v for tag in obj.tags}
            kind = classify(tags)
            if kind is None:
                continue
            identity = (*source_identity, kind)

            if object_name == "Node":
                if not obj.location.valid:
                    counts["malformed"] += 1
                    continue
                emit(osm_type, obj.id, kind, tags, factory.create_point(obj), "point")
            elif object_name == "Relation":
                if identity in pending or identity in places:
                    counts["duplicate"] += 1
                else:
                    pending[identity] = tags
            elif obj.is_closed():
                if identity in pending or identity in places:
                    counts["duplicate"] += 1
                else:
                    pending[identity] = tags
            else:
                emit(
                    osm_type,
                    obj.id,
                    kind,
                    tags,
                    _create_wkt(factory, "create_linestring", obj),
                    "line",
                )

        counts["malformed"] += len(pending)
        pending.clear()

    ordered_places = tuple(
        places[identity]
        for identity in sorted(
            places,
            key=lambda value: (value[0].value, value[1], value[2]),
        )
    )
    report = _read_report(counts)
    return _CatalogPlaces(ordered_places, report)
