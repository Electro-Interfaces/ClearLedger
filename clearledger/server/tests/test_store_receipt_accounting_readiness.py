import inspect
import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.database import STORE_RECEIPT_MIGRATION_DDL
from app.models import (
    AccountingSourceLink,
    Contract,
    Counterparty,
    DataEntry,
    EdgePacketProcessingIssue,
    EdgePacketRevision,
    EdgeAgent,
    Organization,
    SpaceInboundKey,
    StoreReceipt,
    StoreReceiptStockMovement,
    Warehouse,
)
from app.routers import edge_router
from app.services import store_receipt_accounting, store_receipts
from app.services.store_receipt_accounting import (
    ReceiptAccountingError,
    assert_purchase_documents_ready,
    assess_receipt,
    canonicalize_receipt,
)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        if len(self.rows) > 1:
            raise AssertionError("ambiguous fake result")
        return self.rows[0] if self.rows else None


class Session:
    def __init__(self, rows=None):
        self.rows = {model: list(values) for model, values in (rows or {}).items()}
        self.added = []
        self.events = []
        self.business_candidates_only = False
        self.store_receipt_queries = 0

    async def execute(self, statement, _parameters=None):
        if "pg_advisory_xact_lock" in str(statement):
            self.events.append("lock")
            return Result()
        if (
            getattr(statement, "is_insert", False)
            and getattr(getattr(statement, "table", None), "name", None)
            == EdgePacketProcessingIssue.__tablename__
        ):
            values = statement.compile().params
            duplicate = any(
                row.company_id == values["company_id"]
                and row.packet_uuid == values["packet_uuid"]
                and row.content_hash == values["content_hash"]
                and row.error_hash == values["error_hash"]
                for row in self.rows.get(EdgePacketProcessingIssue, [])
            )
            if not duplicate:
                self.add(EdgePacketProcessingIssue(**values))
            return Result()
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        if entity is StoreReceipt and self.business_candidates_only:
            self.store_receipt_queries += 1
            return Result(
                self.rows.get(StoreReceipt, [])
                if self.store_receipt_queries >= 3 else []
            )
        if entity is StoreReceiptStockMovement:
            return Result(self.rows.get(StoreReceiptStockMovement, []))
        return Result(self.rows.get(entity, []))

    def add(self, row):
        self.added.append(row)
        self.rows.setdefault(type(row), []).append(row)

    def add_all(self, rows):
        for row in rows:
            self.add(row)

    async def flush(self):
        pass

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")


def _ready_fixture():
    company_id = uuid.uuid4()
    supplier = Counterparty(
        id=uuid.uuid4(), company_id=company_id, inn="7812345678",
        name="ООО Поставщик", aliases=[], kind="external",
        external_ref=str(uuid.uuid4()),
        lifecycle_status="verified",
    )
    organization = Organization(
        id=uuid.uuid4(), company_id=company_id, inn="7800000000",
        name="ООО ГИГ", external_ref=str(uuid.uuid4()),
    )
    warehouse = Warehouse(
        id=uuid.uuid4(), company_id=company_id, code="208", name="АЗС 208",
        external_ref=str(uuid.uuid4()),
        organization_id=organization.id, station_id=208,
    )
    contract = Contract(
        id=uuid.uuid4(), company_id=company_id, number="П-1", date="2026-08-01",
        counterparty_id=str(supplier.id), organization_id=str(organization.id),
        type="СПоставщиком", kind="СПоставщиком", scope_type="company",
        external_ref=str(uuid.uuid4()), is_closed=False,
    )
    receipt = StoreReceipt(
        id=uuid.uuid4(), company_id=company_id, station_id=208,
        number="П-208-1", doc_date=datetime(2026, 8, 9, tzinfo=timezone.utc),
        supplier_id=supplier.id, supplier=supplier.name,
        contract_id=contract.id, contract=contract.number,
        organization_id=organization.id, warehouse_id=warehouse.id,
        incoming_number="УПД-1",
        incoming_date=datetime(2026, 8, 8, tzinfo=timezone.utc),
        status="accepted", origin="center", delivery_scheme="supplier_to_station",
        receiving_warehouse=warehouse.name, signing_mode="office_director",
        signature_status="pending", evidence={
            "invoice_kind": "УПД", "invoice_number": "УПД-1",
            "invoice_date": "2026-08-08", "currency": "RUB",
            "vat_included": True,
        },
        lines=[{
            "line_id": str(uuid.uuid4()), "name": "Вода",
            "nomenclature_ref": str(uuid.uuid4()), "barcode": "4600000000007",
            "qty_expected": 2, "qty_fact": 2, "price": 50,
            "vat_rate": "БезНДС", "vat_amount": 0, "amount": 100,
        }], services=[], total_amount=100, vat_amount=0,
        accounting_status="pending", accounting_revision=0, version=1,
    )
    rows = {
        StoreReceipt: [receipt], Counterparty: [supplier], Contract: [contract],
        Organization: [organization], Warehouse: [warehouse],
        DataEntry: [], AccountingSourceLink: [], StoreReceiptStockMovement: [],
    }
    return company_id, receipt, supplier, contract, organization, warehouse, Session(rows)


