import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.database import ACCOUNTING_REVISION_MIGRATION_DDL
from app.models import (
    AccountingOutboxAttempt,
    AccountingSourceLink,
    DataEntry,
    ExportPacket,
)
from app.routers.export_packets_router import _reject_accounting_generic_create
from app.services.accounting_outbox import (
    ACCOUNTING_FSM,
    AccountingOutboxService,
    AccountingRevisionConflict,
    append_canonical_fact,
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
    def __init__(self, *, entries=(), packets=(), scripted=()):
        self.entries = list(entries)
        self.packets = list(packets)
        self.scripted = list(scripted)
        self.added = []
        self.flush_count = 0
        self.events = []

    async def execute(self, statement, parameters=None):
        if "pg_advisory_xact_lock" in str(statement):
            self.events.append(("lock", parameters["scope_key"]))
            return _Result([])
        if self.scripted:
            return _Result(self.scripted.pop(0))
        entity = statement.column_descriptions[0].get("entity")
        if entity is DataEntry:
            rows = sorted(
                self.entries, key=lambda row: row.revision or 0, reverse=True,
            )
        elif entity is ExportPacket:
            rows = sorted(
                self.packets, key=lambda row: row.revision or 0, reverse=True,
            )
        else:
            raise AssertionError(f"unexpected statement: {statement}")
        return _Result(rows)

    def add(self, row):
        self.added.append(row)
        if isinstance(row, DataEntry):
            self.entries.append(row)
        elif isinstance(row, ExportPacket):
            self.packets.append(row)

    async def flush(self):
        self.flush_count += 1


def _packet(
    packet_uuid: uuid.UUID,
    revision: int,
    *,
    amount: int = 100,
) -> dict:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    packet = {
        "ВерсияФормата": "3",
        "ИдентификаторПакета": str(packet_uuid),
        "РевизияПакета": revision,
        "Источник": "central-ledger",
        "ИсточникФакта": "store",
        "Смена": {"КодАЗС": "208", "Закрытие": now.isoformat()},
        "Документы": [{
            "Тип": "purchase",
            "ИсточникUUID": str(uuid.uuid4()),
            "Дата": now.isoformat(),
            "СуммаДокумента": amount,
        }],
        "НСИ": [],
        "ХешПакета": "",
    }
    packet["ХешПакета"] = packet_hash(packet)
    return packet


def _outbox(company_id: uuid.UUID, *, status: str = "queued") -> ExportPacket:
    packet_uuid = uuid.uuid4()
    return ExportPacket(
        id=uuid.uuid4(),
        company_id=company_id,
        kind="store_accounting_group",
        idem_key=f"ACCOUNTING|{packet_uuid}|{'a' * 64}",
        source_entry_ids=[],
        status=status,
        payload={"fixed": True},
        packet_uuid=packet_uuid,
        revision=1,
        contract_version="3",
        content_hash="a" * 64,
        fact_origin="store",
        transport_producer="central_ledger",
    )


def test_revision_models_are_nullable_for_legacy_and_scoped_exactly():
    for name in (
        "document_id", "revision", "content_hash", "fact_origin",
        "supersedes_entry_id",
    ):
        assert DataEntry.__table__.c[name].nullable is True
    for name in (
        "packet_uuid", "revision", "contract_version", "content_hash",
        "fact_origin", "transport_producer", "attempt_id", "lease_until",
        "ack_payload", "component_result", "error_code", "error_detail",
    ):
        assert ExportPacket.__table__.c[name].nullable is True
    assert DataEntry.__table__.c.content_hash.type.length == 64
    assert ExportPacket.__table__.c.content_hash.type.length == 64
    assert AccountingSourceLink.__tablename__ == "accounting_source_links"
    assert AccountingOutboxAttempt.__tablename__ == "accounting_outbox_attempts"
    source_index = next(iter(AccountingSourceLink.__table__.indexes))
    assert source_index.name == "uq_accounting_source_link_scope"
    assert [column.name for column in source_index.columns] == [
        "company_id", "projection_source", "source_kind", "source_document_id",
    ]
    data_index = next(
        index for index in DataEntry.__table__.indexes
        if index.name == "uq_data_entry_document_revision"
    )
    assert [column.name for column in data_index.columns] == [
        "company_id", "document_id", "revision",
    ]
    assert str(data_index.dialect_options["postgresql"]["where"]) == (
        "document_id IS NOT NULL"
    )


def test_legacy_active_idem_index_keeps_exact_semantics_except_accounting_kinds():
    ddl = next(
        value for value in ACCOUNTING_REVISION_MIGRATION_DDL
        if "CREATE UNIQUE INDEX uq_export_packets_active_idem" in value
    )
    predicate = ddl.split("WHERE", 1)[1]
    assert "idem_key IS NOT NULL" in predicate
    assert "status <> 'rejected'" in predicate
    excluded = predicate.split("kind NOT IN (", 1)[1].split(")", 1)[0]
    assert {item.strip(" '\n\r") for item in excluded.split(",")} == {
        "food_accounting_group", "store_accounting_group",
    }
    for legacy_kind in ("shift_orp", "purchase_ttn", "cash_pko"):
        assert legacy_kind not in predicate

    accounting = next(
        value for value in ACCOUNTING_REVISION_MIGRATION_DDL
        if "CREATE UNIQUE INDEX IF NOT EXISTS uq_export_packets_accounting_revision"
        in value
    )
    assert "(company_id, packet_uuid, revision)" in accounting
    assert "kind IN ('food_accounting_group', 'store_accounting_group')" in accounting


@pytest.mark.asyncio
async def test_accounting_revision_repeat_is_noop_and_new_hash_appends():
    company_id = uuid.uuid4()
    packet_uuid = uuid.uuid4()
    first_packet = _packet(packet_uuid, 1, amount=100)
    session = _Session()
    service = AccountingOutboxService(session, company_id)

    first = await service.append_validated_revision(
        first_packet, "store_accounting_group",
    )
    repeated = await service.append_validated_revision(
        first_packet, "store_accounting_group",
    )
    old_payload = first.row.payload
    second_packet = _packet(packet_uuid, 2, amount=101)
    second = await service.append_validated_revision(
        second_packet, "store_accounting_group",
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.row is first.row
    assert second.created is True
    assert second.row.revision == 2
    assert second.row.id != first.row.id
    assert first.row.revision == 1
    assert first.row.payload is old_payload
    assert first.row.status == "validated"
    assert second.row.status == "validated"
    assert len(session.packets) == 2


@pytest.mark.asyncio
async def test_lower_revision_service_has_no_deliverable_queue_bypass():
    company_id = uuid.uuid4()
    session = _Session()
    service = AccountingOutboxService(session, company_id)

    public_operations = {
        name for name, member in inspect.getmembers(
            AccountingOutboxService, inspect.iscoroutinefunction,
        )
        if not name.startswith("_")
    }
    assert public_operations == {
        "append_validated_revision",
        "apply_ack",
        "claim_next",
        "fail_attempt",
        "mark_sent",
        "recover_expired_leases",
    }
    result = await service.append_validated_revision(
        _packet(uuid.uuid4(), 1), "store_accounting_group",
    )

    session.scripted.extend([[], []])
    assert await service.claim_next(lease_seconds=30) is None
    assert await service.recover_expired_leases() == []

    attempt_id = uuid.uuid4()
    with pytest.raises(AccountingRevisionConflict):
        await service.mark_sent(result.row.id, attempt_id)
    with pytest.raises(AccountingRevisionConflict):
        await service.fail_attempt(
            result.row.id,
            attempt_id,
            retry_at=datetime.now(timezone.utc),
            error_code="test",
        )
    with pytest.raises(AccountingRevisionConflict):
        await service.apply_ack(
            result.row.id,
            attempt_id=attempt_id,
            content_hash=result.row.content_hash,
            result="accepted",
            ack_payload={"test": True},
        )

    assert result.row.status == "validated"
    assert all(row.status != "queued" for row in session.packets)


@pytest.mark.asyncio
async def test_changed_hash_requires_greater_revision_and_keeps_old_row():
    company_id = uuid.uuid4()
    packet_uuid = uuid.uuid4()
    session = _Session()
    service = AccountingOutboxService(session, company_id)
    first = await service.append_validated_revision(
        _packet(packet_uuid, 2, amount=100), "store_accounting_group",
    )

    with pytest.raises(AccountingRevisionConflict, match="большей РевизииПакета"):
        await service.append_validated_revision(
            _packet(packet_uuid, 2, amount=200), "store_accounting_group",
        )

    assert len(session.packets) == 1
    assert first.row.revision == 2
    assert first.row.payload["Документы"][0]["СуммаДокумента"] == 100


@pytest.mark.asyncio
async def test_canonical_fact_appends_revision_and_supersedes_only_status():
    company_id = uuid.uuid4()
    document_id = uuid.uuid4()
    previous = DataEntry(
        id=uuid.uuid4(), company_id=company_id, title="ПТУ",
        category_id="store", subcategory_id="purchase", status="verified",
        source="api", source_label="Edge", meta={"amount": 100}, layer="clean",
        document_id=document_id, revision=1, content_hash="a" * 64,
        fact_origin="edge",
    )
    new_entry = DataEntry(
        id=uuid.uuid4(), company_id=company_id, title="ПТУ",
        category_id="store", subcategory_id="purchase", status="verified",
        source="api", source_label="Edge", meta={"amount": 101}, layer="clean",
    )
    session = _Session(entries=[previous])

    result = await append_canonical_fact(
        session, new_entry, document_id=document_id, revision=2,
        content_hash="b" * 64, fact_origin="edge",
    )

    assert result.created is True
    assert previous.status == "superseded"
    assert previous.meta == {"amount": 100}
    assert new_entry.supersedes_entry_id == previous.id
    assert new_entry.revision == 2
    assert len(session.entries) == 2


@pytest.mark.asyncio
async def test_lease_claim_and_recovery_are_idempotent():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    row = _outbox(company_id)
    session = _Session(scripted=[[row], [row], []])
    service = AccountingOutboxService(session, company_id)

    claimed = await service.claim_next(lease_seconds=30, now=now)
    attempt_id = claimed.attempt_id
    recovered = await service.recover_expired_leases(
        now=now + timedelta(seconds=31),
    )
    repeated = await service.recover_expired_leases(
        now=now + timedelta(seconds=32),
    )

    assert attempt_id is not None
    assert recovered == [row]
    assert row.status == "retry_wait"
    assert row.attempt_id is None
    assert row.lease_until is None
    assert repeated == []


@pytest.mark.asyncio
async def test_sender_attempt_and_ack_are_bound_to_attempt_and_hash():
    company_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)
    row = _outbox(company_id, status="leased")
    row.attempt_id = uuid.uuid4()
    row.lease_until = now + timedelta(minutes=1)
    attempt_id = row.attempt_id
    session = _Session(scripted=[[row], [row], [row]])
    service = AccountingOutboxService(session, company_id)

    sent = await service.mark_sent(row.id, attempt_id, now=now)
    assert sent.status == "sent_waiting_ack"
    assert sent.attempt_id == attempt_id

    with pytest.raises(AccountingRevisionConflict, match="другому hash"):
        await service.apply_ack(
            row.id, attempt_id=attempt_id, content_hash="b" * 64,
            result="accepted", ack_payload={"ok": True}, now=now,
        )

    accepted = await service.apply_ack(
        row.id, attempt_id=attempt_id, content_hash="a" * 64,
        result="accepted", ack_payload={"ok": True},
        component_result={"purchase": "accepted"}, now=now,
    )
    assert accepted.status == "accepted"
    assert accepted.ack_payload == {"ok": True}
    assert accepted.component_result == {"purchase": "accepted"}


def test_accounting_fsm_and_sql_guards_are_exact_and_append_only():
    assert ACCOUNTING_FSM == {
        "draft": frozenset({"validated"}),
        "validated": frozenset({"queued", "retry_wait"}),
        "queued": frozenset({"leased"}),
        "retry_wait": frozenset({"leased"}),
        "leased": frozenset({"sent_waiting_ack", "retry_wait"}),
        "sent_waiting_ack": frozenset({"accepted", "rejected", "needs_review"}),
        "accepted": frozenset(),
        "rejected": frozenset(),
        "needs_review": frozenset(),
    }
    guard = next(
        value for value in ACCOUNTING_REVISION_MIGRATION_DDL
        if "protect_accounting_export_packet" in value and "RETURNS trigger" in value
    )
    assert "validated accounting outbox core is immutable" in guard
    assert "OLD.status = 'draft' AND NEW.status = 'validated'" in guard
    assert "OLD.status IN ('queued','retry_wait') AND NEW.status = 'leased'" in guard
    assert "OLD.status = 'sent_waiting_ack'" in guard
    assert guard.index("pg_advisory_xact_lock") < guard.index("SELECT p.revision")
    assert "accounting packet revision must increase" in guard
    canonical = next(
        value for value in ACCOUNTING_REVISION_MIGRATION_DDL
        if "protect_canonical_data_entry" in value and "RETURNS trigger" in value
    )
    assert canonical.index("pg_advisory_xact_lock") < canonical.index("SELECT d.id")
    assert "canonical revision must supersede latest row" in canonical
    history = next(
        value for value in ACCOUNTING_REVISION_MIGRATION_DDL
        if "append_accounting_outbox_history" in value and "RETURNS trigger" in value
    )
    immutable = next(
        value for value in ACCOUNTING_REVISION_MIGRATION_DDL
        if "protect_accounting_outbox_attempt" in value and "RETURNS trigger" in value
    )
    assert "INSERT INTO accounting_outbox_attempts" in history
    assert "accounting outbox history is append-only" in immutable


def test_generic_create_cannot_bypass_guard():
    for kind in ("store_accounting_group", "food_accounting_group"):
        with pytest.raises(HTTPException) as error:
            _reject_accounting_generic_create(kind)
        assert error.value.status_code == 409
    _reject_accounting_generic_create("shift_orp")
