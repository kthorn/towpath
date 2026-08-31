import pytest
from pound_build.catalog.geometry import normalize_catalog_geometry
from shapely import wkb
from shapely.geometry import LineString, MultiPolygon, Point, Polygon


def test_point_geometry_uses_point_coordinate_and_round_trips_wkb():
    geometry, coordinate = normalize_catalog_geometry("POINT (-1.25 51.75)", source="point")

    restored = wkb.loads(geometry)
    assert isinstance(restored, Point)
    assert restored.x == pytest.approx(-1.25)
    assert restored.y == pytest.approx(51.75)
    assert coordinate.lat == pytest.approx(51.75)
    assert coordinate.lon == pytest.approx(-1.25)


def test_line_geometry_retains_shape_for_distance_queries():
    geometry, coordinate = normalize_catalog_geometry(
        "LINESTRING (-1.25 51.75, -1.24 51.76, -1.23 51.75)",
        source="line",
    )

    restored = wkb.loads(geometry)
    assert isinstance(restored, LineString)
    assert len(restored.coords) == 3
    assert restored.distance(restored.boundary) >= 0
    assert 51.75 <= coordinate.lat <= 51.76
    assert -1.25 <= coordinate.lon <= -1.23


def test_area_uses_representative_marker_coordinate_and_retains_geometry():
    geometry, coordinate = normalize_catalog_geometry(
        "POLYGON ((-1 51, -1 51.001, -0.999 51.001, -0.999 51, -1 51))",
        source="area",
    )

    restored = wkb.loads(geometry)
    assert isinstance(restored, Polygon)
    assert restored.area > 0
    assert 51 < coordinate.lat < 51.001
    assert -1 < coordinate.lon < -0.999


def test_multipolygon_geometry_is_normalized_as_area():
    geometry, coordinate = normalize_catalog_geometry(
        "MULTIPOLYGON (((-1 51, -1 51.001, -0.999 51.001, -0.999 51, -1 51)), "
        "((-0.99 51, -0.99 51.001, -0.989 51.001, -0.989 51, -0.99 51)))",
        source="area",
    )

    restored = wkb.loads(geometry)
    assert isinstance(restored, MultiPolygon)
    assert len(restored.geoms) == 2
    assert -1 < coordinate.lon < -0.989


@pytest.mark.parametrize(
    ("geometry", "source"),
    [
        ("POINT EMPTY", "point"),
        ("LINESTRING EMPTY", "line"),
        ("POLYGON EMPTY", "area"),
        ("POINT (NaN 51)", "point"),
        ("LINESTRING (0 0, 0 0)", "line"),
    ],
)
def test_geometry_rejects_empty_nonfinite_or_unrepairable_geometry(geometry, source):
    with pytest.raises(ValueError):
        normalize_catalog_geometry(geometry, source=source)


def test_geometry_repairs_valid_area_and_rejects_malformed_or_unsupported_wkt():
    geometry, _ = normalize_catalog_geometry("POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))", source="area")
    assert wkb.loads(geometry).is_valid

    with pytest.raises(ValueError, match="invalid WKT"):
        normalize_catalog_geometry("not WKT", source="point")
    with pytest.raises(ValueError, match="does not match"):
        normalize_catalog_geometry("POINT (0 0)", source="area")
    with pytest.raises(ValueError, match="unsupported"):
        normalize_catalog_geometry("GEOMETRYCOLLECTION EMPTY", source="point")
