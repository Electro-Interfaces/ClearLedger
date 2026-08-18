import inspect
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models import AccountingSourcePolicy, CutoverApproval, CutoverManifest
from app.routers import store_router
from app.services.cutover_policy import (
    CutoverPolicyError,
    CutoverPolicyService,
    canonical_manifest_hash,
    decide_policy_axes,
    trusted_manifest_export,
)


class _Scalars:
    def __init__(self, rows):
        self.rows = list(rows)

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return _Scalars(self.rows)


class _Session:
    def __init__(self, company_id):
        self.company_id = company_id
        self.policies = []
        self.manifests = []
        self.approvals = []
        self.lock_count = 0
        self.flush_count = 0

    async def execute(self, statement, parameters=None):
        if "pg_advisory_xact_lock" in str(statement):
            self.lock_count += 1
            return _Result([])
        entity = statement.column_descriptions[0].get("entity")
        if entity is AccountingSourcePolicy:
            rows = self.policies
        elif entity is CutoverManifest:
            rows = self.manifests
        elif entity is CutoverApproval:
            rows = self.approvals
        else:
            raise AssertionError(f"unexpected statement: {statement}")
        return _Result([
            row for row in rows if row.company_id == self.company_id
        ])

    def add(self, row):
        if getattr(row, "id", None) is None:
            row.id = uuid.uuid4()
        if isinstance(row, AccountingSourcePolicy):
            self.policies.append(row)
        elif isinstance(row, CutoverManifest):
            self.manifests.append(row)
        elif isinstance(row, CutoverApproval):
            self.approvals.append(row)
        else:
            raise AssertionError(type(row))

    async def flush(self):
        self.flush_count += 1


async def _prepared(session, now):
    return await CutoverPolicyService(session, session.company_id).prepare(
        station_id=208,
        fact_cutover_business_date=date(2026, 8, 20),
        transport_cutover_at=now + timedelta(hours=1),
        station_timezone="Europe/Moscow",
        arm_deadline=now + timedelta(minutes=30),
    )


@pytest.mark.asyncio
async def test_one_approver_cannot_arm_or_make_effective():
    company_id = uuid.uuid4()
    now = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    session = _Session(company_id)
    _, manifest = await _prepared(session, now)
    service = CutoverPolicyService(session, company_id)

    await service.approve(manifest.id, uuid.uuid4(), now, station_id=208)

    assert manifest.state == "prepared"
    with pytest.raises(CutoverPolicyError, match="Arm недопустим"):
        await service.arm(
            manifest.id, manifest.manifest_hash, now, station_id=208,
        )
    with pytest.raises(CutoverPolicyError, match="Effective недопустим"):
        await service.make_effective(
            manifest.id, manifest.manifest_hash, now + timedelta(hours=1),
            station_id=208,
        )


@pytest.mark.asyncio
async def test_repeated_same_approver_is_noop_and_second_distinct_approves():
    company_id = uuid.uuid4()
    now = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    session = _Session(company_id)
    policy, manifest = await _prepared(session, now)
    service = CutoverPolicyService(session, company_id)
    first = uuid.uuid4()

    _, approvals, created = await service.approve(
        manifest.id, first, now, station_id=208,
    )
    _, repeated, repeated_created = await service.approve(
        manifest.id, first, now + timedelta(seconds=1), station_id=208,
    )

    assert created is True
    assert repeated_created is False
    assert len(approvals) == len(repeated) == 1
    assert manifest.state == "prepared"

    await service.approve(
        manifest.id, uuid.uuid4(), now + timedelta(minutes=1), station_id=208,
    )

    assert manifest.state == "approved"
    assert policy.state == "approved"


@pytest.mark.asyncio
async def test_strict_approved_arm_effective_transitions():
    company_id = uuid.uuid4()
    now = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    session = _Session(company_id)
    policy, manifest = await _prepared(session, now)
    service = CutoverPolicyService(session, company_id)

    with pytest.raises(CutoverPolicyError, match="Arm недопустим"):
        await service.arm(manifest.id, manifest.manifest_hash, now, station_id=208)
    await service.approve(manifest.id, uuid.uuid4(), now, station_id=208)
    await service.approve(
        manifest.id, uuid.uuid4(), now + timedelta(minutes=1), station_id=208,
    )
    with pytest.raises(CutoverPolicyError, match="Arm hash"):
        await service.arm(manifest.id, "0" * 64, now, station_id=208)

    await service.arm(manifest.id, manifest.manifest_hash, now, station_id=208)
    assert manifest.state == policy.state == "armed"
    with pytest.raises(CutoverPolicyError, match="Transport cutover"):
        await service.make_effective(
            manifest.id, manifest.manifest_hash, now, station_id=208,
        )

    await service.make_effective(
        manifest.id, manifest.manifest_hash, now + timedelta(hours=1),
        station_id=208,
    )
    assert manifest.state == policy.state == "effective"
    assert session.lock_count >= 5


