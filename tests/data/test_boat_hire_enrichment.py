import csv
from collections import Counter
from pathlib import Path

CSV_PATH = Path(__file__).parents[2] / "pound/data/boat-hire-enrichment.csv"
EXPECTED_FIELDS = [
    "record_type",
    "source_provider_id",
    "source_provider_name",
    "source_provider_website",
    "operator_id",
    "operator_name",
    "location_id",
    "location_name",
    "location_area",
    "waterway",
    "review_identity",
    "review_rank",
    "osm_url",
    "latitude",
    "longitude",
    "source_url",
    "source_kind",
    "google_search_url",
    "existing_website",
    "official_location_name",
    "booking_url",
    "hire_type",
    "evidence_url",
    "phone",
    "email",
    "enrichment_status",
    "notes",
    "exclude",
]


def test_boat_hire_enrichment_seed_has_distinct_location_rows():
    with CSV_PATH.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)

    assert reader.fieldnames == EXPECTED_FIELDS
    assert len(rows) == 117
    assert Counter(row["record_type"] for row in rows) == {
        "company_base": 106,
        "review_positive": 11,
    }
    assert len({(row["source_provider_id"], row["location_id"]) for row in rows}) == len(rows)
    assert all(row["source_provider_id"] and row["location_id"] for row in rows)
    assert all(row["exclude"] in {"", "true", "false"} for row in rows)
    assert all(row["source_url"].startswith("https://") for row in rows)
    assert all(
        row["google_search_url"].startswith("https://www.google.com/search?q=") for row in rows
    )
