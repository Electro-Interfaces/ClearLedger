import inspect
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.database import STORE_RECEIPT_MIGRATION_DDL
from app.routers import store_router
from app.routers.store_router import (
    ReceiptAccess,
    ReceiptIn,
    ReceiptScanIn,
    _receipt_downlink_payload,
    _receipt_grant_scope,
    _receipt_list_scope,
    _recalc,
    _require_receipt_canonical,
    _require_receipt_station,
)
from app.services import store_receipts
from app.services import store_costs, store_reports


def test_receipt_lines_reject_negative_quantity_and_price():
    base = {"name": "Вода", "qty_expected": 1, "qty_fact": 1, "price": 10}
    for field in ("qty_expected", "qty_fact", "price"):
        line = {**base, field: -1}
        with pytest.raises(store_receipts.ReceiptValidationError):
            store_receipts.normalize_lines([line])


def test_update_contract_distinguishes_omitted_fields_and_scan_uses_delta():
    body = ReceiptIn(supplier="Снимок")
    assert body.model_fields_set == {"supplier"}
    assert body.lines is None
    scan = ReceiptScanIn(barcode="4600000000007", delta=1)
    assert scan.barcode == "4600000000007"
    assert scan.delta == 1
    assert scan.lines is None


def test_blank_receipt_draft_is_allowed_but_send_requires_lines():
    assert _recalc([], [], require_lines=False) == (0, 0)
    with pytest.raises(HTTPException, match="нет позиций"):
        _recalc([], [])


@pytest.mark.asyncio
async def test_create_receipt_route_allows_blank_draft(monkeypatch):
    class DB:
        def __init__(self):
            self.added = []

        def add(self, row):
            self.added.append(row)

        async def commit(self):
            pass

        async def refresh(self, _row):
            pass

    company_id = uuid.uuid4()

    async def receipt_access(_user, _db):
        return ReceiptAccess(company_id, False, frozenset({208}))

    monkeypatch.setattr(store_router, "_receipt_access", receipt_access)
    db = DB()
    result = await store_router.create_receipt(
        ReceiptIn(
            station_id=208,
            delivery_scheme="supplier_to_station",
            signing_mode="office_director",
            signature_status="pending",
            lines=[],
        ),
        user=SimpleNamespace(id=uuid.uuid4()),
        db=db,
    )

    assert len(db.added) == 1
    assert result["status"] == "draft"
    assert result["station_id"] == 208
    assert result["supplier_id"] is None
    assert result["contract_id"] is None
    assert result["incoming_number"] is None
    assert result["lines"] == []
    assert result["total_amount"] == 0


def test_business_key_is_stable_and_requires_full_basis():
    at = datetime(2026, 8, 9, tzinfo=timezone.utc)
    assert store_receipts.dedup_key(" ООО  Ромашка ", " А-1 ", at) == (
        store_receipts.dedup_key("ооо ромашка", "а-1", "2026-08-09T12:00:00+03:00")
    )
    assert store_receipts.dedup_key("Ромашка", None, at) is None
    supplier_id = uuid.uuid4()
    assert store_receipts.receipt_dedup_key(supplier_id, "Старое имя", "A-1", at) == (
        store_receipts.receipt_dedup_key(supplier_id, "Новое имя", "A-1", at)
    )


def test_receipt_rbac_is_additive_and_operator_has_no_admin_scope():
    grants = [
        {"role": "station_administrator", "scope_type": "station", "scope_id": "208"},
        {"role": "network_merchandiser", "scope_type": "network", "scope_id": "gig"},
    ]
    assert _receipt_grant_scope(
        is_superadmin=False, grants=grants, network_id="gig") == (True, frozenset({208}))
    assert _receipt_grant_scope(
        is_superadmin=False, grants=[], network_id="gig") == (False, frozenset())
    assert _receipt_grant_scope(
        is_superadmin=True, grants=[], network_id="gig") == (True, frozenset())
    station_only = ReceiptAccess(uuid.uuid4(), False, frozenset({208, 209}))
    _require_receipt_station(station_only, 208)
    with pytest.raises(HTTPException) as central:
        _require_receipt_station(station_only, None)
    assert central.value.status_code == 403
    with pytest.raises(HTTPException) as foreign:
        _require_receipt_station(station_only, 210)
    assert foreign.value.status_code == 403
    assert _receipt_list_scope(station_only, set()) == ({208, 209}, False)
    network = ReceiptAccess(uuid.uuid4(), True, frozenset())
    assert _receipt_list_scope(network, {208}) == ({208}, True)


