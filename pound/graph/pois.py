"""Normalize OSM POI geometry and attach it to routing-eligible waterway edges."""

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import networkx as nx
from pyproj import Transformer
from shapely import (
    distance as geometry_distance,
)
from shapely import (
    from_wkt,
    get_point,
    get_type_id,
    is_empty,
    is_valid,
    make_valid,
    point_on_surface,
    shortest_line,
    transform,
)
from shapely.errors import GEOSException
from shapely.geometry import LineString, Point
from shapely.ops import nearest_points
from shapely.strtree import STRtree

from pound.ingest.ir import PoiCandidate, PoiCategory, PointOfInterest

_TO_BNG = Transformer.from_crs("EPSG:4326", "EPSG:27700", always_xy=True)
_TO_WGS84 = Transformer.from_crs("EPSG:27700", "EPSG:4326", always_xy=True)
_CORRIDOR_M = {
    PoiCategory.CANAL_SERVICE: 250.0,
    PoiCategory.PEDESTRIAN_ACCESS: 250.0,
    PoiCategory.PROVISIONS: 1000.0,
    PoiCategory.TRANSPORT: 1000.0,
}
_NON_NAVIGABLE_BOAT_VALUES = {"no", "unsuitable", "canoe"}


@dataclass(frozen=True)
class PoiBuildResult:
    pois: tuple[PointOfInterest, ...]
    summary: dict[str, int]


def _pound_to_xy(coordinate: tuple[float, float]) -> tuple[float, float]:
    """Convert Pound's (lat, lon) tuple to Shapely's (x=lon, y=lat)."""
    lat, lon = coordinate
    return lon, lat


def _xy_to_pound(point: Point) -> tuple[float, float]:
    """Convert a Shapely point to Pound's (lat, lon) ordering."""
    return point.y, point.x


def _to_bng(geometry):
    return transform(geometry, _TO_BNG.transform, interleaved=False)


def _to_wgs84(geometry):
    return transform(geometry, _TO_WGS84.transform, interleaved=False)


def _routing_eligible(data: dict[str, Any]) -> bool:
    if data.get("navigable") is False or data.get("routing_eligible") is False:
        return False
    tags = data.get("tags") or {}
    return data.get("boat", tags.get("boat")) not in _NON_NAVIGABLE_BOAT_VALUES


def _edge_line_wgs84(graph: nx.Graph, u: int, v: int, data: dict[str, Any]) -> LineString:
    coordinates = data.get("geometry")
    if not coordinates:
        coordinates = [
            (graph.nodes[u]["lat"], graph.nodes[u]["lon"]),
            (graph.nodes[v]["lat"], graph.nodes[v]["lon"]),
        ]
    return LineString([_pound_to_xy(coordinate) for coordinate in coordinates])


def _deduplicate_candidates(
    candidates: Iterable[PoiCandidate],
) -> tuple[list[PoiCandidate], int]:
    winners: dict[tuple, PoiCandidate] = {}
    duplicate_count = 0
    for candidate in candidates:
        incumbent = winners.get(candidate.identity)
        if incumbent is None:
            winners[candidate.identity] = candidate
            continue
        duplicate_count += 1
        if candidate.model_dump_json() < incumbent.model_dump_json():
            winners[candidate.identity] = candidate
    ordered = sorted(
        winners.values(),
        key=lambda candidate: (candidate.osm_type.value, candidate.osm_id, candidate.kind),
    )
    return ordered, duplicate_count


def _normalized_geometry(candidate: PoiCandidate):
    try:
        geometry = from_wkt(candidate.geometry_wkt)
    except (GEOSException, ValueError):
        return None, "invalid_geometry"
    if geometry.is_empty:
        return None, "empty_geometry"
    if not geometry.is_valid:
        try:
            geometry = make_valid(geometry)
        except GEOSException:
            return None, "invalid_geometry"
    if geometry.is_empty or not geometry.is_valid:
        return None, "invalid_geometry"
    usable_types = {
        "point": {"Point"},
        "area": {"Polygon", "MultiPolygon"},
        "derived_path": {"LineString", "MultiLineString"},
    }
    if geometry.geom_type not in usable_types[candidate.geometry_source]:
        return None, "invalid_geometry"
    return geometry, None


