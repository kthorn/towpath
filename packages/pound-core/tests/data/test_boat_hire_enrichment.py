import csv
import math
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse, urlunparse

CSV_PATH = Path(__file__).parents[2] / "src/pound/data/boat-hire-enrichment.csv"
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
    assert len(rows) == 136
    assert Counter(row["record_type"] for row in rows) == {
        "company_base": 125,
        "review_positive": 11,
    }
    assert len({(row["source_provider_id"], row["location_id"]) for row in rows}) == len(rows)
    assert all(row["source_provider_id"] and row["location_id"] for row in rows)
    assert all(row["exclude"] in {"", "true", "false"} for row in rows)
    assert all(row["source_url"].startswith("https://") for row in rows)
    assert all(
        row["google_search_url"].startswith("https://www.google.com/search?q=") for row in rows
    )


def _is_https_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    return parsed.scheme == "https" and bool(parsed.netloc)


OUT_OF_ENGLAND_IDENTITIES = {
    ("anglo-welsh", "base:trevor"),
    ("black-prince", "base:chirk-north-wales"),
    ("black-prince", "base:falkirk-scotland"),
    ("marine-cruises", "base:falkirk-marina"),
    ("cambrian-cruisers", "base:ty-newydd-pencelli"),
    ("beacon-park-boats", "base:llangattock"),
    ("canal-holidays", "base:10"),
    ("canal-holidays", "base:20"),
    ("canal-holidays", "base:23"),
    ("canal-holidays", "base:58"),
    ("drifters", "base:canal-boat-holiday-destinations-from-trevor-basin"),
    ("drifters", "base:chirk-marina"),
    ("drifters", "base:falkirk-wheel"),
    ("drifters", "base:goytre-wharf"),
    ("narrow-boat-hire", "base:falkirk-wharf"),
    ("narrow-boat-hire", "base:goytre-wharf"),
}


def test_is_https_url_rejects_malformed_url():
    assert not _is_https_url("https://[")


