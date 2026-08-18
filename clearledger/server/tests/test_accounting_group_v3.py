from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import pytest

from app.models import (
    AccountingBusinessGroup,
    AccountingClaimRequest,
    AccountingSourceDecision,
    AccountingSourcePolicy,
    BusinessShift,
    BusinessShiftAlias,
    CutoverApproval,
    CutoverManifest,
    DataEntry,
    ExportPacket,
)
from app.services.accounting_egress import AccountingEgressGuard
from app.services.accounting_contract_v3 import canonical_hash
from app.services.accounting_group_v3 import (
    AccountingGroupInvariantError,
    build_accounting_business_payload,
)
from app.services.accounting_outbox import AccountingOutboxService
from app.services.accounting_payment import (
    AccountingPaymentMappingBlocked,
    map_accounting_payment,
)
from app.services.bp_export import BpPackageEmitter
from app.services.cutover_policy import (
    canonical_manifest_hash,
    manifest_payload_for_policy,
)


def _line(
    *, returned: bool = False, source_document: str = "return-42",
    source_line: str = "return-line-1",
) -> dict:
    result = {
        "Номенклатура": "dish-coffee",
        "КлассSKU": "Общепит",
        "Количество": 1,
        "Сумма": 122,
        "СуммаНДС": 22,
        "СтавкаНДС": "НДС22",
        "Возврат": returned,
    }
    if returned:
        result["ИсточникДокументаUUID"] = source_document
        result["ИсточникСтрокиUUID"] = source_line
    return result


def _shift_completeness() -> dict:
    counts = {
        "shift_closure": 1, "cheques": 2, "payments": 1, "returns": 1,
        "exact_ttk": 1, "production_snapshot": 1, "cost_snapshot": 1,
    }
    return {
        "version": "1",
        "provisional_business_shift_id": "edge:208:42",
        "status": "complete",
        "sources": [{
            "type": kind, "required": True, "status": "ready",
            "count": counts[kind], "source_hash": f"{number:x}" * 64,
        } for number, kind in enumerate((
            "shift_closure", "cheques", "payments", "returns", "exact_ttk",
            "production_snapshot", "cost_snapshot",
        ), 1)],
    }


def _cost_evidence() -> dict:
    return {
        "version": "1",
        "provisional_business_shift_id": "edge:208:42",
        "company_id": "company-test",
        "business_date": "2026-08-17",
        "station_id": 208,
        "warehouse": "warehouse-208",
        "as_of": "2026-08-17T17:00:00Z",
        "opening_snapshot_id": "opening-208-1",
        "cost_snapshot_revision": 1,
        "ledger_version_hash": "a" * 64,
        "production": [{
            "production_source_uuid": "production-42",
            "dish_uuid": "dish-coffee",
            "quantity_millis": 1000,
        }],
        "ingredients": [{
            "production_source_uuid": "production-42",
            "dish_uuid": "dish-coffee",
            "item_uuid": "bean",
            "required_quantity_millis": 100,
            "unit_cost_micros": 200000000,
            "required_amount_micros": 20000000,
            "coverage_basis_points": 10000,
            "status": "known",
            "provenance": [{
                "source_kind": "opening_snapshot",
                "source_doc_uuid": "opening-208-1",
                "snapshot_id": "opening-208-1",
            }],
        }],
    }


def _raw_packet(payment_field: str = "ВидОплаты", payment: str = "Прочие") -> dict:
    evidence = _cost_evidence()
    completeness = _shift_completeness()
    next(row for row in completeness["sources"] if row["type"] == "cost_snapshot")[
        "source_hash"
    ] = canonical_hash(evidence)
    return {
        "ВерсияФормата": "2",
        "Источник": "Ledger Edge → Ledger",
        "ProvisionalBusinessShiftID": "edge:208:42",
        "ShiftCompleteness": completeness,
        "CostEvidence": evidence,
        "Смена": {
            "КодАЗС": "208",
            "СкладUUID": "warehouse-208",
            "НомерСменыВнутр": "edge-shift-42",
            "НомерСмены": "OSE-42",
            "Открытие": "2026-08-17T08:00:00+03:00",
            "Закрытие": "2026-08-17T20:00:00+03:00",
        },
        "НСИ": [
            {
                "Тип": "Номенклатура", "ИсточникUUID": "dish-coffee",
                "Наименование": "Кофе", "КлассSKU": "Общепит",
            },
            {
                "Тип": "Номенклатура", "ИсточникUUID": "bean",
                "Наименование": "Зерно", "КлассSKU": "Сопутка",
            },
        ],
        "Документы": [
            {
                "Тип": "recipe", "ИсточникUUID": "recipe-coffee-v4",
                "БлюдоUUID": "dish-coffee", "ВерсияТТК": 4,
                "ВерсияНабораТТК": "shift-42-bundle",
                "Ингредиенты": [{
                    "НоменклатураUUID": "bean", "Количество": 0.1,
                    "Единица": "кг",
                }],
            },
            {
                "Тип": "production_release", "ИсточникUUID": "production-42",
                "ВыпускБлюд": [{
                    "Номенклатура": "dish-coffee", "Количество": 1,
                    "Себестоимость": 20,
                }],
            },
            {
                "Тип": "ingredients_writeoff", "ИсточникUUID": "writeoff-42",
                "Товары": [{"Номенклатура": "bean", "Количество": 0.1}],
            },
            {
                "Тип": "retail_sale_sidegoods", "ИсточникUUID": "retail-42",
                "Товары": [_line()],
                "ВозвращенныеТовары": [_line(returned=True)],
                "Оплаты": [{payment_field: payment, "Сумма": 122}],
            },
            {
                "Тип": "return_sale", "ИсточникUUID": "return-42",
                "Товары": [_line(returned=True)],
            },
        ],
    }


