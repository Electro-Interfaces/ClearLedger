import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.database import (
    ACTIVE_GROUP_COLLISION_REPORT_DDL,
    ACTIVE_GROUP_READINESS_DDL,
    ACCOUNTING_REVISION_MIGRATION_DDL,
    BUSINESS_SHIFT_MIGRATION_DDL,
    _ensure_active_group_readiness,
)
from app.models import (
    AccountingBusinessGroup,
    AccountingClaimRequest,
    AccountingOutboxAttempt,
    AccountingSourceDecision,
    AccountingSourceLink,
    BusinessShift,
    BusinessShiftAlias,
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
from app.services.accounting_contract_v3 import (
    ack_hash,
    accounting_packet_uuid,
    alias_hash,
    business_key_hash,
    business_projection_hash,
)
from app.services.business_shift import BusinessShiftResolver


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
    def __init__(
        self, *, entries=(), packets=(), groups=(), shifts=(), aliases=(),
        decisions=(), claims=(), scripted=(), visible_company=None,
    ):
        self.entries = list(entries)
        self.packets = list(packets)
        self.groups = list(groups)
        self.shifts = list(shifts)
        self.aliases = list(aliases)
        self.decisions = list(decisions)
        self.claims = list(claims)
        self.visible_company = visible_company
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
        elif entity is AccountingBusinessGroup:
            rows = self.groups
        elif entity is BusinessShift:
            rows = self.shifts
        elif entity is AccountingClaimRequest:
            rows = self.claims
        elif entity is BusinessShiftAlias:
            rows = self.aliases
        elif entity is AccountingSourceDecision:
            rows = self.decisions
        else:
            raise AssertionError(f"unexpected statement: {statement}")
        if self.visible_company is not None:
            rows = [
                row for row in rows
                if getattr(row, "company_id", self.visible_company) == self.visible_company
            ]
        return _Result(rows)

    def add(self, row):
        self.added.append(row)
        if isinstance(row, DataEntry):
            self.entries.append(row)
        elif isinstance(row, ExportPacket):
            self.packets.append(row)
        elif isinstance(row, AccountingBusinessGroup):
            self.groups.append(row)
        elif isinstance(row, BusinessShift):
            self.shifts.append(row)
        elif isinstance(row, AccountingClaimRequest):
            self.claims.append(row)
        elif isinstance(row, BusinessShiftAlias):
            self.aliases.append(row)
        elif isinstance(row, AccountingSourceDecision):
            self.decisions.append(row)

    async def flush(self):
        self.flush_count += 1


def _identity(company_id: uuid.UUID):
    shift = BusinessShift(
        id=uuid.uuid4(), company_id=company_id,
        company_key="company-synthetic-001", station_id="208",
        business_date=datetime(2026, 8, 1).date(), status="resolved",
    )
    group = AccountingBusinessGroup(
        id=uuid.uuid4(), company_id=company_id, business_shift_id=shift.id,
        business_key_hash=business_key_hash(
            shift.id, shift.company_key, shift.station_id,
        ),
        packet_uuid=accounting_packet_uuid(shift.id), status="active",
    )
    return shift, group


def _packet(
    shift: BusinessShift,
    group: AccountingBusinessGroup,
    revision: int,
    *,
    amount: int = 100,
) -> dict:
    attributes = {
        "company_id": shift.company_key,
        "station_id": shift.station_id,
        "business_date": shift.business_date.isoformat(),
        "ose": "OSE-SYN-0001",
    }
    packet = {
        "ВерсияФормата": "3",
        "ВерсияКонтракта": "3.0.0",
        "ИдентификаторПакета": str(group.packet_uuid),
        "BusinessShiftID": str(shift.id),
        "BusinessShiftAliases": [{
            "Algorithm": "business-shift-common-alias-v1",
            "AliasHash": alias_hash("business-shift-common-alias-v1", attributes),
            "Attributes": attributes,
        }],
        "BusinessDate": shift.business_date.isoformat(),
        "CompanyID": shift.company_key,
        "StationID": shift.station_id,
        "BusinessKeyHash": group.business_key_hash,
        "FactOrigin": "edge",
        "TransportProducer": "central_ledger",
        "РевизияПакета": revision,
        "ИдентификаторПолитики": str(uuid.uuid5(uuid.NAMESPACE_URL, "test-policy-v3")),
        "РевизияПолитики": 1,
        "ХешПолитики": "0" * 64,
        "UnicodeNormalization": "NFC",
        "Смена": {},
        "Документы": [{
            "Тип": "retail_sale_sidegoods",
            "ИсточникUUID": str(uuid.uuid4()),
            "СуммаДокумента": amount,
        }],
        "НСИ": [],
        "ТТК": [],
        "ПолнотаГруппы": {
            "ОжидаемыеКомпоненты": [{
                "Порядок": 1, "Тип": "retail",
                "ИсточникUUID": "retail-synthetic-001",
            }],
        },
        "ХешПакета": "",
    }
    packet["ХешПакета"] = business_projection_hash(packet)
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
    shift, group = _identity(company_id)
    first_packet = _packet(shift, group, 1, amount=100)
    session = _Session(groups=[group], shifts=[shift])
    service = AccountingOutboxService(session, company_id)

    first = await service.append_validated_revision(
        first_packet, "store_accounting_group",
    )
    repeated = await service.append_validated_revision(
        first_packet, "store_accounting_group",
    )
    old_payload = first.row.payload
    first.row.status = "accepted"
    second_packet = _packet(shift, group, 2, amount=101)
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
    assert first.row.status == "accepted"
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
        "apply_ack_contract",
        "claim_next",
        "claim_request",
        "fail_attempt",
        "mark_sent",
        "recover_expired_leases",
    }
    shift, group = _identity(company_id)
    session.groups.append(group)
    session.shifts.append(shift)
    result = await service.append_validated_revision(
        _packet(shift, group, 1), "store_accounting_group",
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
    shift, group = _identity(company_id)
    session = _Session(groups=[group], shifts=[shift])
    service = AccountingOutboxService(session, company_id)
    first = await service.append_validated_revision(
        _packet(shift, group, 1, amount=100), "store_accounting_group",
    )

    with pytest.raises(AccountingRevisionConflict, match="revision_hash_conflict"):
        await service.append_validated_revision(
            _packet(shift, group, 1, amount=200), "store_accounting_group",
        )

    assert len(session.packets) == 1
    assert first.row.revision == 1
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
        "sent_waiting_ack": frozenset({
            "accepted", "rejected", "blocked_mapping", "retry_wait", "needs_review",
        }),
        "blocked_mapping": frozenset({"leased"}),
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
    assert "accounting packet revision must increase exactly by one" in guard
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


def _aliases(shift: BusinessShift, *, edge: bool) -> list[dict]:
    common = {
        "company_id": shift.company_key,
        "station_id": shift.station_id,
        "business_date": shift.business_date.isoformat(),
        "ose": "OSE-SYN-0001",
    }
    result = [{
        "Algorithm": "business-shift-common-alias-v1",
        "AliasHash": alias_hash("business-shift-common-alias-v1", common),
        "Attributes": common,
    }]
    if edge:
        internal = {
            "company_id": shift.company_key,
            "station_id": shift.station_id,
            "business_date": shift.business_date.isoformat(),
            "internal_shift_no": "SYN-0001",
        }
        result.append({
            "Algorithm": "business-shift-alias-v1",
            "AliasHash": alias_hash("business-shift-alias-v1", internal),
            "Attributes": internal,
        })
    return result


@pytest.mark.asyncio
async def test_business_shift_resolver_links_edge_and_legacy_without_amount():
    company_id = uuid.uuid4()
    template, _ = _identity(company_id)
    session = _Session(visible_company=company_id)
    resolver = BusinessShiftResolver(session, company_id)

    edge = await resolver.resolve(
        company_key=template.company_key, station_id=template.station_id,
        business_date=template.business_date, aliases=_aliases(template, edge=True),
        winner_fact_id="edge:packet-1", loser_fact_ids=[], fact_origin="edge",
        reason="edge fact", shadow_status="winner",
    )
    legacy = await resolver.resolve(
        company_key=template.company_key, station_id=template.station_id,
        business_date=template.business_date, aliases=_aliases(template, edge=False),
        winner_fact_id="edge:packet-1", loser_fact_ids=["onec:shift-1"],
        fact_origin="edge", reason="common alias", shadow_status="shadow",
    )

    assert edge.created is True
    assert legacy.created is False
    assert legacy.shift.id == edge.shift.id
    assert legacy.group.id == edge.group.id
    assert legacy.decision.loser_fact_ids == ["onec:shift-1"]
    assert len(session.shifts) == 1
    assert len(session.groups) == 1
    assert all("amount" not in str(event).lower() for event in session.events)


@pytest.mark.asyncio
async def test_business_shift_alias_ambiguity_is_needs_review():
    company_id = uuid.uuid4()
    first, _ = _identity(company_id)
    second, _ = _identity(company_id)
    common_alias = _aliases(first, edge=False)[0]
    aliases = [
        BusinessShiftAlias(
            id=uuid.uuid4(), company_id=company_id, business_shift_id=first.id,
            algorithm=common_alias["Algorithm"],
            alias_hash=common_alias["AliasHash"],
            attributes=common_alias["Attributes"],
        ),
        BusinessShiftAlias(
            id=uuid.uuid4(), company_id=company_id, business_shift_id=second.id,
            algorithm=common_alias["Algorithm"],
            alias_hash=common_alias["AliasHash"],
            attributes=common_alias["Attributes"],
        ),
    ]
    session = _Session(
        shifts=[first, second], aliases=aliases, visible_company=company_id,
    )

    result = await BusinessShiftResolver(session, company_id).resolve(
        company_key=first.company_key, station_id=first.station_id,
        business_date=first.business_date, aliases=[common_alias],
        winner_fact_id=None, loser_fact_ids=[], fact_origin=None,
        reason="ambiguous aliases",
    )

    assert result.needs_review is True
    assert result.shift is None
    assert result.group is None
    assert first.status == second.status == "needs_review"
    assert set(result.decision.candidate_business_shift_ids) == {
        str(first.id), str(second.id),
    }


@pytest.mark.asyncio
async def test_business_shift_alias_scope_isolated_by_company():
    company_a = uuid.uuid4()
    company_b = uuid.uuid4()
    shift_a, _ = _identity(company_a)
    common = _aliases(shift_a, edge=False)[0]
    existing_alias = BusinessShiftAlias(
        id=uuid.uuid4(), company_id=company_a, business_shift_id=shift_a.id,
        algorithm=common["Algorithm"], alias_hash=common["AliasHash"],
        attributes=common["Attributes"],
    )
    session = _Session(
        shifts=[shift_a], aliases=[existing_alias], visible_company=company_b,
    )
    resolver = BusinessShiftResolver(session, company_b)

    result = await resolver.resolve(
        company_key=shift_a.company_key, station_id=shift_a.station_id,
        business_date=shift_a.business_date, aliases=[common],
        winner_fact_id="legacy:b", loser_fact_ids=[], fact_origin="onec_legacy",
        reason="tenant scoped alias",
    )

    assert result.created is True
    assert result.shift.company_id == company_b
    assert result.shift.id != shift_a.id


@pytest.mark.asyncio
async def test_revision_table_rejects_gap_stale_same_revision_conflict_and_no_change():
    from copy import deepcopy

    company_id = uuid.uuid4()
    shift, group = _identity(company_id)
    session = _Session(groups=[group], shifts=[shift], visible_company=company_id)
    service = AccountingOutboxService(session, company_id)

    with pytest.raises(AccountingRevisionConflict, match="revision_gap"):
        await service.append_validated_revision(
            _packet(shift, group, 2), "store_accounting_group",
        )
    first_payload = _packet(shift, group, 1, amount=100)
    first = await service.append_validated_revision(
        first_payload, "store_accounting_group",
    )
    with pytest.raises(AccountingRevisionConflict, match="revision_hash_conflict"):
        await service.append_validated_revision(
            _packet(shift, group, 1, amount=101), "store_accounting_group",
        )
    first.row.status = "accepted"
    unchanged = deepcopy(first_payload)
    unchanged["РевизияПакета"] = 2
    with pytest.raises(AccountingRevisionConflict, match="revision_without_change"):
        await service.append_validated_revision(
            unchanged, "store_accounting_group",
        )
    with pytest.raises(AccountingRevisionConflict, match="revision_gap"):
        await service.append_validated_revision(
            _packet(shift, group, 3, amount=103), "store_accounting_group",
        )
    second = await service.append_validated_revision(
        _packet(shift, group, 2, amount=102), "store_accounting_group",
    )
    second.row.status = "accepted"
    with pytest.raises(AccountingRevisionConflict, match="revision_stale"):
        await service.append_validated_revision(
            first_payload, "store_accounting_group",
        )


@pytest.mark.asyncio
async def test_claim_request_repeat_is_one_attempt_and_changed_body_conflicts():
    company_id = uuid.uuid4()
    shift, group = _identity(company_id)
    row = _outbox(company_id, status="queued")
    row.accounting_group_id = group.id
    group.current_packet_id = row.id
    group.current_revision = row.revision
    group.current_content_hash = row.content_hash
    session = _Session(
        packets=[row], groups=[group], shifts=[shift], visible_company=company_id,
    )
    service = AccountingOutboxService(session, company_id)
    request_id = uuid.uuid4()
    now = datetime.now(timezone.utc).replace(microsecond=0)

    first = await service.claim_request(
        consumer_id="base2", claim_request_id=request_id,
        lease_seconds=300, now=now,
    )
    repeated = await service.claim_request(
        consumer_id="base2", claim_request_id=request_id,
        lease_seconds=300, now=now + timedelta(seconds=1),
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.attempt_id == first.attempt_id
    assert repeated.lease_until == first.lease_until
    assert len(session.claims) == 1
    assert len([event for event in session.events if event[0] == "lock"]) == 2
    with pytest.raises(AccountingRevisionConflict, match="claim_request_conflict"):
        await service.claim_request(
            consumer_id="base2", claim_request_id=request_id,
            lease_seconds=301, now=now,
        )


def _accepted_ack(
    row: ExportPacket,
    group: AccountingBusinessGroup,
    claim: AccountingClaimRequest,
) -> dict:
    component = {
        "Порядок": 1, "Тип": "retail",
        "ИсточникUUID": "retail-synthetic-001",
        "СсылкаБП": "e1cib/data/Document.ОРП?ref=synthetic",
        "SourceHash": "b" * 64, "TargetHash": "c" * 64,
        "Проведен": False, "Результат": "accepted",
        "КодОшибки": None, "ОписаниеОшибки": None,
    }
    result = {
        "ТипСообщения": "ack", "ВерсияКонтракта": "3.0.0",
        "ConsumerID": claim.consumer_id,
        "ClaimRequestID": str(claim.claim_request_id),
        "AttemptID": str(claim.attempt_id), "PacketID": str(row.id),
        "ИдентификаторПакета": str(row.packet_uuid),
        "BusinessShiftID": str(group.business_shift_id),
        "BusinessKeyHash": group.business_key_hash,
        "РевизияПакета": row.revision, "ХешПакета": row.content_hash,
        "Результат": "accepted", "КодОшибки": None,
        "ОписаниеОшибки": None, "Компоненты": [component], "AckHash": "",
    }
    result["AckHash"] = ack_hash(result)
    return result


@pytest.mark.asyncio
async def test_exact_ack_repeat_is_noop_and_mismatched_identity_conflicts():
    company_id = uuid.uuid4()
    shift, group = _identity(company_id)
    row = _outbox(company_id, status="sent_waiting_ack")
    row.accounting_group_id = group.id
    row.payload = {
        "Документы": [{
            "Тип": "retail_sale_sidegoods",
            "SourceHash": "b" * 64,
        }],
        "ПолнотаГруппы": {"ОжидаемыеКомпоненты": [{
            "Порядок": 1, "Тип": "retail",
            "ИсточникUUID": "retail-synthetic-001",
        }]},
    }
    row.attempt_id = uuid.uuid4()
    claim = AccountingClaimRequest(
        id=uuid.uuid4(), company_id=company_id, consumer_id="base2",
        claim_request_id=uuid.uuid4(), request_hash="d" * 64,
        lease_seconds=300, attempt_id=row.attempt_id, packet_id=row.id,
        lease_until=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    session = _Session(
        packets=[row], groups=[group], shifts=[shift], claims=[claim],
        visible_company=company_id,
    )
    service = AccountingOutboxService(session, company_id)
    body = _accepted_ack(row, group, claim)

    unknown_field = dict(body)
    unknown_field["ЛишнееПоле"] = True
    with pytest.raises(AccountingRevisionConflict, match="запрещены"):
        await service.apply_ack_contract(unknown_field)

    unknown_component_field = dict(body)
    unknown_component_field["Компоненты"] = [dict(body["Компоненты"][0])]
    unknown_component_field["Компоненты"][0]["ЛишнееПоле"] = True
    with pytest.raises(AccountingRevisionConflict, match="exact schema"):
        await service.apply_ack_contract(unknown_component_field)

    foreign_source = dict(body)
    foreign_source["Компоненты"] = [dict(body["Компоненты"][0])]
    foreign_source["Компоненты"][0]["SourceHash"] = "e" * 64
    foreign_source["AckHash"] = ack_hash(foreign_source)
    with pytest.raises(AccountingRevisionConflict, match="чужой SourceHash"):
        await service.apply_ack_contract(foreign_source)

    accepted = await service.apply_ack_contract(body)
    repeated = await service.apply_ack_contract(body)
    assert accepted is repeated is row
    assert row.status == "accepted"
    assert row.component_result == body["Компоненты"]

    mismatched = dict(body)
    mismatched["BusinessShiftID"] = str(uuid.uuid4())
    mismatched["AckHash"] = ack_hash(mismatched)
    with pytest.raises(AccountingRevisionConflict, match="ACK identity"):
        await service.apply_ack_contract(mismatched)


@pytest.mark.asyncio
async def test_lost_ack_redelivers_same_revision_then_accepts_and_unblocks_next():
    company_id = uuid.uuid4()
    shift, group = _identity(company_id)
    session = _Session(groups=[group], shifts=[shift], visible_company=company_id)
    service = AccountingOutboxService(session, company_id)
    packet = _packet(shift, group, 1, amount=100)
    packet["Документы"][0]["SourceHash"] = "b" * 64
    packet["ХешПакета"] = business_projection_hash(packet)
    first = await service.append_validated_revision(
        packet, "store_accounting_group",
    )
    first.row.status = "queued"
    started = datetime.now(timezone.utc).replace(microsecond=0)
    first_claim = await service.claim_request(
        consumer_id="base2", claim_request_id=uuid.uuid4(),
        lease_seconds=30, now=started,
    )
    await service.mark_sent(
        first.row.id, first_claim.attempt_id, now=started,
        ack_timeout_seconds=30,
    )
    identity = (
        first.row.id, first.row.packet_uuid, first.row.revision,
        first.row.content_hash, first.row.payload,
    )

    recovered = await service.recover_expired_leases(
        now=started + timedelta(seconds=31),
    )

    assert recovered == [first.row]
    assert first.row.status == "retry_wait"
    assert first.row.error_code == "ack_deadline_expired"
    assert (
        first.row.id, first.row.packet_uuid, first.row.revision,
        first.row.content_hash, first.row.payload,
    ) == identity

    lost_ack = _accepted_ack(first.row, group, session.claims[0])
    with pytest.raises(AccountingRevisionConflict, match="ACK identity"):
        await service.apply_ack_contract(lost_ack)

    session.scripted.extend([[], [first.row]])
    second_claim = await service.claim_request(
        consumer_id="base2", claim_request_id=uuid.uuid4(),
        lease_seconds=30, now=started + timedelta(seconds=32),
    )
    assert second_claim.packet is first.row
    assert second_claim.attempt_id != first_claim.attempt_id
    await service.mark_sent(
        first.row.id, second_claim.attempt_id,
        now=started + timedelta(seconds=32), ack_timeout_seconds=30,
    )
    claim = session.claims[-1]
    body = _accepted_ack(first.row, group, claim)
    session.scripted.extend([[first.row], [claim], [group]])
    accepted = await service.apply_ack_contract(body)
    session.scripted.extend([[first.row], [claim], [group]])
    repeated = await service.apply_ack_contract(body)

    assert accepted is repeated is first.row
    assert first.row.status == "accepted"
    second = await service.append_validated_revision(
        _packet(shift, group, 2, amount=101), "store_accounting_group",
    )
    assert second.created is True
    assert second.row.revision == 2


def test_business_shift_migration_is_staged_and_reports_collisions():
    ddl = "\n".join(BUSINESS_SHIFT_MIGRATION_DDL)
    assert ddl.index("ADD COLUMN IF NOT EXISTS accounting_group_id UUID") < ddl.index(
        "INSERT INTO business_shift_migration_collisions"
    )
    assert ddl.index("INSERT INTO business_shift_migration_collisions") < ddl.index(
        "INSERT INTO business_shifts"
    )
    assert "identity_mismatch" in ddl
    assert "uuid_cross_company" in ddl
    assert "alias_ambiguity" in ddl
    assert "NOT VALID" in ddl
    assert "uq_export_packets_active_business_group" in ddl
    assert "active_group_duplicate" in ddl
    assert "accounting migration readiness failed: active group duplicates" in ddl
    assert "accounting migration readiness failed: active group index missing" in ddl
    assert ddl.index("active_group_duplicate") < ddl.index(
        "accounting migration readiness failed: active group duplicates"
    ) < ddl.index("CREATE UNIQUE INDEX IF NOT EXISTS uq_export_packets_active_business_group")
    assert ddl.index("CREATE UNIQUE INDEX IF NOT EXISTS uq_export_packets_active_business_group") < ddl.index(
        "to_regclass('uq_export_packets_active_business_group')"
    )
    assert "accounting source decision is append-only" in ddl
    database_source = inspect.getsource(__import__("app.database", fromlist=["create_all"]))
    assert "ALTER TABLE counterparties ADD COLUMN IF NOT EXISTS is_group" in database_source


@pytest.mark.asyncio
async def test_active_group_collision_report_commits_before_readiness_failure():
    class Connection:
        def __init__(self, owner):
            self.owner = owner

        async def execute(self, statement):
            self.owner.statements.append(str(statement))
            if self.owner.fail_readiness \
                    and str(statement) == ACTIVE_GROUP_READINESS_DDL:
                raise RuntimeError("active group duplicates")

    class Transaction:
        def __init__(self, owner):
            self.owner = owner

        async def __aenter__(self):
            return Connection(self.owner)

        async def __aexit__(self, exc_type, exc, traceback):
            if exc_type is None:
                self.owner.commits += 1

    class Engine:
        def __init__(self, fail_readiness):
            self.fail_readiness = fail_readiness
            self.begins = 0
            self.commits = 0
            self.statements = []

        def begin(self):
            self.begins += 1
            return Transaction(self)

    engine = Engine(fail_readiness=True)

    with pytest.raises(RuntimeError, match="active group duplicates"):
        await _ensure_active_group_readiness(engine)

    assert engine.begins == 2
    assert engine.commits == 1
    assert engine.statements == [
        ACTIVE_GROUP_COLLISION_REPORT_DDL,
        ACTIVE_GROUP_READINESS_DDL,
    ]

    clean_engine = Engine(fail_readiness=False)
    await _ensure_active_group_readiness(clean_engine)

    assert clean_engine.begins == 2
    assert clean_engine.commits == 2
    assert clean_engine.statements == [
        ACTIVE_GROUP_COLLISION_REPORT_DDL,
        ACTIVE_GROUP_READINESS_DDL,
    ]