def test_line_id_is_reorder_safe_and_mutable_amounts_do_not_change_identity():
    receipt_id = uuid.uuid4()
    first = {"name": "Вода", "barcode": "1", "price": 10, "vat_rate": "НДС22"}
    second = {"name": "Сок", "barcode": "2", "price": 20, "vat_rate": "НДС10"}
    one, _ = store_receipts.ensure_line_ids(receipt_id, [first, second])
    changed, _ = store_receipts.ensure_line_ids(
        receipt_id,
        [{**second, "price": 999, "vat_rate": "БезНДС"},
         {**first, "price": 1, "vat_rate": "НДС0"}],
    )
    assert {row["name"]: row["line_id"] for row in one} == {
        row["name"]: row["line_id"] for row in changed
    }
    with pytest.raises(store_receipts.ReceiptValidationError, match="Неразличимые"):
        store_receipts.ensure_line_ids(receipt_id, [first, dict(first)])
    provisional, _ = store_receipts.assign_provisional_ambiguous_line_ids(
        receipt_id, [first, dict(first)],
    )
    assert len({row["line_id"] for row in provisional}) == 2


@pytest.mark.asyncio
async def test_provisional_ambiguous_line_ids_never_become_accounting_ready():
    _company_id, receipt, *_rest, session = _ready_fixture()
    receipt.evidence = {"line_identity_needs_review": True}
    readiness = await assess_receipt(session, receipt)
    assert not readiness.ready
    assert "постоянные line_id" in "; ".join(readiness.errors)


@pytest.mark.asyncio
async def test_canonicalization_appends_fact_and_source_link_without_mutating_evidence():
    company_id, receipt, *_rest, session = _ready_fixture()
    evidence = dict(receipt.evidence)
    row = await canonicalize_receipt(
        session, company_id, receipt.id, uuid.uuid4(), "проверено центром")

    assert row.accounting_status == "ready"
    assert row.accounting_revision == 1
    assert len(row.content_hash) == 64
    assert row.evidence == evidence
    assert len(session.rows[DataEntry]) == 1
    assert session.rows[DataEntry][0].document_id == receipt.id
    assert len(session.rows[AccountingSourceLink]) == 1
    document = session.rows[DataEntry][0].meta["document"]
    assert document["ВалютаДокумента"] == "RUB"
    assert document["СуммаВключаетНДС"] is True
    assert document["ВидДокументаНДС"] == "УПД"
    assert document["КонтрольныеИтоги"] == {
        "goods": 100.0, "services": 0.0, "vat": 0.0, "document": 100.0,
        # Сумма к оплате отдаётся отдельно: в БП «СуммаДокумента» — сумма с
        # налогом. У этой приёмки цены с НДС внутри, поэтому она равна
        # товарному итогу.
        "payable": 100.0,
        # Подвал накладной оператор не заполнял — сверять нечего.
        "declared": None,
    }


