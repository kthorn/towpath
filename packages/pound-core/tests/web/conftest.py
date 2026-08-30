import csv
from collections.abc import Generator
from pathlib import Path

import networkx as nx
import pytest  # pyright: ignore[reportMissingImports]
from fastapi.testclient import TestClient  # pyright: ignore[reportMissingImports]
from pound.artifact import ROUTING_ARTIFACT_SCHEMA_VERSION
from pound.catalog.metadata import CatalogMetadata
from pound.catalog.models import CatalogPlace
from pound.models import OsmElementType, PoiCategory, RuntimePoi, WayDimensions
from pound.web.app import create_app
from pound.web.boat_hire import BOAT_HIRE_ENRICHMENT_FIELDS
from pound.web.config import WebSettings
from shapely import wkb
from shapely.geometry import Point

from tests.fixtures import write_catalog_payload
from tests.fixtures import write_runtime_artifact as save_artifact


@pytest.fixture(autouse=True)
def _clear_network_geometry_cache():
    """Keep the process-global API geometry caches from leaking between tests."""
    import pound.web.api as api_module

    api_module._network_union_cache.clear()
    api_module._network_highlight_cache.clear()
    yield
    api_module._network_union_cache.clear()
    api_module._network_highlight_cache.clear()


def catalog_place(kind: str, osm_id: int, lat: float, lon: float) -> CatalogPlace:
    return CatalogPlace(
        osm_type=OsmElementType.NODE,
        osm_id=osm_id,
        kind=kind,
        name=f"{kind} {osm_id}",
        lat=lat,
        lon=lon,
        metadata=CatalogMetadata(name=f"{kind} {osm_id}"),
        geometry_wkb=wkb.dumps(Point(lon, lat), output_dimension=2),
        geometry_source="point",
    )


def artifact_metadata(revision: str, *, source: str = "test") -> dict:
    return {
        "artifact_schema_version": ROUTING_ARTIFACT_SCHEMA_VERSION,
        "artifact_revision": revision,
        "source": source,
        "fetched_at": "2026-07-11T00:00:00Z",
        "built_at": "2026-07-12T00:00:00Z",
        "validation": {},
        "poi_summary": {},
    }


def write_boat_hire_row(
    location_id: str, latitude: str, longitude: str, osm_node_id: int
) -> dict[str, str]:
    row = dict.fromkeys(BOAT_HIRE_ENRICHMENT_FIELDS, "")
    row.update(
        record_type="company_base",
        source_provider_id="test-provider",
        location_id=location_id,
        latitude=latitude,
        longitude=longitude,
        osm_url=f"https://www.openstreetmap.org/node/{osm_node_id}",
        exclude="",
    )
    return row


def write_boat_hire_enrichment(
    path: Path,
    *,
    rows: list[dict[str, str]] | None = None,
) -> Path:
    default = write_boat_hire_row("base:test", "51.0", "-1.0", 1)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=BOAT_HIRE_ENRICHMENT_FIELDS)
        writer.writeheader()
        if rows is None:
            writer.writerows([default])
        else:
            merged = []
            for row in rows:
                m = default.copy()
                m.update(row)
                merged.append(m)
            writer.writerows(merged)
    return path


@pytest.fixture
def route_graph() -> nx.Graph:
    graph = nx.Graph(fetched_at="2026-07-11T00:00:00Z", marker={"stable": True})
    graph.add_node(
        1,
        lat=51.0,
        lon=-1.0,
        osm_node_ids={"1"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
        name="Start",
        tags={"kind": "canal"},
    )
    graph.add_node(
        2,
        lat=51.001,
        lon=-1.001,
        osm_node_ids={"2"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
        name="Middle",
        tags={"kind": "canal"},
    )
    graph.add_node(
        3,
        lat=51.002,
        lon=-1.002,
        osm_node_ids={"3"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
        name="End",
        tags={"kind": "canal"},
    )
    graph.add_node(
        4,
        lat=52.0,
        lon=-2.0,
        osm_node_ids={"4"},
        movable_bridge_ids=(),
        turning_point=False,
        turning_max_length_m=None,
        name="Island",
        tags={"kind": "canal"},
    )
    dimensions = WayDimensions(max_beam_m=3.0)
    graph.add_edge(
        1,
        2,
        length_m=100.0,
        locks=0,
        dimensions=dimensions,
        osm_way_id=12,
        name="First reach",
        kind="canal",
        geometry=[(51.0, -1.0), (51.001, -1.001)],
        has_tunnel=False,
        has_movable_bridge=False,
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(),
        tags={"stable": True},
    )
    graph.add_edge(
        2,
        3,
        length_m=100.0,
        locks=1,
        dimensions=dimensions,
        osm_way_id=23,
        name="Second reach",
        kind="canal",
        geometry=[(51.001, -1.001), (51.002, -1.002)],
        has_tunnel=False,
        has_movable_bridge=False,
        movable_bridge_ids=(),
        tunnel_restrictions=(),
        access_caveats=(),
        tags={"stable": True},
    )
    return graph


def fixture_pois() -> tuple[RuntimePoi, ...]:
    return (
        RuntimePoi(
            OsmElementType.NODE,
            101,
            PoiCategory.PROVISIONS,
            "pub",
            "The Test Pub",
            51.0,
            -1.0,
        ),
        RuntimePoi(
            OsmElementType.NODE,
            102,
            PoiCategory.PROVISIONS,
            "shop",
            "The Test Shop",
            51.001,
            -1.001,
        ),
    )


@pytest.fixture
def web_client(tmp_path: Path, route_graph: nx.Graph) -> Generator[TestClient, None, None]:
    yield from build_web_client(tmp_path, route_graph, boat_hire_rows=None)


def build_web_client(
    tmp_path: Path,
    route_graph: nx.Graph,
    *,
    boat_hire_rows: list[dict[str, str]] | None,
) -> Generator[TestClient, None, None]:
    artifact_path = tmp_path / "graph.pkl"
    save_artifact(route_graph, fixture_pois(), artifact_path, artifact_metadata("revision-test"))
    catalog_path = tmp_path / "catalog.pkl"
    write_catalog_payload(
        (
            catalog_place("pub", 201, 51.0, -1.0),
            catalog_place("museum", 202, 51.002, -1.002),
            catalog_place("marina", 203, 51.001, -1.001),
        ),
        catalog_path,
        {
            "source": "catalog-test",
            "fetched_at": "2026-07-11T00:00:00Z",
            "built_at": "2026-07-12T00:00:00Z",
            "inventory_summary": {},
            "build_summary": {},
        },
    )
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
        boat_hire_enrichment_path=write_boat_hire_enrichment(
            tmp_path / "boat-hire.csv",
            rows=boat_hire_rows if boat_hire_rows is not None else None,
        ),
        catalog_path=catalog_path,
        candidate_pool_size=3,
        google_destination_limit=2,
        minimum_candidate_spacing_m=0,
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def client_without_catalog(
    tmp_path: Path, route_graph: nx.Graph
) -> Generator[TestClient, None, None]:
    artifact_path = tmp_path / "graph.pkl"
    save_artifact(route_graph, fixture_pois(), artifact_path, artifact_metadata("revision-test"))
    settings = WebSettings(
        artifact_path=artifact_path,
        static_dir=tmp_path / "static",
        boat_hire_enrichment_path=write_boat_hire_enrichment(
            tmp_path / "boat-hire.csv",
            rows=[
                {
                    "source_provider_id": "test-provider",
                    "location_id": "base:test",
                    "exclude": "true",
                }
            ],
        ),
    )
    with TestClient(create_app(settings)) as client:
        yield client
