from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from app.services.accounting_contract_v3 import canonical_hash
from app.services.accounting_payment import map_accounting_payment


class AccountingGroupInvariantError(ValueError):
    pass


def _decimal(value: object, scale: int, field: str) -> str:
    try:
        result = Decimal(str(value or 0)).quantize(
            Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP,
        )
    except (InvalidOperation, ValueError) as exc:
        raise AccountingGroupInvariantError(f"Некорректное decimal-поле {field}") from exc
    if result == 0:
        result = abs(result)
    return f"{result:.{scale}f}"


def _timestamp(value: object, field: str) -> str:
    raw = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AccountingGroupInvariantError(f"Некорректный timestamp {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AccountingGroupInvariantError(f"Timestamp {field} не содержит timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z",
    )


def _nullable_timestamp(value: object, field: str) -> str | None:
    if value in (None, ""):
        return None
    return _timestamp(value, field)


def _source_hash(value: Any) -> str:
    return canonical_hash(value)


def _source_entry(
    kind: str,
    required: bool,
    count: int,
    content: Any | None,
) -> dict:
    if not required:
        return {
            "Тип": kind, "Требуется": False, "Статус": "not_applicable",
            "Количество": 0, "SourceHash": None,
        }
    return {
        "Тип": kind, "Требуется": True, "Статус": "ready",
        "Количество": count, "SourceHash": _source_hash(content),
    }


_COMPLETENESS_TYPES = {
    "shift_closure", "cheques", "payments", "returns", "exact_ttk",
    "production_snapshot", "cost_snapshot",
}
_COST_EVIDENCE_FIELDS = {
    "version", "provisional_business_shift_id", "company_id", "business_date",
    "station_id", "warehouse", "as_of", "opening_snapshot_id",
    "cost_snapshot_revision", "ledger_version_hash", "production", "ingredients",
}
_COST_PRODUCTION_FIELDS = {
    "production_source_uuid", "dish_uuid", "quantity_millis",
}
_COST_INGREDIENT_FIELDS = {
    "production_source_uuid", "dish_uuid", "item_uuid",
    "required_quantity_millis", "unit_cost_micros", "required_amount_micros",
    "coverage_basis_points", "status", "provenance",
}


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise AccountingGroupInvariantError(f"{field} должен быть положительным integer")
    return value