@pytest.mark.asyncio
async def test_late_link_changes_only_canonical_refs_and_builds_revision():
    company_id, receipt, supplier, contract, organization, warehouse, session = _ready_fixture()
    receipt.supplier_id = None
    receipt.contract_id = None
    receipt.organization_id = None
    receipt.warehouse_id = None
    evidence = dict(receipt.evidence)
    lines = [dict(row) for row in receipt.lines]
    version = receipt.version
    operational = (
        receipt.status, receipt.station_id, receipt.total_amount,
        receipt.incoming_number, receipt.incoming_date,
    )

    row = await store_receipt_accounting.link_receipt_canonical_refs(
        session, company_id, receipt.id,
        supplier_id=supplier.id, contract_id=contract.id,
        organization_id=organization.id, warehouse_id=warehouse.id,
        confirmed_by=uuid.uuid4(), expected_version=receipt.version,
    )

    assert (row.supplier_id, row.contract_id, row.organization_id, row.warehouse_id) == (
        supplier.id, contract.id, organization.id, warehouse.id,
    )
    assert row.evidence == evidence
    assert row.lines == lines
    assert operational == (
        row.status, row.station_id, row.total_amount,
        row.incoming_number, row.incoming_date,
    )
    assert row.accounting_revision == 1
    assert row.version == version + 1
    with pytest.raises(ReceiptAccountingError, match="изменён другим пользователем"):
        await store_receipt_accounting.link_receipt_canonical_refs(
            session, company_id, receipt.id,
            supplier_id=supplier.id, contract_id=contract.id,
            organization_id=organization.id, warehouse_id=warehouse.id,
            confirmed_by=uuid.uuid4(), expected_version=version,
        )
    assert row.accounting_revision == 1
    assert row.evidence == evidence
    assert row.lines == lines
    assert not session.rows[StoreReceiptStockMovement]

    repeated = await canonicalize_receipt(
        session, company_id, receipt.id, uuid.uuid4(), "повтор")
    assert repeated.accounting_revision == 1
    assert len(session.rows[DataEntry]) == 1
    assert len(session.rows[AccountingSourceLink]) == 1


@pytest.mark.asyncio
async def test_guard_rechecks_live_nsi_under_lock_and_rejects_closed_contract():
    company_id, receipt, _supplier, contract, _org, _warehouse, session = _ready_fixture()
    ready = await assess_receipt(session, receipt)
    receipt.accounting_status = "ready"
    receipt.accounting_revision = 1
    receipt.content_hash = ready.content_hash
    entry = DataEntry(
        id=uuid.uuid4(), company_id=company_id, title="Поступление",
        category_id="store", subcategory_id="purchase", status="verified",
        source="store", source_label="", layer="clean", meta={},
        document_id=receipt.id, revision=1, content_hash=ready.content_hash,
        fact_origin="store",
    )
    link = AccountingSourceLink(
        id=uuid.uuid4(), company_id=company_id, projection_source="store",
        source_kind="purchase", source_document_id=receipt.id,
        canonical_document_id=receipt.id, confirmed_by=uuid.uuid4(),
        confirmed_at=datetime.now(timezone.utc),
    )
    session.rows[DataEntry] = [entry]
    session.rows[AccountingSourceLink] = [link]
    packet = {"Документы": [{
        "Тип": "purchase", "document_id": str(receipt.id),
        "revision": 1, "content_hash": ready.content_hash,
    }]}
    await assert_purchase_documents_ready(session, company_id, packet)
    assert session.events

    contract.is_closed = True
    with pytest.raises(ReceiptAccountingError, match="live НСИ"):
        await assert_purchase_documents_ready(session, company_id, packet)


@pytest.mark.asyncio
async def test_strict_readiness_rejects_supplier_lifecycle_warehouse_scope_and_totals():
    _company_id, receipt, supplier, _contract, organization, warehouse, session = _ready_fixture()
    supplier.lifecycle_status = "blocked"
    warehouse.organization_id = uuid.uuid4()
    warehouse.station_id = 209
    receipt.total_amount = 99
    readiness = await assess_receipt(session, receipt, lock=True)
    errors = "; ".join(readiness.errors)
    assert not readiness.ready
    assert "verified" in errors
    assert "организации" in errors
    assert "станции" in errors
    assert "Итог документа" in errors
    assert organization.id != warehouse.organization_id


