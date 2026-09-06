import pytest
from pound.catalog.metadata import CatalogAddress, CatalogMetadata
from pound.catalog.models import CatalogPlace
from pound.catalog.resolve import PlaceNameIndex, resolve_place
from pound.models import OsmElementType
from pound.schemas import ResolvePlaceRequest
from pydantic import ValidationError
from shapely.geometry import Point


def place(uid=1, name="Bletchley Park", **changes):
    values = dict(
        osm_type=OsmElementType.NODE,
        osm_id=uid,
        kind="museum",
        name=name,
        lat=51.997,
        lon=-0.741,
        metadata=CatalogMetadata(),
        geometry_wkb=Point(-0.741, 51.997).wkb,
        geometry_source="point",
    )
    values.update(changes)
    return CatalogPlace(**values)


def resolve(places, query="Bletchley Park", **limits):
    return resolve_place(
        ResolvePlaceRequest(query=query), index=PlaceNameIndex(tuple(places), "catalog-1"), **limits
    )


def test_exact_source_backed_match():
    result = resolve([place()])
    assert result.status == "resolved"
    assert result.options[0].source_id == "osm:node:1"
    assert result.options[0].coordinate.lat == 51.997
    assert result.options[0].locality is None
    assert result.options[0].catalog_revision == "catalog-1"
    assert result.work_used == 1


def test_alias_normalization_and_locality():
    result = resolve(
        [
            place(
                metadata=CatalogMetadata(
                    alt_name="Station X; BP Museum", address=CatalogAddress(city="Milton Keynes")
                )
            )
        ],
        "  STATION   X ",
    )
    assert result.status == "resolved"
    assert result.options[0].locality == "Milton Keynes"


def test_duplicates_and_partial_require_selection():
    assert resolve([place(), place(2)]).status == "ambiguous"
    assert resolve([place()], "Bletchley").status == "ambiguous"


def test_absent_catalog_and_complete_miss_are_distinct():
    assert resolve_place(ResolvePlaceRequest(query="x"), index=None).status == "unavailable"
    assert resolve([place()], "absent museum").status == "not_found"


def test_overflow_and_work_exhaustion_never_resolve():
    assert resolve([place(i) for i in range(1, 8)]).status == "incomplete"
    assert resolve([place()], max_work=0).status == "incomplete"


def test_scope_kind_and_duplicate_source_filtering():
    index = PlaceNameIndex((place(), place(kind="historic_site"), place(2, lat=40.0)), "r")
    result = resolve_place(ResolvePlaceRequest(query="Bletchley Park"), index=index)
    assert result.status == "resolved"
    assert len(result.options) == 1
    assert (
        resolve_place(
            ResolvePlaceRequest(query="Bletchley Park", kinds=["pub"]), index=index
        ).status
        == "not_found"
    )


def test_order_independent_and_index_bounds_work():
    records = [place(i, f"Museum {i}") for i in range(1, 1001)] + [place(1001)]
    a = resolve(records)
    b = resolve(list(reversed(records)))
    assert a == b
    assert a.work_used == 1


@pytest.mark.parametrize(
    "changes",
    [
        dict(query=" "),
        dict(query="x" * 201),
        dict(kinds=["invented"]),
        dict(scope_id="moon"),
        dict(max_work=1000000),
        dict(kinds=[]),
        dict(kinds=["museum"] * 17),
    ],
)
def test_strict_request(changes):
    with pytest.raises(ValidationError):
        ResolvePlaceRequest(**({"query": "museum"} | changes))


def test_resolution_cannot_claim_success_without_options():
    from pound.schemas import PlaceResolution

    with pytest.raises(ValidationError):
        PlaceResolution(status='resolved', reason='exact')
    with pytest.raises(ValidationError):
        PlaceResolution(status='not_found', reason='exact')