def test_invariant_edge_and_onec_payments_use_one_fail_closed_mapper():
    edge = build_accounting_business_payload(_raw_packet("ВидОплаты", "Прочие"))
    onec = build_accounting_business_payload(
        _raw_packet("ФормаОплаты", "Банковская карта"),
    )

    assert edge["Документы"][2]["Содержимое"]["Оплаты"][0]["Вид"] == "Безнал"
    assert onec["Документы"][2]["Содержимое"]["Оплаты"][0]["Вид"] == "Безнал"
    assert map_accounting_payment("Наличные") == "Наличные"
    assert map_accounting_payment("PayTerm") == "Безнал"
    # На 208 касса пишет вид «Карты МПС» во множественном числе; маппер должен
    # покрывать обе формы, иначе весь ОРП смены блокируется (поймано 19.08).
    assert map_accounting_payment("Карты МПС") == "Безнал"
    assert map_accounting_payment("карта мпс") == "Безнал"
    assert map_accounting_payment("Прочие") == "Безнал"
    with pytest.raises(AccountingPaymentMappingBlocked) as error:
        map_accounting_payment("неизвестный QR-агрегатор")
    assert error.value.code == "blocked_mapping"


@pytest.mark.parametrize("mutation", ["missing_bundle", "duplicate"])
def test_invariant_exact_shift_bundle_ttk_is_required_and_unique(mutation):
    raw = _raw_packet()
    recipe = raw["Документы"][0]
    if mutation == "missing_bundle":
        recipe["ВерсияНабораТТК"] = ""
    else:
        raw["Документы"].insert(1, deepcopy(recipe))
        raw["Документы"][1]["ИсточникUUID"] = "recipe-coffee-v4-duplicate"

    with pytest.raises(AccountingGroupInvariantError, match="exact.*ТТК|ТТК.*exact"):
        build_accounting_business_payload(raw)


def test_invariant_return_sale_is_embedded_exactly_once():
    payload = build_accounting_business_payload(_raw_packet())
    retail = next(
        row for row in payload["Документы"]
        if row["Тип"] == "retail_sale_sidegoods"
    )
    embedded = next(row for row in payload["Документы"] if row["Тип"] == "return_sale")

    assert len(retail["Содержимое"]["Возвраты"]) == 1
    assert embedded["РольВГруппе"] == "embedded"
    assert embedded["Содержимое"] == {
        "ВстроеноВОРП": "retail-42", "КоличествоСтрок": 1,
    }
    assert [row["Тип"] for row in payload["ПолнотаГруппы"]["ОжидаемыеКомпоненты"]] == [
        "assembly", "retail", "disassembly",
    ]


def test_invariant_identical_value_returns_with_different_source_lines_are_both_kept():
    raw = _raw_packet()
    second = _line(
        returned=True, source_document="return-43", source_line="return-line-2",
    )
    raw["Документы"].append({
        "Тип": "return_sale", "ИсточникUUID": "return-43", "Товары": [second],
    })

    payload = build_accounting_business_payload(raw)
    retail = next(
        row for row in payload["Документы"]
        if row["Тип"] == "retail_sale_sidegoods"
    )

    assert len(retail["Содержимое"]["Возвраты"]) == 2
    assert {
        (row["ИсточникДокументаUUID"], row["ИсточникСтрокиUUID"])
        for row in retail["Содержимое"]["Возвраты"]
    } == {
        ("return-42", "return-line-1"),
        ("return-43", "return-line-2"),
    }