@pytest.mark.asyncio
async def test_strict_readiness_rejects_negative_and_forged_line_values_without_mutation():
    company_id, receipt, *_rest, session = _ready_fixture()
    receipt.lines[0]["qty_expected"] = -2
    receipt.lines[0]["qty_fact"] = -1
    receipt.lines[0]["price"] = -50
    receipt.lines[0]["amount"] = 50
    receipt.total_amount = 50
    receipt.services = [{
        "line_id": str(uuid.uuid4()), "name": "Доставка",
        "amount": -1, "vat_rate": "БезНДС", "vat_amount": 0,
    }]
    original_lines = [dict(row) for row in receipt.lines]
    original_services = [dict(row) for row in receipt.services]
    readiness = await assess_receipt(session, receipt, lock=True)
    errors = "; ".join(readiness.errors)
    assert not readiness.ready
    assert "конечным и неотрицательным" in errors
    assert receipt.lines == original_lines
    assert receipt.services == original_services

    receipt.lines = [{
        **original_lines[0],
        "qty_expected": 2, "qty_fact": 2, "price": 50,
        "amount": 999, "vat_amount": 0,
    }]
    receipt.services = []
    receipt.total_amount = 999
    receipt.vat_amount = 0
    receipt.accounting_status = "ready"
    receipt.accounting_revision = 1
    receipt.content_hash = "a" * 64
    packet = {"Документы": [{
        "Тип": "purchase", "document_id": str(receipt.id),
        "revision": 1, "content_hash": receipt.content_hash,
    }]}
    with pytest.raises(ReceiptAccountingError, match="live НСИ"):
        await assert_purchase_documents_ready(session, company_id, packet)


@pytest.mark.asyncio
async def test_incomplete_v3_purchase_is_persisted_as_needs_review_not_422():
    company_id = uuid.uuid4()
    session = Session({
        StoreReceipt: [], Counterparty: [], Contract: [], Organization: [],
        Warehouse: [], StoreReceiptStockMovement: [],
    })
    document_id = uuid.uuid4()
    payload = {
        "ВерсияФормата": "3", "ИдентификаторПакета": str(uuid.uuid4()),
        "ХешПакета": "raw",
    }
    document = {
        "Тип": "purchase", "document_id": str(document_id),
        "ИсточникUUID": str(uuid.uuid4()), "Дата": "2026-08-09T10:00:00+03:00",
        "Номер": "П-1", "Контрагент": "Новый поставщик",
        "НомерВходящегоДокумента": "УПД-1",
        "ДатаВходящегоДокумента": "2026-08-08",
        "Товары": [{
            "Наименование": "Вода", "ШтрихКод": "4600000000007",
            "Количество": 2, "Цена": 50, "Сумма": 100,
            "СтавкаНДС": "БезНДС",
        }],
    }
    await edge_router._ingest_receipts(session, company_id, 208, payload, [document])

    receipts = [row for row in session.added if isinstance(row, StoreReceipt)]
    assert len(receipts) == 1
    assert receipts[0].status == "accepted"
    assert receipts[0].accounting_status == "needs_review"
    assert "canonical supplier_id" in receipts[0].accounting_error
    assert receipts[0].lines[0]["line_id"]

    receipts[0].accounting_status = "ready"
    receipts[0].accounting_error = None
    await edge_router._ingest_receipts(session, company_id, 208, payload, [document])
    assert receipts[0].accounting_status == "ready"


@pytest.mark.asyncio
async def test_indistinguishable_legacy_lines_are_persistent_needs_review():
    company_id = uuid.uuid4()
    session = Session({
        StoreReceipt: [], Counterparty: [], Contract: [], Organization: [],
        Warehouse: [], StoreReceiptStockMovement: [],
    })
    line = {
        "Наименование": "Вода", "ШтрихКод": "4600000000007",
        "Количество": 1, "Цена": 50, "Сумма": 50,
    }
    document = {
        "Тип": "purchase", "ИсточникUUID": str(uuid.uuid4()),
        "Дата": "2026-08-09T10:00:00+03:00", "Номер": "П-2",
        "Контрагент": "Новый поставщик", "НомерВходящегоДокумента": "УПД-2",
        "ДатаВходящегоДокумента": "2026-08-08", "Товары": [line, dict(line)],
    }
    payload = {
        "ВерсияФормата": "2", "ИдентификаторПакета": str(uuid.uuid4()),
    }
    await edge_router._ingest_receipts(session, company_id, 208, payload, [document])

    receipt = next(row for row in session.added if isinstance(row, StoreReceipt))
    assert receipt.accounting_status == "needs_review"
    assert receipt.evidence["line_identity_needs_review"] is True
    assert len({row["line_id"] for row in receipt.lines}) == 2