def _nonnegative_int(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AccountingGroupInvariantError(f"{field} должен быть non-negative integer")
    return value


def _sha256(value: object, field: str) -> str:
    result = str(value or "")
    if len(result) != 64 or any(char not in "0123456789abcdef" for char in result):
        raise AccountingGroupInvariantError(f"{field} не является canonical SHA-256")
    return result


def _quantity_millis(value: object, field: str) -> int:
    try:
        scaled = Decimal(str(value)) * 1000
    except (InvalidOperation, ValueError) as exc:
        raise AccountingGroupInvariantError(f"Некорректное количество {field}") from exc
    if scaled != scaled.to_integral_value() or scaled <= 0:
        raise AccountingGroupInvariantError(
            f"{field} нельзя точно представить в quantity_millis",
        )
    return int(scaled)


def _validated_cost_evidence(
    raw_packet: dict,
    production_docs: list[dict],
    accounting_scope: dict | None,
) -> tuple[dict[tuple[str, str], int], dict | None]:
    evidence = raw_packet.get("CostEvidence")
    if evidence is None:
        return {}, None
    if not isinstance(evidence, dict) or set(evidence) != _COST_EVIDENCE_FIELDS:
        raise AccountingGroupInvariantError("CostEvidence содержит не exact v1 schema")
    if evidence.get("version") != "1":
        raise AccountingGroupInvariantError("CostEvidence version должен быть 1")
    provisional = str(raw_packet.get("ProvisionalBusinessShiftID") or "").strip()
    if not provisional or evidence.get("provisional_business_shift_id") != provisional:
        raise AccountingGroupInvariantError("CostEvidence относится к другой provisional смене")
    raw_shift = raw_packet.get("Смена") or {}
    expected_scope = {
        "company_id": str((accounting_scope or {}).get("company_id") or ""),
        "station_id": str(
            (accounting_scope or {}).get("station_id")
            or raw_shift.get("КодАЗС") or ""
        ),
        "business_date": str((accounting_scope or {}).get("business_date") or ""),
    }
    if expected_scope["company_id"] \
            and str(evidence.get("company_id") or "") != expected_scope["company_id"]:
        raise AccountingGroupInvariantError("CostEvidence вне CompanyID scope")
    if str(evidence.get("station_id") or "") != expected_scope["station_id"]:
        raise AccountingGroupInvariantError("CostEvidence вне StationID scope")
    if expected_scope["business_date"] \
            and str(evidence.get("business_date") or "") != expected_scope["business_date"]:
        raise AccountingGroupInvariantError("CostEvidence вне BusinessDate scope")
    warehouse = str(raw_shift.get("СкладUUID") or raw_shift.get("Склад") or "").strip()
    if not warehouse or str(evidence.get("warehouse") or "").strip() != warehouse:
        raise AccountingGroupInvariantError("CostEvidence вне warehouse scope")
    _timestamp(evidence.get("as_of"), "CostEvidence.as_of")
    opening_snapshot_id = str(evidence.get("opening_snapshot_id") or "").strip()
    if not opening_snapshot_id:
        raise AccountingGroupInvariantError("CostEvidence без opening_snapshot_id")
    _positive_int(evidence.get("cost_snapshot_revision"), "cost_snapshot_revision")
    _sha256(evidence.get("ledger_version_hash"), "ledger_version_hash")

    production = evidence.get("production")
    ingredients = evidence.get("ingredients")
    if not isinstance(production, list) or not production \
            or not isinstance(ingredients, list) or not ingredients:
        raise AccountingGroupInvariantError("CostEvidence не содержит production/ingredients")
    expected_production: dict[tuple[str, str], int] = {}
    for document in production_docs:
        source_id = str(document.get("ИсточникUUID") or "").strip()
        for line in document.get("ВыпускБлюд") or []:
            key = (source_id, str(line.get("Номенклатура") or "").strip())
            if not all(key) or key in expected_production:
                raise AccountingGroupInvariantError("production_release содержит неуникальный dish key")
            expected_production[key] = _quantity_millis(
                line.get("Количество"), "production_release.Количество",
            )
    evidence_production: dict[tuple[str, str], int] = {}
    production_order = []
    for row in production:
        if not isinstance(row, dict) or set(row) != _COST_PRODUCTION_FIELDS:
            raise AccountingGroupInvariantError("CostEvidence production содержит не exact schema")
        key = (
            str(row.get("production_source_uuid") or "").strip(),
            str(row.get("dish_uuid") or "").strip(),
        )
        if not all(key) or key in evidence_production:
            raise AccountingGroupInvariantError("CostEvidence production key неуникален")
        evidence_production[key] = _positive_int(
            row.get("quantity_millis"), "production.quantity_millis",
        )
        production_order.append(key)
    if production_order != sorted(production_order) or evidence_production != expected_production:
        raise AccountingGroupInvariantError("CostEvidence production не совпадает с выпуском")

    costs: dict[tuple[str, str], int] = {key: 0 for key in evidence_production}
    ingredient_counts: dict[tuple[str, str], int] = {
        key: 0 for key in evidence_production
    }
    ingredient_order = []
    for row in ingredients:
        if not isinstance(row, dict) or set(row) != _COST_INGREDIENT_FIELDS:
            raise AccountingGroupInvariantError("CostEvidence ingredient содержит не exact schema")
        production_key = (
            str(row.get("production_source_uuid") or "").strip(),
            str(row.get("dish_uuid") or "").strip(),
        )
        key = (*production_key, str(row.get("item_uuid") or "").strip())
        if not all(key) or production_key not in costs:
            raise AccountingGroupInvariantError("CostEvidence ingredient не связан с выпуском")
        quantity = _positive_int(
            row.get("required_quantity_millis"), "required_quantity_millis",
        )
        unit_cost = _nonnegative_int(row.get("unit_cost_micros"), "unit_cost_micros")
        amount = _nonnegative_int(
            row.get("required_amount_micros"), "required_amount_micros",
        )
        if amount != (unit_cost * quantity + 500) // 1000:
            raise AccountingGroupInvariantError(
                "required_amount_micros не воспроизводится из unit cost и quantity",
            )
        costs[production_key] += amount
        ingredient_counts[production_key] += 1
        if row.get("coverage_basis_points") != 10000 or row.get("status") != "known":
            raise AccountingGroupInvariantError("CostEvidence ingredient не имеет exact known cost")
        provenance = row.get("provenance")
        if not isinstance(provenance, list) or not provenance:
            raise AccountingGroupInvariantError("CostEvidence ingredient без provenance")
        provenance_keys = []
        for source in provenance:
            if not isinstance(source, dict) or set(source) not in (
                {"source_kind", "source_doc_uuid"},
                {"source_kind", "source_doc_uuid", "snapshot_id"},
            ) or not str(source.get("source_kind") or "").strip() \
                    or not str(source.get("source_doc_uuid") or "").strip():
                raise AccountingGroupInvariantError("CostEvidence содержит не exact provenance")
            if source["source_kind"] == "opening_snapshot":
                if source["source_doc_uuid"] != opening_snapshot_id \
                        or source.get("snapshot_id") != opening_snapshot_id:
                    raise AccountingGroupInvariantError(
                        "CostEvidence opening_snapshot provenance не совпадает с opening_snapshot_id",
                    )
            provenance_keys.append((
                source["source_kind"], source["source_doc_uuid"],
                source.get("snapshot_id") or "",
            ))
        if provenance_keys != sorted(set(provenance_keys)):
            raise AccountingGroupInvariantError("CostEvidence provenance не canonical")
        ingredient_order.append(key)
    if ingredient_order != sorted(set(ingredient_order)) \
            or any(value <= 0 for value in ingredient_counts.values()):
        raise AccountingGroupInvariantError("CostEvidence ingredients не canonical/complete")
    return costs, evidence


def _edge_completeness_sources(
    raw_packet: dict,
    *,
    has_food: bool,
    exact_ttk_count: int,
    production_count: int,
    onec_cost_evidence: list[dict],
    production_line_count: int,
    cost_evidence: dict | None,
) -> list[dict] | None:
    manifest = raw_packet.get("ShiftCompleteness")
    if manifest is None:
        if has_food:
            is_onec = str(raw_packet.get("Источник") or "").startswith("TradeLedger")
            if not is_onec or production_line_count <= 0 \
                    or len(onec_cost_evidence) != production_line_count:
                raise AccountingGroupInvariantError(
                    "Общепит без реального cost_snapshot или exact Себестоимость 1С запрещён",
                )
        return None
    if not isinstance(manifest, dict) or manifest.get("version") != "1" \
            or manifest.get("status") != "complete" \
            or not str(manifest.get("provisional_business_shift_id") or "").strip():
        raise AccountingGroupInvariantError("ShiftCompleteness не содержит complete-шапку")
    if str(raw_packet.get("ProvisionalBusinessShiftID") or "").strip() \
            != str(manifest["provisional_business_shift_id"]).strip():
        raise AccountingGroupInvariantError("ShiftCompleteness относится к другой смене")
    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) != len(_COMPLETENESS_TYPES):
        raise AccountingGroupInvariantError("ShiftCompleteness должен содержать семь источников")

    by_type: dict[str, dict] = {}
    translated = []
    for source in raw_sources:
        if not isinstance(source, dict):
            raise AccountingGroupInvariantError("Источник ShiftCompleteness не является объектом")
        kind = str(source.get("type") or "")
        if kind not in _COMPLETENESS_TYPES or kind in by_type:
            raise AccountingGroupInvariantError("Неверный или дублирующийся источник ShiftCompleteness")
        required = source.get("required")
        count = source.get("count")
        status = source.get("status")
        source_hash = source.get("source_hash")
        if not isinstance(required, bool) or isinstance(count, bool) \
                or not isinstance(count, int) or count < 0:
            raise AccountingGroupInvariantError(f"Неверные required/count источника {kind}")
        if status == "ready":
            if not isinstance(source_hash, str) or len(source_hash) != 64 \
                    or any(char not in "0123456789abcdef" for char in source_hash):
                raise AccountingGroupInvariantError(f"Источник {kind} ready без SHA-256")
        elif status == "not_applicable":
            if required or count != 0 or source_hash is not None:
                raise AccountingGroupInvariantError(f"Неверный not_applicable источника {kind}")
        else:
            raise AccountingGroupInvariantError(f"Источник {kind} не готов: {status or 'unknown'}")
        if required and status != "ready":
            raise AccountingGroupInvariantError(f"Обязательный источник {kind} не готов")
        by_type[kind] = source
        translated.append({
            "Тип": kind, "Требуется": required, "Статус": status,
            "Количество": count, "SourceHash": source_hash,
        })
    if set(by_type) != _COMPLETENESS_TYPES:
        raise AccountingGroupInvariantError("ShiftCompleteness не содержит семь точных источников")
    if has_food:
        expected_counts = {
            "exact_ttk": exact_ttk_count,
            "production_snapshot": production_count,
        }
        for kind, expected in expected_counts.items():
            source = by_type[kind]
            if not source["required"] or source["status"] != "ready" \
                    or source["count"] != expected or expected <= 0:
                raise AccountingGroupInvariantError(
                    f"Источник {kind} не покрывает exact-состав смены",
                )
        cost_source = by_type["cost_snapshot"]
        if not cost_source["required"] or cost_source["status"] != "ready" \
                or cost_source["count"] <= 0:
            raise AccountingGroupInvariantError(
                "Источник cost_snapshot не покрывает exact-состав смены",
            )
        if cost_evidence is None \
                or cost_source["count"] != len(cost_evidence["ingredients"]) \
                or cost_source["source_hash"] != canonical_hash(cost_evidence):
            raise AccountingGroupInvariantError(
                "Источник cost_snapshot не совпадает с exact CostEvidence",
            )
    translated.sort(key=lambda row: row["Тип"])
    return translated