def test_invariant_ingredients_writeoff_is_absorbed_by_assembly():
    payload = build_accounting_business_payload(_raw_packet())
    writeoff = next(
        row for row in payload["Документы"]
        if row["Тип"] == "ingredients_writeoff"
    )

    assert writeoff["РольВГруппе"] == "absorbed"
    assert writeoff["Содержимое"] == {
        "ПоглощенКомпонентом": "assembly:retail-42:dish-coffee",
    }
    assert "ingredients_writeoff" not in {
        row["Тип"] for row in payload["ПолнотаГруппы"]["ОжидаемыеКомпоненты"]
    }


def test_invariant_each_dish_has_its_own_material_component():
    raw = _raw_packet()
    raw["НСИ"].append({
        "Тип": "Номенклатура", "ИсточникUUID": "dish-tea",
        "Наименование": "Чай", "КлассSKU": "Общепит",
    })
    recipe = deepcopy(raw["Документы"][0])
    recipe.update({"ИсточникUUID": "recipe-tea-v1", "БлюдоUUID": "dish-tea"})
    raw["Документы"].insert(1, recipe)
    production = next(row for row in raw["Документы"] if row["Тип"] == "production_release")
    production["ВыпускБлюд"].append({
        "Номенклатура": "dish-tea", "Количество": 1, "Себестоимость": 10,
    })
    retail = next(row for row in raw["Документы"] if row["Тип"] == "retail_sale_sidegoods")
    tea = {**_line(), "Номенклатура": "dish-tea"}
    retail["Товары"].append(tea)
    retail["ВозвращенныеТовары"].append({
        **tea,
        "Возврат": True,
        "ИсточникДокументаUUID": "return-tea",
        "ИсточникСтрокиUUID": "return-tea-line-1",
    })
    sources = {row["type"]: row for row in raw["ShiftCompleteness"]["sources"]}
    sources["exact_ttk"]["count"] = 2
    sources["production_snapshot"]["count"] = 2
    raw["CostEvidence"]["production"].append({
        "production_source_uuid": "production-42",
        "dish_uuid": "dish-tea",
        "quantity_millis": 1000,
    })
    raw["CostEvidence"]["ingredients"].append({
        "production_source_uuid": "production-42",
        "dish_uuid": "dish-tea",
        "item_uuid": "bean",
        "required_quantity_millis": 100,
        "unit_cost_micros": 100000000,
        "required_amount_micros": 10000000,
        "coverage_basis_points": 10000,
        "status": "known",
        "provenance": [{
            "source_kind": "opening_snapshot",
            "source_doc_uuid": "opening-208-1",
            "snapshot_id": "opening-208-1",
        }],
    })
    sources["cost_snapshot"]["count"] = 2
    sources["cost_snapshot"]["source_hash"] = canonical_hash(raw["CostEvidence"])

    payload = build_accounting_business_payload(raw)
    components = payload["ПолнотаГруппы"]["ОжидаемыеКомпоненты"]

    assert [(row["Тип"], row["ИсточникUUID"]) for row in components] == [
        ("assembly", "assembly:retail-42:dish-coffee"),
        ("assembly", "assembly:retail-42:dish-tea"),
        ("retail", "retail-42"),
        ("disassembly", "disassembly:retail-42:dish-coffee"),
        ("disassembly", "disassembly:retail-42:dish-tea"),
    ]


def test_invariant_return_only_dish_has_no_current_shift_assembly():
    raw = _raw_packet()
    retail = next(row for row in raw["Документы"] if row["Тип"] == "retail_sale_sidegoods")
    retail["Товары"] = []
    raw["Документы"] = [
        row for row in raw["Документы"] if row["Тип"] != "ingredients_writeoff"
    ]

    payload = build_accounting_business_payload(raw)
    components = payload["ПолнотаГруппы"]["ОжидаемыеКомпоненты"]

    assert [(row["Тип"], row["ИсточникUUID"]) for row in components] == [
        ("retail", "retail-42"),
        ("disassembly", "disassembly:retail-42:dish-coffee"),
    ]


def test_invariant_recipe_production_context_retail_order_is_unposted():
    payload = build_accounting_business_payload(_raw_packet())
    documents = payload["Документы"]

    assert payload["ТТК"][0]["БлюдоUUID"] == "dish-coffee"
    assert [row["Тип"] for row in documents] == [
        "production_release", "ingredients_writeoff",
        "retail_sale_sidegoods", "return_sale",
    ]
    assert documents[0]["РольВГруппе"] == "evidence"
    assert all(
        row["Содержимое"]["Проведен"] is False
        for row in documents if row["РольВГруппе"] in {"evidence", "materialized"}
    )


