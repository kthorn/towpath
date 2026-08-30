import pytest
from pound_web.api import CanalNetworkRequest, CanalRouteRequest
from pydantic import ValidationError


def test_movable_bridge_delay_is_finite_and_nonnegative():
    with pytest.raises(ValidationError):
        CanalRouteRequest(
            start_uid=1,
            end_uid=2,
            artifact_revision="r",
            movable_bridge_delay_min=float("nan"),
        )


@pytest.mark.parametrize(
    "field",
    ["hours_per_day", "boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m"],
)
def test_route_trust_boundary_rejects_nonfinite_hours_and_dimensions(field):
    payload = {
        "start_uid": 1,
        "end_uid": 2,
        "artifact_revision": "revision-test",
        field: float("inf"),
    }

    with pytest.raises(ValidationError):
        CanalRouteRequest.model_validate(payload)

    valid = CanalRouteRequest.model_validate(
        {"start_uid": 1, "end_uid": 2, "artifact_revision": "revision-test"}
    )
    assert valid.days is None


def test_network_request_requires_bounded_schedule():
    assert CanalNetworkRequest(days=365, hours_per_day=1).days == 365
    assert CanalNetworkRequest(days=1, hours_per_day=24).hours_per_day == 24
    with pytest.raises(ValidationError):
        CanalNetworkRequest(days=366, hours_per_day=1)
    with pytest.raises(ValidationError):
        CanalNetworkRequest(days=1, hours_per_day=25)
    with pytest.raises(ValidationError):
        CanalNetworkRequest.model_validate({"days": 1})


@pytest.mark.parametrize(
    "field",
    ["hours_per_day", "boat_length_m", "boat_beam_m", "boat_draft_m", "boat_height_m"],
)
def test_network_request_rejects_nonfinite_hours_and_dimensions(field):
    payload = {"days": 1, "hours_per_day": 6, field: float("inf")}

    with pytest.raises(ValidationError):
        CanalNetworkRequest.model_validate(payload)