@pytest.mark.asyncio
async def test_business_key_match_creates_manual_candidate_without_old_fact_mutation():
    company_id, old, *_rest, session = _ready_fixture()
    old.dedup_key = store_receipts.receipt_dedup_key(
        None, old.supplier, old.incoming_number, old.incoming_date,
    )
    old_lines = [dict(row) for row in old.lines]
    session.business_candidates_only = True
    document_id = uuid.uuid4()
    document = {
        "Тип": "purchase", "document_id": str(document_id),
        "ИсточникUUID": str(uuid.uuid4()), "Дата": old.doc_date.isoformat(),
        "Номер": "ПОВТОР", "Контрагент": old.supplier,
        "НомерВходящегоДокумента": old.incoming_number,
        "ДатаВходящегоДокумента": old.incoming_date.isoformat(),
        "Товары": [{
            "Наименование": "Другая строка", "ШтрихКод": "2",
            "Количество": 1, "Цена": 1, "Сумма": 1, "СтавкаНДС": "БезНДС",
        }],
    }
    payload = {
        "ВерсияФормата": "3", "ИдентификаторПакета": str(uuid.uuid4()),
    }
    await edge_router._ingest_receipts(session, company_id, 208, payload, [document])

    candidate = next(
        row for row in session.added
        if isinstance(row, StoreReceipt) and row.id == document_id
    )
    assert candidate.id != old.id
    assert candidate.accounting_status == "needs_review"
    assert candidate.evidence["manual_candidate_ids"] == [str(old.id)]
    assert old.lines == old_lines
    assert not any(isinstance(row, StoreReceiptStockMovement) for row in session.added)

    evidence = dict(candidate.evidence)
    session.business_candidates_only = False
    session.rows[StoreReceipt] = [candidate]
    await edge_router._ingest_receipts(session, company_id, 208, payload, [document])
    assert candidate.accounting_status == "needs_review"
    assert candidate.evidence == evidence
    assert not any(isinstance(row, StoreReceiptStockMovement) for row in session.added)


@pytest.mark.asyncio
async def test_raw_revision_error_is_persisted_after_derived_rollback():
    company_id = uuid.uuid4()
    revision = EdgePacketRevision(
        id=uuid.uuid4(), company_id=company_id, edge_packet_id=uuid.uuid4(),
        packet_uuid=str(uuid.uuid4()), content_hash="a" * 64, payload={"raw": True},
        size_bytes=10, status="received",
    )
    session = Session({EdgePacketRevision: [revision]})
    await edge_router._persist_edge_revision_error(
        session, company_id=company_id, edge_packet_id=revision.edge_packet_id,
        packet_uuid=revision.packet_uuid, content_hash=revision.content_hash,
        payload=revision.payload, size_bytes=10, wire_size_bytes=None,
        error="HTTPException: purchase invalid",
    )
    assert session.events[:2] == ["rollback", "commit"]
    assert revision.status == "received"
    assert revision.error is None
    issues = [
        row for row in session.added if isinstance(row, EdgePacketProcessingIssue)
    ]
    assert len(issues) == 1
    assert issues[0].status == "needs_review"
    assert issues[0].error == "HTTPException: purchase invalid"
    await edge_router._persist_edge_revision_error(
        session, company_id=company_id, edge_packet_id=revision.edge_packet_id,
        packet_uuid=revision.packet_uuid, content_hash=revision.content_hash,
        payload=revision.payload, size_bytes=10, wire_size_bytes=None,
        error="HTTPException: purchase invalid",
    )
    assert len([
        row for row in session.added if isinstance(row, EdgePacketProcessingIssue)
    ]) == 1


@pytest.mark.asyncio
async def test_edge_identity_is_station_bound_and_cross_station_route_is_rejected():
    company = type("CompanyRow", (), {"id": uuid.uuid4(), "slug": "gig"})()
    key = SpaceInboundKey(
        id=uuid.uuid4(), company_id=company.id, consumer="Edge 208",
        key_hash=edge_router.hashlib.sha256(b"secret").hexdigest(),
        key_prefix="prefix", station_id=208,
    )

    class AuthSession(Session):
        async def get(self, model, value):
            return company if model.__name__ == "Company" and value == company.id else None

    session = AuthSession({
        SpaceInboundKey: [key],
        EdgeAgent: [type("Agent", (), {"id": uuid.uuid4()})()],
    })
    identity = await edge_router.get_edge_identity("secret", session)
    assert identity.station_id == 208

    key.station_id = None
    with pytest.raises(Exception) as unbound:
        await edge_router.get_edge_identity("secret", session)
    assert getattr(unbound.value, "status_code", None) == 403
    key.station_id = 208

    class Request:
        headers = {}

        async def body(self):
            return json.dumps({
                "ИдентификаторПакета": str(uuid.uuid4()),
                "Смена": {"КодАЗС": 209},
            }).encode()

    with pytest.raises(Exception) as error:
        await edge_router.receive_packet(Request(), identity, session)
    assert getattr(error.value, "status_code", None) == 403


