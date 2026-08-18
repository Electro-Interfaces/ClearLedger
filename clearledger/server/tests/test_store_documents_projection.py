import inspect
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import database, main
from app.models import (
    AccountingDoc,
    AccountingSourceLink,
    CbInventoryDoc,
    CbMovementDoc,
    Company,
    DataEntry,
    EdgeAgent,
    EdgeDownlink,
    EdgePacket,
    ExportPacket,
    StoreCheque,
    StoreDocFile,
    StoreDocumentProjection,
    StoreDocumentProjectionLine,
    StoreDocumentRelation,
    StoreReceipt,
    StoreReceiptStockMovement,
)
from app.routers import (
    intake_router, references_router, store_documents_router, store_router,
)
from app.routers import edge_router
from app.services import (
    accounting_egress, ops_terms, store_document_print, store_document_sync,
    store_documents, store_receipt_accounting,
)
from app.services.store_document_snapshot import (
    build_snapshot_headers,
    queue_onec_document_snapshot,
    snapshot_content_hash,
    validate_snapshot_headers,
)
from app.services.store_document_contract import (
    ACCOUNTING_DOCUMENT_KINDS,
    PROJECTION_DOCUMENT_KINDS,
)
from app.services.store_documents import (
    ProjectionCandidate,
    goods_only_cheque_totals,
    safe_document_detail,
)


class Result:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class ListResult(Result):
    def one(self):
        return self.rows[0]

    def scalar(self):
        return self.rows[0] if self.rows else None


class ListSession:
    def __init__(self):
        self.statements = []
        # последняя колонка выборки статистики — момент сборки проекции
        self.results = [
            ListResult([(4, 3, 2, 1, datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc))]),
            ListResult([0]), ListResult([]),
        ]

    async def execute(self, statement, _parameters=None):
        self.statements.append(statement)
        return self.results.pop(0)


class SnapshotSession:
    def __init__(self, rows):
        self.rows = rows
        self.added = []

    async def execute(self, statement, _parameters=None):
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        return Result(self.rows.get(entity, ()))

    def add(self, row):
        self.added.append(row)


class Session:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, statement, _parameters=None):
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        return Result(self.rows.get(entity, ()))


class IngestSession:
    def __init__(self, existing=None):
        self.existing = existing
        self.added = []

    async def execute(self, _statement, _parameters=None):
        return Result([self.existing] if self.existing is not None else [])

    def add(self, row):
        self.added.append(row)


class RebuildSession:
    def __init__(self, rows):
        self.rows = rows
        self.added = []
        self.deleted_tables = []

    async def execute(self, statement, _parameters=None):
        table = getattr(statement, "table", None)
        if table is not None and statement.__class__.__name__ == "Delete":
            self.deleted_tables.append(table.name)
            return Result()
        descriptions = getattr(statement, "column_descriptions", [])
        entity = descriptions[0].get("entity") if descriptions else None
        return Result(self.rows.get(entity, ()))

    def add(self, row):
        self.added.append(row)

    async def flush(self):
        return None


def cheque(*, had_fuel, lines, number=1):
    return SimpleNamespace(
        id=uuid.uuid4(), station_id=208, shift_number=7001, number=number,
        fiscal_number=1000 + number, at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        is_return=False, had_fuel=had_fuel, pay_name="Карта", lines=lines,
        version=1,
        received_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
    )


def test_projection_allowlist_is_explicit_superset_of_accounting_contract():
    assert tuple(accounting_egress.ACCOUNTING_DOCUMENT_KINDS) == ACCOUNTING_DOCUMENT_KINDS
    assert set(ACCOUNTING_DOCUMENT_KINDS) < set(PROJECTION_DOCUMENT_KINDS)
    assert {"fiscal_receipt", "store_shift", "revaluation"}.issubset(
        PROJECTION_DOCUMENT_KINDS)
    assert not any("fuel" in kind for kind in PROJECTION_DOCUMENT_KINDS)
    assert "fiscal_receipt" not in ACCOUNTING_DOCUMENT_KINDS
    assert "store_shift" not in ACCOUNTING_DOCUMENT_KINDS