def _retail_line(line: dict, number: int) -> dict:
    item = str(line.get("Номенклатура") or line.get("НоменклатураUUID") or "").strip()
    if not item:
        raise AccountingGroupInvariantError("Строка ОРП не содержит номенклатуру")
    sku_class = str(line.get("КлассSKU") or "Сопутка").strip()
    if sku_class not in {"Сопутка", "Общепит"}:
        raise AccountingGroupInvariantError("Неизвестный КлассSKU строки ОРП")
    result = {
        "НомерСтроки": number,
        "НоменклатураUUID": item,
        "КлассSKU": sku_class,
        "АналитикаПродажи": "Сопутствующие товары",
        "Количество": _decimal(line.get("Количество"), 3, "Количество"),
        "Сумма": _decimal(line.get("Сумма"), 2, "Сумма"),
        "НДС": _decimal(line.get("СуммаНДС"), 2, "СуммаНДС"),
        "СтавкаНДС": str(line.get("СтавкаНДС") or "").removeprefix("НДС"),
    }
    if not result["СтавкаНДС"]:
        raise AccountingGroupInvariantError("Строка ОРП не содержит ставку НДС")
    return result


def _return_identity(
    line: dict,
    containing_source_id: str,
    *,
    require_explicit_document: bool,
) -> tuple[str, str]:
    document_id = str(line.get("ИсточникДокументаUUID") or "").strip()
    if not document_id and not require_explicit_document:
        document_id = containing_source_id
    line_id = str(
        line.get("ИсточникСтрокиUUID") or line.get("ИдентификаторСтроки")
        or line.get("line_uuid") or ""
    ).strip()
    if not document_id or not line_id:
        raise AccountingGroupInvariantError(
            "Возврат не содержит exact source document + line UUID",
        )
    return document_id, line_id