DRIFTERS_MAP_URL = "https://www.drifters.co.uk/uk-canal-map/"
DRIFTERS_MAP_ATTESTATIONS = {
    ("drifters", "base:acton-bridge"): (
        "860",
        "Acton Bridge",
        "https://www.drifters.co.uk/bases/acton-bridge",
        "53.284143",
        "-2.598801",
    ),
    ("drifters", "base:aldermaston"): (
        "923",
        "Aldermaston",
        "https://www.drifters.co.uk/bases/aldermaston",
        "51.400554",
        "-1.136945",
    ),
    ("drifters", "base:bradford-on-avon"): (
        "745",
        "Bradford on Avon",
        "https://www.drifters.co.uk/bases/bradford-on-avon",
        "51.341918",
        "-2.251406",
    ),
    ("drifters", "base:canal-boat-holiday-destinations-from-autherley"): (
        "1013",
        "Autherley",
        "https://www.drifters.co.uk/bases/canal-boat-holiday-destinations-from-autherley",
        "52.616361",
        "-2.147335",
    ),
    ("drifters", "base:canal-boat-holiday-destinations-from-weedon"): (
        "2201",
        "Weedon",
        "https://www.drifters.co.uk/bases/canal-boat-holiday-destinations-from-weedon",
        "52.232557",
        "-1.078218",
    ),
    ("drifters", "base:lower-heyford"): (
        "645",
        "Lower Heyford",
        "https://www.drifters.co.uk/bases/lower-heyford",
        "51.918833",
        "-1.298733",
    ),
    ("drifters", "base:sowerby-bridge"): (
        "1389",
        "Sowerby Bridge",
        "https://www.drifters.co.uk/bases/sowerby-bridge",
        "53.709957",
        "-1.903440",
    ),
    ("drifters", "base:springwood"): (
        "2198",
        "Springwood Haven",
        "https://www.drifters.co.uk/bases/springwood",
        "52.540303",
        "-1.494511",
    ),
    ("drifters", "base:stoke-on-trent"): (
        "864",
        "Stoke on Trent",
        "https://www.drifters.co.uk/bases/stoke-on-trent",
        "53.024572",
        "-2.196654",
    ),
    ("drifters", "base:stoke-prior"): (
        "737",
        "Stoke Prior",
        "https://www.drifters.co.uk/bases/stoke-prior",
        "52.301568",
        "-2.072659",
    ),
    ("drifters", "base:sydney-wharf-bath"): (
        "736",
        "Bath",
        "https://www.drifters.co.uk/bases/sydney-wharf-bath",
        "51.383267",
        "-2.348722",
    ),
    ("drifters", "base:wootton-wawen"): (
        "1080",
        "Wootton Wawen",
        "https://www.drifters.co.uk/bases/wootton-wawen",
        "52.264757",
        "-1.768773",
    ),
    ("drifters", "base:barnoldswick-boatyard"): (
        "1457",
        "Barnoldswick",
        "https://www.drifters.co.uk/bases/barnoldswick",
        "53.913162",
        "-2.174942",
    ),
    ("drifters", "base:brewood-canal-holidays"): (
        "787",
        "Brewood",
        "https://www.drifters.co.uk/bases/brewood",
        "52.680537",
        "-2.181273",
    ),
    ("drifters", "base:bunbury-boatyard"): (
        "1016",
        "Bunbury",
        "https://www.drifters.co.uk/bases/bunbury",
        "53.126942",
        "-2.632598",
    ),
    ("drifters", "base:ely-marina"): (
        "862",
        "Ely",
        "https://www.drifters.co.uk/bases/ely",
        "52.394221",
        "0.270200",
    ),
    ("drifters", "base:gailey-marina"): (
        "1075",
        "Gailey",
        "https://www.drifters.co.uk/bases/gailey",
        "52.690911",
        "-2.119550",
    ),
    ("drifters", "base:kings-orchard-marina"): (
        "2192",
        "Kings Orchard",
        "https://www.drifters.co.uk/bases/kings-orchard",
        "52.690710",
        "-1.780740",
    ),
    ("drifters", "base:march-marina"): (
        "1459",
        "March",
        "https://www.drifters.co.uk/bases/march/?location=March",
        "52.554836",
        "0.066645",
    ),
    ("drifters", "base:monkton-combe-boatyard"): (
        "1391",
        "Monkton Combe",
        "https://www.drifters.co.uk/bases/monkton-combe",
        "51.357826",
        "-2.315244",
    ),
    ("drifters", "base:nantwich"): (
        "2199",
        "Nantwich",
        "https://www.drifters.co.uk/bases/nantwich/?location=Nantwich",
        "53.071015",
        "-2.538735",
    ),
    ("drifters", "base:silsden-hire-base-for-drifters-canal-boat-holidays"): (
        "822",
        "Silsden",
        "https://www.drifters.co.uk/bases/silsden",
        "53.911752",
        "-1.938201",
    ),
    ("drifters", "base:stockton-marina"): (
        "1077",
        "Stockton",
        "https://www.drifters.co.uk/bases/stockton",
        "52.282509",
        "-1.360343",
    ),
}

DRIFTERS_MAP_APPROVED_ALIASES = {
    ("drifters", "base:barnoldswick-boatyard"): (
        "https://www.drifters.co.uk/bases/barnoldswick-boatyard/",
        "https://www.drifters.co.uk/bases/barnoldswick",
    ),
    ("drifters", "base:brewood-canal-holidays"): (
        "https://www.drifters.co.uk/bases/brewood-canal-holidays/",
        "https://www.drifters.co.uk/bases/brewood",
    ),
    ("drifters", "base:bunbury-boatyard"): (
        "https://www.drifters.co.uk/bases/bunbury-boatyard/",
        "https://www.drifters.co.uk/bases/bunbury",
    ),
    ("drifters", "base:ely-marina"): (
        "https://www.drifters.co.uk/bases/ely-marina/",
        "https://www.drifters.co.uk/bases/ely",
    ),
    ("drifters", "base:gailey-marina"): (
        "https://www.drifters.co.uk/bases/gailey-marina/",
        "https://www.drifters.co.uk/bases/gailey",
    ),
    ("drifters", "base:kings-orchard-marina"): (
        "https://www.drifters.co.uk/bases/kings-orchard-marina/",
        "https://www.drifters.co.uk/bases/kings-orchard",
    ),
    ("drifters", "base:march-marina"): (
        "https://www.drifters.co.uk/bases/march-marina/",
        "https://www.drifters.co.uk/bases/march/?location=March",
    ),
    ("drifters", "base:monkton-combe-boatyard"): (
        "https://www.drifters.co.uk/bases/monkton-combe-boatyard/",
        "https://www.drifters.co.uk/bases/monkton-combe",
    ),
    ("drifters", "base:nantwich"): (
        "https://www.drifters.co.uk/bases/nantwich/",
        "https://www.drifters.co.uk/bases/nantwich/?location=Nantwich",
    ),
    ("drifters", "base:silsden-hire-base-for-drifters-canal-boat-holidays"): (
        "https://www.drifters.co.uk/bases/silsden-hire-base-for-drifters-canal-boat-holidays/",
        "https://www.drifters.co.uk/bases/silsden",
    ),
    ("drifters", "base:stockton-marina"): (
        "https://www.drifters.co.uk/bases/stockton-marina/",
        "https://www.drifters.co.uk/bases/stockton",
    ),
}