def test_invariant_cost_snapshot_is_transferred_exactly_from_edge_manifest():
    raw = _raw_packet()
    expected = next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )

    payload = build_accounting_business_payload(raw)
    actual = next(
        row for row in payload["ПолнотаГруппы"]["Источники"]
        if row["Тип"] == "cost_snapshot"
    )

    assert actual == {
        "Тип": "cost_snapshot", "Требуется": expected["required"],
        "Статус": expected["status"], "Количество": expected["count"],
        "SourceHash": expected["source_hash"],
    }


def test_invariant_cost_count_cannot_exceed_exact_cost_evidence():
    raw = _raw_packet()
    recipe = next(row for row in raw["Документы"] if row["Тип"] == "recipe")
    recipe["Ингредиенты"][0]["НоменклатураUUID"] = "semi-coffee-base"
    cost = next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )
    cost["count"] = 2

    with pytest.raises(AccountingGroupInvariantError, match="CostEvidence"):
        build_accounting_business_payload(raw)


def test_invariant_completeness_must_belong_to_same_provisional_shift():
    raw = _raw_packet()
    raw["ProvisionalBusinessShiftID"] = "edge:208:another-shift"

    with pytest.raises(AccountingGroupInvariantError, match="другой.*смене"):
        build_accounting_business_payload(raw)


@pytest.mark.parametrize("status", ["unknown", "partial"])
def test_invariant_unknown_or_partial_food_cost_fails_closed(status):
    raw = _raw_packet()
    cost = next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )
    cost["status"] = status
    cost["source_hash"] = None

    with pytest.raises(AccountingGroupInvariantError, match="cost_snapshot.*не готов"):
        build_accounting_business_payload(raw)


def test_invariant_food_without_cost_manifest_fails_closed():
    raw = _raw_packet()
    raw.pop("ShiftCompleteness")

    with pytest.raises(AccountingGroupInvariantError, match="cost_snapshot"):
        build_accounting_business_payload(raw)


def test_invariant_onec_food_accepts_only_explicit_cost_evidence():
    raw = _raw_packet()
    raw["Источник"] = "TradeLedger (Ledger)"
    raw.pop("ShiftCompleteness")
    raw.pop("CostEvidence")

    payload = build_accounting_business_payload(raw)
    cost = next(
        row for row in payload["ПолнотаГруппы"]["Источники"]
        if row["Тип"] == "cost_snapshot"
    )

    assert cost["Статус"] == "ready"
    assert cost["Количество"] == 1


def test_invariant_onec_sales_sum_cannot_replace_explicit_cost():
    raw = _raw_packet()
    raw["Источник"] = "TradeLedger (Ledger)"
    raw.pop("ShiftCompleteness")
    raw.pop("CostEvidence")
    production = next(
        row for row in raw["Документы"] if row["Тип"] == "production_release"
    )
    line = production["ВыпускБлюд"][0]
    line.pop("Себестоимость")
    line["Сумма"] = 122

    with pytest.raises(AccountingGroupInvariantError, match="exact Себестоимость 1С"):
        build_accounting_business_payload(raw)


def test_invariant_onec_unknown_zero_cannot_become_known_cost():
    raw = _raw_packet()
    raw["Источник"] = "TradeLedger (Ledger)"
    raw.pop("ShiftCompleteness")
    raw.pop("CostEvidence")
    production = next(
        row for row in raw["Документы"] if row["Тип"] == "production_release"
    )
    production["ВыпускБлюд"][0]["Себестоимость"] = 0

    with pytest.raises(AccountingGroupInvariantError, match="exact Себестоимость 1С"):
        build_accounting_business_payload(raw)


def test_invariant_edge_cost_comes_from_evidence_not_sales_sum():
    raw = _raw_packet()
    production = next(
        row for row in raw["Документы"] if row["Тип"] == "production_release"
    )
    line = production["ВыпускБлюд"][0]
    line.pop("Себестоимость")
    line["Сумма"] = 122

    payload = build_accounting_business_payload(raw)
    release = next(row for row in payload["Документы"] if row["Тип"] == "production_release")

    assert release["Содержимое"]["ВыпускБлюд"][0]["Себестоимость"] == "20.000000"