def test_bp_package_checks_station_before_building_sensitive_payload():
    for endpoint in (
        store_router.store_bp_package,
        store_router.store_bp_package_emit,
        store_router.store_bp_package_verify,
    ):
        source = inspect.getsource(endpoint)
        assert source.index("resolve_shift_station") < source.index("_require_receipt_station")
        if "build_shift_package" in source:
            assert source.index("_require_receipt_station") < source.index("build_shift_package")


def test_draft_can_keep_supplier_snapshot_but_accept_requires_both_canonical_ids():
    pending = SimpleNamespace(supplier="ООО Новый", contract="Д-1",
                              supplier_id=None, contract_id=None,
                              organization_id=None, warehouse_id=None)
    with pytest.raises(HTTPException, match="поставщика, договор, организацию и склад"):
        _require_receipt_canonical(pending)
    pending.supplier_id = uuid.uuid4()
    with pytest.raises(HTTPException):
        _require_receipt_canonical(pending)
    pending.contract_id = uuid.uuid4()
    pending.organization_id = uuid.uuid4()
    pending.warehouse_id = uuid.uuid4()
    _require_receipt_canonical(pending)


def test_distribution_identity_is_order_independent_and_request_specific():
    receipt_id = uuid.uuid4()
    one = store_receipts.allocation_identity(
        receipt_id, 208, [{"line_index": 1, "qty": 2}, {"line_index": 0, "qty": 1}])
    two = store_receipts.allocation_identity(
        receipt_id, 208, [{"line_index": 0, "qty": 1}, {"line_index": 1, "qty": 2}])
    other = store_receipts.allocation_identity(
        receipt_id, 209, [{"line_index": 0, "qty": 1}, {"line_index": 1, "qty": 2}])
    assert one == two
    assert one != other


def test_expected_receipt_payload_keeps_accounting_evidence_roundtrip():
    row = SimpleNamespace(
        id=uuid.uuid4(), number="П-208-1", supplier="ООО Поставщик",
        supplier_id=uuid.uuid4(), contract="Д-1", contract_id=uuid.uuid4(),
        organization_id=uuid.uuid4(), warehouse_id=uuid.uuid4(),
        incoming_number="УПД-7", incoming_date=datetime(2026, 8, 8, tzinfo=timezone.utc),
        doc_date=datetime(2026, 8, 9, tzinfo=timezone.utc), services=[{
            "name": "Доставка", "amount": 100, "vat_rate": "НДС22",
            "vat_amount": 18.03, "into_cost": True,
        }],
        evidence={"purpose": "Магазин", "invoice_kind": "УПД",
                  "invoice_number": "СФ-7", "invoice_date": "2026-08-08",
                  "source_kind": "supplier", "purchased_by": "Иванов",
                  "payment_kind": "bank", "place": "20800001"},
        comment="Оригинал у администратора", delivery_scheme="supplier_to_station",
        receiving_warehouse=None, signing_mode="office_director", signer_name="Петров",
        mchd_guid=None, mchd_registry=None, mchd_valid_until=None,
        signature_status="signed", signature_ref="sig-1",
        signed_at=datetime(2026, 8, 9, tzinfo=timezone.utc), origin="center",
        lines=[{
            "nomenclature_ref": str(uuid.uuid4()), "name": "Вода", "barcode": "4600000000007",
            "qty_expected": 2, "qty_fact": 0, "price": 50, "vat_rate": "НДС22",
            "unit": "шт", "pack_factor": 6, "purpose": "Магазин", "series": "A",
            "expiry": "2027-01-01", "retail_price": 80, "markup": 60,
            "upd_codes": ["mark-1"], "mark_codes": [], "pack_codes": [],
            "requires_mark": True,
        }],
    )
    payload = _receipt_downlink_payload(row)
    assert payload["document_id"] == str(row.id)
    assert payload["supplier_id"] == str(row.supplier_id)
    assert payload["contract_id"] == str(row.contract_id)
    assert payload["services"] == [{
        "line_id": "",
        "key": "", "name": "Доставка", "sum": 100.0,
        "vat_rate": "НДС22", "into_cost": True,
    }]
    assert payload["purchased_by"] == "Иванов"
    assert payload["payment_kind"] == "bank"
    assert payload["comment"] == row.comment
    assert payload["lines"][0] == {
        "line_id": "",
        "item_uuid": row.lines[0]["nomenclature_ref"], "name": "Вода",
        "barcode": "4600000000007", "qty_expected": 2.0, "price": 50.0,
        "vat_rate": "НДС22", "unit": "шт", "pack_factor": 6.0,
        "purpose": "Магазин", "series": "A", "expiry": "2027-01-01",
        "retail_price": 80.0, "markup": 60.0, "mark_codes": ["mark-1"],
        "requires_mark": True,
    }