class PoiAttachmentIndex:
    """Reusable navigable-edge spatial index for single-candidate attachment."""

    def __init__(self, graph: nx.Graph) -> None:
        self.graph = graph
        edge_records: list[tuple[tuple[int, int], LineString]] = []
        for u, v, data in graph.edges(data=True):
            if not _routing_eligible(data):
                continue
            key = (min(u, v), max(u, v))
            edge_records.append((key, _edge_line_wgs84(graph, u, v, data)))
        edge_records.sort(key=lambda record: record[0])
        self.edge_keys = [record[0] for record in edge_records]
        if edge_records:
            edge_geometries = transform(
                [record[1] for record in edge_records],
                _TO_BNG.transform,
                interleaved=False,
            )
            self.tree = STRtree(edge_geometries)
        else:
            self.tree = None

    def attach(self, candidate: PoiCandidate) -> tuple[PointOfInterest | None, str | None]:
        geometry_wgs84, skip_reason = _normalized_geometry(candidate)
        if skip_reason is not None:
            return None, skip_reason
        if self.tree is None:
            return None, "rejected_by_corridor"

        geometry_bng = _to_bng(geometry_wgs84)
        indexes, distances = self.tree.query_nearest(
            geometry_bng, all_matches=True, return_distance=True
        )
        ranked = sorted(
            (float(distance), self.edge_keys[int(index)], int(index))
            for index, distance in zip(indexes, distances, strict=True)
        )
        distance_m, edge_key, edge_index = ranked[0]
        if distance_m > _CORRIDOR_M[candidate.category]:
            return None, "rejected_by_corridor"

        return self._finish_attachment(
            candidate, geometry_wgs84, geometry_bng, distance_m, edge_key, edge_index
        )

    def attach_many(
        self, candidates: Iterable[PoiCandidate]
    ) -> list[tuple[PointOfInterest | None, str | None]]:
        """Attach a bounded batch with vectorized geometry and nearest-edge operations."""
        candidate_list = list(candidates)
        results: list[tuple[PointOfInterest | None, str | None] | None] = [
            None
        ] * len(candidate_list)
        if not candidate_list:
            return []

        geometries = from_wkt(
            [candidate.geometry_wkt for candidate in candidate_list], on_invalid="ignore"
        )
        empty_flags = is_empty(geometries)
        valid_flags = is_valid(geometries)
        repair_indexes = [
            index
            for index, geometry in enumerate(geometries)
            if geometry is not None and not empty_flags[index] and not valid_flags[index]
        ]
        if repair_indexes:
            try:
                repaired = make_valid(geometries[repair_indexes])
            except GEOSException:
                for index in repair_indexes:
                    try:
                        geometries[index] = make_valid(geometries[index])
                    except GEOSException:
                        geometries[index] = None
            else:
                for index, geometry in zip(repair_indexes, repaired, strict=True):
                    geometries[index] = geometry
            empty_flags = is_empty(geometries)
            valid_flags = is_valid(geometries)
        type_ids = get_type_id(geometries)
        usable_type_ids = {
            "point": {0},
            "area": {3, 6},
            "derived_path": {1, 5},
        }
        usable_indexes = []
        for index, candidate in enumerate(candidate_list):
            geometry = geometries[index]
            if geometry is None:
                results[index] = (None, "invalid_geometry")
            elif empty_flags[index]:
                results[index] = (None, "empty_geometry")
            elif not valid_flags[index]:
                results[index] = (None, "invalid_geometry")
            elif int(type_ids[index]) not in usable_type_ids[candidate.geometry_source]:
                results[index] = (None, "invalid_geometry")
            else:
                usable_indexes.append(index)

        if not usable_indexes:
            return [result for result in results if result is not None]
        if self.tree is None:
            for index in usable_indexes:
                results[index] = (None, "rejected_by_corridor")
            return [result for result in results if result is not None]

        geometries_bng = _to_bng(geometries[usable_indexes])
        corridors = [
            _CORRIDOR_M[candidate_list[index].category] for index in usable_indexes
        ]
        indexes = self.tree.query(
            geometries_bng,
            predicate="dwithin",
            distance=corridors,
        )
        distances = geometry_distance(
            geometries_bng[indexes[0]], self.tree.geometries[indexes[1]]
        )
        ranked: dict[int, tuple[float, tuple[int, int], int]] = {}
        for source_index, edge_index, distance in zip(
            indexes[0], indexes[1], distances, strict=True
        ):
            edge_position = int(edge_index)
            choice = (float(distance), self.edge_keys[edge_position], edge_position)
            source_position = int(source_index)
            incumbent = ranked.get(source_position)
            if incumbent is None or choice < incumbent:
                ranked[source_position] = choice

        accepted = []
        for local_index, candidate_index in enumerate(usable_indexes):
            nearest = ranked.get(local_index)
            if nearest is None:
                results[candidate_index] = (None, "rejected_by_corridor")
            else:
                distance_m, edge_key, edge_index = nearest
                accepted.append(
                    (candidate_index, local_index, edge_index, distance_m, edge_key)
                )

        if accepted:
            accepted_bng = geometries_bng[[item[1] for item in accepted]]
            edge_geometries = self.tree.geometries[[item[2] for item in accepted]]
            nearest_lines = shortest_line(accepted_bng, edge_geometries)
            candidate_nearest_bng = get_point(nearest_lines, 0)
            projected_bng = get_point(nearest_lines, -1)
            candidate_nearest_wgs84 = _to_wgs84(candidate_nearest_bng)
            projected_wgs84 = _to_wgs84(projected_bng)
            representative_wgs84 = point_on_surface(
                geometries[[item[0] for item in accepted]]
            )

            for accepted_index, (
                candidate_index,
                local_index,
                _edge_index,
                distance_m,
                edge_key,
            ) in enumerate(accepted):
                candidate = candidate_list[candidate_index]
                geometry_wgs84 = geometries[candidate_index]
                geometry_bng = geometries_bng[local_index]
                if candidate.geometry_source == "derived_path":
                    display_wgs84 = candidate_nearest_wgs84[accepted_index]
                elif geometry_wgs84.geom_type == "Point":
                    display_wgs84 = geometry_wgs84
                else:
                    display_wgs84 = representative_wgs84[accepted_index]
                projected = projected_wgs84[accepted_index]
                lat, lon = _xy_to_pound(display_wgs84)
                projected_lat, projected_lon = _xy_to_pound(projected)

                endpoint_choices = []
                for uid in edge_key:
                    node = self.graph.nodes[uid]
                    endpoint = Point(*_TO_BNG.transform(node["lon"], node["lat"]))
                    endpoint_choices.append((geometry_bng.distance(endpoint), uid))
                nearest_node_uid = min(endpoint_choices)[1]
                results[candidate_index] = (
                    PointOfInterest(
                        osm_type=candidate.osm_type,
                        osm_id=candidate.osm_id,
                        category=candidate.category,
                        kind=candidate.kind,
                        name=candidate.name,
                        lat=lat,
                        lon=lon,
                        source_tags=candidate.tags,
                        geometry_source=candidate.geometry_source,
                        nearest_waterway_distance_m=distance_m,
                        nearest_edge=edge_key,
                        nearest_node_uid=nearest_node_uid,
                        projected_lat=projected_lat,
                        projected_lon=projected_lon,
                    ),
                    None,
                )

        assert all(result is not None for result in results)
        return [result for result in results if result is not None]

    def _finish_attachment(
        self,
        candidate: PoiCandidate,
        geometry_wgs84,
        geometry_bng,
        distance_m: float,
        edge_key: tuple[int, int],
        edge_index: int,
    ) -> tuple[PointOfInterest, None]:

        candidate_nearest_bng, projected_bng = nearest_points(
            geometry_bng, self.tree.geometries[edge_index]
        )
        if candidate.geometry_source == "derived_path":
            display_wgs84 = _to_wgs84(candidate_nearest_bng)
        elif geometry_wgs84.geom_type == "Point":
            display_wgs84 = geometry_wgs84
        else:
            display_wgs84 = geometry_wgs84.representative_point()
        projected_wgs84 = _to_wgs84(projected_bng)
        lat, lon = _xy_to_pound(display_wgs84)
        projected_lat, projected_lon = _xy_to_pound(projected_wgs84)

        endpoint_choices = []
        for uid in edge_key:
            node = self.graph.nodes[uid]
            endpoint = Point(*_TO_BNG.transform(node["lon"], node["lat"]))
            endpoint_choices.append((geometry_bng.distance(endpoint), uid))
        nearest_node_uid = min(endpoint_choices)[1]

        return (
            PointOfInterest(
                osm_type=candidate.osm_type,
                osm_id=candidate.osm_id,
                category=candidate.category,
                kind=candidate.kind,
                name=candidate.name,
                lat=lat,
                lon=lon,
                source_tags=candidate.tags,
                geometry_source=candidate.geometry_source,
                nearest_waterway_distance_m=distance_m,
                nearest_edge=edge_key,
                nearest_node_uid=nearest_node_uid,
                projected_lat=projected_lat,
                projected_lon=projected_lon,
            ),
            None,
        )