NARROW_BOAT_HIRE_DETAIL_ATTESTATIONS = {
    ("narrow-boat-hire", "base:aldermaston-wharf"): (
        "Aldermaston Wharf",
        "https://www.narrow-boat-hire.co.uk/narrow-boat-hire-at-Aldermaston.html",
        "51.4009381",
        "-1.13438445",
        "aldermaston",
    ),
    ("narrow-boat-hire", "base:fox-s-marina"): (
        "Fox's Marina",
        "https://www.narrow-boat-hire.co.uk/narrow-boat-hire-at-March.html",
        "52.5553134298208",
        "0.061396416448774305",
        "march",
    ),
    ("narrow-boat-hire", "base:kings-orchard-marina"): (
        "Kings Orchard Marina",
        "https://www.narrow-boat-hire.co.uk/narrow-boat-hire-at-Kings%20Orchard.html",
        "52.69100303119615",
        "-1.7814762490083236",
        "kings-orchard",
    ),
}


def _normalized_drifters_local_routes_url(value: str) -> str:
    parsed = urlparse(value)
    return urlunparse(
        parsed._replace(netloc=parsed.netloc.lower(), path=parsed.path.removesuffix("/"))
    )


def test_drifters_map_rows_are_offline_attested():
    with CSV_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    map_rows = [row for row in rows if row["evidence_url"] == DRIFTERS_MAP_URL]
    assert len(map_rows) == len(DRIFTERS_MAP_ATTESTATIONS)
    map_row_identities = {(row["source_provider_id"], row["location_id"]) for row in map_rows}
    assert map_row_identities == set(DRIFTERS_MAP_ATTESTATIONS)

    marker_ids = [attestation[0] for attestation in DRIFTERS_MAP_ATTESTATIONS.values()]
    raw_urls = [attestation[2] for attestation in DRIFTERS_MAP_ATTESTATIONS.values()]
    assert len(marker_ids) == len(set(marker_ids))
    assert len(raw_urls) == len({_normalized_drifters_local_routes_url(url) for url in raw_urls})
    assert set(DRIFTERS_MAP_APPROVED_ALIASES) <= set(DRIFTERS_MAP_ATTESTATIONS)
    assert all(
        _normalized_drifters_local_routes_url(source_url)
        != _normalized_drifters_local_routes_url(raw_url)
        for source_url, raw_url in DRIFTERS_MAP_APPROVED_ALIASES.values()
    )

    for row in map_rows:
        identity = (row["source_provider_id"], row["location_id"])
        marker_id, title, raw_url, latitude, longitude = DRIFTERS_MAP_ATTESTATIONS[identity]
        assert row["exclude"] != "true"
        assert row["source_provider_id"] == "drifters"
        assert row["enrichment_status"] == "provider_map_verified"
        assert row["osm_url"] == ""
        assert _is_https_url(raw_url)
        assert urlparse(raw_url).hostname == "www.drifters.co.uk"
        approved_alias = DRIFTERS_MAP_APPROVED_ALIASES.get(identity)
        if approved_alias is None:
            assert _normalized_drifters_local_routes_url(row["source_url"]) == (
                _normalized_drifters_local_routes_url(raw_url)
            )
        else:
            assert approved_alias == (row["source_url"], raw_url)
        assert row["latitude"] == latitude
        assert row["longitude"] == longitude
        assert row["review_identity"] == f"ukwg-gbb/{marker_id}"
        assert title in row["notes"]
        assert raw_url in row["notes"]