def test_invariant_cost_evidence_hash_and_production_binding_are_exact():
    raw = _raw_packet()
    raw["CostEvidence"]["ingredients"][0]["required_amount_micros"] += 1
    cost = next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )
    cost["source_hash"] = canonical_hash(raw["CostEvidence"])

    with pytest.raises(AccountingGroupInvariantError, match="не воспроизводится"):
        build_accounting_business_payload(raw)

    raw = _raw_packet()
    raw["CostEvidence"]["production"][0]["quantity_millis"] += 1
    cost = next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )
    cost["source_hash"] = canonical_hash(raw["CostEvidence"])
    with pytest.raises(AccountingGroupInvariantError, match="не совпадает с выпуском"):
        build_accounting_business_payload(raw)


@pytest.mark.parametrize("field", ["source_doc_uuid", "snapshot_id"])
def test_invariant_cost_opening_provenance_matches_exact_snapshot(field):
    raw = _raw_packet()
    provenance = raw["CostEvidence"]["ingredients"][0]["provenance"][0]
    provenance[field] = "other-opening-snapshot"
    cost = next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )
    cost["source_hash"] = canonical_hash(raw["CostEvidence"])

    with pytest.raises(
        AccountingGroupInvariantError,
        match="opening_snapshot provenance не совпадает",
    ):
        build_accounting_business_payload(raw)


def test_invariant_receipt_only_cost_provenance_is_valid_without_opening_entry():
    raw = _raw_packet()
    raw["CostEvidence"]["ingredients"][0]["provenance"] = [{
        "source_kind": "purchase",
        "source_doc_uuid": "receipt-42",
    }]
    cost = next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )
    cost["source_hash"] = canonical_hash(raw["CostEvidence"])

    payload = build_accounting_business_payload(raw)
    production = next(
        row for row in payload["Документы"]
        if row["Тип"] == "production_release"
    )

    assert production["Содержимое"]["ВыпускБлюд"][0]["Себестоимость"] == "20.000000"


def test_invariant_unexpanded_facts_block_v3_business_payload():
    raw = _raw_packet()
    raw["НеРазложено"] = [{"Тип": "return_sale", "Причина": "нет исходного чека"}]

    with pytest.raises(AccountingGroupInvariantError, match="неразложенные"):
        build_accounting_business_payload(raw)


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


class _DbBoundarySession:
    def __init__(self, policy, manifest, approvals, entries=()):
        self.policies = [policy]
        self.manifests = [manifest]
        self.approvals = list(approvals)
        self.aliases = []
        self.shifts = []
        self.groups = []
        self.decisions = []
        self.packets = []
        self.claims = []
        self.entries = list(entries)
        self.added = []

    async def execute(self, statement, parameters=None):
        if "pg_advisory_xact_lock" in str(statement):
            return _Result([])
        entity = statement.column_descriptions[0].get("entity")
        rows_by_entity = {
            AccountingSourcePolicy: self.policies,
            CutoverManifest: self.manifests,
            CutoverApproval: self.approvals,
            BusinessShiftAlias: self.aliases,
            BusinessShift: self.shifts,
            AccountingBusinessGroup: self.groups,
            AccountingSourceDecision: self.decisions,
            ExportPacket: self.packets,
            AccountingClaimRequest: self.claims,
            DataEntry: self.entries,
        }
        if entity not in rows_by_entity:
            raise AssertionError(f"unexpected DB-boundary statement: {statement}")
        return _Result(rows_by_entity[entity])

    def add(self, row):
        self.added.append(row)
        targets = (
            (AccountingSourcePolicy, self.policies),
            (CutoverManifest, self.manifests),
            (CutoverApproval, self.approvals),
            (BusinessShiftAlias, self.aliases),
            (BusinessShift, self.shifts),
            (AccountingBusinessGroup, self.groups),
            (AccountingSourceDecision, self.decisions),
            (ExportPacket, self.packets),
            (AccountingClaimRequest, self.claims),
        )
        for model, rows in targets:
            if isinstance(row, model):
                if row not in rows:
                    rows.append(row)
                return
        raise AssertionError(f"unexpected DB-boundary insert: {type(row)}")

    async def flush(self):
        pass


