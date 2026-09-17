"""Tests for charity_data_tools.ftc.geo (no network — pure record parsing)."""
from charity_data_tools.ftc import geo

REC = {
    "location": [
        {"id": "TS10 5NA", "name": "TS10 5NA", "geoCode": "E06000003", "type": "HQ"},
        {"id": "E06000001", "name": "Porthaven", "geoCode": "E06000001", "type": "AOO"},
        {"id": "E06000002", "name": "Coast", "geoCode": "E06000002", "type": "AOO"},
    ]
}


def test_hq_geocode():
    assert geo.extract_hq_geocode(REC) == "E06000003"


def test_hq_postcode_via_id():
    assert geo.extract_hq(REC).get("id") == "TS10 5NA"


def test_areas_of_benefit():
    assert set(geo.extract_areas_of_benefit(REC)) == {"E06000001", "E06000002"}


def test_is_based_in():
    assert geo.is_based_in(REC, "E06000003") is True
    assert geo.is_based_in(REC, "E06000001") is False   # that's an area of benefit, not HQ


def test_names_the_area():
    assert geo.names_the_area(REC, "E06000001") is True
    assert geo.names_the_area(REC, "E09000001") is False


def test_missing_location_is_safe():
    assert geo.extract_hq_geocode({}) == ""
    assert geo.extract_areas_of_benefit({}) == []
    assert geo.is_based_in({}, "E06000003") is False
