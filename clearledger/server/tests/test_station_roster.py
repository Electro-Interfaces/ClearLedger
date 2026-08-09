"""Ростер станции строится только из явных бизнес-grant."""

from app.business_access import (
    ROLE_NETWORK_MERCHANDISER,
    ROLE_STATION_ADMINISTRATOR,
    SCOPE_NETWORK,
    SCOPE_STATION,
)
from app.services.station_roster import _covers, _effective_grants


def test_covers_only_explicit_station_administrator_grant():
    assert _covers(None, 208) is False
    assert _covers([], 208) is False
    assert _covers([
        {"role": ROLE_NETWORK_MERCHANDISER, "scope_type": SCOPE_NETWORK, "scope_id": "gig"},
    ], 208) is False
    assert _covers([
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": SCOPE_STATION, "scope_id": "209"},
    ], 208) is False
    assert _covers([
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": SCOPE_STATION, "scope_id": "208"},
    ], 208) is True


def test_grants_are_union_across_roles():
    grants = [
        {"role": ROLE_NETWORK_MERCHANDISER, "scope_type": SCOPE_NETWORK, "scope_id": "gig"},
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": SCOPE_STATION, "scope_id": "208"},
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": SCOPE_STATION, "scope_id": "210"},
    ]
    assert _covers(grants, 208) is True
    assert _covers(grants, 210) is True
    assert _covers(grants, 211) is False


def test_superadmin_gets_additive_synthetic_station_grant():
    grants = [{
        "role": ROLE_NETWORK_MERCHANDISER,
        "scope_type": SCOPE_NETWORK,
        "scope_id": "gig",
    }]
    effective = _effective_grants(grants, 208, is_superadmin=True)
    assert effective[0] == grants[0]
    assert _covers(effective, 208) is True
    assert effective[-1] == {
        "role": ROLE_STATION_ADMINISTRATOR,
        "scope_type": SCOPE_STATION,
        "scope_id": "208",
        "synthetic": True,
    }
    assert _effective_grants(grants, 208, is_superadmin=False) == grants