def test_existing_database_migration_is_idempotent_by_construction():
    statements = "\n".join(STORE_RECEIPT_MIGRATION_DDL)
    assert "ADD COLUMN IF NOT EXISTS services" in statements
    assert "ADD COLUMN IF NOT EXISTS supplier_id" in statements
    assert "ADD COLUMN IF NOT EXISTS organization_id" in statements
    assert "ADD COLUMN IF NOT EXISTS warehouse_id" in statements
    assert "store receipt stock movements are append-only" in statements
    assert "CREATE TABLE IF NOT EXISTS store_receipt_stock_movements" in statements
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_edge_downlink_company_idempotency" in statements
    assert "DROP CONSTRAINT IF EXISTS store_receipts_source_uuid_key" in statements


@pytest.mark.asyncio
async def test_acceptance_ledger_is_idempotent_for_edge_and_center():
    class Result:
        def __init__(self, values):
            self.values = values

        def scalars(self):
            return self

        def all(self):
            return self.values

    class DB:
        def __init__(self):
            self.existing = []
            self.added = []

        async def execute(self, _query):
            return Result(self.existing)

        def add(self, movement):
            self.added.append(movement)

    db = DB()
    receipt = SimpleNamespace(
        id=uuid.uuid4(), company_id=uuid.uuid4(), station_id=208,
        delivery_scheme="supplier_to_station", receiving_warehouse=None,
        warehouse_id=uuid.uuid4(),
        evidence={"warehouse_id": "warehouse-208"},
        lines=[{"line_id": str(uuid.uuid4()), "name": "Вода", "nomenclature_ref": str(uuid.uuid4()),
                "barcode": "4600000000007", "qty_fact": 2, "price": 50}],
    )
    await store_receipts.record_acceptance(db, receipt)
    assert len(db.added) == 1
    assert float(db.added[0].quantity) == 2
    assert db.added[0].station_id == 208
    db.existing = [db.added[0].idempotency_key]
    await store_receipts.record_acceptance(db, receipt)
    assert len(db.added) == 1


@pytest.mark.asyncio
async def test_costs_and_document_report_use_only_accepted_and_deduplicate_edge():
    class Result:
        def mappings(self):
            return self

        def all(self):
            return []

    class DB:
        def __init__(self):
            self.queries = []

        async def execute(self, query, _params=None):
            self.queries.append(str(query))
            return Result()

    db = DB()
    await store_costs.ориентиры(db, uuid.uuid4())
    await store_reports.documents(
        db, uuid.uuid4(), "2026-08-01", "2026-08-09")
    sql = "\n".join(db.queries)
    assert "status = 'accepted'" in sql
    assert "r.id::text = d->>'document_id'" in sql
    assert "r.source_uuid = d->>'ИсточникUUID'" in sql


def test_duplicate_audit_only_proposes_manual_review():
    source = str(uuid.uuid4())
    rows = [
        SimpleNamespace(id=uuid.uuid4(), status="expected", source_uuid=source,
                        dedup_key=None, evidence={}),
        SimpleNamespace(id=uuid.uuid4(), status="accepted", source_uuid=source,
                        dedup_key=None, evidence={}),
    ]
    plan = store_receipts.duplicate_plan(rows)
    assert len(plan) == 1
    assert plan[0]["action"] == "manual_review"
    assert plan[0]["suggested_keep_id"] in plan[0]["receipt_ids"]
