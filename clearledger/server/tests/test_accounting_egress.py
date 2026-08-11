import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.dialects import postgresql

from app.database import ACCOUNTING_EGRESS_MIGRATION_DDL
from app.models import (
    AccountingShadowResult,
    AccountingSourcePolicy,
    CutoverManifest,
    ExportPacket,
)
from app.routers import store_router
from app.routers import export_packets_router
from app.routers.export_packets_router import (
    _extension_queue_statement,
    _generic_packet_list_statement,
    _generic_packet_stats_statement,
    _generic_packets_by_doc_statement,
    _reject_accounting_generic_mutation,
)
from app.schemas import ExportPacketUpdate
from app.services import bp_export
from app.services.accounting_egress import (
    ACCOUNTING_DOCUMENT_KINDS,
    ACCOUNTING_PACKET_KINDS,
    AccountingEgressDenied,
    AccountingEgressGuard,
    canonical_manifest_hash,
    manifest_payload_for_policy,
)
from app.services.bp_canon import packet_hash


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
    def __init__(self, policies=(), manifests=(), packets=()):
        self.policies = list(policies)
        self.manifests = list(manifests)
        self.packets = list(packets)
        self.added = []
        self.deleted = []
        self.flush_count = 0
        self.events = []
        self.lock_scope_keys = []
        self.for_update_entities = []

    async def execute(self, statement, parameters=None):
        if "pg_advisory_xact_lock" in str(statement):
            self.events.append("scope_lock")
            self.lock_scope_keys.append(parameters["scope_key"])
            return _Result([])
        entity = statement.column_descriptions[0].get("entity")
        if entity is AccountingSourcePolicy:
            rows = self.policies
            self.events.append("policy_read")
        elif entity is CutoverManifest:
            rows = self.manifests
            self.events.append("manifest_read")
        elif entity is ExportPacket:
            rows = self.packets
            self.events.append("outbox_read")
        else:
            raise AssertionError(f"unexpected statement: {statement}")
        if statement._for_update_arg is not None:
            self.for_update_entities.append(entity)
        return _Result(rows)

    def add(self, row):
        self.added.append(row)
        if isinstance(row, ExportPacket):
            self.packets.append(row)
            self.events.append("outbox_insert")

    async def flush(self):
        self.flush_count += 1

    async def refresh(self, _row):
        pass

    async def delete(self, row):
        self.deleted.append(row)


def _packet(
    station_id: int,
    fact_at: datetime,
    *,
    food: bool = False,
    policy: AccountingSourcePolicy | None = None,
    manifest: CutoverManifest | None = None,
    version: str = "3",
    document_kind: str | None = None,
    revision: int = 1,
    fact_origin: str = "store",
) -> dict:
    document = {
        "Тип": document_kind or ("retail_sale_sidegoods" if food else "inventory"),
        "ИсточникUUID": str(uuid.uuid4()),
        "Дата": fact_at.isoformat(),
        "Товары": [{"ЭтоБлюдо": True}] if food else [],
    }
    packet = {
        "ВерсияФормата": version,
        "ИдентификаторПакета": str(uuid.uuid4()),
        "РевизияПакета": revision,
        "ИсточникФакта": fact_origin,
        "ИдентификаторПолитики": str(policy.id) if policy else str(uuid.uuid4()),
        "РевизияПолитики": policy.revision if policy else 1,
        "ХешПолитики": manifest.manifest_hash if manifest else "sha256:" + "0" * 64,
        "Смена": {
            "КодАЗС": str(station_id),
            "Открытие": (fact_at - timedelta(hours=8)).isoformat(),
            "Закрытие": fact_at.isoformat(),
        },
        "Документы": [document],
        "НСИ": [],
        "ХешПакета": "",
    }
    packet["ХешПакета"] = packet_hash(packet)
    return packet


def _policy(
    company_id: uuid.UUID,
    station_id: int,
    effective_from: datetime,
    *,
    revision: int = 1,
    producer: str = "central_ledger",
    effective_to: datetime | None = None,
) -> AccountingSourcePolicy:
    return AccountingSourcePolicy(
        id=uuid.uuid4(),
        company_id=company_id,
        station_id=station_id,
        policy_group="sidegoods_foodservice",
        revision=revision,
        effective_from=effective_from,
        effective_to=effective_to,
        transport_producer=producer,
        shadow_validation_enabled=True,
    )


