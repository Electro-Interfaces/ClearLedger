"""Authored unit specifications; NOTRUN by the author (no import/collection).

The repository conftest is not isolated by this module. ROOT owns the future
execution boundary; ordinary pytest invocation is not claimed safe.
"""
from copy import copy, deepcopy
from dataclasses import FrozenInstanceError, replace
import hashlib
from uuid import UUID

import pytest
from sqlalchemy import Integer
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from app.services import contract_write_locks as locks


U1 = UUID("00000000-0000-0000-0000-000000000001")
U2 = UUID("00000000-0000-0000-0000-000000000002")
U3 = UUID("00000000-0000-0000-0000-000000000003")
U4 = UUID("00000000-0000-0000-0000-000000000004")
U5 = UUID("00000000-0000-0000-0000-000000000005")
U6 = UUID("00000000-0000-0000-0000-000000000006")

# Literal bytes and complete digests independently hashed with stdlib only.
# No production encoder was called to derive these expectations.
GOLDENS = (
    (locks.AppKey(U1), 0x50430010,
     b'{"key":"app","parts":{"app_id":"00000000-0000-0000-0000-000000000001"},"v":1}',
     "ecf05944133da2dd9cac8e935ee13a319819715aa0b76855571084d6514d6f88", -319792828),
    (locks.ClientKey("client-A"), 0x50430020,
     b'{"key":"client","parts":{"client_id":"client-A"},"v":1}',
     "69630af0726cee7674ef25bafbbfbd4b3618b154c08f668bc34a3b16815a3e56", 1768098544),
    (locks.UserKey(U2), 0x50430030,
     b'{"key":"user","parts":{"user_id":"00000000-0000-0000-0000-000000000002"},"v":1}',
     "cc2cc6c2e0b77ec39351f43b338e271d17dffb1ed5ec2314b67bff2518b6c55c", -869480766),
    (locks.CompanyKey(U3), 0x50430040,
     b'{"key":"company","parts":{"company_id":"00000000-0000-0000-0000-000000000003"},"v":1}',
     "cdd56396e65159d2b8f0fa18690157d4e95da67403546e3da07234757ef220a8", -841653354),
    (locks.InstallationKey(U4), 0x50430050,
     b'{"key":"installation","parts":{"installation_id":"00000000-0000-0000-0000-000000000004"},"v":1}',
     "602de6a432251500136e9b8dcb84428be0c3dd7b5ad061e02a6c1a4a021e837a", 1613620900),
    (locks.CreateProfileKey(U5), 0x50430060,
     b'{"key":"create_profile","parts":{"profile_id":"00000000-0000-0000-0000-000000000005"},"v":1}',
     "52697f44fd26ac7eda36b01c82a61444a81f23398e9aab5b7673c3839fc6ee25", 1382645572),
    (locks.RoleKey(U3, U6), 0x50430070,
     b'{"key":"role","parts":{"company_id":"00000000-0000-0000-0000-000000000003","role_id":"00000000-0000-0000-0000-000000000006"},"v":1}',
     "0343196270bdf3cad67c3ddb6b2592c0402f08164f19a16da56ccb6c8247e712", 54729058),
    (locks.MemberKey(U3, U2), 0x50430080,
     b'{"key":"member","parts":{"company_id":"00000000-0000-0000-0000-000000000003","user_id":"00000000-0000-0000-0000-000000000002"},"v":1}',
     "69b929ee74b36386ddc397f86f012bbeb809b9358d50c5049f312bb1d1cfaa48", 1773742574),
    (locks.RefCompositeKey(U3), 0x50430090,
     b'{"key":"ref_composite","parts":{"company_id":"00000000-0000-0000-0000-000000000003"},"v":1}',
     "5ed08e6466353575a9fbfceabb5b153f81d6a9a641c211a1febb947be53dd79c", 1590726244),
    (locks.TypeCatalogKey("Договор A "), 0x50430095,
     b'{"key":"type_catalog","parts":{"type_code":"\\u0414\\u043e\\u0433\\u043e\\u0432\\u043e\\u0440 A "},"v":1}',
     "25102e3a65e56f60f92a3e7f4c1b15e41456c374cdf65eded642e1336a3a95d7", 621817402),
)


@pytest.mark.parametrize("key,namespace,payload,digest,signed", GOLDENS)
def test_independent_literal_goldens(key, namespace, payload, digest, signed):
    assert hashlib.sha256(payload).hexdigest() == digest
    assert locks.encode_key(key) == payload
    assert locks.advisory_key(key) == (namespace, signed)


class UUIDSubclass(UUID):
    pass


class StringSubclass(str):
    pass


class AppSubclass(locks.AppKey):
    pass