def _effective_policy_manifest(company_id: uuid.UUID, station_id: int):
    effective = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(days=1)
    policy = AccountingSourcePolicy(
        id=uuid.uuid4(), company_id=company_id, station_id=station_id,
        policy_group="sidegoods_foodservice", revision=1, state="effective",
        fact_cutover_business_date=effective.date(), station_timezone="Europe/Moscow",
        fact_origin_before="onec_legacy", fact_origin_after="edge",
        effective_from=effective, effective_to=None,
        transport_cutover_at=effective,
        transport_producer_before="legacy_epf",
        transport_producer="central_ledger", shadow_validation_enabled=True,
    )
    payload = manifest_payload_for_policy(policy)
    manifest_hash = canonical_manifest_hash(payload)
    manifest = CutoverManifest(
        id=uuid.uuid4(), policy_id=policy.id, company_id=company_id,
        station_id=station_id, policy_group=policy.policy_group,
        revision=policy.revision, state="effective", canonical_payload=payload,
        manifest_hash=manifest_hash, approvals=[],
        operational_cutover_at=effective - timedelta(minutes=5),
        accounting_transport_cutover_at=effective,
        late_arrival_until=None, arm_deadline=effective - timedelta(minutes=1),
        prepare_ack_hash=manifest_hash, arm_ack_hash=manifest_hash,
        armed_at=effective - timedelta(minutes=2), effective_at=effective,
    )
    approvals = [
        CutoverApproval(
            id=uuid.uuid4(), manifest_id=manifest.id, company_id=company_id,
            user_id=uuid.uuid4(), approved_at=effective - timedelta(minutes=3),
        ),
        CutoverApproval(
            id=uuid.uuid4(), manifest_id=manifest.id, company_id=company_id,
            user_id=uuid.uuid4(), approved_at=effective - timedelta(minutes=2),
        ),
    ]
    return policy, manifest, approvals


def _fact_candidate(source: str, day: date) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(), source=source,
        status="superseded" if source == "oneC" else "verified",
        source_id=f"{source}-shift-42",
        meta={"Смена": {
            "Смена": "shift-42", "КодАЗС": "208",
            "НомерСмены": "OSE-42", "ОСЭНомер": "OSE-42",
            "НомерСменыВнутр": "edge-shift-42",
            "Закрытие": f"{day.isoformat()}T20:00:00+03:00",
        }},
    )


@pytest.mark.parametrize(("business_day", "expected_source", "expected_origin"), [
    (date(2026, 8, 17), "oneC", "onec_legacy"),
    (date(2026, 8, 18), "edge", "edge"),
])
@pytest.mark.asyncio
async def test_invariant_emitter_selects_fact_winner_before_resolver_by_cutover(
    business_day, expected_source, expected_origin,
):
    company_id = uuid.uuid4()
    policy, manifest, approvals = _effective_policy_manifest(company_id, 208)
    policy.fact_cutover_business_date = date(2026, 8, 18)
    manifest.canonical_payload = manifest_payload_for_policy(policy)
    manifest.manifest_hash = canonical_manifest_hash(manifest.canonical_payload)
    session = _DbBoundarySession(policy, manifest, approvals)
    emitter = BpPackageEmitter(session, company_id)
    emitter._shift_candidates_cache["shift-42"] = [
        _fact_candidate("edge", business_day),
        _fact_candidate("oneC", business_day),
    ]

    context = await emitter.select_accounting_source(
        "shift-42", manifest.manifest_hash,
    )

    assert context["winner"].source == expected_source
    assert context["axes"].fact_origin == expected_origin
    assert [row["Algorithm"] for row in context["aliases"]] == (
        ["business-shift-common-alias-v1"]
        if expected_origin == "onec_legacy"
        else ["business-shift-alias-v1", "business-shift-common-alias-v1"]
    )
    assert len(context["loser_fact_ids"]) == 1
    assert session.shifts == []
    assert session.groups == []


@pytest.mark.parametrize(("business_day", "expected_source", "expected_origin"), [
    (date(2026, 8, 17), "oneC", "onec_legacy"),
    (date(2026, 8, 18), "edge", "edge"),
])
@pytest.mark.asyncio
async def test_route_station_lookup_preserves_all_candidates_until_policy_winner(
    business_day, expected_source, expected_origin,
):
    company_id = uuid.uuid4()
    policy, manifest, approvals = _effective_policy_manifest(company_id, 208)
    policy.fact_cutover_business_date = date(2026, 8, 18)
    manifest.canonical_payload = manifest_payload_for_policy(policy)
    manifest.manifest_hash = canonical_manifest_hash(manifest.canonical_payload)
    candidates = [
        _fact_candidate("edge", business_day),
        _fact_candidate("oneC", business_day),
    ]
    session = _DbBoundarySession(policy, manifest, approvals, candidates)
    emitter = BpPackageEmitter(session, company_id)

    station_id = await emitter.resolve_shift_station("shift-42")
    context = await emitter.select_accounting_source(
        "shift-42", manifest.manifest_hash,
    )

    assert station_id == 208
    assert len(emitter._shift_candidates_cache["shift-42"]) == 2
    assert context["winner"].source == expected_source
    assert context["axes"].fact_origin == expected_origin
    assert context["loser_fact_ids"] == [
        f"{'oneC' if expected_source == 'edge' else 'edge'}-shift-42",
    ]
    assert emitter._shift_targets["shift-42"] is context["winner"]