def _return_line(line: dict, number: int, identity: tuple[str, str]) -> dict:
    result = _retail_line(line, number)
    result["ИсточникДокументаUUID"] = identity[0]
    result["ИсточникСтрокиUUID"] = identity[1]
    return result


def _exact_recipes(recipe_docs: list[dict], dishes: set[str]) -> tuple[list[dict], dict[str, dict]]:
    by_dish: dict[str, dict] = {}
    for document in recipe_docs:
        dish = str(document.get("БлюдоUUID") or "").strip()
        recipe_id = str(document.get("ИсточникUUID") or "").strip()
        bundle_id = str(document.get("ВерсияНабораТТК") or "").strip()
        try:
            revision = int(document.get("ВерсияТТК") or 0)
        except (TypeError, ValueError) as exc:
            raise AccountingGroupInvariantError("Ревизия exact ТТК должна быть целым числом") from exc
        if not dish or not recipe_id or not bundle_id or revision <= 0:
            raise AccountingGroupInvariantError(
                "ТТК без exact shift/bundle identity запрещена",
            )
        if dish in by_dish:
            raise AccountingGroupInvariantError(f"Для блюда {dish} найдено больше одной exact ТТК")
        ingredients = []
        for number, ingredient in enumerate(document.get("Ингредиенты") or [], 1):
            item = str(
                ingredient.get("НоменклатураUUID")
                or ingredient.get("Номенклатура") or ""
            ).strip()
            unit = str(ingredient.get("Единица") or "").strip()
            if not item or not unit:
                raise AccountingGroupInvariantError("Ингредиент ТТК заполнен не полностью")
            ingredients.append({
                "НомерСтроки": int(ingredient.get("НомерСтроки") or number),
                "ИнгредиентUUID": item,
                "Количество": _decimal(ingredient.get("Количество"), 3, "Количество ТТК"),
                "Единица": unit,
            })
        ingredients.sort(key=lambda row: (row["НомерСтроки"], row["ИнгредиентUUID"]))
        if not ingredients:
            raise AccountingGroupInvariantError(f"Exact ТТК блюда {dish} не содержит ингредиенты")
        bundle_hash = canonical_hash({
            "БлюдоUUID": dish,
            "ИдентификаторТТК": recipe_id,
            "РевизияТТК": revision,
            "ВерсияНабораТТК": bundle_id,
            "Ингредиенты": ingredients,
        })
        by_dish[dish] = {
            "БлюдоUUID": dish,
            "ИдентификаторТТК": recipe_id,
            "РевизияТТК": revision,
            "BundleHash": bundle_hash,
            "Ингредиенты": ingredients,
        }
    missing = sorted(dishes - set(by_dish))
    if missing:
        raise AccountingGroupInvariantError(
            "Для проданных или возвращённых блюд нет exact ТТК: " + ", ".join(missing[:5]),
        )
    return sorted(
        by_dish.values(),
        key=lambda row: (row["БлюдоUUID"], row["ИдентификаторТТК"], row["РевизияТТК"]),
    ), by_dish