def test_projection_schema_allows_multiple_sources_for_one_canonical_document():
    unique_names = {
        constraint.name
        for constraint in StoreDocumentProjection.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert "uq_store_document_projection_source" in unique_names
    assert "uq_store_document_projection_document" not in unique_names
    source_unique = next(
        constraint for constraint in StoreDocumentProjection.__table__.constraints
        if constraint.name == "uq_store_document_projection_source"
    )
    assert tuple(column.name for column in source_unique.columns) == (
        "company_id", "projection_source", "source_kind", "source_record_id",
    )
    assert {"accounting_group_id", "document_role", "source_document_id"}.issubset(
        StoreDocumentProjection.__table__.columns.keys())
    assert {column.name for column in StoreDocumentProjectionLine.__table__.columns} == {
        "id", "company_id", "record_id", "source_section", "source_line_id", "ordinal",
    }


def test_projection_record_id_is_tenant_scoped():
    document_id = uuid.uuid4()
    left = ProjectionCandidate(
        company_id=uuid.uuid4(), projection_source="store", source_kind="receipt",
        source_record_id="same", document_id=document_id, document_kind="purchase", priority=1)
    right = ProjectionCandidate(
        company_id=uuid.uuid4(), projection_source="store", source_kind="receipt",
        source_record_id="same", document_id=document_id, document_kind="purchase", priority=1)
    assert left.record_id != right.record_id


def test_projection_record_id_includes_full_source_scope():
    company_id = uuid.uuid4()
    document_id = uuid.uuid4()
    left = ProjectionCandidate(
        company_id=company_id, projection_source="store", source_kind="same",
        source_record_id="same", document_id=document_id, document_kind="purchase", priority=1)
    right = ProjectionCandidate(
        company_id=company_id, projection_source="edge", source_kind="same",
        source_record_id="same", document_id=document_id, document_kind="purchase", priority=1)
    assert left.record_id != right.record_id


def test_mixed_cheque_never_uses_declared_total_and_unclassified_is_quarantined():
    result = goods_only_cheque_totals([
        {"scope": "store", "qty": 1, "price": 100, "amount": 100},
        {"name": "неразмеченная строка", "amount": 900},
    ], had_fuel=True)
    assert result["quarantined"] is True
    assert result["explicit_goods"] == 1
    assert result["amount"] == Decimal("0.00")
    assert result["lines"] == []


@pytest.mark.asyncio
async def test_pure_fuel_cheque_creates_neither_cheque_nor_shift_projection():
    row = cheque(had_fuel=True, lines=[
        {"scope": "fuel", "qty": 10, "price": 60, "amount": 600},
    ])
    result = await store_documents._cheque_adapter(
        Session({StoreCheque: [row]}), uuid.uuid4())
    assert result == []


@pytest.mark.asyncio
async def test_mixed_cheque_with_explicit_goods_uses_goods_amount_only():
    row = cheque(had_fuel=True, lines=[
        {"scope": "store", "qty": 2, "price": 50, "amount": 100,
         "vat_rate": "БезНДС"},
    ])
    result = await store_documents._cheque_adapter(
        Session({StoreCheque: [row]}), uuid.uuid4())
    cheque_projection = next(item for item in result if item.document_kind == "fiscal_receipt")
    shift_projection = next(item for item in result if item.document_kind == "store_shift")
    assert cheque_projection.amount == Decimal("100.00")
    assert shift_projection.amount == Decimal("100.00")
    assert cheque_projection.has_fuel is True


@pytest.mark.asyncio
async def test_edge_mixed_sale_filters_declared_total_fail_closed():
    packet = SimpleNamespace(
        packet_uuid=str(uuid.uuid4()), station_id=208,
        received_at=datetime(2026, 8, 9, tzinfo=timezone.utc),
        payload={"Документы": [{
            "Тип": "retail_sale_sidegoods", "ИдентификаторДокумента": str(uuid.uuid4()),
            "БылоТопливо": True, "СуммаДокумента": 999,
            "Товары": [{"scope": "store", "amount": 100}, {"amount": 899}],
        }]},
    )
    result = await store_documents._edge_adapter(
        Session({EdgePacket: [packet]}), uuid.uuid4())
    assert len(result) == 1
    assert result[0].amount == Decimal("0.00")
    assert result[0].requires_attention is True
    assert len(result[0].lines) == 1


def test_safe_detail_does_not_expose_canonical_meta_or_bp_result():
    row = SimpleNamespace(source_kind="canonical_entry", operational_status="verified")
    detail = safe_document_detail(row, {
        "status": "verified", "metadata": {"secret": "raw"}, "result": {"bp": "raw"},
    })
    assert detail["status"] == "verified"
    assert "metadata" not in detail and "result" not in detail
    assert "raw" not in repr(detail)
    assert detail["detail_mode"] == "header_only"


def test_rbac_has_no_module_based_accountant_fallback_and_station_null_is_network_only():
    source = inspect.getsource(store_documents_router.resolve_document_access)
    assert "resolve_member_modules" not in source
    assert 'role.name.casefold() == "бухгалтер"' in source
    station = store_documents_router.DocumentAccess(
        uuid.uuid4(), False, False, False, frozenset({208}))
    accountant = store_documents_router.DocumentAccess(
        uuid.uuid4(), False, False, True, frozenset())
    assert store_documents_router._station_allowed(station, 208)
    assert not store_documents_router._station_allowed(station, None)
    assert store_documents_router._station_allowed(accountant, None)
    assert not station.can_raw
    assert accountant.can_raw


def test_relation_and_file_endpoints_do_not_expose_unscoped_refs_or_generic_url():
    relation_source = inspect.getsource(store_documents_router.document_relations)
    file_source = inspect.getsource(store_documents_router.document_files)
    assert "target_ref" not in relation_source
    assert "related_record_id is None" in relation_source
    assert "/api/files/" not in file_source
    assert "/api/store/documents/" in file_source
    assert "authorize_store_file_download" in inspect.getsource(intake_router.download_file)


def test_new_router_is_registered_before_store_catch_all():
    source = inspect.getsource(main)
    documents_at = source.index("include_router(store_documents_router.router")
    store_at = source.index("include_router(store_router.router")
    assert documents_at < store_at


def test_legacy_file_and_meta_routes_cannot_mutate_projection_records():
    assert 'doc_ref.startswith("projection:")' in inspect.getsource(
        store_router.store_doc_meta_save)
    assert 'doc_ref.startswith("projection:")' in inspect.getsource(
        store_router.store_doc_file_upload)
    assert "row.record_id is not None" in inspect.getsource(
        store_router.store_doc_file_delete)


def test_file_migration_is_additive_and_checksum_unique():
    source = inspect.getsource(database.create_all)
    for token in (
        "ADD COLUMN IF NOT EXISTS record_id UUID",
        "ADD COLUMN IF NOT EXISTS document_id UUID",
        "ADD COLUMN IF NOT EXISTS sha256 CHAR(64)",
        "ADD COLUMN IF NOT EXISTS tombstoned_at TIMESTAMPTZ",
        "uq_store_doc_file_revision",
    ):
        assert token in source
    signature = inspect.signature(ops_terms.store_file)
    assert signature.parameters["file_id"].default is None


def test_adapter_registry_covers_required_sources_without_fuel():
    names = tuple(name for name, _ in store_documents.ADAPTER_REGISTRY)
    assert names == (
        "onec_headers", "edge_documents", "canonical_entries",
        "accounting_outbox", "store_receipts", "store_cheques",
    )
    assert "fuel" not in " ".join(names)


def test_legacy_line_identity_survives_unrelated_reorder():
    first = [
        {"item_uuid": "a", "name": "A", "price": 10},
        {"item_uuid": "b", "name": "B", "price": 20},
        {"item_uuid": "c", "name": "C", "price": 30},
    ]
    reordered = [first[2], first[0], first[1]]
    left, left_ambiguous = store_documents._line_refs(first, "goods")
    right, right_ambiguous = store_documents._line_refs(reordered, "goods")
    assert {row.source_line_id for row in left} == {row.source_line_id for row in right}
    assert [row.ordinal for row in right] == [0, 1, 2]
    assert left_ambiguous is right_ambiguous is False


def test_duplicate_legacy_line_identity_is_explicitly_ambiguous_but_stable():
    duplicate = {"item_uuid": "a", "name": "A", "price": 10}
    first, ambiguous = store_documents._line_refs(
        [duplicate, {"item_uuid": "b"}, duplicate], "goods")
    reordered, reordered_ambiguous = store_documents._line_refs(
        [duplicate, duplicate, {"item_uuid": "b"}], "goods")
    assert ambiguous and reordered_ambiguous
    assert {row.source_line_id for row in first} == {
        row.source_line_id for row in reordered}


@pytest.mark.asyncio
async def test_mixed_cheque_without_explicit_scope_is_persistent_quarantine_zero():
    row = cheque(had_fuel=True, lines=[
        {"name": "неразмеченная строка", "qty": 1, "price": 100, "amount": 100},
    ])
    result = await store_documents._cheque_adapter(
        Session({StoreCheque: [row]}), uuid.uuid4())
    cheque_projection = next(
        item for item in result if item.document_kind == "fiscal_receipt")
    assert cheque_projection.amount == Decimal("0.00")
    assert cheque_projection.accounting_status == "not_applicable"
    assert cheque_projection.requires_attention is True


@pytest.mark.asyncio
async def test_untrusted_no_fuel_header_cannot_admit_unclassified_line_amount():
    row = cheque(had_fuel=False, lines=[
        {"name": "ДТ неизвестного контура", "qty": 10, "price": 60, "amount": 600},
    ])
    result = await store_documents._cheque_adapter(
        Session({StoreCheque: [row]}), uuid.uuid4())
    cheque_projection = next(
        item for item in result if item.document_kind == "fiscal_receipt")
    assert cheque_projection.amount == Decimal("0.00")
    assert cheque_projection.requires_attention is True
    assert cheque_projection.lines == []


def test_goods_line_without_frozen_vat_is_quarantined_but_no_vat_is_valid():
    unknown = goods_only_cheque_totals([
        {"scope": "store", "qty": 1, "price": 100, "amount": 100},
    ], had_fuel=False)
    assert unknown["quarantined"] is True
    assert unknown["amount"] == Decimal("100.00")
    assert unknown["vat_amount"] is None
    assert len(unknown["lines"]) == 1
    assert "НДС" in unknown["reason"]

    no_vat = goods_only_cheque_totals([
        {"scope": "store", "qty": 1, "price": 100, "amount": 100,
         "vat_rate": "БезНДС"},
    ], had_fuel=False)
    assert no_vat["quarantined"] is False
    assert no_vat["amount"] == Decimal("100.00")
    assert no_vat["vat_amount"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_fuel_entries_and_unconfirmed_onec_headers_never_project():
    company_id = uuid.uuid4()
    document_id = uuid.uuid4()
    fuel_entry = SimpleNamespace(
        id=uuid.uuid4(), company_id=company_id, document_id=document_id,
        category_id="fuel", doc_type_id="purchase", meta={}, fact_origin="store",
        title="Топливное поступление", status="verified", created_at=datetime.now(timezone.utc),
        revision=1, content_hash="a" * 64, layer="clean",
    )
    canonical = await store_documents._canonical_adapter(
        Session({DataEntry: [fuel_entry]}), company_id)
    assert canonical == []

    accounting = SimpleNamespace(
        id=uuid.uuid4(), matched_entry_id=fuel_entry.id,
        external_id=str(uuid.uuid4()), doc_type="Поступление нефтепродуктов",
    )
    # Документы центральной базы вне области станции и периода в реестр не
    # берутся: в ЦБ лежит история всей сети с 2016 года.
    чужие = SimpleNamespace(
        customization={"edge": {"onec_documents_from": "2026-06-11T00:00:00+03:00",
                                "onec_documents_stations": [208]}})
    inventory = SimpleNamespace(
        id=uuid.uuid4(), external_ref=str(uuid.uuid4()), number="ИНВ-1",
        doc_date=datetime(2026, 5, 1, tzinfo=timezone.utc), net_amount=10, posted=True,
        warehouse_code="209", warehouse_name="АЗС №209", lines=[],
        snapshot_at=datetime.now(timezone.utc))
    movement = SimpleNamespace(
        id=uuid.uuid4(), kind="writeoff", external_ref=str(uuid.uuid4()), number="СП-1",
        doc_date=datetime(2026, 5, 1, tzinfo=timezone.utc), total_amount=10, posted=True,
        warehouse_code="208", warehouse_name="АЗС №208", warehouse_to_name=None,
        inventory_ref=None, lines=[], snapshot_at=datetime.now(timezone.utc))
    session = Session({
        DataEntry: [fuel_entry], AccountingSourceLink: [],
        AccountingDoc: [accounting], CbInventoryDoc: [inventory],
        CbMovementDoc: [movement], Company: [чужие],
    })
    async def _get(model, key):
        return чужие

    session.get = _get
    onec = await store_documents._onec_adapter(session, company_id)
    assert onec == [], "документ до даты перехода или чужой станции не проецируется"


@pytest.mark.asyncio
async def test_edge_fuel_rows_cannot_project_under_goods_document_names():
    company_id = uuid.uuid4()
    packet = SimpleNamespace(
        packet_uuid=str(uuid.uuid4()), station_id=208,
        received_at=datetime.now(timezone.utc),
        payload={"Документы": [
            {"Тип": kind, "ИдентификаторДокумента": str(uuid.uuid4()),
             "Товары": [{"scope": "fuel", "amount": 100}]}
            for kind in ("purchase", "writeoff", "inventory")
        ]},
    )
    assert await store_documents._edge_adapter(
        Session({EdgePacket: [packet]}), company_id) == []


@pytest.mark.asyncio
async def test_accounting_outbox_adapter_is_allowlisted_and_header_only():
    company_id = uuid.uuid4()
    document_id = uuid.uuid4()
    packet = SimpleNamespace(
        id=uuid.uuid4(), company_id=company_id,
        kind="store_accounting_group", fact_origin="store",
        payload={"Документы": [
            {"Тип": "fuel_purchase", "document_id": str(uuid.uuid4())},
            {"Тип": "fiscal_receipt", "document_id": str(uuid.uuid4())},
            {"Тип": "store_shift", "document_id": str(uuid.uuid4())},
            {"Тип": "purchase", "document_id": str(document_id),
             "station_id": 208, "СуммаДокумента": 100},
        ]},
        packet_uuid=uuid.uuid4(), revision=2, contract_version="3",
        content_hash="b" * 64, transport_producer="central_ledger",
        attempt_id=None, error_code=None, created_at=datetime.now(timezone.utc),
        status="queued",
    )
    result = await store_documents._accounting_outbox_adapter(
        Session({ExportPacket: [packet]}), company_id)
    assert len(result) == 1
    assert result[0].document_id == document_id
    assert result[0].document_role == "accounting_derived"
    assert "payload" not in result[0].header
    assert "Документы" not in result[0].header


def test_candidate_hash_covers_all_projected_identity_and_status_fields():
    base = dict(
        company_id=uuid.uuid4(), projection_source="store", source_kind="receipt",
        source_record_id="r", document_id=uuid.uuid4(), document_kind="purchase",
        priority=1, document_role="primary_evidence",
    )
    left = ProjectionCandidate(counterparty_name="A", **base)
    right = ProjectionCandidate(counterparty_name="B", **base)
    assert store_documents._candidate_hash(left) != store_documents._candidate_hash(right)
    right.counterparty_name = "A"
    right.has_fuel = True
    assert store_documents._candidate_hash(left) != store_documents._candidate_hash(right)


def test_legacy_station_scope_intersects_client_filter_and_never_defaults_to_all():
    company_id = uuid.uuid4()
    station = store_documents_router.DocumentAccess(
        company_id, False, False, False, frozenset({208}))
    network = store_documents_router.DocumentAccess(
        company_id, False, True, False, frozenset())
    assert store_router._legacy_station_scope(station, None) == (208,)
    assert store_router._legacy_station_scope(station, {208, 209}) == (208,)
    assert store_router._legacy_station_scope(station, {209}) == ()
    assert store_router._legacy_station_scope(network, {209}) == (209,)


def test_legacy_routes_share_document_rbac_and_reject_nonprojection_kinds():
    station_docs = inspect.getsource(store_router.store_station_docs)
    cheques = inspect.getsource(store_router.store_cheques)
    detail = inspect.getsource(store_router.store_station_doc)
    assert "resolve_document_access" in station_docs
    assert "resolve_document_access" in cheques
    assert "resolve_document_access" in detail
    assert "_station_allowed" in detail
    assert "STATION_DOC_ALLOWED_KINDS" in station_docs
    assert "STATION_DOC_ALLOWED_KINDS" in detail
    assert "fuel" not in store_router.STATION_DOC_ALLOWED_KINDS
    assert "sanitize_edge_document" in station_docs
    assert "sanitize_edge_document" in detail
    assert "goods_only_cheque_totals" in cheques
    assert "StoreCheque.total" not in cheques


def test_cheque_version_and_projection_role_migrations_are_explicit():
    source = inspect.getsource(database.create_all)
    assert "store_cheques ADD COLUMN IF NOT EXISTS version" in source
    assert "store_cheques ADD COLUMN IF NOT EXISTS cash_key" in source
    assert "(company_id, station_id, shift_number, cash_key)" in source
    assert "ck_store_cheque_version" in source
    assert "counterparties ADD COLUMN IF NOT EXISTS is_group" in source
    assert "accounting_group_id UUID" in source
    assert "document_role VARCHAR(30)" in source
    assert "source_document_id UUID" in source
    assert "ALTER COLUMN vat_amount DROP NOT NULL" in source
    assert StoreDocumentProjection.__table__.c.vat_amount.nullable is True


def test_normalized_payload_uses_company_predicate_for_accounting_sources():
    source = inspect.getsource(store_documents.normalized_document_payload)
    assert "DataEntry.company_id == row.company_id" in source
    assert "AccountingDoc.company_id == row.company_id" in source


def test_legacy_meta_and_file_save_resolve_projection_identity():
    meta_source = inspect.getsource(store_router.store_doc_meta_save)
    file_source = inspect.getsource(store_router.store_doc_file_upload)
    assert "row.record_id = document.id" in meta_source
    assert "row.document_id = document.document_id" in meta_source
    assert "record_id=document.id if document else None" in file_source
    assert "revision=document.revision if document else 1" in file_source


def test_movement_relation_is_typed_and_never_returns_target_ref():
    source = inspect.getsource(store_documents_router.document_relations)
    assert 'relation.relation_kind == "stock_movement"' in source
    assert '"count": 1' in source
    assert "target_ref" not in source
    rebuild_source = inspect.getsource(
        store_documents.rebuild_store_document_projection)
    assert '"accounting_group_member"' in rebuild_source


def fiscal_payload(*, amount=100, scope="store", vat_amount=9.09):
    return {
        "Смена": {"НомерСменыВнутр": 7001},
        "Документы": [{
            "Тип": "fiscal_receipts",
            "Чеки": [{
                "Номер": 1, "Пост": 1, "КлючЧека": "1:1",
                "ФН": 1001, "Время": "2026-08-09T12:00:00+03:00",
                "БылоТопливо": True, "Сумма": amount, "ВидОплаты": 2,
                "ВидОплатыНазвание": "Карта",
                "Товары": [{
                    "Номенклатура": "coffee", "Наименование": "Кофе",
                    "Количество": 1, "Цена": amount, "Сумма": amount,
                    "scope": scope, "Секция": "Товары",
                    "СтавкаНДС": "НДС10", "СуммаНДС": vat_amount,
                }],
            }],
        }],
    }


@pytest.mark.asyncio
async def test_raw_cheque_ingest_preserves_scope_vat_and_projects_goods_only():
    company_id = uuid.uuid4()
    session = IngestSession()
    accepted = await edge_router._ingest_cheques(
        session, company_id, 208, fiscal_payload(), str(uuid.uuid4()))
    assert accepted == 1 and len(session.added) == 1
    stored = session.added[0]
    assert stored.lines[0]["scope"] == "store"
    assert stored.lines[0]["vat_rate"] == "НДС10"
    assert stored.lines[0]["vat_amount"] == 9.09
    projected = await store_documents._cheque_adapter(
        Session({StoreCheque: [stored]}), company_id)
    receipt = next(row for row in projected if row.document_kind == "fiscal_receipt")
    assert receipt.amount == Decimal("100.00")
    assert receipt.vat_amount == Decimal("9.09")


@pytest.mark.asyncio
async def test_authenticated_fiscal_v1_infers_store_scope_but_keeps_unknown_vat_null():
    company_id = uuid.uuid4()
    payload = fiscal_payload(amount=999, scope=None, vat_amount=None)
    line = payload["Документы"][0]["Чеки"][0]["Товары"][0]
    line.pop("СтавкаНДС")
    line["Сумма"] = 125
    session = IngestSession()
    await edge_router._ingest_cheques(
        session, company_id, 208, payload, str(uuid.uuid4()))
    stored = session.added[0]
    assert stored.total == 125
    assert stored.lines[0]["scope"] == "store"
    assert stored.lines[0]["scope_source"] == "edge_fiscal_receipts_filtered_v1"

    projected = await store_documents._cheque_adapter(
        Session({StoreCheque: [stored]}), company_id)
    receipt = next(row for row in projected if row.document_kind == "fiscal_receipt")
    assert receipt.amount == Decimal("125.00")
    assert receipt.vat_amount is None
    assert receipt.accounting_status == "not_applicable"


@pytest.mark.asyncio
async def test_historical_fiscal_v1_requires_exact_packet_line_provenance():
    company_id = uuid.uuid4()
    packet_uuid = str(uuid.uuid4())
    stored = cheque(had_fuel=True, lines=[{
        "item_uuid": "coffee", "name": "Кофе", "ns_code": 17,
        "qty": 1, "price": 125, "amount": 125, "section": 2,
    }])
    stored.packet_uuid = packet_uuid
    packet = SimpleNamespace(
        packet_uuid=packet_uuid, station_id=208,
        payload={
            "Смена": {"НомерСменыВнутр": 7001},
            "Документы": [{
                "Тип": "fiscal_receipts", "Чеки": [{
                    "Номер": 1, "БылоТопливо": True,
                    "Товары": [{
                        "Номенклатура": "coffee", "Наименование": "Кофе", "КодНС": 17,
                        "Количество": 1, "Цена": 125, "Сумма": 125, "Секция": 2,
                    }],
                }],
            }],
        },
    )
    projected = await store_documents._cheque_adapter(
        Session({StoreCheque: [stored], EdgePacket: [packet]}), company_id)
    receipt = next(row for row in projected if row.document_kind == "fiscal_receipt")
    assert receipt.amount == Decimal("125.00")
    assert receipt.vat_amount is None
    assert len(receipt.lines) == 1

    forged = cheque(had_fuel=True, lines=[{
        "item_uuid": "coffee", "name": "Кофе", "ns_code": 17,
        "qty": 1, "price": 125, "amount": 999, "section": 2,
    }])
    forged.packet_uuid = packet_uuid
    rejected = await store_documents._cheque_adapter(
        Session({StoreCheque: [forged], EdgePacket: [packet]}), company_id)
    rejected_receipt = next(
        row for row in rejected if row.document_kind == "fiscal_receipt")
    assert rejected_receipt.amount == Decimal("0.00")
    assert rejected_receipt.lines == []
    assert rejected_receipt.accounting_status == "not_applicable"


@pytest.mark.asyncio
async def test_operational_edge_document_needs_no_vat_but_rejects_unknown_lines():
    company_id = uuid.uuid4()
    packet = SimpleNamespace(
        packet_uuid=str(uuid.uuid4()), station_id=208,
        received_at=datetime.now(timezone.utc),
        payload={"Документы": [{
            "Тип": "transfer", "ИдентификаторДокумента": str(uuid.uuid4()),
            "Товары": [
                {"Номенклатура": str(uuid.uuid4()), "Наименование": "Кофе", "Количество": 2},
                {"Наименование": "без НСИ", "Количество": 1},
            ],
        }]},
    )
    result = await store_documents._edge_adapter(
        Session({EdgePacket: [packet]}), company_id)
    assert len(result) == 1
    assert result[0].vat_amount is None
    assert result[0].accounting_status == "needs_review"
    assert len(result[0].lines) == 1

    detail = safe_document_detail(result[0], packet.payload["Документы"][0])
    assert len(detail["lines"]) == 1
    assert detail["lines"][0]["Наименование"] == "Кофе"
    assert all(row.get("Наименование") != "без НСИ" for row in detail["lines"])
    clean = store_documents.sanitize_edge_document({
        "Тип": "transfer",
        "Товары": [{"Номенклатура": str(uuid.uuid4()), "Количество": 1}],
    }, trusted_station_packet=True)
    assert clean["quarantined"] is False
    assert clean["vat_amount"] == Decimal("0.00")


@pytest.mark.asyncio
async def test_station_price_change_projects_as_revaluation():
    company_id = uuid.uuid4()
    source_uuid = str(uuid.uuid4())
    packet = SimpleNamespace(
        packet_uuid=str(uuid.uuid4()), station_id=208,
        received_at=datetime.now(timezone.utc),
        payload={"Документы": [{
            "Тип": "price_change", "ИсточникUUID": source_uuid,
            "НоменклатураUUID": str(uuid.uuid4()), "Штрихкод": "4600",
            "ЦенаБыла": 100, "ЦенаСтала": 120, "Автор": "Товаровед",
            "Причина": "новая закупка", "Момент": "2026-08-17T12:00:00+03:00",
        }]},
    )
    projected = await store_documents._edge_adapter(
        Session({EdgePacket: [packet], StoreReceipt: []}), company_id)
    assert len(projected) == 1
    row = projected[0]
    assert row.document_kind == "revaluation"
    assert row.header["old_price"] == 100
    assert row.header["new_price"] == 120
    detail = safe_document_detail(
        SimpleNamespace(source_kind="edge_document", operational_status="received"),
        store_documents._projection_edge_document(packet.payload["Документы"][0]),
    )
    assert detail["lines"][0]["ЦенаСтала"] == 120


@pytest.mark.asyncio
async def test_shift_revision_changes_when_second_v1_cheque_is_added():
    company_id = uuid.uuid4()
    first = cheque(had_fuel=False, number=1, lines=[
        {"scope": "store", "item_uuid": "a", "amount": 100,
         "vat_rate": "БезНДС"},
    ])
    second = cheque(had_fuel=False, number=2, lines=[
        {"scope": "store", "item_uuid": "b", "amount": 50,
         "vat_rate": "БезНДС"},
    ])
    one = await store_documents._cheque_adapter(
        Session({StoreCheque: [first]}), company_id)
    two = await store_documents._cheque_adapter(
        Session({StoreCheque: [second, first]}), company_id)
    two_reordered = await store_documents._cheque_adapter(
        Session({StoreCheque: [first, second]}), company_id)
    shift_one = next(row for row in one if row.document_kind == "store_shift")
    shift_two = next(row for row in two if row.document_kind == "store_shift")
    assert shift_one.revision == 1
    assert shift_two.revision == 2
    assert shift_one.content_hash != shift_two.content_hash
    shift_two_reordered = next(
        row for row in two_reordered if row.document_kind == "store_shift")
    assert [relation.target_ref for relation in shift_two.relations] == [
        relation.target_ref for relation in shift_two_reordered.relations]


@pytest.mark.asyncio
async def test_cheque_exact_replay_is_noop_and_correction_increments_version():
    company_id = uuid.uuid4()
    first_session = IngestSession()
    await edge_router._ingest_cheques(
        first_session, company_id, 208, fiscal_payload(), str(uuid.uuid4()))
    stored = first_session.added[0]
    original_packet = stored.packet_uuid

    replay_session = IngestSession(stored)
    await edge_router._ingest_cheques(
        replay_session, company_id, 208, fiscal_payload(), str(uuid.uuid4()))
    assert stored.version == 1
    assert stored.packet_uuid == original_packet

    await edge_router._ingest_cheques(
        replay_session, company_id, 208,
        fiscal_payload(amount=120, vat_amount=10.91), str(uuid.uuid4()))
    assert stored.version == 2
    assert stored.total == 120


@pytest.mark.asyncio
async def test_cheque_ingest_keeps_same_number_from_two_posts_and_zero_return():
    company_id = uuid.uuid4()
    payload = fiscal_payload()
    first = payload["Документы"][0]["Чеки"][0]
    second = dict(first, Пост=2, КлючЧека="2:1", ФН=2001)
    returned = dict(first, Номер=0, КлючЧека="1:0:55:901:2026-08-09T12:00:00+03:00",
                    Возврат=True, ФН=901)
    payload["Документы"][0]["Чеки"] = [first, second, returned]

    session = IngestSession()
    accepted = await edge_router._ingest_cheques(
        session, company_id, 208, payload, str(uuid.uuid4()))

    assert accepted == 3
    assert [row.cash_key for row in session.added] == [
        "1:1", "2:1", "1:0:55:901:2026-08-09T12:00:00+03:00",
    ]
    assert session.added[-1].number == 0
    assert session.added[-1].is_return is True


def test_store_cheque_identity_contains_cash_key():
    unique = next(
        constraint for constraint in StoreCheque.__table__.constraints
        if constraint.name == "uq_store_cheque"
    )
    assert tuple(column.name for column in unique.columns) == (
        "company_id", "station_id", "shift_number", "cash_key",
    )


@pytest.mark.asyncio
async def test_direct_station_document_cross_station_is_404_before_payload(
    monkeypatch,
):
    company_id = uuid.uuid4()
    access = store_documents_router.DocumentAccess(
        company_id, False, False, False, frozenset({208}))

    async def scoped(_user, _db):
        return company_id

    async def resolved(_user, _db, _company_id):
        return access

    monkeypatch.setattr(store_router, "scope_company_id", scoped)
    monkeypatch.setattr(store_router, "resolve_document_access", resolved)
    packet = SimpleNamespace(station_id=209)
    db = IngestSession(packet)
    with pytest.raises(Exception) as exc:
        await store_router.store_station_doc(
            packet_uuid=str(uuid.uuid4()), index=0,
            user=SimpleNamespace(), db=db)
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_direct_station_document_fuel_kind_is_404(monkeypatch):
    company_id = uuid.uuid4()
    access = store_documents_router.DocumentAccess(
        company_id, False, False, False, frozenset({208}))

    async def scoped(_user, _db):
        return company_id

    async def resolved(_user, _db, _company_id):
        return access

    monkeypatch.setattr(store_router, "scope_company_id", scoped)
    monkeypatch.setattr(store_router, "resolve_document_access", resolved)
    packet = SimpleNamespace(
        station_id=208, payload={"Документы": [{"Тип": "fuel_purchase"}]})
    db = IngestSession(packet)
    with pytest.raises(Exception) as exc:
        await store_router.store_station_doc(
            packet_uuid=str(uuid.uuid4()), index=0,
            user=SimpleNamespace(), db=db)
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_generic_file_download_rechecks_projection_station_scope(monkeypatch):
    company_id = uuid.uuid4()
    file_id = uuid.uuid4()
    record_id = uuid.uuid4()
    file_row = SimpleNamespace(
        file_id=file_id, company_id=company_id, record_id=record_id,
        doc_ref=f"projection:{record_id}", tombstoned_at=None)
    projection = SimpleNamespace(
        id=record_id, company_id=company_id, station_id=209)
    access = store_documents_router.DocumentAccess(
        company_id, False, False, False, frozenset({208}))

    async def resolved(_user, _db, _company_id):
        return access

    monkeypatch.setattr(store_documents_router, "resolve_document_access", resolved)
    db = Session({StoreDocFile: [file_row], StoreDocumentProjection: [projection]})
    with pytest.raises(Exception) as exc:
        await store_documents_router.authorize_store_file_download(
            db, SimpleNamespace(), file_id)
    assert getattr(exc.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_rebuild_adapter_failure_preserves_last_good_without_mutation(monkeypatch):
    async def broken(_db, _company_id):
        raise RuntimeError("adapter failed")

    monkeypatch.setattr(store_documents, "ADAPTER_REGISTRY", (("broken", broken),))
    session = RebuildSession({})
    with pytest.raises(RuntimeError, match="adapter failed"):
        await store_documents.rebuild_store_document_projection(
            session, uuid.uuid4())
    assert session.added == []
    assert session.deleted_tables == []


@pytest.mark.asyncio
async def test_rebuild_stale_delete_is_explicit_and_company_scoped(monkeypatch):
    async def empty(_db, _company_id):
        return []

    monkeypatch.setattr(store_documents, "ADAPTER_REGISTRY", (("empty", empty),))
    stale = SimpleNamespace(id=uuid.uuid4())
    session = RebuildSession({
        AccountingSourceLink: [], StoreDocFile: [],
        StoreDocumentProjection: [stale], StoreDocumentProjectionLine: [],
        StoreDocumentRelation: [],
    })
    result = await store_documents.rebuild_store_document_projection(
        session, uuid.uuid4())
    assert "store_document_projections" in session.deleted_tables
    assert result["removed"] == 1
    source = inspect.getsource(store_documents.rebuild_store_document_projection)
    assert "StoreDocumentProjection.company_id == company_id" in source


@pytest.mark.asyncio
async def test_document_registry_filters_stats_and_station_scope(monkeypatch):
    company_id = uuid.uuid4()
    access = store_documents_router.DocumentAccess(
        company_id, False, False, False, frozenset({208}))

    async def resolved(_user, _db, _company_id=None):
        return access

    monkeypatch.setattr(store_documents_router, "resolve_document_access", resolved)
    session = ListSession()
    result = await store_documents_router.list_documents(
        station_id=None,
        stations="208,209",
        date_from=date(2026, 8, 1),
        date_to=date(2026, 8, 9),
        kind="purchase",
        q="УПД-42",
        supplier="7701234567",
        operational_status="accepted",
        sync_status="queued",
        accounting_status="needs_review",
        discrepancy_status="material",
        source="edge",
        warehouse=None,
        attention=True,
        has_files=False,
        counter=None,
        limit=50,
        offset=0,
        user=SimpleNamespace(),
        db=session,
    )

    assert result["stats"] == {
        "attention": 4,
        "missing_evidence": 3,
        "not_accounting_ready": 2,
        "onec_mismatch": 1,
    }
    assert result["documents"] == []
    # реестр — проекция: человек видит момент сборки и может её повторить
    assert result["rebuilt_at"] == datetime(2026, 8, 9, 21, 0, tzinfo=timezone.utc)
    # пересборка — работа сети: администратору станции кнопка не показывается
    assert result["rebuild_allowed"] is False
    assert len(session.statements) == 3
    stats_sql = str(session.statements[0])
    result_sql = str(session.statements[2])
    assert "store_document_projections.document_at >=" in stats_sql
    assert "store_document_projections.document_at <" in stats_sql
    assert "store_document_projections.accounting_status =" not in stats_sql
    assert "store_document_projections.discrepancy_status =" not in stats_sql
    assert "not_applicable" in repr(session.statements[0].compile().params)
    assert "fiscal_receipt" in repr(session.statements[0].compile().params)
    assert "store_shift" in repr(session.statements[0].compile().params)
    assert "store_document_projections.accounting_status =" in result_sql
    assert "store_document_projections.discrepancy_status =" in result_sql
    assert [208] in list(session.statements[0].compile().params.values())


def test_document_registry_api_declares_inclusive_period_and_null_scope_policy():
    source = inspect.getsource(store_documents_router.list_documents)
    assert "date_to + timedelta(days=1)" in source
    assert "allowed.intersection_update(requested_stations)" in source
    assert "StoreDocumentProjection.station_id.in_(sorted(allowed))" in source
    assert "StoreDocumentProjection.station_id.is_(None)" in source
    assert "stats_conditions = [*base_conditions, *filter_conditions]" in source


@pytest.mark.asyncio
async def test_network_station_filter_keeps_central_null_scope(monkeypatch):
    company_id = uuid.uuid4()
    access = store_documents_router.DocumentAccess(
        company_id, False, True, False, frozenset())

    async def resolved(_user, _db, _company_id=None):
        return access

    monkeypatch.setattr(store_documents_router, "resolve_document_access", resolved)
    session = ListSession()
    await store_documents_router.list_documents(
        station_id=None, stations="208", date_from=None, date_to=None,
        kind=None, q=None, supplier=None, operational_status=None,
        sync_status=None, accounting_status=None, discrepancy_status=None,
        source=None, warehouse=None, attention=None, has_files=None, counter=None,
        limit=50, offset=0, user=SimpleNamespace(), db=session,
    )
    sql = str(session.statements[0])
    assert "store_document_projections.station_id IN" in sql
    assert "store_document_projections.station_id IS NULL" in sql


@pytest.mark.asyncio
async def test_counter_filter_reuses_the_expression_that_produced_the_number(monkeypatch):
    """Кнопка счётчика обязана отбирать ровно то, что он посчитал."""
    company_id = uuid.uuid4()
    access = store_documents_router.DocumentAccess(
        company_id, True, False, False, frozenset())

    async def resolved(_user, _db, _company_id=None):
        return access

    monkeypatch.setattr(store_documents_router, "resolve_document_access", resolved)
    for name in store_documents_router.COUNTER_CONDITIONS:
        session = ListSession()
        await store_documents_router.list_documents(
            station_id=None, stations=None, date_from=None, date_to=None,
            kind=None, q=None, supplier=None, operational_status=None,
            sync_status=None, accounting_status=None, discrepancy_status=None,
            source=None, warehouse=None, attention=None, has_files=None,
            counter=name, limit=50, offset=0, user=SimpleNamespace(), db=session,
        )
        stats_params = repr(session.statements[0].compile().params)
        result_params = repr(session.statements[2].compile().params)
        for condition in store_documents_router.COUNTER_CONDITIONS[name]():
            for value in condition.compile().params.values():
                assert repr(value) in stats_params
                assert repr(value) in result_params, (
                    f"счётчик {name} считает не то, что отбирает его кнопка")

    session = ListSession()
    with pytest.raises(Exception) as unknown:
        await store_documents_router.list_documents(
            station_id=None, stations=None, date_from=None, date_to=None,
            kind=None, q=None, supplier=None, operational_status=None,
            sync_status=None, accounting_status=None, discrepancy_status=None,
            source=None, warehouse=None, attention=None, has_files=None,
            counter="выдумка", limit=50, offset=0, user=SimpleNamespace(), db=session,
        )
    assert getattr(unknown.value, "status_code", None) == 400


@pytest.mark.asyncio
async def test_warehouse_filter_falls_back_to_header_name_when_not_uuid(monkeypatch):
    company_id = uuid.uuid4()
    access = store_documents_router.DocumentAccess(
        company_id, True, False, False, frozenset())

    async def resolved(_user, _db, _company_id=None):
        return access

    monkeypatch.setattr(store_documents_router, "resolve_document_access", resolved)
    canonical = uuid.uuid4()
    session = ListSession()
    await store_documents_router.list_documents(
        station_id=None, stations=None, date_from=None, date_to=None, kind=None,
        q=None, supplier=None, operational_status=None, sync_status=None,
        accounting_status=None, discrepancy_status=None, source=None,
        warehouse=str(canonical), attention=None, has_files=None, counter=None,
        limit=50, offset=0, user=SimpleNamespace(), db=session,
    )
    assert "store_document_projections.warehouse_id =" in str(session.statements[0])

    session = ListSession()
    await store_documents_router.list_documents(
        station_id=None, stations=None, date_from=None, date_to=None, kind=None,
        q=None, supplier=None, operational_status=None, sync_status=None,
        accounting_status=None, discrepancy_status=None, source=None,
        warehouse="Зал", attention=None, has_files=None, counter=None,
        limit=50, offset=0, user=SimpleNamespace(), db=session,
    )
    params = session.statements[0].compile().params
    assert "warehouse" in params.values() and "warehouse_to" in params.values()
    assert "%Зал%" in params.values()


def test_header_only_sources_say_so_instead_of_pretending_there_are_no_lines():
    for source_kind in ("onec_inventory", "onec_movement", "canonical_entry",
                        "accounting_packet", "неизвестный"):
        row = SimpleNamespace(source_kind=source_kind, operational_status="posted")
        detail = safe_document_detail(row, {"status": "posted", "lines": [{"x": 1}]})
        assert detail["detail_mode"] == "header_only"
        assert detail["lines"] == []
        assert detail["detail_note"]
    lines_row = SimpleNamespace(source_kind="accounting_doc", operational_status="posted")
    lines_detail = safe_document_detail(
        lines_row, {"status": "posted", "lines": [{"Наименование": "Кофе", "Сумма": 10}]})
    assert lines_detail["detail_mode"] == "lines"
    assert lines_detail["lines"][0]["Наименование"] == "Кофе"


def test_onec_snapshot_is_header_only_confirmed_accounting_scope():
    company_id = uuid.uuid4()
    canonical_id = uuid.uuid4()
    confirmed_at = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)

    source_document_id = uuid.uuid4()

    def projection(kind, source_id, source="onec_legacy"):
        return SimpleNamespace(
            company_id=company_id, station_id=208, document_id=canonical_id,
            document_kind=kind, projection_source=source,
            source_record_id=source_id, source_document_id=source_document_id,
            source_kind=kind,
            is_primary=False, document_at=confirmed_at,
            number="УПД-42", counterparty_name="Поставщик",
            amount=Decimal("125.40"), vat_amount=Decimal("20.90"),
            operational_status="posted",
            # Реквизиты исходного документа 1С: снимок везёт их станции, и
            # заглушка обязана их иметь — иначе тест падает не на предмете
            # проверки, а на отсутствующем поле.
            author="Товаровед 208",
            header={"warehouse": "АЗС 208", "raw": "secret", "lines": ["hidden"]},
        )

    link = SimpleNamespace(
        projection_source="onec_legacy", source_kind="purchase",
        source_document_id=source_document_id,
        canonical_document_id=canonical_id, confirmed_at=confirmed_at,
    )
    entry = SimpleNamespace(
        document_id=canonical_id, revision=3, content_hash="a" * 64,
    )
    headers = build_snapshot_headers([
        projection("fiscal_receipt", "cheque"),
        projection("store_shift", "shift"),
        projection("revaluation", "revaluation"),
        projection("fuel_sale", "fuel"),
        projection("purchase", "purchase-b"),
        projection("purchase", "purchase-a", source="cash"),
        projection("purchase", "receipt-1", source="store"),
        projection("purchase", "own-1", source="edge"),
    ], [link], [entry])

    # переоценка в 1С есть и человеку нужна; чек, смена и топливо — нет
    # станции нужны документы, которых у неё нет: из 1С и из реестра центра.
    # Собственные документы станции («edge») и кассовый архив не дублируем.
    assert [header["source_id"] for header in headers] == [
        "onec_legacy:purchase-b", "onec_legacy:revaluation", "store:receipt-1"]
    assert headers[0]["canonical_link"] is not None, "подтверждённая связь сохраняется"
    assert headers[1]["canonical_link"] is None, "без связи документ едет как есть"
    assert headers[0]["amount"] == "125.40"
    assert headers[0]["vat"] == "20.90"
    encoded = str(headers)
    assert "secret" not in encoded
    # Состав документа снимок теперь везёт отдельным полем — станция показывает
    # накладную целиком. Но берёт его из состава, а не из сырого `header`:
    # там лежит всё подряд, включая поля, которых станции знать незачем.
    assert "hidden" not in encoded
    assert all(header["lines"] == [] for header in headers), (
        "состав не передавали — значит и в снимке его быть не должно")
    assert "fuel" not in encoded
    assert snapshot_content_hash(headers) == snapshot_content_hash(list(headers))
    wrong_link = SimpleNamespace(
        projection_source="onec_legacy", source_kind="purchase",
        source_document_id=uuid.uuid4(), canonical_document_id=canonical_id,
        confirmed_at=confirmed_at,
    )
    # чужая связь не приклеивается к документу: он едет без неё
    без_связи = build_snapshot_headers(
        [projection("purchase", "purchase-b")], [wrong_link], [entry])
    assert без_связи and без_связи[0]["canonical_link"] is None
    # а вот без документа проекции снимок пуст
    assert build_snapshot_headers([], [link], [entry]) == []
    # Один документ — одна строка на станции: в снимок идёт основная запись,
    # иначе накладная, пришедшая и пакетом, и в реестр, приедет дважды.
    source = inspect.getsource(queue_onec_document_snapshot)
    assert "StoreDocumentProjection.is_primary" in source


@pytest.mark.asyncio
async def test_onec_snapshot_queue_is_explicit_monotonic_and_idempotent():
    company_id = uuid.uuid4()
    canonical_id = uuid.uuid4()
    source_document_id = uuid.uuid4()
    confirmed_at = datetime(2026, 8, 9, 12, tzinfo=timezone.utc)
    projection = SimpleNamespace(
        company_id=company_id, station_id=208, is_primary=True,
        document_id=canonical_id, document_kind="purchase",
        projection_source="onec_legacy", source_record_id="source-1",
        source_document_id=source_document_id, source_kind="purchase",
        document_at=confirmed_at, number="42", counterparty_name="Поставщик",
        amount=Decimal("10.00"), vat_amount=Decimal("2.00"),
        operational_status="posted", header={"warehouse": "АЗС 208"},
        author="Товаровед 208",
    )
    link = SimpleNamespace(
        projection_source="onec_legacy", source_kind="purchase",
        source_document_id=source_document_id,
        canonical_document_id=canonical_id, confirmed_at=confirmed_at,
    )
    entry = SimpleNamespace(
        document_id=canonical_id, revision=2, content_hash="b" * 64,
    )
    rows = {
        EdgeAgent: [SimpleNamespace(station_id=208)],
        StoreDocumentProjection: [projection],
        AccountingSourceLink: [link],
        DataEntry: [entry],
        EdgeDownlink: [],
    }
    first_session = SnapshotSession(rows)
    first, created = await queue_onec_document_snapshot(first_session, company_id, 208)
    assert created is True
    assert first.kind == "onec_document_snapshot"
    assert first.payload["schema_version"] == 1
    assert first.payload["revision"] == 1
    assert first.idempotency_key.startswith("onec-documents:208:")
    assert first.payload["headers"][0]["canonical_link"]["revision"] == 2
    assert len(first_session.added) == 1

    repeat_session = SnapshotSession({**rows, EdgeDownlink: [first]})
    repeat, repeat_created = await queue_onec_document_snapshot(
        repeat_session, company_id, 208)
    assert repeat_created is False
    assert repeat.id == first.id
    assert repeat_session.added == []

    projection.amount = Decimal("11.00")
    changed_session = SnapshotSession({**rows, EdgeDownlink: [first]})
    changed, changed_created = await queue_onec_document_snapshot(
        changed_session, company_id, 208)
    assert changed_created is True
    assert changed.payload["revision"] == 2
    assert changed.payload["content_hash"] != first.payload["content_hash"]


@pytest.mark.asyncio
async def test_station_admin_cannot_queue_network_snapshot(monkeypatch):
    company_id = uuid.uuid4()
    access = store_documents_router.DocumentAccess(
        company_id, False, False, False, frozenset({208}))

    async def resolved(_user, _db, _company_id=None):
        return access

    monkeypatch.setattr(store_documents_router, "resolve_document_access", resolved)
    with pytest.raises(Exception) as exc:
        await store_documents_router.queue_document_snapshot(
            station_id=209, user=SimpleNamespace(), db=SimpleNamespace())
    assert getattr(exc.value, "status_code", None) == 403


def test_onec_snapshot_rejects_unacknowledgeable_header():
    header = {
        "source_id": "onec_legacy:source-1", "kind": "purchase",
        "number": None, "document_at": None, "amount": "10.0", "vat": "2.00",
        "canonical_link": {
            "kind": "purchase", "document_id": str(uuid.uuid4()),
            "revision": 1, "content_hash": "a" * 64,
            "confirmed_at": datetime.now(timezone.utc).isoformat(),
        },
    }
    with pytest.raises(ValueError, match="onec_legacy:source-1"):
        validate_snapshot_headers([header])


@pytest.mark.asyncio
async def test_fiscal_documents_deny_file_mutations_for_superadmin(monkeypatch):
    company_id = uuid.uuid4()
    access = store_documents_router.DocumentAccess(
        company_id, True, False, False, frozenset())
    fiscal = SimpleNamespace(
        id=uuid.uuid4(), station_id=208, document_kind="fiscal_receipt")

    async def resolved(_user, _db, _company_id=None):
        return access

    async def projected(_db, _access, _record_id):
        return fiscal

    monkeypatch.setattr(store_documents_router, "resolve_document_access", resolved)
    monkeypatch.setattr(store_documents_router, "_projection", projected)
    with pytest.raises(Exception) as upload_error:
        await store_documents_router.document_file_upload(
            record_id=fiscal.id, role="прочее", note=None,
            file=SimpleNamespace(), user=SimpleNamespace(), db=SimpleNamespace())
    assert getattr(upload_error.value, "status_code", None) == 403

    with pytest.raises(Exception) as delete_error:
        await store_documents_router.document_file_tombstone(
            record_id=fiscal.id, file_row_id=uuid.uuid4(), reason="ошибка",
            user=SimpleNamespace(), db=SimpleNamespace())
    assert getattr(delete_error.value, "status_code", None) == 403
    assert store_documents_router._file_write_allowed(
        access, 208, "store_shift") is False


def test_amount_in_words_declines_roubles_and_kopecks():
    assert store_document_print.сумма_прописью(0) == "Ноль рублей 00 копеек"
    assert store_document_print.сумма_прописью(1) == "Один рубль 00 копеек"
    assert store_document_print.сумма_прописью(2.5) == "Два рубля 50 копеек"
    assert store_document_print.сумма_прописью(21.01) == "Двадцать один рубль 01 копейка"
    assert store_document_print.сумма_прописью(2000) == "Две тысячи рублей 00 копеек"
    assert store_document_print.сумма_прописью(1234.56) == (
        "Одна тысяча двести тридцать четыре рубля 56 копеек")


def print_row(kind="purchase"):
    return SimpleNamespace(
        document_kind=kind, number="ПН-7", station_id=208,
        document_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        counterparty_name="ООО «Поставщик»", counterparty_inn="7701234567",
        header={"warehouse": "зал", "incoming_number": "УПД-42"}, amount=240,
    )


def test_print_form_uses_the_blank_people_already_know():
    """Бланк узнают по номеру формы, ОКУД и нумерации граф — их и печатаем."""
    payload = {"lines": [{
        "name": "Кофе 3в1", "barcode": "4600000000001", "unit": "шт",
        "qty": 10, "price": 24, "amount": 240, "vat_rate": "20%", "vat_amount": 40,
    }]}
    form = store_document_print.печатная_форма(
        print_row(), payload, компания="ООО «ГазИнвестГрупп»")
    for want in ("ТОРГ-12", "0330212", "Товарная накладная", "ООО «ГазИнвестГрупп»",
                 "Кофе 3в1", "4600000000001", "УПД-42", "АЗС 208",
                 "Двести сорок рублей 00 копеек", "Товар принял", "window.print()"):
        assert want in form, want
    assert "Строк нет" not in form

    for kind, blank in (("transfer", "ТОРГ-13"), ("inventory", "ИНВ-3"),
                        ("writeoff", "ТОРГ-16"), ("gain", "М-4"), ("recipe", "ОП-1")):
        other = store_document_print.печатная_форма(print_row(kind), payload)
        assert blank in other, kind

    # чек печатает касса, смена — архив, переоценка идёт приказом по ценам
    for kind in ("fiscal_receipt", "store_shift", "revaluation"):
        assert store_document_print.печатная_форма(print_row(kind), payload) is None


def test_discrepancy_blank_prints_only_diverging_lines_and_never_empty():
    """ТОРГ-2 и ИНВ-19 печатаются только там, где расхождение есть."""
    payload = {"lines": [
        {"name": "Кофе", "barcode": "460", "unit": "шт",
         "qty_expected": 10, "qty": 8, "price": 24, "amount": 192},
        {"name": "Вода", "barcode": "461", "unit": "шт",
         "qty_expected": 5, "qty": 5, "price": 40, "amount": 200},
    ]}
    акт = store_document_print.печатная_форма(print_row(), payload, вариант="diff")
    assert "ТОРГ-2" in акт and "0330202" in акт
    assert "претензии поставщику" in акт
    assert "Кофе" in акт
    assert "Вода" not in акт, "в акт попала строка без расхождения"

    ведомость = store_document_print.печатная_форма(
        print_row("inventory"), payload, вариант="diff")
    assert "ИНВ-19" in ведомость and "0317017" in ведомость

    ровный = {"lines": [payload["lines"][1]]}
    assert store_document_print.печатная_форма(
        print_row(), ровный, вариант="diff") is None, "пустой акт печатать нельзя"
    for kind in ("writeoff", "transfer", "gain", "fiscal_receipt"):
        assert store_document_print.печатная_форма(
            print_row(kind), payload, вариант="diff") is None, kind


def test_print_form_escapes_data_and_never_leaks_markup():
    payload = {"lines": [{"name": "<script>alert(1)</script>", "amount": 10}]}
    row = print_row()
    row.counterparty_name = "ООО «Рога & Копыта»"
    form = store_document_print.печатная_форма(row, payload)
    assert "<script>alert(1)</script>" not in form
    assert "&lt;script&gt;" in form
    assert "Рога &amp; Копыта" in form


def test_receipt_with_services_is_blocked_until_bp_can_take_them():
    """Услуги ПТУ приёмник БП не переносит — документ не уезжает молча.

    Иначе в БП попадёт поступление на сумму товаров, а СуммаДокумента придёт с
    услугами: расхождение обнаружится сверкой уже после проведения.
    """
    receipt = SimpleNamespace(
        total_amount=Decimal("240.00"), vat_amount=Decimal("40.00"),
        evidence={"currency": "RUB", "vat_included": True, "invoice_kind": "УПД",
                  "invoice_number": "УПД-1", "invoice_date": "2026-08-08"},
    )
    goods = [{"qty_expected": 2, "qty_fact": 2, "price": 120, "amount": 240,
              "vat_amount": 40, "vat_rate": "20%"}]

    errors: list[str] = []
    store_receipt_accounting._strict_document_values(receipt, goods, [], errors)
    assert errors == [], "чистая товарная приёмка не должна блокироваться"

    receipt.total_amount = Decimal("340.00")
    receipt.vat_amount = Decimal("56.67")
    service = [{"amount": 100, "vat_amount": 16.67, "vat_rate": "20%", "into_cost": True}]
    with_services: list[str] = []
    store_receipt_accounting._strict_document_values(
        receipt, goods, service, with_services)
    assert any("Поступление доп. расходов" in item for item in with_services)


class VerifySession:
    """Сессия для проверки подтверждения карточки: только db.get."""

    def __init__(self, company=None, membership=None):
        self.company = company
        self.membership = membership

    async def get(self, model, key):
        if model.__name__ == "Company":
            return self.company
        if model.__name__ == "UserCompany":
            return self.membership
        return None


@pytest.mark.asyncio
async def test_supplier_becomes_canonical_only_by_network_role_and_with_requisites():
    company_id = uuid.uuid4()
    company = SimpleNamespace(id=company_id, slug="gig")
    station_admin = SimpleNamespace(
        id=uuid.uuid4(), is_superadmin=False,
    )
    station_membership = SimpleNamespace(business_grants=[
        {"role": "station_administrator", "scope_type": "station", "scope_id": 208},
    ])
    merchandiser_membership = SimpleNamespace(business_grants=[
        {"role": "network_merchandiser", "scope_type": "network", "scope_id": "gig"},
    ])
    requisites = {"inn": "7701234567", "kpp": "770101001", "name": "ООО «Поставщик»"}

    with pytest.raises(Exception) as denied:
        await references_router._assert_can_verify_counterparty(
            VerifySession(company, station_membership), station_admin, company_id,
            **requisites)
    assert getattr(denied.value, "status_code", None) == 403

    # товаровед сети — можно
    await references_router._assert_can_verify_counterparty(
        VerifySession(company, merchandiser_membership), station_admin, company_id,
        **requisites)
    # суперадминистратор — можно и без grants
    await references_router._assert_can_verify_counterparty(
        VerifySession(company, None),
        SimpleNamespace(id=uuid.uuid4(), is_superadmin=True), company_id, **requisites)

    for broken, reason in (
        ({**requisites, "inn": ""}, "ИНН"),
        ({**requisites, "inn": "77012345"}, "ИНН"),
        ({**requisites, "name": "  "}, "наименование"),
        ({**requisites, "kpp": None}, "КПП"),
    ):
        with pytest.raises(Exception) as invalid:
            await references_router._assert_can_verify_counterparty(
                VerifySession(company, merchandiser_membership), station_admin,
                company_id, **broken)
        assert getattr(invalid.value, "status_code", None) == 400, reason

    # у ИП КПП не существует — карточка обязана подтверждаться без него
    await references_router._assert_can_verify_counterparty(
        VerifySession(company, merchandiser_membership), station_admin, company_id,
        inn="770123456789", kpp=None, name="ИП Морозов")


def edge_sale_packet(*, packet_uuid, internal_shift, received_at, amount):
    """Копия смены: агент пересобирает пакет, ИсточникUUID при этом другой."""
    return SimpleNamespace(
        packet_uuid=packet_uuid, station_id=208, received_at=received_at,
        payload={
            "Смена": {"НомерСменыВнутр": internal_shift, "НомерСмены": "217"},
            "Документы": [{
                "Тип": "retail_sale_sidegoods",
                "ИсточникUUID": str(uuid.uuid4()),
                "Товары": [{"scope": "store", "Номенклатура": str(uuid.uuid4()),
                            "Наименование": "Кофе", "Количество": 1,
                            "Сумма": amount, "СтавкаНДС": "БезНДС"}],
            }],
        },
    )


@pytest.mark.asyncio
async def test_edge_packet_copies_of_one_shift_project_as_single_document():
    company_id = uuid.uuid4()
    base = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    copies = [
        edge_sale_packet(packet_uuid=str(uuid.uuid4()), internal_shift="7046",
                         received_at=base, amount=1000),
        edge_sale_packet(packet_uuid=str(uuid.uuid4()), internal_shift="7046",
                         received_at=base.replace(hour=21), amount=1200),
        edge_sale_packet(packet_uuid=str(uuid.uuid4()), internal_shift="7051",
                         received_at=base, amount=300),
    ]
    result = await store_documents._edge_adapter(
        Session({EdgePacket: copies}), company_id)
    sales = [row for row in result if row.document_kind == "retail_sale_sidegoods"]
    assert len(sales) == 2, "копии одной смены обязаны схлопнуться в один документ"
    assert sum(row.amount for row in sales) == Decimal("1500.00")
    latest = next(row for row in sales
                  if row.header["packet_uuid"] == copies[1].packet_uuid)
    assert latest.amount == Decimal("1200.00"), "остаётся самая свежая доставка"

    # служебные пакеты приходят с внутренним номером "0" — они не один документ
    service = [
        edge_sale_packet(packet_uuid=str(uuid.uuid4()), internal_shift="0",
                         received_at=base, amount=10),
        edge_sale_packet(packet_uuid=str(uuid.uuid4()), internal_shift="0",
                         received_at=base, amount=20),
    ]
    assert len(await store_documents._edge_adapter(
        Session({EdgePacket: service}), company_id)) == 2


@pytest.mark.asyncio
async def test_edge_packet_never_projects_fiscal_receipt_or_store_shift():
    company_id = uuid.uuid4()
    packet = SimpleNamespace(
        packet_uuid=str(uuid.uuid4()), station_id=208,
        received_at=datetime.now(timezone.utc),
        payload={"Документы": [
            {"Тип": "store_shift", "Номер": "7046", "СтатусБухгалтерии": "pending"},
            {"Тип": "fiscal_receipt", "Номер": "1"},
        ]},
    )
    assert await store_documents._edge_adapter(
        Session({EdgePacket: packet and [packet]}), company_id) == []


@pytest.mark.asyncio
async def test_every_station_document_kind_keeps_its_identity_fields():
    """Каждый вид, который станция реально отправляет, доезжает целиком.

    Проверяются ровно те реквизиты, по которым документ узнают в реестре:
    вид, номер, дата, станция, контрагент, автор и сумма товарной части.
    """
    company_id = uuid.uuid4()
    goods = [{"scope": "store", "Номенклатура": "item-1", "Наименование": "Кофе",
              "Количество": 2, "Сумма": 240, "СтавкаНДС": "20%"}]
    kinds = ("purchase", "transfer", "inventory", "gain", "writeoff",
             "return_purchase", "return_sale", "production_release", "recipe",
             "retail_sale_sidegoods")
    packets = [SimpleNamespace(
        packet_uuid=f"p-{kind}", station_id=208,
        received_at=datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc),
        payload={"Смена": {"НомерСменыВнутр": "7046"}, "Документы": [{
            "Тип": kind, "Номер": f"№{kind}", "Дата": "2026-08-08T10:00:00+03:00",
            "Автор": "Жукова", "Контрагент": "ООО «Поставщик»",
            "ИННКонтрагента": "7701234567", "Склад": "Зал",
            "Товары": goods,
        }]},
    ) for kind in kinds]
    result = await store_documents._edge_adapter(
        Session({EdgePacket: packets}), company_id)

    assert {row.document_kind for row in result} == set(kinds), "вид потерян по дороге"
    for row in result:
        assert row.station_id == 208
        assert row.number == f"№{row.document_kind}"
        assert row.document_at.date() == date(2026, 8, 8)
        assert row.author == "Жукова", f"{row.document_kind}: потерян автор"
        assert row.counterparty_name == "ООО «Поставщик»"
        assert row.counterparty_inn == "7701234567"
        assert row.header["warehouse"] == "Зал"
        assert row.amount == Decimal("240.00"), f"{row.document_kind}: сумма искажена"
        assert row.lines and row.lines[0].section == "goods"
        assert row.projection_source == "edge"
        assert row.raw_payload_available is True
        # НДС обязателен только там, где документ денежный
        if row.document_kind in store_documents.EDGE_VAT_KINDS:
            assert row.vat_amount == Decimal("40.00"), row.document_kind
        assert row.accounting_status != "not_applicable"


def test_station_line_classes_are_understood_in_both_alphabets():
    """Станция помечает строки и по-русски, и латиницей.

    Непонятый класс уводил документ в карантин целиком: продажи смены
    показывали нулевую сумму, хотя строки были размечены.
    """
    for значение in ("Сопутка", "товар", "store", "sidegoods"):
        assert store_documents._sku_scope(значение) == "store", значение
    for значение in ("Общепит", "блюдо", "dish", "ingredient", "food"):
        assert store_documents._sku_scope(значение) == "food", значение
    for значение in ("Топливо", "fuel", "ГСМ"):
        assert store_documents._sku_scope(значение) == "fuel", значение
    assert store_documents._sku_scope("выдумка") is None


def test_retail_sale_lines_with_known_item_are_goods_not_quarantine():
    """Отчёт продаж магазина товарный по построению: топливо в него не кладут."""
    продажа = {
        "Тип": "retail_sale_sidegoods",
        "Товары": [
            {"Номенклатура": "u-1", "Наименование": "Кофе", "Количество": 1,
             "Сумма": 120, "СтавкаНДС": "20%", "КлассSKU": "Общепит"},
            {"Номенклатура": "u-2", "Наименование": "Вода", "Количество": 1,
             "Сумма": 60, "СтавкаНДС": "20%"},
            {"Номенклатура": "u-3", "Наименование": "Булочка", "Количество": 1,
             "Сумма": 40, "СтавкаНДС": "20%", "ЭтоБлюдо": True},
        ],
    }
    итог = store_documents.sanitize_edge_document(продажа, trusted_station_packet=True)
    assert итог["quarantined"] is False
    assert итог["amount"] == Decimal("220.00")
    assert len(итог["lines"]) == 3

    # топливная строка по-прежнему не попадает в сумму магазина
    с_топливом = {**продажа, "Товары": [*продажа["Товары"],
                                        {"Номенклатура": "f-1", "Наименование": "АИ-95",
                                         "Количество": 20, "Сумма": 1300, "IsFuel": True}]}
    смешанный = store_documents.sanitize_edge_document(
        с_топливом, trusted_station_packet=True)
    assert смешанный["amount"] == Decimal("220.00")
    assert смешанный["fuel_lines"] == 1

    # строка без опознанной номенклатуры всё так же уводит документ в карантин
    безымянная = {**продажа, "Товары": [*продажа["Товары"],
                                        {"Наименование": "неизвестно", "Сумма": 999}]}
    assert store_documents.sanitize_edge_document(
        безымянная, trusted_station_packet=True)["quarantined"] is True


@pytest.mark.asyncio
async def test_packet_purchase_and_receipt_are_one_document_not_two():
    """Накладная приезжает пакетом и разворачивается в реестр приёмок.

    Это один документ: без связи по source_uuid он стоял в реестре дважды, и
    копия из пакета показывала нулевую сумму — строки в ней ещё не разобраны.
    """
    company_id = uuid.uuid4()
    source_uuid = str(uuid.uuid4())
    receipt_id = uuid.uuid4()
    receipt = SimpleNamespace(
        id=receipt_id, company_id=company_id, station_id=208, number="208000000112",
        doc_date=datetime(2026, 6, 11, tzinfo=timezone.utc), source_uuid=source_uuid,
        supplier="ООО «Поставщик»", supplier_snapshot={"name": "ООО «Поставщик»", "inn": "7701"},
        organization_id=None, warehouse_id=None, incoming_number="УПД-1",
        incoming_date=None, signature_status="signed", delivery_scheme="supplier_to_station",
        status="accepted", accounting_status="ready", accounting_revision=1, version=1,
        content_hash=None, total_amount=Decimal("22304.50"), vat_amount=Decimal("3717.42"),
        author="Жукова", lines=[{"line_id": "l-1", "name": "Кофе", "qty_fact": 1}], services=[],
        # Реквизиты, которые реестр показывает бухгалтерии рядом с суммой:
        # договор, организация, склад приёмки.
        contract_snapshot={"name": "Договор поставки № 12"},
        organization_snapshot={"name": "ООО «ГАЗИНВЕСТГРУПП»"},
        warehouse_snapshot={"name": "АЗС №208, Торговый зал"},
        receiving_warehouse="АЗС №208, Торговый зал",
    )
    packet = SimpleNamespace(
        packet_uuid=str(uuid.uuid4()), station_id=208,
        received_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        payload={"Документы": [{
            "Тип": "purchase", "ИсточникUUID": source_uuid,
            "ИдентификаторДокумента": str(uuid.uuid4()), "Номер": "208000000112",
            "Товары": [{"Наименование": "Кофе", "Количество": 1}],
        }]},
    )
    session = Session({EdgePacket: [packet], StoreReceipt: [receipt],
                       StoreReceiptStockMovement: []})
    из_пакета = await store_documents._edge_adapter(session, company_id)
    из_реестра = await store_documents._receipt_adapter(session, company_id)
    assert len(из_пакета) == 1 and len(из_реестра) == 1
    assert из_пакета[0].document_id == receipt_id, (
        "накладная из пакета и приёмка обязаны быть одним документом")
    # запись пакета остаётся отдельным свидетельством, но реестр показывает
    # приёмку: у неё выше приоритет и настоящая сумма
    assert из_реестра[0].priority > из_пакета[0].priority
    assert из_реестра[0].amount == Decimal("22304.50")


@pytest.mark.asyncio
async def test_edge_documents_without_number_dedupe_by_body_not_by_packet():
    company_id = uuid.uuid4()
    body = {"Тип": "writeoff", "Товары": [
        {"scope": "store", "Номенклатура": "item-1", "Количество": 1, "Сумма": 90}]}
    base = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    packets = [
        SimpleNamespace(packet_uuid="p-1", station_id=208, received_at=base,
                        payload={"Документы": [dict(body)]}),
        SimpleNamespace(packet_uuid="p-2", station_id=208,
                        received_at=base.replace(hour=21),
                        payload={"Документы": [dict(body)]}),
        SimpleNamespace(packet_uuid="p-3", station_id=209, received_at=base,
                        payload={"Документы": [dict(body)]}),
    ]
    result = await store_documents._edge_adapter(
        Session({EdgePacket: packets}), company_id)
    assert len(result) == 2, "копия тела схлопывается, чужая станция — нет"
    assert {row.station_id for row in result} == {208, 209}


class SyncSession:
    """Сессия для сверки документов: помнит, что её просили сделать."""

    def __init__(self, собран=None):
        self.собран = собран
        self.rolled_back = False

    async def execute(self, statement, _parameters=None):
        return ListResult([self.собран])

    async def rollback(self):
        self.rolled_back = True


@pytest.mark.asyncio
async def test_document_sync_skips_when_registry_is_fresh(monkeypatch):
    """Реестр собирается на всю компанию — не на каждый стук станции."""
    вызовы = []

    async def rebuild(*_args, **_kwargs):
        вызовы.append("rebuild")
        return {"records": 1}

    monkeypatch.setattr(store_document_sync, "rebuild_store_document_projection", rebuild)
    свежий = datetime.now(timezone.utc)
    итог = await store_document_sync.сверить_документы(
        SyncSession(свежий), uuid.uuid4(), 208)
    assert вызовы == []
    assert итог["rebuilt"] is False and "свежий" in итог["detail"]


@pytest.mark.asyncio
async def test_document_sync_never_breaks_the_exchange(monkeypatch):
    """Сверка не имеет права уронить обмен: станция потеряла бы задания."""

    async def rebuild(*_args, **_kwargs):
        raise RuntimeError("база недоступна")

    monkeypatch.setattr(store_document_sync, "rebuild_store_document_projection", rebuild)
    session = SyncSession(None)
    итог = await store_document_sync.сверить_документы(session, uuid.uuid4(), 208)
    assert итог["rebuilt"] is False
    assert "не собран" in итог["detail"]
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_document_sync_queues_snapshot_after_rebuild(monkeypatch):
    """Собрали реестр — сразу кладём станции свежий снимок заголовков."""

    async def rebuild(*_args, **_kwargs):
        return {"records": 1313}

    async def queue(_db, _company_id, station_id):
        assert station_id == 208
        return SimpleNamespace(payload={"headers": [{"kind": "purchase"}] * 116}), True

    monkeypatch.setattr(store_document_sync, "rebuild_store_document_projection", rebuild)
    monkeypatch.setattr(store_document_sync, "queue_onec_document_snapshot", queue)
    итог = await store_document_sync.сверить_документы(
        SyncSession(None), uuid.uuid4(), 208)
    assert итог["rebuilt"] is True and итог["snapshot"] is True
    assert итог["headers"] == 116


def test_exchange_with_station_triggers_document_sync():
    """Сверка живёт в обмене, а не в отдельном планировщике."""
    source = inspect.getsource(edge_router.downlink)
    assert "сверить_документы" in source