@pytest.mark.asyncio
async def test_invariant_business_date_conflict_is_recorded_needs_review():
    company_id = uuid.uuid4()
    policy, manifest, approvals = _effective_policy_manifest(company_id, 208)
    session = _DbBoundarySession(policy, manifest, approvals)
    emitter = BpPackageEmitter(session, company_id)
    candidate = _fact_candidate("edge", date(2026, 8, 18))
    candidate.meta["Смена"]["ДатаОСЭ"] = "2026-08-17"
    emitter._shift_candidates_cache["shift-42"] = [candidate]

    with pytest.raises(ValueError, match="BusinessDate требует проверки"):
        await emitter.prepare_accounting_packet(
            "shift-42", manifest.manifest_hash,
        )

    assert session.decisions[-1].status == "needs_review"
    assert session.decisions[-1].shadow_status == "blocked"
    assert session.shifts == []
    assert session.groups == []


@pytest.mark.asyncio
async def test_invariant_late_correction_preserves_existing_origin_and_group():
    company_id = uuid.uuid4()
    policy, manifest, approvals = _effective_policy_manifest(company_id, 208)
    policy.fact_cutover_business_date = date(2026, 8, 18)
    manifest.canonical_payload = manifest_payload_for_policy(policy)
    manifest.manifest_hash = canonical_manifest_hash(manifest.canonical_payload)
    shift = BusinessShift(
        id=uuid.uuid4(), company_id=company_id, company_key=str(company_id),
        station_id="208", business_date=date(2026, 8, 18), status="resolved",
    )
    group = AccountingBusinessGroup(
        id=uuid.uuid4(), company_id=company_id, business_shift_id=shift.id,
        business_key_hash="b" * 64, packet_uuid=uuid.uuid4(),
        current_revision=1, current_content_hash="a" * 64,
        current_packet_id=uuid.uuid4(), status="active",
    )
    current = ExportPacket(
        id=group.current_packet_id, company_id=company_id,
        kind="food_accounting_group", status="accepted", payload={},
        source_entry_ids=[], packet_uuid=group.packet_uuid, revision=1,
        content_hash="a" * 64, fact_origin="onec_legacy",
        transport_producer="central_ledger", accounting_group_id=group.id,
    )
    aliases = BpPackageEmitter._aliases(
        company_key=str(company_id), station_id="208",
        business_date="2026-08-18", ose="OSE-42",
        internal_shift_no="edge-shift-42", include_edge=True,
    )
    common = next(
        row for row in aliases
        if row["Algorithm"] == "business-shift-common-alias-v1"
    )
    stored_alias = BusinessShiftAlias(
        id=uuid.uuid4(), company_id=company_id, business_shift_id=shift.id,
        algorithm=common["Algorithm"], alias_hash=common["AliasHash"],
        attributes=common["Attributes"],
    )
    session = _DbBoundarySession(policy, manifest, approvals)
    session.shifts.append(shift)
    session.groups.append(group)
    session.aliases.append(stored_alias)
    session.packets.append(current)
    emitter = BpPackageEmitter(session, company_id)
    emitter._shift_candidates_cache["shift-42"] = [
        _fact_candidate("edge", date(2026, 8, 18)),
        _fact_candidate("oneC", date(2026, 8, 18)),
    ]
    raw = _raw_packet()
    raw["Источник"] = "TradeLedger (Ledger)"
    raw["Смена"]["Открытие"] = "2026-08-18T08:00:00+03:00"
    raw["Смена"]["Закрытие"] = "2026-08-18T20:00:00+03:00"
    raw.pop("ShiftCompleteness")
    raw.pop("CostEvidence")

    packet = await emitter.prepare_accounting_packet(
        "shift-42", manifest.manifest_hash, raw_packet=raw,
    )

    assert packet["FactOrigin"] == "onec_legacy"
    assert packet["BusinessShiftID"] == str(shift.id)
    assert packet["ИдентификаторПакета"] == str(group.packet_uuid)
    assert packet["РевизияПакета"] == 2
    assert [row["Algorithm"] for row in packet["BusinessShiftAliases"]] == [
        "business-shift-common-alias-v1",
    ]
    assert all(
        "internal_shift_no" not in row["Attributes"]
        for row in packet["BusinessShiftAliases"]
    )
    assert session.decisions[-1].winner_fact_id == "oneC-shift-42"
    assert session.decisions[-1].loser_fact_ids == ["edge-shift-42"]