def _nsi_projection(rows: list[dict], dish_ids: set[str]) -> list[dict]:
    result: dict[tuple[str, str], dict] = {}
    for row in rows:
        kind = str(row.get("Тип") or "").strip()
        source_id = str(row.get("ИсточникUUID") or "").strip()
        name = str(row.get("Наименование") or "").strip()
        if not kind or not source_id or not name:
            raise AccountingGroupInvariantError("НСИ v3 содержит незаполненную карточку")
        sku_class = "НеПрименимо"
        if kind == "Номенклатура":
            sku_class = str(row.get("КлассSKU") or "").strip()
            if source_id in dish_ids:
                sku_class = "Общепит"
            elif sku_class not in {"Сопутка", "Общепит"}:
                sku_class = "Сопутка"
        projected = {
            "Тип": kind,
            "ИсточникUUID": source_id,
            "Наименование": name,
            "КлассSKU": sku_class,
        }
        key = (kind, source_id)
        if key in result and result[key] != projected:
            raise AccountingGroupInvariantError("Конфликт карточек НСИ в одной группе")
        result[key] = projected
    return sorted(result.values(), key=lambda row: (row["Тип"], row["ИсточникUUID"]))


def build_accounting_business_payload(
    raw_packet: dict,
    accounting_scope: dict | None = None,
) -> dict:
    if raw_packet.get("НеРазложено"):
        raise AccountingGroupInvariantError(
            "Бухгалтерская группа содержит неразложенные факты",
        )
    documents = list(raw_packet.get("Документы") or [])
    retail_docs = [row for row in documents if row.get("Тип") == "retail_sale_sidegoods"]
    if len(retail_docs) != 1:
        raise AccountingGroupInvariantError("В группе должен быть ровно один ОРП")
    retail = retail_docs[0]
    retail_source = str(retail.get("ИсточникUUID") or "").strip()
    if not retail_source:
        raise AccountingGroupInvariantError("ОРП не содержит ИсточникUUID")
    sales = [
        _retail_line(line, number)
        for number, line in enumerate(retail.get("Товары") or [], 1)
    ]
    returns = []
    return_lines: dict[tuple[str, str], dict] = {}
    for number, line in enumerate(retail.get("ВозвращенныеТовары") or [], 1):
        identity = _return_identity(
            line, retail_source, require_explicit_document=True,
        )
        projected = _return_line(line, number, identity)
        if identity in return_lines:
            raise AccountingGroupInvariantError("ОРП содержит дубль source line возврата")
        return_lines[identity] = projected
        returns.append(projected)

    return_docs = [row for row in documents if row.get("Тип") == "return_sale"]
    return_source_ids: set[str] = set()
    embedded_documents = []
    for document in return_docs:
        source_id = str(document.get("ИсточникUUID") or "").strip()
        if not source_id or source_id in return_source_ids:
            raise AccountingGroupInvariantError("return_sale не имеет уникального ИсточникUUID")
        return_source_ids.add(source_id)
        embedded_count = 0
        for line in document.get("Товары") or document.get("ВозвращенныеТовары") or []:
            identity = _return_identity(
                line, source_id, require_explicit_document=False,
            )
            projected = _return_line(line, len(returns) + 1, identity)
            existing = return_lines.get(identity)
            if existing is not None and {
                key: value for key, value in existing.items()
                if key != "НомерСтроки"
            } != {
                key: value for key, value in projected.items()
                if key != "НомерСтроки"
            }:
                raise AccountingGroupInvariantError(
                    "Один source line возврата содержит разные значения",
                )
            if existing is None:
                returns.append(projected)
                return_lines[identity] = projected
            embedded_count += 1
        if embedded_count == 0:
            raise AccountingGroupInvariantError("return_sale не содержит строк для ОРП")
        embedded_documents.append((source_id, embedded_count))

    sold_dish_ids = {
        line["НоменклатураUUID"] for line in sales
        if line["КлассSKU"] == "Общепит"
    }
    dish_ids = sold_dish_ids | {
        line["НоменклатураUUID"] for line in returns
        if line["КлассSKU"] == "Общепит"
    }
    recipe_docs = [row for row in documents if row.get("Тип") == "recipe"]
    recipes, recipe_by_dish = _exact_recipes(recipe_docs, dish_ids)
    returned_dishes = {
        line["НоменклатураUUID"] for line in returns
        if line["НоменклатураUUID"] in recipe_by_dish
    }

    payments = []
    for number, payment in enumerate(retail.get("Оплаты") or [], 1):
        raw_kind = (
            payment.get("ВидОплаты") or payment.get("ФормаОплатыКанон")
            or payment.get("ФормаОплаты")
        )
        payments.append({
            "НомерСтроки": number,
            "Вид": map_accounting_payment(raw_kind),
            "Сумма": _decimal(payment.get("Сумма"), 2, "Сумма оплаты"),
        })

    production_docs = [row for row in documents if row.get("Тип") == "production_release"]
    produced_dishes = {
        str(line.get("Номенклатура") or "").strip()
        for document in production_docs
        for line in document.get("ВыпускБлюд") or []
    }
    missing_production = sorted(dish_ids - produced_dishes)
    if missing_production:
        raise AccountingGroupInvariantError(
            "Для блюд нет production snapshot: " + ", ".join(missing_production[:5]),
        )
    edge_costs, cost_evidence = _validated_cost_evidence(
        raw_packet, production_docs, accounting_scope,
    )

    v3_documents = []
    onec_cost_evidence = []
    production_line_count = 0
    order = 1
    for document in sorted(production_docs, key=lambda row: str(row.get("ИсточникUUID") or "")):
        source_id = str(document.get("ИсточникUUID") or "").strip()
        if not source_id:
            raise AccountingGroupInvariantError("production_release без ИсточникUUID")
        release_lines = []
        for line in document.get("ВыпускБлюд") or []:
            production_line_count += 1
            release_line = {
                "НоменклатураUUID": str(line.get("Номенклатура") or "").strip(),
                "Количество": _decimal(line.get("Количество"), 3, "Количество выпуска"),
            }
            edge_cost_micros = edge_costs.get((
                source_id, release_line["НоменклатураUUID"],
            ))
            if edge_cost_micros is not None:
                release_line["Себестоимость"] = _decimal(
                    Decimal(edge_cost_micros) / Decimal(1_000_000),
                    6, "Себестоимость CostEvidence",
                )
            elif line.get("Себестоимость") is not None:
                release_line["Себестоимость"] = _decimal(
                    line["Себестоимость"], 6, "Себестоимость выпуска",
                )
                if Decimal(release_line["Себестоимость"]) > 0:
                    onec_cost_evidence.append({
                        "НоменклатураUUID": release_line["НоменклатураUUID"],
                        "Себестоимость": release_line["Себестоимость"],
                    })
            release_lines.append(release_line)
        content = {"Проведен": False, "ВыпускБлюд": release_lines}
        v3_documents.append({
            "ПорядокГруппы": order, "Тип": "production_release",
            "ИсточникUUID": source_id, "РольВГруппе": "evidence",
            "SourceHash": _source_hash(content), "Содержимое": content,
        })
        order += 1

    assembly_sources = {
        dish_id: f"assembly:{retail_source}:{dish_id}"
        for dish_id in sorted(sold_dish_ids)
    }
    for document in sorted(
        (row for row in documents if row.get("Тип") == "ingredients_writeoff"),
        key=lambda row: str(row.get("ИсточникUUID") or ""),
    ):
        source_id = str(document.get("ИсточникUUID") or "").strip()
        if not source_id:
            raise AccountingGroupInvariantError("ingredients_writeoff без ИсточникUUID")
        absorbed_by = list(assembly_sources.values())
        content = (
            {"ПоглощенКомпонентом": absorbed_by[0]}
            if len(absorbed_by) == 1
            else {"ПоглощенКомпонентами": absorbed_by}
        )
        v3_documents.append({
            "ПорядокГруппы": order, "Тип": "ingredients_writeoff",
            "ИсточникUUID": source_id, "РольВГруппе": "absorbed",
            "SourceHash": _source_hash(content), "Содержимое": content,
        })
        order += 1

    retail_content = {
        "Проведен": False,
        "Продажи": sales,
        "Возвраты": returns,
        "Оплаты": payments,
    }
    v3_documents.append({
        "ПорядокГруппы": order, "Тип": "retail_sale_sidegoods",
        "ИсточникUUID": retail_source, "РольВГруппе": "materialized",
        "SourceHash": _source_hash(retail_content), "Содержимое": retail_content,
    })
    order += 1
    for source_id, embedded_count in embedded_documents:
        content = {"ВстроеноВОРП": retail_source, "КоличествоСтрок": embedded_count}
        v3_documents.append({
            "ПорядокГруппы": order, "Тип": "return_sale",
            "ИсточникUUID": source_id, "РольВГруппе": "embedded",
            "SourceHash": _source_hash(content), "Содержимое": content,
        })
        order += 1

    raw_shift = raw_packet.get("Смена") or {}
    shift = {
        "НомерВнутренний": str(raw_shift.get("НомерСменыВнутр") or "").strip(),
        "ОСЭ": str(raw_shift.get("ОСЭНомер") or raw_shift.get("НомерСмены") or "").strip(),
        "ОткрытаВ": _timestamp(raw_shift.get("Открытие"), "Смена.Открытие"),
        "ЗакрытаВ": _nullable_timestamp(raw_shift.get("Закрытие"), "Смена.Закрытие"),
        "ЧасовойПояс": "Europe/Moscow",
    }
    if not shift["НомерВнутренний"] or not shift["ОСЭ"]:
        raise AccountingGroupInvariantError("Смена не содержит внутренний номер или ОСЭ")

    components = [
        {"Порядок": number, "Тип": "assembly", "ИсточникUUID": source_id}
        for number, source_id in enumerate(assembly_sources.values(), 1)
    ]
    components.append({
        "Порядок": len(components) + 1,
        "Тип": "retail", "ИсточникUUID": retail_source,
    })
    for dish_id in sorted(returned_dishes):
        components.append({
            "Порядок": len(components) + 1, "Тип": "disassembly",
            "ИсточникUUID": f"disassembly:{retail_source}:{dish_id}",
        })

    has_food = bool(dish_ids)
    completeness_sources = _edge_completeness_sources(
        raw_packet,
        has_food=has_food,
        exact_ttk_count=len(recipes),
        production_count=len(produced_dishes),
        onec_cost_evidence=onec_cost_evidence,
        production_line_count=production_line_count,
        cost_evidence=cost_evidence,
    )
    if completeness_sources is None:
        completeness_sources = [
            _source_entry("cheques", True, len(sales) + len(returns), [sales, returns]),
            _source_entry("cost_snapshot", has_food, len(onec_cost_evidence), onec_cost_evidence),
            _source_entry("exact_ttk", has_food, len(recipes), recipes),
            _source_entry("payments", True, len(payments), payments),
            _source_entry("production_snapshot", has_food, len(produced_dishes), v3_documents[:len(production_docs)]),
            _source_entry("returns", bool(returns), len(returns), returns),
            _source_entry("shift_closure", True, 1, shift),
        ]
        completeness_sources.sort(key=lambda row: row["Тип"])

    # Статус группы наследуется от станции: смену, где часть себестоимости
    # посчитана по оценке центра, агент помечает «needs_review». Терять этот
    # признак при пересборке пакета нельзя — по нему гейт решает, пускать ли
    # документ в бухгалтерию.
    станционный = (raw_packet.get("ShiftCompleteness") or {})
    статус_группы = "complete"
    if str(станционный.get("status") or "").strip() == "needs_review":
        статус_группы = "needs_review"

    return {
        "ПолнотаГруппы": {
            "Версия": "1", "Статус": статус_группы,
            "Источники": completeness_sources,
            "ОжидаемыеКомпоненты": components,
        },
        "Смена": shift,
        "НСИ": _nsi_projection(list(raw_packet.get("НСИ") or []), dish_ids),
        "ТТК": recipes,
        "Документы": v3_documents,
    }