def test_narrow_boat_hire_detail_map_rows_are_offline_attested():
    with CSV_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    detail_rows = [
        row
        for row in rows
        if row["evidence_url"]
        in {attestation[1] for attestation in NARROW_BOAT_HIRE_DETAIL_ATTESTATIONS.values()}
    ]
    detail_row_identities = {(row["source_provider_id"], row["location_id"]) for row in detail_rows}
    assert detail_row_identities == set(NARROW_BOAT_HIRE_DETAIL_ATTESTATIONS)

    for row in detail_rows:
        identity = (row["source_provider_id"], row["location_id"])
        location_name, detail_url, latitude, longitude, detail_id = (
            NARROW_BOAT_HIRE_DETAIL_ATTESTATIONS[identity]
        )
        assert row["source_provider_id"] == "narrow-boat-hire"
        assert row["source_url"] == "https://www.narrow-boat-hire.co.uk/locations.html"
        assert row["official_location_name"] == location_name
        assert row["evidence_url"] == detail_url
        assert row["osm_url"] == ""
        assert row["latitude"] == latitude
        assert row["longitude"] == longitude
        assert row["review_identity"] == f"narrow-boat-hire-detail-map/{detail_id}"
        assert row["enrichment_status"] == "provider_map_verified"
        assert location_name in row["notes"]


def test_nonexcluded_rows_are_coordinate_and_evidence_ready():
    with CSV_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    problems = []
    excluded = {
        (row["source_provider_id"], row["location_id"]) for row in rows if row["exclude"] == "true"
    }
    if excluded != OUT_OF_ENGLAND_IDENTITIES:
        problems.append(
            "excluded-identity mismatch: "
            f"unexpected={sorted(excluded - OUT_OF_ENGLAND_IDENTITIES)!r} "
            f"missing={sorted(OUT_OF_ENGLAND_IDENTITIES - excluded)!r}"
        )
    active_rows = [row for row in rows if row["exclude"] != "true"]
    if not active_rows:
        problems.append("no active rows remain")
    for row in active_rows:
        identity = (row["source_provider_id"], row["location_id"])
        row_problems = []
        try:
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
        except ValueError:
            row_problems.append("latitude/longitude not parseable as floats")
        else:
            if not math.isfinite(latitude) or not -90 <= latitude <= 90:
                row_problems.append(f"latitude {row['latitude']!r} outside WGS84 bounds")
            if not math.isfinite(longitude) or not -180 <= longitude <= 180:
                row_problems.append(f"longitude {row['longitude']!r} outside WGS84 bounds")
        if not any(_is_https_url(row[field]) for field in ("osm_url", "evidence_url")):
            row_problems.append("missing https osm_url or evidence_url")
        if row_problems:
            problems.append(f"{identity}: " + "; ".join(row_problems))
    assert not problems, "unresolved boat-hire rows:\n" + "\n".join(
        f"- {problem}" for problem in problems
    )