@pytest.mark.asyncio
async def test_real_emitter_resolver_versioner_guard_outbox_claim_vertical_slice():
    company_id = uuid.uuid4()
    policy, manifest, approvals = _effective_policy_manifest(company_id, 208)
    session = _DbBoundarySession(policy, manifest, approvals)
    raw = _raw_packet()
    raw["Смена"]["КодАЗС"] = "208"
    raw["CostEvidence"]["company_id"] = str(company_id)
    next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )["source_hash"] = canonical_hash(raw["CostEvidence"])
    provisional_edge_id = uuid.uuid4()
    emitter = BpPackageEmitter(session, company_id)
    emitter._shift_targets["shift-42"] = SimpleNamespace(
        id=provisional_edge_id, source="edge", source_id="edge-shift-42",
    )

    packet = await emitter.prepare_accounting_packet(
        "shift-42", manifest.manifest_hash, raw_packet=raw,
    )
    queued = await AccountingEgressGuard(session, company_id).queue_packet(
        packet, manifest.manifest_hash,
    )
    claimed = await AccountingOutboxService(session, company_id).claim_request(
        consumer_id="tradeledger-test", claim_request_id=uuid.uuid4(),
        lease_seconds=60,
    )

    assert packet["ВерсияКонтракта"] == "3.0.0"
    assert packet["BusinessShiftID"] != str(provisional_edge_id)
    assert packet["BusinessShiftID"] == str(session.shifts[0].id)
    assert packet["РевизияПакета"] == 1
    assert [row["Algorithm"] for row in packet["BusinessShiftAliases"]] == [
        "business-shift-alias-v1", "business-shift-common-alias-v1",
    ]
    assert queued.created is True
    assert claimed.packet is queued.packet
    assert claimed.packet.payload == packet
    assert claimed.packet.status == "leased"


@pytest.mark.asyncio
async def test_prepare_packet_uses_ose_business_date_when_close_is_missing():
    company_id = uuid.uuid4()
    policy, manifest, approvals = _effective_policy_manifest(company_id, 208)
    session = _DbBoundarySession(policy, manifest, approvals)
    raw = _raw_packet()
    raw["Смена"].pop("Закрытие")
    raw["Смена"]["НомерСмены"] = "2082081708202601"
    raw["Смена"]["ОСЭНомер"] = "2082081708202601"
    raw["CostEvidence"]["company_id"] = str(company_id)
    next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )["source_hash"] = canonical_hash(raw["CostEvidence"])
    emitter = BpPackageEmitter(session, company_id)
    emitter._shift_targets["shift-42"] = _fact_candidate(
        "edge", date(2026, 8, 17),
    )

    packet = await emitter.prepare_accounting_packet(
        "shift-42", manifest.manifest_hash, raw_packet=raw,
    )
    queued = await AccountingEgressGuard(session, company_id).queue_packet(
        packet, manifest.manifest_hash,
    )

    assert packet["BusinessDate"] == "2026-08-17"
    assert packet["Смена"]["ЗакрытаВ"] is None
    assert queued.created is True


@pytest.mark.asyncio
async def test_prepare_packet_normalizes_entire_payload_to_nfc_before_queue():
    company_id = uuid.uuid4()
    policy, manifest, approvals = _effective_policy_manifest(company_id, 208)
    session = _DbBoundarySession(policy, manifest, approvals)
    raw = _raw_packet()
    raw["НСИ"][0]["Наименование"] = "Кафе\u0308"
    raw["CostEvidence"]["company_id"] = str(company_id)
    next(
        row for row in raw["ShiftCompleteness"]["sources"]
        if row["type"] == "cost_snapshot"
    )["source_hash"] = canonical_hash(raw["CostEvidence"])
    emitter = BpPackageEmitter(session, company_id)
    emitter._shift_targets["shift-42"] = _fact_candidate(
        "edge", date(2026, 8, 17),
    )

    packet = await emitter.prepare_accounting_packet(
        "shift-42", manifest.manifest_hash, raw_packet=raw,
    )
    dish = next(
        row for row in packet["НСИ"]
        if row["ИсточникUUID"] == "dish-coffee"
    )

    assert packet["UnicodeNormalization"] == "NFC"
    assert dish["Наименование"] == "Кафё"
    assert "Кафе\u0308" not in str(packet)
