import pytest

from app.business_access import (
    DEFAULT_STORE_POLICY,
    ROLE_NETWORK_MERCHANDISER,
    ROLE_STATION_ADMINISTRATOR,
    normalize_business_grants,
    store_policy,
)


def test_business_grants_are_scoped_deduplicated_and_additive():
    grants = normalize_business_grants([
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": "station", "scope_id": "208"},
        {"role": ROLE_NETWORK_MERCHANDISER, "scope_type": "network", "scope_id": "wrong"},
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": "station", "scope_id": "208"},
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": "station", "scope_id": "210"},
    ], network_id="gig", station_ids={"208", "210"})
    assert grants == [
        {"role": ROLE_NETWORK_MERCHANDISER, "scope_type": "network", "scope_id": "gig"},
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": "station", "scope_id": "208"},
        {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": "station", "scope_id": "210"},
    ]


def test_station_grant_cannot_reference_foreign_station():
    with pytest.raises(ValueError, match="не принадлежит"):
        normalize_business_grants([
            {"role": ROLE_STATION_ADMINISTRATOR, "scope_type": "station", "scope_id": "999"},
        ], network_id="gig", station_ids={"208"})


def test_store_policy_v1_fails_closed_to_station():
    assert store_policy({"storePolicy": {"commercial_owner": "network"}}) == DEFAULT_STORE_POLICY