def _effective_manifest(policy: AccountingSourcePolicy) -> CutoverManifest:
    approvals = [
        {"approver_id": "merchandiser", "approved_at": "2026-08-01T08:00:00Z"},
        {"approver_id": "accountant", "approved_at": "2026-08-01T08:05:00Z"},
    ]
    operational = policy.effective_from - timedelta(minutes=5)
    accounting = policy.effective_from
    deadline = policy.effective_from - timedelta(minutes=1)
    payload = manifest_payload_for_policy(
        policy,
        approvals=approvals,
        operational_cutover_at=operational,
        accounting_transport_cutover_at=accounting,
        arm_deadline=deadline,
    )
    manifest_hash = canonical_manifest_hash(payload)
    return CutoverManifest(
        id=uuid.uuid4(),
        policy_id=policy.id,
        company_id=policy.company_id,
        station_id=policy.station_id,
        policy_group=policy.policy_group,
        revision=policy.revision,
        state="effective",
        canonical_payload=payload,
        manifest_hash=manifest_hash,
        approvals=approvals,
        operational_cutover_at=operational,
        accounting_transport_cutover_at=accounting,
        late_arrival_until=None,
        arm_deadline=deadline,
        prepare_ack_hash=manifest_hash,
        arm_ack_hash=manifest_hash,
        armed_at=deadline,
        effective_at=accounting,
    )