class PoiBuildAccumulator:
    """Attach candidates immediately while retaining deterministic identity winners only."""

    def __init__(
        self, index: PoiAttachmentIndex, *, retain_rejected_winners: bool = True
    ) -> None:
        self.index = index
        self._retain_rejected_winners = retain_rejected_winners
        self._winners: dict[
            tuple, tuple[str, PointOfInterest | None, str | None]
        ] = {}
        self._summary = {
            "duplicate_identities": 0,
            "empty_geometry": 0,
            "invalid_geometry": 0,
            "rejected_by_corridor": 0,
        }

    def add(self, candidate: PoiCandidate) -> None:
        poi, skip_reason = self.index.attach(candidate)
        self._record(candidate, poi, skip_reason)

    def add_many(self, candidates: Iterable[PoiCandidate]) -> None:
        candidate_list = list(candidates)
        for candidate, (poi, skip_reason) in zip(
            candidate_list, self.index.attach_many(candidate_list), strict=True
        ):
            self._record(candidate, poi, skip_reason)

    def _record(
        self,
        candidate: PoiCandidate,
        poi: PointOfInterest | None,
        skip_reason: str | None,
    ) -> None:
        if not self._retain_rejected_winners:
            if skip_reason is not None:
                self._summary[skip_reason] += 1
                return
            assert poi is not None
            candidate_key = candidate.model_dump_json()
            incumbent = self._winners.get(candidate.identity)
            if incumbent is not None:
                self._summary["duplicate_identities"] += 1
                if candidate_key >= incumbent[0]:
                    return
            self._winners[candidate.identity] = (candidate_key, poi, None)
            return

        candidate_key = candidate.model_dump_json()
        incumbent = self._winners.get(candidate.identity)
        if incumbent is not None:
            self._summary["duplicate_identities"] += 1
            if candidate_key >= incumbent[0]:
                return
            incumbent_skip_reason = incumbent[2]
            if incumbent_skip_reason is not None:
                self._summary[incumbent_skip_reason] -= 1

        if skip_reason is not None:
            self._summary[skip_reason] += 1
        else:
            assert poi is not None
        self._winners[candidate.identity] = (candidate_key, poi, skip_reason)

    @property
    def accepted_count(self) -> int:
        return sum(winner[1] is not None for winner in self._winners.values())

    def build_result(self) -> PoiBuildResult:
        pois = sorted(
            (winner[1] for winner in self._winners.values() if winner[1] is not None),
            key=lambda poi: (poi.osm_type.value, poi.osm_id, poi.kind),
        )
        return PoiBuildResult(pois=tuple(pois), summary=dict(self._summary))


def attach_pois(graph: nx.Graph, candidates: Iterable[PoiCandidate]) -> PoiBuildResult:
    """Return deterministically normalized POIs attached to eligible graph edges.

    Distances and nearest-point operations are performed in British National Grid.
    Neither the graph nor any input candidate is modified.
    """
    ordered_candidates, duplicate_count = _deduplicate_candidates(candidates)
    accumulator = PoiBuildAccumulator(
        PoiAttachmentIndex(graph), retain_rejected_winners=False
    )
    for candidate in ordered_candidates:
        accumulator.add(candidate)
    result = accumulator.build_result()
    result.summary["duplicate_identities"] += duplicate_count
    return result