OURBOATS_BASE_ATTESTATIONS = {
    ("shire-cruisers", "base:sowerby-bridge"): (
        "53.709957",
        "-1.903440",
        "https://www.shirecruisers.co.uk/about/find-us-sowerby-bridge.php",
        "",
    ),
    ("shire-cruisers", "base:barnoldswick"): (
        "53.913162",
        "-2.174942",
        "https://www.shirecruisers.co.uk/about/find-us-barnoldswick.php",
        "",
    ),
    ("marine-cruises", "base:swanley-bridge-marina"): (
        "53.0731203",
        "-2.5747632",
        "https://marinecruises.co.uk/swanley-bridge-marina.htm",
        "",
    ),
    ("marine-cruises", "base:falkirk-marina"): (
        "56.000301",
        "-3.841953",
        "https://marinecruises.co.uk/falkirk-marina.htm",
        "true",
    ),
    ("chas-hardern-boats", "base:beeston-castle-wharf"): (
        "53.135",
        "-2.671",
        "https://www.chashardern.co.uk/contact-us.htm",
        "",
    ),
    ("rose-narrowboats", "base:stretton-stop"): (
        "52.4224899",
        "-1.3555092",
        "https://www.rose-narrowboats.co.uk/how-to-find-us.html",
        "",
    ),
    ("cambrian-cruisers", "base:ty-newydd-pencelli"): (
        "51.9245689",
        "-3.3283138",
        "https://www.cambriancruisers.co.uk/contact",
        "true",
    ),
    ("beacon-park-boats", "base:llangattock"): (
        "",
        "",
        "https://beaconparkboats.com/contact",
        "true",
    ),
    ("norbury-wharf", "base:norbury-junction"): (
        "52.8029796",
        "-2.3074336",
        "https://www.norburywharfltd.co.uk/contact-us/",
        "",
    ),
    ("starline-narrowboats", "base:stourport-marina"): (
        "52.3265559",
        "-2.2690314",
        "https://www.starlinenarrowboats.co.uk/routes.html",
        "",
    ),
    ("fox-narrowboats", "base:march-wharf"): (
        "52.5553134298208",
        "0.061396416448774305",
        "https://www.foxboats.co.uk/contact-us/",
        "",
    ),
    ("kate-boats", "base:stockton-top-marina"): (
        "52.2827551",
        "-1.3608859",
        "https://www.kateboats.co.uk/how-to-find-us/",
        "",
    ),
    ("college-cruisers", "base:combe-road-wharf"): (
        "51.7581917",
        "-1.2703537",
        "https://www.collegecruisers.com/boat-yard-services/",
        "",
    ),
    ("oxfordshire-narrowboats", "base:lower-heyford"): (
        "51.9187513",
        "-1.2984992",
        "https://www.oxfordshire-narrowboats.co.uk/new-page",
        "",
    ),
    ("oxfordshire-narrowboats", "base:bradford-on-avon"): (
        "51.3411477",
        "-2.2524255",
        "https://www.oxfordshire-narrowboats.co.uk/new-page",
        "",
    ),
    ("white-horse-boats", "base:devizes-wharf"): (
        "51.3553014",
        "-1.9953834",
        "https://whitehorsenarrowboats.co.uk/contact",
        "",
    ),
    ("foxhangers", "base:lower-foxhangers"): (
        "51.3537852",
        "-2.0512676",
        "https://www.foxhangers.co.uk/contact-2/",
        "",
    ),
    ("wyvern-shipping", "base:leighton-buzzard"): (
        "51.922869",
        "-0.667910",
        "https://www.canalholidays.co.uk/contact-us/",
        "",
    ),
    ("honeystreet-boats", "base:honeystreet-mill"): (
        "51.3535269",
        "-1.8534747",
        "https://www.honeystreetboats.co.uk/about-us/",
        "",
    ),
}


def test_ourboats_member_bases_are_offline_attested():
    with CSV_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    found = {
        (row["source_provider_id"], row["location_id"]): (
            row["latitude"],
            row["longitude"],
            row["source_url"],
            row["exclude"],
        )
        for row in rows
        if (row["source_provider_id"], row["location_id"]) in OURBOATS_BASE_ATTESTATIONS
    }
    assert found == OURBOATS_BASE_ATTESTATIONS


CANAL_HOLIDAYS_BASE_62_ATTESTATION = {
    "source_url": "https://www.canalholidays.com/bases/62.htm",
    "evidence_url": "https://www.canalholidays.com/canal-map/",
    "latitude": "52.2559783723458",
    "longitude": "-1.31417997134753",
    "exclude": "",
}
CANAL_HOLIDAYS_BASE_62_NOTES = (
    "Canal Holidays official map BaseId 62 supplies this base coordinate; "
    "source URL is an exact BaseId match.",
    "User-approved one-base startup snap exception: the current England artifact "
    "measures 250.968 m; this identity is permitted up to 251 m.",
)


def test_canal_holidays_base_62_row_is_offline_attested():
    with CSV_PATH.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))

    row = next(
        row
        for row in rows
        if (row["source_provider_id"], row["location_id"]) == ("canal-holidays", "base:62")
    )
    for field, value in CANAL_HOLIDAYS_BASE_62_ATTESTATION.items():
        assert row[field] == value
    for note in CANAL_HOLIDAYS_BASE_62_NOTES:
        assert note in row["notes"]