@pytest.mark.asyncio
async def test_missing_policy_and_legacy_policy_do_not_create_outbox():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    packet = _packet(9201, now - timedelta(hours=1))
    session = _Session()

    with pytest.raises(AccountingEgressDenied, match="effective-policy"):
        await AccountingEgressGuard(session, company_id).queue_packet(
            packet, "sha256:" + "0" * 64,
        )
    assert session.added == []

    session.policies = [
        _policy(company_id, 9201, now - timedelta(days=1), producer="legacy_epf")
    ]
    with pytest.raises(AccountingEgressDenied, match="legacy_epf"):
        await AccountingEgressGuard(session, company_id).queue_packet(
            packet, "sha256:" + "0" * 64,
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_overlapping_policy_intervals_fail_closed():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policies = [
        _policy(
            company_id, 9202, now - timedelta(days=3),
            revision=1, effective_to=now + timedelta(days=1),
        ),
        _policy(company_id, 9202, now - timedelta(days=2), revision=2),
    ]
    session = _Session(policies=policies)

    with pytest.raises(AccountingEgressDenied, match="перекрывающиеся"):
        await AccountingEgressGuard(session, company_id).queue_packet(
            _packet(9202, now - timedelta(hours=1)), "sha256:" + "0" * 64,
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_manifest_hash_mismatch_does_not_create_outbox():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9203, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    session = _Session([policy], [manifest])

    with pytest.raises(AccountingEgressDenied, match="manifest_hash запроса"):
        await AccountingEgressGuard(session, company_id).queue_packet(
            _packet(
                9203, now - timedelta(hours=1), policy=policy, manifest=manifest,
            ),
            "sha256:" + "f" * 64,
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_central_ledger_rejects_v2_contract():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9210, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    packet = _packet(
        9210, now - timedelta(hours=1), policy=policy, manifest=manifest,
        version="2",
    )
    session = _Session([policy], [manifest])

    with pytest.raises(AccountingEgressDenied, match="только контракт v3"):
        await AccountingEgressGuard(session, company_id).queue_packet(
            packet, manifest.manifest_hash,
        )
    assert session.added == []


@pytest.mark.parametrize(("field", "bad_value", "message"), [
    ("ИдентификаторПолитики", "00000000-0000-0000-0000-000000000000", "ИдентификаторПолитики"),
    ("РевизияПолитики", 999, "РевизияПолитики"),
    ("ХешПолитики", "sha256:" + "f" * 64, "ХешПолитики"),
])
@pytest.mark.asyncio
async def test_v3_policy_identity_must_match_exactly(field, bad_value, message):
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9211, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    packet = _packet(
        9211, now - timedelta(hours=1), policy=policy, manifest=manifest,
    )
    packet[field] = bad_value
    packet["ХешПакета"] = packet_hash(packet)
    session = _Session([policy], [manifest])

    with pytest.raises(AccountingEgressDenied, match=message):
        await AccountingEgressGuard(session, company_id).queue_packet(
            packet, manifest.manifest_hash,
        )
    assert session.added == []


@pytest.mark.parametrize(("case", "message"), [
    ("missing_armed", "armed_at"),
    ("missing_effective", "effective_at"),
    ("late_arm", "armed после arm_deadline"),
    ("early_effective", "effective раньше accounting cutover"),
    ("future_effective", "effective_at находится в будущем"),
])
@pytest.mark.asyncio
async def test_effective_manifest_requires_valid_lifecycle_times(case, message):
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9212, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    if case == "missing_armed":
        manifest.armed_at = None
    elif case == "missing_effective":
        manifest.effective_at = None
    elif case == "late_arm":
        manifest.armed_at = manifest.arm_deadline + timedelta(seconds=1)
    elif case == "early_effective":
        manifest.effective_at = manifest.accounting_transport_cutover_at - timedelta(seconds=1)
    else:
        manifest.effective_at = now + timedelta(hours=1)
    packet = _packet(
        9212, now - timedelta(hours=1), policy=policy, manifest=manifest,
    )
    session = _Session([policy], [manifest])

    with pytest.raises(AccountingEgressDenied, match=message):
        await AccountingEgressGuard(session, company_id).queue_packet(
            packet, manifest.manifest_hash,
        )
    assert session.added == []


@pytest.mark.asyncio
async def test_invalid_packet_uuid_does_not_create_outbox():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9213, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    packet = _packet(
        9213, now - timedelta(hours=1), policy=policy, manifest=manifest,
    )
    packet["ИдентификаторПакета"] = "not-a-uuid"
    packet["ХешПакета"] = packet_hash(packet)
    session = _Session([policy], [manifest])

    with pytest.raises(AccountingEgressDenied, match="корректным UUID"):
        await AccountingEgressGuard(session, company_id).queue_packet(
            packet, manifest.manifest_hash,
        )
    assert session.added == []
    assert session.packets == []


@pytest.mark.asyncio
async def test_guarded_queue_is_idempotent_and_food_kind_isolated():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9204, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    packet = _packet(
        9204, now - timedelta(hours=1), food=True,
        policy=policy, manifest=manifest,
    )
    session = _Session([policy], [manifest])
    guard = AccountingEgressGuard(session, company_id)

    first = await guard.queue_packet(packet, manifest.manifest_hash)
    second = await guard.queue_packet(packet, manifest.manifest_hash)

    assert first.created is True
    assert second.created is False
    assert second.packet.id == first.packet.id
    assert first.packet.status == "queued"
    assert first.packet.kind == "food_accounting_group"
    assert first.packet.idem_key.endswith(packet["ХешПакета"].removeprefix("sha256:"))
    assert len(first.packet.idem_key) == 112
    assert len(session.packets) == 1

    first.packet.status = "accepted"
    terminal_repeat = await guard.queue_packet(packet, manifest.manifest_hash)

    assert terminal_repeat.created is False
    assert terminal_repeat.packet.status == "accepted"
    assert len(session.packets) == 1


def test_shadow_result_is_stored_outside_deliverable_outbox():
    assert AccountingShadowResult.__tablename__ == "accounting_shadow_results"
    assert AccountingShadowResult.__tablename__ != ExportPacket.__tablename__
    assert {constraint.name for constraint in AccountingShadowResult.__table__.constraints} >= {
        "ck_accounting_shadow_result_status",
        "uq_accounting_shadow_result_version",
    }


def test_legacy_extension_queue_excludes_only_new_accounting_kinds():
    assert ACCOUNTING_PACKET_KINDS == (
        "food_accounting_group", "store_accounting_group",
    )
    company_id = uuid.uuid4()
    statement = _extension_queue_statement(company_id, None)
    sql = str(statement.compile(
        dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
    ))

    excluded = sql.split("export_packets.kind NOT IN (", 1)[1].split(")", 1)[0]
    assert {value.strip(" '") for value in excluded.split(",")} == {
        "food_accounting_group", "store_accounting_group",
    }
    assert "shift_orp" not in sql
    assert "purchase_ttn" not in sql
    assert "cash_pko" not in sql


def test_overlap_trigger_locks_scope_before_checking_existing_rows():
    trigger_ddl = next(
        ddl for ddl in ACCOUNTING_EGRESS_MIGRATION_DDL
        if "reject_accounting_source_policy_overlap" in ddl
        and "RETURNS trigger" in ddl
    )

    lock_at = trigger_ddl.index("pg_advisory_xact_lock")
    exists_at = trigger_ddl.index("IF EXISTS")
    assert lock_at < exists_at
    assert "NEW.company_id::text" in trigger_ddl
    assert "NEW.station_id::text" in trigger_ddl
    assert "NEW.policy_group" in trigger_ddl


def test_manifest_trigger_serializes_insert_and_update_on_same_scope_key():
    function_ddl = next(
        ddl for ddl in ACCOUNTING_EGRESS_MIGRATION_DDL
        if "protect_cutover_manifest_payload" in ddl
        and "RETURNS trigger" in ddl
    )
    trigger_ddl = next(
        ddl for ddl in ACCOUNTING_EGRESS_MIGRATION_DDL
        if "CREATE TRIGGER cutover_manifest_immutable_trg" in ddl
    )

    assert "pg_advisory_xact_lock" in function_ddl
    assert "NEW.company_id::text" in function_ddl
    assert "NEW.station_id::text" in function_ddl
    assert "NEW.policy_group" in function_ddl
    assert "BEFORE INSERT OR UPDATE OR DELETE" in trigger_ddl


@pytest.mark.asyncio
async def test_guard_locks_then_reads_for_update_then_inserts_in_same_session():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9214, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    packet = _packet(
        9214, now - timedelta(hours=1), policy=policy, manifest=manifest,
    )
    session = _Session([policy], [manifest])

    result = await AccountingEgressGuard(session, company_id).queue_packet(
        packet, manifest.manifest_hash,
    )

    assert result.created is True
    assert session.events == [
        "scope_lock", "policy_read", "manifest_read", "scope_lock",
        "outbox_read", "outbox_insert",
    ]
    assert session.lock_scope_keys == [
        f"{company_id}:9214:sidegoods_foodservice",
        f"accounting-outbox:{company_id}:{packet['ИдентификаторПакета']}",
    ]
    assert session.for_update_entities == [
        AccountingSourcePolicy, CutoverManifest, ExportPacket,
    ]


@pytest.mark.parametrize("document_kind", ["shift_orp", "fuel_sale", "unknown_kind"])
@pytest.mark.asyncio
async def test_unknown_and_fuel_document_kinds_never_reach_outbox(document_kind):
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9215, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    packet = _packet(
        9215, now - timedelta(hours=1), policy=policy, manifest=manifest,
        document_kind=document_kind,
    )
    session = _Session([policy], [manifest])

    with pytest.raises(AccountingEgressDenied, match="не разрешён"):
        await AccountingEgressGuard(session, company_id).queue_packet(
            packet, manifest.manifest_hash,
        )

    assert session.events == ["scope_lock"]
    assert session.added == []
    assert session.packets == []


def test_accounting_document_allowlist_is_exact():
    assert ACCOUNTING_DOCUMENT_KINDS == (
        "purchase", "return_purchase", "transfer", "inventory", "gain",
        "writeoff", "retail_sale_sidegoods", "return_sale", "recipe",
        "production_release", "ingredients_writeoff",
    )


def test_generic_reads_exclude_accounting_payloads_only():
    company_id = uuid.uuid4()
    statements = (
        _generic_packet_list_statement(company_id),
        _generic_packet_stats_statement(company_id),
        _generic_packets_by_doc_statement(uuid.uuid4()),
    )
    for statement in statements:
        sql = str(statement.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True},
        ))
        excluded = sql.split("export_packets.kind NOT IN (", 1)[1].split(")", 1)[0]
        assert {value.strip(" '") for value in excluded.split(",")} == {
            "food_accounting_group", "store_accounting_group",
        }
        assert "shift_orp" not in sql
        assert "purchase_ttn" not in sql


@pytest.mark.asyncio
async def test_generic_mutations_reject_accounting_packets(monkeypatch):
    packet_id = uuid.uuid4()
    current = [None]

    async def owned(_model, _packet_id, _user, _db):
        return current[0]

    monkeypatch.setattr(export_packets_router, "get_owned", owned)
    for kind in ("store_accounting_group", "food_accounting_group"):
        for operation in ("update", "delete", "ack"):
            packet = ExportPacket(
                id=packet_id,
                company_id=uuid.uuid4(),
                kind=kind,
                idem_key=f"TEST|{kind}|{operation}",
                source_entry_ids=[],
                status="queued",
                payload={"original": True},
            )
            current[0] = packet
            session = _Session(packets=[packet])
            with pytest.raises(HTTPException) as error:
                if operation == "update":
                    await export_packets_router.update_packet(
                        str(packet_id),
                        ExportPacketUpdate(status="sent", payload={"tampered": True}),
                        db=session,
                        _u=SimpleNamespace(),
                    )
                elif operation == "delete":
                    await export_packets_router.delete_packet(
                        str(packet_id), db=session, _u=SimpleNamespace(),
                    )
                else:
                    await export_packets_router.ack_packet(
                        str(packet_id), {}, db=session, _u=SimpleNamespace(),
                    )
            assert error.value.status_code == 409
            assert packet.status == "queued"
            assert packet.payload == {"original": True}
            assert session.deleted == []
            assert session.flush_count == 0

    _reject_accounting_generic_mutation(ExportPacket(kind="shift_orp"))


@pytest.mark.asyncio
async def test_emit_route_queues_and_never_calls_file_writer(monkeypatch):
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9207, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    packet = _packet(
        9207, now - timedelta(hours=1), policy=policy, manifest=manifest,
    )
    session = _Session([policy], [manifest])
    file_writer_called = False

    class Emitter:
        def __init__(self, _db, _company_id):
            pass

        async def verify_shift_package(self, _shift_key):
            return {"ok": True, "checks": []}

        async def build_shift_package(self, _shift_key):
            return packet

        async def emit_to_dir(self, _shift_key, _directory):
            nonlocal file_writer_called
            file_writer_called = True
            raise AssertionError("file writer must not be called")

    async def receipt_access(_user, _db):
        return store_router.ReceiptAccess(company_id, False, frozenset({9207}))

    monkeypatch.setattr(bp_export, "BpPackageEmitter", Emitter)
    monkeypatch.setattr(store_router, "_receipt_access", receipt_access)
    monkeypatch.setattr(store_router, "log_export", lambda *_args, **_kwargs: None)

    response = await store_router.store_bp_package_emit(
        shift_key="test-shift",
        manifest_hash=manifest.manifest_hash,
        user=SimpleNamespace(id=uuid.uuid4()),
        db=session,
    )

    assert response["status"] == "queued"
    assert response["created"] is True
    assert response["packet_uuid"] == packet["ИдентификаторПакета"]
    assert response["revision"] == packet["РевизияПакета"]
    assert response["contract_version"] == "3"
    assert "file" not in response and "path" not in response
    assert file_writer_called is False


@pytest.mark.asyncio
async def test_emit_route_checks_station_scope_before_creating_packet(monkeypatch):
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    policy = _policy(company_id, 9208, now - timedelta(days=1))
    manifest = _effective_manifest(policy)
    packet = _packet(
        9208, now - timedelta(hours=1), policy=policy, manifest=manifest,
    )
    session = _Session([policy], [manifest])
    verify_called = False

    class Emitter:
        def __init__(self, _db, _company_id):
            pass

        async def verify_shift_package(self, _shift_key):
            nonlocal verify_called
            verify_called = True
            return {"ok": True, "checks": []}

        async def build_shift_package(self, _shift_key):
            return packet

    async def receipt_access(_user, _db):
        return store_router.ReceiptAccess(company_id, False, frozenset({9999}))

    monkeypatch.setattr(bp_export, "BpPackageEmitter", Emitter)
    monkeypatch.setattr(store_router, "_receipt_access", receipt_access)

    with pytest.raises(HTTPException) as error:
        await store_router.store_bp_package_emit(
            shift_key="forbidden-shift",
            manifest_hash=manifest.manifest_hash,
            user=SimpleNamespace(id=uuid.uuid4()),
            db=session,
        )

    assert error.value.status_code == 403
    assert verify_called is False
    assert session.added == []
    assert session.packets == []


@pytest.mark.parametrize("operation", ["preview", "verify"])
@pytest.mark.asyncio
async def test_preview_and_verify_enforce_station_scope(monkeypatch, operation):
    company_id = uuid.uuid4()
    packet = _packet(9216, datetime.now(timezone.utc).replace(microsecond=0))
    verify_called = False

    class Emitter:
        def __init__(self, _db, _company_id):
            assert _company_id == company_id

        async def build_shift_package(self, _shift_key):
            return packet

        async def verify_shift_package(self, _shift_key):
            nonlocal verify_called
            verify_called = True
            return {"ok": True, "checks": []}

    async def receipt_access(_user, _db):
        return store_router.ReceiptAccess(company_id, False, frozenset({9999}))

    monkeypatch.setattr(bp_export, "BpPackageEmitter", Emitter)
    monkeypatch.setattr(store_router, "_receipt_access", receipt_access)

    with pytest.raises(HTTPException) as error:
        if operation == "preview":
            await store_router.store_bp_package(
                shift_key="forbidden-shift", user=SimpleNamespace(), db=SimpleNamespace(),
            )
        else:
            await store_router.store_bp_package_verify(
                shift_key="forbidden-shift", user=SimpleNamespace(), db=SimpleNamespace(),
            )

    assert error.value.status_code == 403
    assert verify_called is False


@pytest.mark.asyncio
async def test_public_file_emitter_is_fail_closed(tmp_path):
    emitter = bp_export.BpPackageEmitter(SimpleNamespace(), uuid.uuid4())

    with pytest.raises(AccountingEgressDenied, match="Прямая запись"):
        await emitter.emit_to_dir("any-shift", str(tmp_path))
    assert list(tmp_path.iterdir()) == []