@pytest.mark.parametrize("invalid", [str(U1), True, 1, None, UUIDSubclass(str(U1))])
@pytest.mark.parametrize("factory", [locks.AppKey, locks.UserKey, locks.CompanyKey,
                                    locks.InstallationKey, locks.CreateProfileKey,
                                    locks.RefCompositeKey])
def test_uuid_parts_require_exact_uuid(factory, invalid):
    with pytest.raises(TypeError):
        factory(invalid)


@pytest.mark.parametrize("factory", [locks.RoleKey, locks.MemberKey])
@pytest.mark.parametrize("invalid", [str(U1), True, UUIDSubclass(str(U1))])
def test_both_composite_parts_are_exact_uuid(factory, invalid):
    with pytest.raises(TypeError):
        factory(invalid, U2)
    with pytest.raises(TypeError):
        factory(U1, invalid)


@pytest.mark.parametrize("factory", [locks.ClientKey, locks.TypeCatalogKey])
@pytest.mark.parametrize("invalid", ["", StringSubclass("client"), True, None, U1])
def test_exact_nonempty_text(factory, invalid):
    with pytest.raises(TypeError):
        factory(invalid)


def test_no_normalization_or_uuid_string_coercion():
    values = ("client-A", "client-a", " client-A", "client-A ", " ", "é", "e\u0301")
    assert len({locks.encode_key(locks.ClientKey(value)) for value in values}) == len(values)
    assert locks.RoleKey(U1, U2) != locks.RoleKey(U3, U2)
    assert locks.MemberKey(U1, U2) != locks.MemberKey(U3, U2)
    with pytest.raises(TypeError):
        AppSubclass(U1)
    for invalid in (1, True, "SHARED"):
        with pytest.raises(TypeError):
            locks.LockRequest(locks.AppKey(U1), invalid)


def test_full_numeric_order_and_strongest_duplicate_merge():
    shared, exclusive = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE
    originals = tuple(locks.LockRequest(key, shared) for key, *_ in reversed(GOLDENS))
    originals += (locks.LockRequest(locks.ClientKey("collision-12634"), shared),
                  locks.LockRequest(locks.AppKey(U1), exclusive))
    plan = locks.LockPlan(originals)
    assert plan.requests == originals
    assert [(lock.namespace, lock.key) for lock in plan.locks] == [
        (0x50430010, -319792828), (0x50430020, -1045510226),
        (0x50430020, 1768098544), (0x50430030, -869480766),
        (0x50430040, -841653354), (0x50430050, 1613620900),
        (0x50430060, 1382645572), (0x50430070, 54729058),
        (0x50430080, 1773742574), (0x50430090, 1590726244),
        (0x50430095, 621817402),
    ]
    assert plan.locks[0].mode is exclusive
    with pytest.raises(FrozenInstanceError):
        plan.requests = ()
    with pytest.raises(TypeError):
        locks.LockPlan(list(originals))
    with pytest.raises(TypeError):
        locks.LockPlan(())


def test_real_sha_prefix_collision_is_serialization_only():
    a, b = locks.ClientKey("collision-12634"), locks.ClientKey("collision-44041")
    assert a != b
    assert locks.advisory_key(a) == locks.advisory_key(b) == (0x50430020, -1045510226)
    shared, exclusive = locks.LockMode.SHARED, locks.LockMode.EXCLUSIVE
    requests = (locks.LockRequest(a, shared), locks.LockRequest(b, exclusive))
    plan = locks.LockPlan(requests)
    assert plan.requests == requests
    assert plan.locks == (locks.ActualLock(0x50430020, -1045510226, exclusive),)


@pytest.mark.parametrize("statement,function", [
    (locks._SHARED_SQL, "pg_advisory_xact_lock_shared"),
    (locks._EXCLUSIVE_SQL, "pg_advisory_xact_lock"),
])
def test_explicit_two_integer_sql_shape(statement, function):
    assert set(statement._bindparams) == {"namespace", "key"}
    assert all(type(param.type) is Integer for param in statement._bindparams.values())
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert sql == f"SELECT {function}(CAST(%(namespace)s AS INTEGER), CAST(%(key)s AS INTEGER))"
    assert "bigint" not in sql.lower()


def test_forged_and_copied_caps_have_no_issuance():
    plan = locks.LockPlan((locks.LockRequest(locks.AppKey(U1), locks.LockMode.SHARED),))
    forged = locks.ScopedLockCapability(plan)
    with Session() as session:
        for capability in (forged, copy(forged), deepcopy(forged), replace(forged), object()):
            with pytest.raises(locks.ScopedLockError, match="not issued"):
                locks.require_scoped_locks(session, capability, plan.requests)