def test_stage3_ddl_and_raw_path_are_fail_closed_and_append_only():
    ddl = "\n".join(STORE_RECEIPT_MIGRATION_DDL)
    assert ddl.index("DROP TRIGGER IF EXISTS store_receipt_stock_movement_immutable_trg") < ddl.index(
        "UPDATE store_receipt_stock_movements movement")
    assert "store receipt stock movements are append-only" in ddl
    assert "edge packet raw revisions are append-only" in ddl
    assert "edge packet processing issues are append-only" in ddl
    assert "uq_edge_packet_processing_issue_error" in ddl
    assert "Неразличимые legacy-строки" in ddl
    assert "space_inbound_keys ADD COLUMN IF NOT EXISTS station_id" in ddl
    assert "ck_counterparty_lifecycle_status" in ddl
    assert "ix_warehouses_accounting_scope" in ddl
    assert EdgePacketRevision.__table__.c.content_hash.type.length == 64
    assert all(not text(statement)._bindparams for statement in STORE_RECEIPT_MIGRATION_DDL)

    source = inspect.getsource(edge_router.receive_packet)
    assert "existing.payload = payload" not in source
    raw_marker = source.index("# L1 фиксируется отдельной транзакцией")
    raw_commit = source.index("await db.commit()", raw_marker)
    assert raw_commit < source.index("await _ingest_receipts", raw_commit)
    assert "status=\"needs_review\"" in source


@pytest.mark.asyncio
async def test_declared_total_is_payable_sum_and_tolerates_rounding():
    """Контрольный итог накладной — сумма К ОПЛАТЕ, с допуском на округление.

    До 27.08.2026 declared_total сверялся с товарным итогом БЕЗ налога, а
    станция шлёт сумму к оплате: расхождение выходило на всю величину НДС, и ни
    одна накладная с заполненным подвалом в БП не уезжала. Плюс сам подвал
    вводит человек с бумаги, а НДС считается построчно — копейки округления не
    ошибка ввода и не повод задержать документ.
    """
    _company_id, receipt, *_rest, session = _ready_fixture()
    receipt.evidence = {
        **receipt.evidence, "vat_included": False,
        "invoice_kind": "УПД", "invoice_number": "УПД-1", "invoice_date": "2026-08-08",
    }
    receipt.lines = [{
        "line_id": str(uuid.uuid4()), "name": "Энергетик",
        "nomenclature_ref": str(uuid.uuid4()), "barcode": "9002490100070",
        "qty_expected": 24, "qty_fact": 24, "price": 100,
        "vat_rate": "НДС22", "vat_amount": 528, "amount": 2400,
    }]
    receipt.total_amount, receipt.vat_amount = 2400, 528

    # Ровно сумма к оплате: 2400 товаров + 528 налога.
    receipt.evidence["declared_total"] = 2928
    readiness = await assess_receipt(session, receipt, lock=True)
    assert readiness.ready, readiness.errors
    assert readiness.document["СуммаДокумента"] == 2928
    assert readiness.document["КонтрольныеИтоги"]["payable"] == 2928

    # Копейки построчного округления — не ошибка.
    receipt.evidence["declared_total"] = 2927.96
    readiness = await assess_receipt(session, receipt, lock=True)
    assert readiness.ready, readiness.errors
    # И в бухгалтерию уезжает именно цифра накладной, а не наш расчёт:
    # первичный документ — бумага, копейки округления НДС её не отменяют.
    assert readiness.document["СуммаДокумента"] == 2927.96

    # Товарный итог без налога на месте суммы к оплате — это уже ошибка ввода.
    receipt.evidence["declared_total"] = 2400
    readiness = await assess_receipt(session, receipt, lock=True)
    assert not readiness.ready
    assert "declared_total" in "; ".join(readiness.errors)