@pytest.mark.asyncio
async def test_company_and_station_isolation_fail_closed():
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    now = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    session_a = _Session(company_a)
    _, manifest = await _prepared(session_a, now)

    session_b = _Session(company_b)
    session_b.manifests = session_a.manifests
    session_b.policies = session_a.policies
    with pytest.raises(CutoverPolicyError) as company_error:
        await CutoverPolicyService(session_b, company_b).export_manifest(
            manifest.id, station_id=208,
        )
    assert company_error.value.status_code == 404

    with pytest.raises(CutoverPolicyError) as station_error:
        await CutoverPolicyService(session_a, company_a).export_manifest(
            manifest.id, station_id=209,
        )
    assert station_error.value.status_code == 404


@pytest.mark.asyncio
async def test_manifest_hash_stable_when_approval_audit_is_appended():
    company_id = uuid.uuid4()
    now = datetime(2026, 8, 18, 10, 0, tzinfo=timezone.utc)
    session = _Session(company_id)
    _, manifest = await _prepared(session, now)
    original_payload = dict(manifest.canonical_payload)
    original_hash = manifest.manifest_hash
    service = CutoverPolicyService(session, company_id)

    await service.approve(manifest.id, uuid.uuid4(), now, station_id=208)
    await service.approve(
        manifest.id, uuid.uuid4(), now + timedelta(minutes=1), station_id=208,
    )
    _, approvals, exported = await service.export_manifest(
        manifest.id, station_id=208,
    )

    assert "approvals" not in manifest.canonical_payload
    assert "late_arrival_until" not in manifest.canonical_payload
    assert manifest.canonical_payload == original_payload
    assert manifest.manifest_hash == original_hash
    assert canonical_manifest_hash(manifest.canonical_payload) == original_hash
    assert len(exported["approvals"]) == len(approvals) == 2
    assert exported["policy_hash"] == original_hash
    assert trusted_manifest_export(manifest, approvals) == exported


def test_fact_and_transport_axes_are_independent_for_late_correction():
    cutover = datetime(2026, 8, 20, 21, 0, tzinfo=timezone.utc)
    policy = AccountingSourcePolicy(
        id=uuid.uuid4(), company_id=uuid.uuid4(), station_id=208,
        policy_group="sidegoods_foodservice", revision=1, state="effective",
        fact_cutover_business_date=date(2026, 8, 21),
        station_timezone="Europe/Moscow", fact_origin_before="onec_legacy",
        fact_origin_after="edge", effective_from=cutover, effective_to=None,
        transport_cutover_at=cutover, transport_producer_before="legacy_epf",
        transport_producer="central_ledger", shadow_validation_enabled=True,
    )

    before = decide_policy_axes(
        policy, business_date=date(2026, 8, 20),
        delivery_at=cutover - timedelta(seconds=1),
    )
    after = decide_policy_axes(
        policy, business_date=date(2026, 8, 21), delivery_at=cutover,
    )
    late_correction = decide_policy_axes(
        policy, business_date=date(2026, 8, 20),
        delivery_at=cutover + timedelta(days=7),
        existing_fact_origin="onec_legacy",
    )

    assert (before.fact_origin, before.transport_producer) == (
        "onec_legacy", "legacy_epf",
    )
    assert (after.fact_origin, after.transport_producer) == (
        "edge", "central_ledger",
    )
    assert (late_correction.fact_origin, late_correction.transport_producer) == (
        "onec_legacy", "central_ledger",
    )


def test_unsafe_direct_effective_endpoint_and_approved_by_parameter_are_gone():
    direct_posts = [
        route for route in store_router.router.routes
        if route.path == "/store/bp-package/cutover" and "POST" in route.methods
    ]
    assert direct_posts == []
    assert "approved_by" not in inspect.signature(
        store_router.store_bp_package_cutover_approve
    ).parameters
