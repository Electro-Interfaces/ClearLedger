from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingDoc,
    Company,
    AccountingSourceLink,
    CbInventoryDoc,
    CbMovementDoc,
    DataEntry,
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
from app.services.store_document_contract import (
    ACCOUNTING_DOCUMENT_KINDS,
    PROJECTION_DOCUMENT_KINDS,
)


PROJECTION_NAMESPACE = uuid.UUID("4e99072c-7e16-4e3f-8886-e0a2e9320b13")
ADVISORY_LOCK = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
)


class ProjectionRevisionConflict(ValueError):
    pass


@dataclass(frozen=True)
class ProjectionLineRef:
    section: str
    source_line_id: str
    ordinal: int


@dataclass(frozen=True)
class ProjectionRelationRef:
    kind: str
    target_ref: str
    related_document_id: uuid.UUID | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class ProjectionCandidate:
    company_id: uuid.UUID
    projection_source: str
    source_kind: str
    source_record_id: str
    document_id: uuid.UUID
    document_kind: str
    priority: int
    document_role: str = "operational"
    accounting_group_id: uuid.UUID | None = None
    shift_no: int | None = None
    source_document_id: uuid.UUID | None = None
    station_id: int | None = None
    organization_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    number: str | None = None
    document_at: datetime | None = None
    counterparty_name: str | None = None
    counterparty_inn: str | None = None
    amount: Decimal = Decimal("0")
    vat_amount: Decimal | None = Decimal("0")
    author: str | None = None
    operational_status: str = "unknown"
    sync_status: str = "unknown"
    accounting_status: str = "pending"
    discrepancy_status: str = "none"
    requires_attention: bool = False
    has_fuel: bool = False
    raw_payload_available: bool = False
    revision: int = 1
    content_hash: str | None = None
    header: dict = field(default_factory=dict)
    lines: list[ProjectionLineRef] = field(default_factory=list)
    relations: list[ProjectionRelationRef] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source_document_id is None:
            self.source_document_id = self.document_id

    @property
    def record_id(self) -> uuid.UUID:
        return uuid.uuid5(
            PROJECTION_NAMESPACE,
            f"{self.company_id}:{self.projection_source}:"
            f"{self.source_kind}:{self.source_record_id}",
        )


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _derived_uuid(company_id: uuid.UUID, source: str, value: object) -> uuid.UUID:
    return uuid.uuid5(PROJECTION_NAMESPACE, f"{company_id}:{source}:{value}")


def _iso(value: object) -> str | None:
    """Дата/время для JSONB: только строкой."""
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _counterparty(*candidates: object) -> str | None:
    """Имя контрагента для колонки журнала.

    В исторических документах, приехавших из старой 1С, в поле контрагента лежит
    ССЫЛКА - guid справочника, а не наименование. Показывать его нельзя: человек
    видит строку вида `7a9ebeb3-f1e8-…` и не понимает, кто привёз товар. Имени в
    контуре для этих ссылок нет вовсе (ни в справочнике станции, ни в контрагентах
    Ядра), поэтому честный ответ - пусто: колонка покажет прочерк.
    """
    for value in candidates:
        name = str(value or "").strip()
        if name and _uuid(name) is None:
            return name
    return None


def _decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _revision(value: datetime | None, fallback: int = 1) -> int:
    return max(fallback, int(value.timestamp())) if value else max(1, fallback)


def _hash(value: object) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _shift_no(value: object) -> int | None:
    """Внутренний номер кассовой смены из шапки пакета.

    Ноль — не смена: так агент помечает документы, которые смене не
    принадлежат (приёмка, инвентаризация, перемещение). Возвращаем None,
    чтобы они не склеились в одну ложную «нулевую смену».
    """
    try:
        номер = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return номер if номер > 0 else None


def _station(value: object) -> int | None:
    if isinstance(value, int):
        return value
    raw = str(value or "")
    match = re.search(r"(?<!\d)(\d{1,6})(?!\d)", raw)
    return int(match.group(1)) if match else None


def _line_identity(row: dict) -> tuple[str, bool]:
    explicit = (
        row.get("line_id") or row.get("ИдентификаторСтроки")
        or row.get("Key") or row.get("Ключ")
    )
    if explicit:
        return str(explicit)[:200], True
    identity = {
        "item": (row.get("item_uuid") or row.get("Номенклатура")
                 or row.get("НоменклатураUUID") or row.get("ref")),
        "barcode": row.get("barcode") or row.get("ШтрихКод"),
        "name": row.get("name") or row.get("Наименование"),
        "unit": row.get("unit") or row.get("Единица"),
        "series": row.get("series") or row.get("Серия"),
        "expiry": row.get("expiry") or row.get("СрокГодности"),
        "purpose": row.get("purpose") or row.get("Назначение"),
    }
    return f"legacy:{_hash(identity)}", False


def _line_refs(rows: list[dict], section: str) -> tuple[list[ProjectionLineRef], bool]:
    identities = [_line_identity(row) for row in rows]
    totals: dict[str, int] = {}
    for key, _ in identities:
        totals[key] = totals.get(key, 0) + 1
    seen: dict[str, int] = {}
    refs = []
    ambiguous = False
    for ordinal, (key, explicit) in enumerate(identities):
        occurrence = seen.get(key, 0)
        seen[key] = occurrence + 1
        if totals[key] > 1:
            ambiguous = True
            key = f"{key}:duplicate:{occurrence}"
        refs.append(ProjectionLineRef(section, key[:200], ordinal))
    return refs, ambiguous


def _candidate_lines(
    goods: list[dict], services: list[dict] | None = None,
) -> tuple[list[ProjectionLineRef], bool]:
    goods_refs, goods_ambiguous = _line_refs(goods, "goods")
    service_refs, service_ambiguous = _line_refs(services or [], "services")
    return goods_refs + service_refs, goods_ambiguous or service_ambiguous


def _mark_ambiguous_lines(candidate: ProjectionCandidate, ambiguous: bool) -> None:
    """Строки без собственного ключа: факт записываем, тревогу не поднимаем.

    Раньше это включало «требует внимания» и уводило документ в «нужна
    проверка». На 208 так были помечены 333 документа из 350 — все, где в
    чеке встретились две одинаковых позиции, а это норма розницы. Разобрать
    такой документ человек не может: у него нет ни ошибки, ни действия, и
    счётчик проблем переставал что-либо значить.

    Ключи строк присваивает станция (ключиСтрок в пакете агента); документы,
    собранные до этого, так и останутся без ключей — их прошлое не переписать.
    Признак остаётся в разрезе расхождений: там он читается как свойство
    данных, а не как невыполненная работа.
    """
    if not ambiguous:
        return
    candidate.discrepancy_status = "line_identity_ambiguous"


def _line_scope(row: dict) -> str | None:
    raw = str(
        row.get("scope") or row.get("line_scope") or row.get("Контур") or ""
    ).strip().casefold()
    if raw in {"store", "sidegoods", "сопутка", "товар", "goods"}:
        return "store"
    if raw in {"food", "foodservice", "общепит", "кафе", "kitchen"}:
        return "food"
    if raw in {"fuel", "топливо", "гсм", "нефтепродукт"}:
        return "fuel"
    return None


def _data_entry_scope(row: DataEntry) -> str | None:
    raw = str(row.category_id or "").strip().casefold()
    if raw in {"store", "sidegoods"}:
        return "store"
    if raw in {"food", "foodservice"}:
        return "food"
    return None


def _line_amount(line: dict) -> Decimal:
    for key in ("amount", "Сумма", "СуммаОтклонения"):
        if line.get(key) is not None:
            return _decimal(line.get(key))
    return (_decimal(line.get("qty") or line.get("Количество"))
            * _decimal(line.get("price") or line.get("Цена"))).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)


def _line_vat(line: dict, amount: Decimal) -> tuple[Decimal, bool]:
    explicit_vat = line.get("vat_amount")
    if explicit_vat is None:
        explicit_vat = line.get("СуммаНДС")
    if explicit_vat is not None:
        return _decimal(explicit_vat), False
    rate_raw = str(line.get("vat_rate") or line.get("СтавкаНДС") or "").strip()
    normalized_rate = re.sub(r"[\s_%]", "", rate_raw).casefold().replace("ё", "е")
    if normalized_rate in {"безндс", "ндс0", "0"}:
        return Decimal("0"), False
    match = re.search(r"(10|20|22)", rate_raw)
    if match:
        rate = Decimal(match.group(1))
        return (amount * rate / (Decimal("100") + rate)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP), False
    return Decimal("0"), True


def goods_only_cheque_totals(
    lines: list[dict], had_fuel: bool, *, require_vat: bool = True,
) -> dict:
    goods: list[dict] = []
    unclassified = False
    explicit_goods = 0
    fuel_lines = 0
    for line in lines:
        scope = _line_scope(line)
        if scope == "fuel":
            fuel_lines += 1
            continue
        if scope in {"store", "food"}:
            explicit_goods += 1
            goods.append(line)
            continue
        if scope not in {"store", "food"}:
            unclassified = True
            continue
    if unclassified:
        return {
            "amount": Decimal("0"), "vat_amount": Decimal("0"), "lines": [],
            "quarantined": True,
            "reason": "Чек содержит строки без подтверждённого контура store|food",
            "explicit_goods": explicit_goods, "fuel_lines": fuel_lines,
        }
    amount = Decimal("0")
    vat = Decimal("0")
    vat_unknown = False
    for line in goods:
        line_amount = _line_amount(line)
        amount += line_amount
        line_vat, unknown = _line_vat(line, line_amount)
        vat += line_vat
        vat_unknown = vat_unknown or unknown
    if vat_unknown and require_vat:
        return {
            "amount": amount.quantize(Decimal("0.01")), "vat_amount": None,
            "lines": goods,
            "quarantined": True,
            "reason": "У товарной строки не подтверждена ставка или сумма НДС",
            "explicit_goods": explicit_goods, "fuel_lines": fuel_lines,
        }
    return {
        "amount": amount.quantize(Decimal("0.01")),
        "vat_amount": vat.quantize(Decimal("0.01")),
        "lines": goods,
        "quarantined": False,
        "reason": None,
        "explicit_goods": explicit_goods, "fuel_lines": fuel_lines,
    }


def _legacy_fiscal_line_fingerprint(line: dict) -> tuple[str, ...]:
    def numeric(*keys: str) -> str:
        for key in keys:
            if line.get(key) is not None:
                try:
                    return format(Decimal(str(line[key])).normalize(), "f")
                except (InvalidOperation, TypeError, ValueError):
                    return "invalid"
        return "0"

    return (
        str(line.get("item_uuid") or line.get("Номенклатура") or "").strip(),
        str(line.get("name") or line.get("Наименование") or "").strip(),
        str(line.get("ns_code") or line.get("КодНС") or "").strip(),
        numeric("qty", "Количество"),
        numeric("price", "Цена"),
        numeric("amount", "Сумма"),
        str(line.get("section") or line.get("Секция") or "").strip(),
    )


def cheque_lines_with_legacy_provenance(
    cheque: StoreCheque, packet: EdgePacket | None,
) -> list[dict]:
    lines = [dict(line) for line in (cheque.lines or []) if isinstance(line, dict)]
    if not lines or any(_line_scope(line) is not None for line in lines):
        return lines
    if (packet is None or not getattr(cheque, "packet_uuid", None)
            or str(packet.packet_uuid) != str(cheque.packet_uuid)
            or packet.station_id != cheque.station_id):
        return lines
    shift = (packet.payload or {}).get("Смена") or {}
    packet_shift = int(shift.get("НомерСменыВнутр") or shift.get("НомерСмены") or 0)
    if packet_shift != cheque.shift_number:
        return lines
    matches = []
    for document in (packet.payload or {}).get("Документы") or []:
        if not isinstance(document, dict) or document.get("Тип") != "fiscal_receipts":
            continue
        for raw_cheque in document.get("Чеки") or []:
            if not isinstance(raw_cheque, dict):
                continue
            if int(raw_cheque.get("Номер") or 0) == cheque.number:
                matches.append(raw_cheque)
    if len(matches) != 1:
        return lines
    raw_cheque = matches[0]
    if bool(raw_cheque.get("БылоТопливо")) != bool(cheque.had_fuel):
        return lines
    raw_lines = [line for line in raw_cheque.get("Товары") or [] if isinstance(line, dict)]
    if sorted(_legacy_fiscal_line_fingerprint(line) for line in raw_lines) != sorted(
            _legacy_fiscal_line_fingerprint(line) for line in lines):
        return lines
    return [
        {
            **line,
            "scope": "store",
            "scope_source": "edge_fiscal_receipts_filtered_v1_historical_exact",
        }
        for line in lines
    ]


async def load_item_catalog(db: AsyncSession) -> dict[str, dict]:
    """Контур и ставка НДС из карточки станции.

    Строка чека приезжает с `vat_rate: null`, а у чеков старше внедрения
    фильтра нет и контура. Любая из этих двух дыр уводит в карантин ВЕСЬ чек,
    а с ним и смену: на 208 так стояли 784 чека из 1155, и НДС не был посчитан
    ни у одного.

    Карточка — источник истины по обоим полям, поэтому добираем их здесь, а не
    ждём перевыгрузки со станции: иначе уже приехавшие чеки не поднять. Это
    заодно снимает зависимость от побайтового совпадения с сырым пакетом —
    единственного, что до сих пор спасало контур старых чеков и делало чистку
    архива пакетов операцией, обнуляющей выручку задним числом.
    """
    try:
        rows = (await db.execute(text(
            "SELECT external_uuid::text, vat_rate, sku_class, is_dish, purpose"
            " FROM edge.item WHERE external_uuid IS NOT NULL"
            " ORDER BY deleted DESC"  # живая карточка перезаписывает удалённый дубль
        ))).all()
    except Exception:
        # Схемы edge может не быть вовсе (пространство без станций, тестовый
        # SQLite). Обогащение необязательное: без него чек остаётся в карантине
        # ровно как раньше, а не теряет сумму.
        return {}
    out: dict[str, dict] = {}
    for uid, vat_rate, sku_class, is_dish, purpose in rows:
        scope = _sku_scope(sku_class)
        if scope is None and is_dish:
            scope = "food"
        if scope is None:
            scope = _purpose_scope(purpose)
        карточка = {}
        if str(vat_rate or "").strip():
            карточка["vat_rate"] = str(vat_rate)
        if scope is not None:
            карточка["scope"] = scope
        if карточка:
            out[str(uid)] = карточка
    return out


def cheque_lines_from_catalog(
    lines: list[dict], catalog: dict[str, dict],
) -> list[dict]:
    """Добрать строкам чека контур и ставку из справочника, где станция их не дала.

    Присланное станцией не трогаем: она ближе к кассе и знает лучше.
    """
    if not catalog:
        return lines
    out: list[dict] = []
    for line in lines:
        карточка = catalog.get(str(line.get("item_uuid") or "").strip())
        if not карточка:
            out.append(line)
            continue
        добавка: dict = {}
        ставка_известна = (line.get("vat_amount") is not None
                           or line.get("СуммаНДС") is not None
                           or str(line.get("vat_rate")
                                  or line.get("СтавкаНДС") or "").strip())
        if not ставка_известна and карточка.get("vat_rate"):
            добавка["vat_rate"] = карточка["vat_rate"]
        if _line_scope(line) is None and карточка.get("scope"):
            добавка["scope"] = карточка["scope"]
        if not добавка:
            out.append(line)
            continue
        out.append({**line, **добавка, "enriched_from": "catalog"})
    return out


EDGE_QUANTITY_ONLY_KINDS = frozenset({
    "transfer", "inventory", "writeoff", "production_release", "recipe",
    "ingredients_writeoff", "revaluation",
})
EDGE_VAT_KINDS = frozenset({
    "purchase", "return_purchase", "return_sale", "gain", "retail_sale_sidegoods",
})


def _purpose_scope(value: object) -> str | None:
    raw = str(value or "").strip().casefold().replace("ё", "е")
    if raw in {"магазин", "store", "sidegoods", "сопутка"}:
        return "store"
    if raw in {"кафе", "кухня", "food", "foodservice", "общепит"}:
        return "food"
    return None


def _sku_scope(value: object) -> str | None:
    raw = str(value or "").strip().casefold().replace("ё", "е")
    if raw in {"сопутка", "товар", "store", "sidegoods"}:
        return "store"
    # станция помечает строки и по-русски, и латиницей: «Общепит», «dish»,
    # «ingredient» приходят из кассы наравне с «блюдо». Непонятый класс уводил
    # весь документ в карантин, и продажи смены показывали нулевую сумму
    if raw in {"блюдо", "сырье", "кафе", "общепит", "food", "foodservice",
               "dish", "ingredient", "semi", "combo"}:
        return "food"
    if raw in {"топливо", "fuel", "гсм", "нефтепродукт"}:
        return "fuel"
    return None


def _edge_line_identity_present(line: dict) -> bool:
    return bool(
        line.get("item_uuid") or line.get("Номенклатура")
        or line.get("НоменклатураUUID") or line.get("ШтрихКод")
    )


def _edge_line_scope(kind: str, document: dict, line: dict) -> str | None:
    if bool(line.get("IsFuel") or line.get("is_fuel") or line.get("Топливо")):
        return "fuel"
    explicit = _line_scope(line)
    if explicit is not None:
        return explicit
    sku_scope = _sku_scope(line.get("КлассSKU") or line.get("sku_class"))
    if sku_scope is not None:
        return sku_scope
    if bool(line.get("ЭтоБлюдо") or line.get("is_dish")):
        return "food"
    # Отчёт о розничных продажах магазина товарный по построению: топливо в
    # него не кладут, топливная строка отсекается выше по IsFuel. Строка с
    # опознанной номенклатурой — продажа магазина, а не повод обнулить смену.
    if kind == "retail_sale_sidegoods" and _edge_line_identity_present(line):
        return "store"
    purpose = _purpose_scope(
        line.get("МестоОприходования") or line.get("purpose")
        or document.get("МестоОприходования") or document.get("purpose")
    )
    if purpose is not None:
        return purpose
    if kind in {"production_release", "recipe", "ingredients_writeoff"}:
        return "food" if _edge_line_identity_present(line) else None
    # Все прочие документы станции товарные: топливо в них не заводят, а
    # топливная строка отсекается выше по IsFuel. Перечислять виды поимённо
    # значило забыть один — так и вышло с поступлением: 82 накладные висели с
    # нулевой суммой и без единой строки, потому что «purchase» в списке не был.
    return "store" if _edge_line_identity_present(line) else None


def _edge_sections(document: dict, kind: str) -> list[tuple[str, list[dict], int]]:
    sections: list[tuple[str, list[dict], int]] = []
    for section, key, sign in (
        ("goods", "Товары", 1),
        ("returns", "ВозвращенныеТовары", -1),
        ("goods", "ВыпускБлюд", 1),
        ("ingredients", "Ингредиенты", 1),
        ("services", "Услуги", 1),
    ):
        rows = document.get(key) or []
        if isinstance(rows, list):
            sections.append((section, [row for row in rows if isinstance(row, dict)], sign))
    return sections


def _projection_edge_document(document: dict) -> dict:
    """Представить станционное изменение цены как документ переоценки."""
    if str(document.get("Тип") or "").strip() != "price_change":
        return document
    source = str(document.get("ИсточникUUID") or "")
    return {
        **document,
        "Тип": "revaluation",
        "Номер": document.get("Номер") or (source[-12:] if source else None),
        "Дата": document.get("Момент"),
        "СуммаДокумента": 0,
        "Товары": [{
            "НоменклатураUUID": document.get("НоменклатураUUID"),
            "ШтрихКод": document.get("Штрихкод"),
            "ЦенаБыла": document.get("ЦенаБыла"),
            "ЦенаСтала": document.get("ЦенаСтала"),
            "Количество": 0,
            "Сумма": 0,
        }],
    }


def sanitize_edge_document(document: dict, *, trusted_station_packet: bool) -> dict:
    kind = str(document.get("Тип") or "").strip()
    if (not trusted_station_packet or kind not in PROJECTION_DOCUMENT_KINDS
            or kind in {"fiscal_receipt", "store_shift"}
            or _line_scope(document) == "fuel"):
        return {
            "amount": Decimal("0"), "vat_amount": None, "lines": [], "services": [],
            "quarantined": True, "pure_fuel": _line_scope(document) == "fuel",
            "reason": "Контур документа не подтверждён",
        }
    accepted: dict[str, list[tuple[dict, int]]] = {"lines": [], "services": []}
    rejected = 0
    fuel_lines = 0
    total_lines = 0
    for section, rows, sign in _edge_sections(document, kind):
        for line in rows:
            total_lines += 1
            scope = _edge_line_scope(kind, document, line)
            if scope == "fuel":
                fuel_lines += 1
                continue
            if scope not in {"store", "food"}:
                rejected += 1
                continue
            key = "services" if section == "services" else "lines"
            accepted[key].append((line, sign))
    amount = Decimal("0")
    vat = Decimal("0")
    vat_unknown = False
    for line, sign in accepted["lines"] + accepted["services"]:
        line_amount = _line_amount(line)
        amount += sign * line_amount
        if kind in EDGE_VAT_KINDS:
            line_vat, unknown = _line_vat(line, line_amount)
            vat += sign * line_vat
            vat_unknown = vat_unknown or unknown
    no_confirmed_lines = total_lines == 0 or not (accepted["lines"] or accepted["services"])
    quarantined = rejected > 0 or no_confirmed_lines or vat_unknown
    reasons = []
    if rejected:
        reasons.append("есть строки без подтверждённого контура/НСИ")
    if no_confirmed_lines:
        reasons.append("нет строк сопутки/общепита")
    if vat_unknown:
        reasons.append("не подтверждён НДС")
    return {
        "amount": (Decimal("0") if rejected else amount).quantize(Decimal("0.01")),
        "vat_amount": (None if rejected or vat_unknown
                       else vat.quantize(Decimal("0.01"))),
        "lines": [line for line, _ in accepted["lines"]],
        "services": [line for line, _ in accepted["services"]],
        "quarantined": quarantined,
        "pure_fuel": total_lines > 0 and fuel_lines == total_lines,
        "reason": "; ".join(reasons) or None,
        "fuel_lines": fuel_lines,
        "rejected_lines": rejected,
    }


# PROJECTION_RULES_VERSION — версия наших правил разбора, а не данных.
#
# Защита «тот же revision, другой hash» ловит подмену: источник переписал
# документ, не подняв версию. Но тот же хеш меняется и когда правила меняем мы
# сами — сняли ложную пометку, добавили поле. Без этой версии любая такая
# правка навсегда роняла пересборку реестра, и чинить приходилось руками, в
# базе. Меняется логика — поднимаем версию, и расхождение хеша на строках
# старой версии считается ожидаемым.
PROJECTION_RULES_VERSION = 2


def _candidate_hash(candidate: ProjectionCandidate) -> str:
    return _hash({
        "projection_source": candidate.projection_source,
        "source": candidate.source_kind,
        "source_record_id": candidate.source_record_id,
        "document_id": str(candidate.document_id),
        "accounting_group_id": str(candidate.accounting_group_id or ""),
        "source_document_id": str(candidate.source_document_id),
        "kind": candidate.document_kind,
        "role": candidate.document_role,
        "station_id": candidate.station_id,
        "organization_id": str(candidate.organization_id or ""),
        "warehouse_id": str(candidate.warehouse_id or ""),
        "number": candidate.number,
        "document_at": candidate.document_at,
        "counterparty_name": candidate.counterparty_name,
        "counterparty_inn": candidate.counterparty_inn,
        "amount": str(candidate.amount),
        "vat_amount": str(candidate.vat_amount),
        "author": candidate.author,
        "statuses": [candidate.operational_status, candidate.sync_status,
                     candidate.accounting_status, candidate.discrepancy_status],
        "flags": [candidate.requires_attention, candidate.has_fuel,
                  candidate.raw_payload_available],
        "header": candidate.header,
        "lines": [(line.section, line.source_line_id, line.ordinal) for line in candidate.lines],
        "relations": [
            (relation.kind, relation.target_ref,
             str(relation.related_document_id or ""), relation.metadata)
            for relation in candidate.relations
        ],
    })


async def _receipt_adapter(db: AsyncSession, company_id: uuid.UUID) -> list[ProjectionCandidate]:
    rows = (await db.execute(select(StoreReceipt).where(
        StoreReceipt.company_id == company_id))).scalars().all()
    receipt_ids = [row.id for row in rows]
    movement_rows = (await db.execute(select(StoreReceiptStockMovement).where(
        StoreReceiptStockMovement.company_id == company_id,
        StoreReceiptStockMovement.receipt_id.in_(receipt_ids),
    ))).scalars().all() if receipt_ids else []
    movements: dict[uuid.UUID, list[StoreReceiptStockMovement]] = {}
    for movement in movement_rows:
        movements.setdefault(movement.receipt_id, []).append(movement)
    out = []
    for row in rows:
        candidate = ProjectionCandidate(
            company_id=company_id,
            projection_source="store",
            source_kind="receipt",
            source_record_id=str(row.id),
            document_id=row.id,
            document_kind="purchase",
            priority=500,
            document_role="primary_evidence",
            station_id=row.station_id,
            organization_id=row.organization_id,
            warehouse_id=row.warehouse_id,
            number=row.number,
            document_at=row.doc_date,
            counterparty_name=_counterparty((row.supplier_snapshot or {}).get("name"), row.supplier),
            counterparty_inn=(row.supplier_snapshot or {}).get("inn"),
            amount=_decimal(row.total_amount),
            vat_amount=_decimal(row.vat_amount),
            author=row.author,
            operational_status=row.status,
            sync_status="accepted" if row.status == "accepted" else "local",
            accounting_status=row.accounting_status,
            discrepancy_status="needs_review" if row.accounting_status == "needs_review" else "none",
            requires_attention=row.accounting_status == "needs_review",
            raw_payload_available=True,
            revision=max(1, int(row.accounting_revision or row.version or 1)),
            content_hash=row.content_hash,
            header={
                "incoming_number": row.incoming_number,
                # дата в JSONB только строкой: объект даты валит сериализацию
                # всей пересборки, а всплывает это лишь когда поле заполнено
                "incoming_date": _iso(row.incoming_date),
                "signature_status": row.signature_status,
                "delivery_scheme": row.delivery_scheme,
                # реквизиты исходного документа 1С: бухгалтерия сверяет по ним
                "contract": (row.contract_snapshot or {}).get("name"),
                "organization": (row.organization_snapshot or {}).get("name"),
                "warehouse": ((row.warehouse_snapshot or {}).get("name")
                              or row.receiving_warehouse),
            },
        )
        candidate.lines, ambiguous = _candidate_lines(
            row.lines or [], row.services or [])
        _mark_ambiguous_lines(candidate, ambiguous)
        candidate.relations = [ProjectionRelationRef(
            "stock_movement", f"movement:{movement.id}",
            metadata={"kind": movement.kind, "id": str(movement.id)}
        ) for movement in movements.get(row.id, [])]
        candidate.content_hash = candidate.content_hash or _candidate_hash(candidate)
        out.append(candidate)
    return out


def _edge_document_identity(packet: EdgePacket, document: dict, kind: str) -> tuple:
    """Что считать ОДНИМ документом станции.

    Агент пересобирает и досылает смену: одна смена лежит в `edge_packets` до
    девяти раз. Ключом нельзя брать ни `ИсточникUUID` (пересчитывается при
    пересборке), ни время закрытия (двигается на секунду), ни печатный номер
    смены (строится из даты открытия и склеивает две разные смены). Та же
    логика — в `store_reports._КЛЮЧ_ДОКУМЕНТА`.
    """
    if kind == "retail_sale_sidegoods":
        shift = (packet.payload or {}).get("Смена") or {}
        internal = str(shift.get("НомерСменыВнутр") or "").strip()
        # у служебных пакетов внутренний номер равен "0" — иначе они схлопнутся
        # все в один документ продаж
        tail = (f"смена:{internal}" if internal and internal != "0"
                else f"пакет:{packet.packet_uuid}")
    else:
        number = str(document.get("Номер") or "").strip()
        tail = f"номер:{number}" if number else f"тело:{_hash(document)}"
    return (packet.station_id, kind, tail)


async def _edge_adapter(db: AsyncSession, company_id: uuid.UUID) -> list[ProjectionCandidate]:
    packets = (await db.execute(select(EdgePacket).where(
        EdgePacket.company_id == company_id))).scalars().all()
    # Приёмка приезжает пакетом и тут же разворачивается в реестр приёмок: это
    # один документ, а не два. Связь известна по source_uuid — без неё каждая
    # накладная стояла в реестре дважды, причём копия из пакета с нулевой
    # суммой, потому что её строки ещё не разобраны по контуру.
    receipt_by_source = {
        str(row.source_uuid): row.id
        for row in (await db.execute(select(StoreReceipt).where(
            StoreReceipt.company_id == company_id,
        ))).scalars().all()
        if getattr(row, "source_uuid", None)
    }
    # копия пакета — не второй документ: на ключ остаётся самая свежая доставка
    freshest: dict[tuple, tuple[datetime, str, ProjectionCandidate]] = {}
    for packet in packets:
        for index, document in enumerate((packet.payload or {}).get("Документы") or []):
            if not isinstance(document, dict):
                continue
            document = _projection_edge_document(document)
            kind = str(document.get("Тип") or "").strip()
            # чеки и смены приходят своим источником (архив кассы) и остаются
            # неучётным evidence: из пакета их сюда не пускаем вовсе
            if kind not in PROJECTION_DOCUMENT_KINDS or kind in {
                    "fiscal_receipt", "store_shift"}:
                continue
            raw_id = document.get("ИдентификаторДокумента") or document.get("ИсточникUUID")
            document_id = _uuid(raw_id) or _derived_uuid(
                company_id, "edge", f"{packet.packet_uuid}:{index}")
            приёмка = receipt_by_source.get(str(document.get("ИсточникUUID") or ""))
            if kind == "purchase" and приёмка is not None:
                document_id = приёмка
            source_record_id = f"{packet.packet_uuid}:{index}"
            has_fuel = bool(document.get("БылоТопливо") or document.get("has_fuel"))
            filtered = sanitize_edge_document(
                document, trusted_station_packet=True)
            if filtered["pure_fuel"]:
                continue
            candidate = ProjectionCandidate(
                company_id=company_id,
                projection_source="edge",
                source_kind="edge_document",
                source_record_id=source_record_id,
                document_id=document_id,
                document_kind=kind,
                priority=300,
                document_role="operational",
                shift_no=_shift_no(
                    ((packet.payload or {}).get("Смена") or {}).get("НомерСменыВнутр")),
                station_id=packet.station_id,
                number=document.get("Номер"),
                document_at=_datetime(document.get("Дата")) or packet.received_at,
                counterparty_name=_counterparty(document.get("Контрагент")),
                counterparty_inn=document.get("ИННКонтрагента"),
                amount=filtered["amount"],
                vat_amount=filtered["vat_amount"],
                author=document.get("Автор"),
                operational_status=str(document.get("Статус") or "received"),
                sync_status="received",
                accounting_status=("needs_review" if filtered["quarantined"]
                                   else str(document.get("СтатусБухгалтерии") or "pending")),
                discrepancy_status=("quarantined" if filtered["quarantined"]
                                    else "none"),
                requires_attention=bool(document.get("Ошибка") or document.get("ТребуетВнимания")
                                        or filtered["quarantined"]),
                has_fuel=has_fuel,
                raw_payload_available=True,
                revision=_revision(packet.received_at),
                header={
                    "warehouse": document.get("Склад") or document.get("СкладОтправитель"),
                    "warehouse_to": document.get("СкладПолучатель"),
                    "incoming_number": document.get("НомерВходящегоДокумента"),
                    "packet_uuid": packet.packet_uuid,
                    "document_index": index,
                    "goods_classification": (
                        "quarantined" if filtered["quarantined"] else "store_food"),
                    "classification_error": filtered["reason"],
                    "item_uuid": document.get("НоменклатураUUID"),
                    "barcode": document.get("Штрихкод"),
                    "old_price": document.get("ЦенаБыла"),
                    "new_price": document.get("ЦенаСтала"),
                    "reason": document.get("Причина"),
                },
            )
            candidate.lines, ambiguous = _candidate_lines(
                filtered["lines"], filtered["services"])
            _mark_ambiguous_lines(candidate, ambiguous)
            candidate.content_hash = _candidate_hash(candidate)
            identity = _edge_document_identity(packet, document, kind)
            received_at = packet.received_at or datetime.min.replace(tzinfo=timezone.utc)
            previous = freshest.get(identity)
            if previous is None or (received_at, str(packet.packet_uuid)) > previous[:2]:
                freshest[identity] = (received_at, str(packet.packet_uuid), candidate)
    return [item[2] for item in freshest.values()]


async def _cheque_adapter(db: AsyncSession, company_id: uuid.UUID) -> list[ProjectionCandidate]:
    rows = (await db.execute(select(StoreCheque).where(
        StoreCheque.company_id == company_id))).scalars().all()
    packet_uuids = sorted({
        str(row.packet_uuid) for row in rows if getattr(row, "packet_uuid", None)})
    packet_rows = (await db.execute(select(EdgePacket).where(
        EdgePacket.company_id == company_id,
        EdgePacket.packet_uuid.in_(packet_uuids),
    ))).scalars().all() if packet_uuids else []
    packets = {str(row.packet_uuid): row for row in packet_rows}
    catalog = await load_item_catalog(db)
    out: list[ProjectionCandidate] = []
    shifts: dict[tuple[int, int], list[tuple[StoreCheque, ProjectionCandidate]]] = {}
    rows = sorted(rows, key=lambda row: (row.station_id, row.shift_number, row.at, str(row.id)))
    for row in rows:
        classified_lines = cheque_lines_from_catalog(
            cheque_lines_with_legacy_provenance(
                row, packets.get(str(getattr(row, "packet_uuid", "")))),
            catalog)
        totals = goods_only_cheque_totals(classified_lines, bool(row.had_fuel))
        if ((row.had_fuel and not row.lines)
                or (row.lines and totals["fuel_lines"] == len(row.lines))):
            continue
        candidate = ProjectionCandidate(
            company_id=company_id,
            projection_source="cash",
            source_kind="cheque",
            source_record_id=str(row.id),
            document_id=row.id,
            document_kind="fiscal_receipt",
            priority=450,
            document_role="fiscal",
            shift_no=_shift_no(row.shift_number),
            station_id=row.station_id,
            number=str(row.number),
            document_at=row.at,
            amount=totals["amount"],
            vat_amount=totals["vat_amount"],
            operational_status="return" if row.is_return else "sale",
            sync_status="received",
            accounting_status="not_applicable",
            discrepancy_status="quarantined" if totals["quarantined"] else "none",
            requires_attention=bool(totals["quarantined"]),
            has_fuel=bool(row.had_fuel),
            raw_payload_available=True,
            revision=max(1, int(row.version or 1)),
            header={
                "shift_number": row.shift_number,
                "cash_no": getattr(row, "cash_no", 0),
                "cash_key": getattr(row, "cash_key", f"0:{row.number}"),
                "fiscal_number": row.fiscal_number,
                "pay_name": row.pay_name,
                "is_return": row.is_return,
                "goods_classification": "quarantined" if totals["quarantined"] else "store_food",
                "classification_error": totals["reason"],
            },
        )
        candidate.lines, ambiguous = _candidate_lines(totals["lines"])
        _mark_ambiguous_lines(candidate, ambiguous)
        candidate.content_hash = _candidate_hash(candidate)
        out.append(candidate)
        shifts.setdefault((row.station_id, row.shift_number), []).append((row, candidate))

    for (station_id, shift_number), items in sorted(shifts.items()):
        items = sorted(items, key=lambda item: (item[0].at, str(item[0].id)))
        shift_document_id = _derived_uuid(company_id, "store_shift", f"{station_id}:{shift_number}")
        # Смену уводит в карантин только НЕРАЗОБРАННАЯ классификация чека, а не
        # любой повод обратить внимание. Иначе туда попадала каждая смена, где
        # покупатель взял две одинаковых позиции: строки без своего
        # идентификатора дают одинаковый ключ, и чек помечается
        # «line_identity_ambiguous». Для розницы это норма, суммы при этом
        # сходятся, и разводятся такие строки суффиксом порядка.
        quarantined = any(candidate.discrepancy_status == "quarantined"
                          for _, candidate in items)
        shift_vat = (None if any(candidate.vat_amount is None for _, candidate in items)
                     else sum((candidate.vat_amount for _, candidate in items), Decimal("0")))
        shift = ProjectionCandidate(
            company_id=company_id,
            projection_source="cash",
            source_kind="store_shift",
            source_record_id=f"{station_id}:{shift_number}",
            document_id=shift_document_id,
            document_kind="store_shift",
            priority=440,
            document_role="fiscal",
            shift_no=_shift_no(shift_number),
            station_id=station_id,
            number=str(shift_number),
            document_at=max(row.at for row, _ in items),
            amount=sum((candidate.amount for _, candidate in items), Decimal("0")),
            vat_amount=shift_vat,
            operational_status="closed",
            sync_status="received",
            accounting_status="not_applicable",
            discrepancy_status="quarantined" if quarantined else "none",
            requires_attention=quarantined,
            has_fuel=any(bool(row.had_fuel) for row, _ in items),
            revision=sum(max(1, int(row.version or 1)) for row, _ in items),
            header={"cheques": len(items)},
            relations=[ProjectionRelationRef(
                "contains_cheque", f"cheque:{candidate.record_id}", candidate.document_id
            ) for _, candidate in items],
        )
        shift.content_hash = _candidate_hash(shift)
        out.append(shift)
        for _, candidate in items:
            candidate.relations.append(ProjectionRelationRef(
                "belongs_to_shift", f"shift:{shift.record_id}", shift.document_id
            ))
            candidate.content_hash = _candidate_hash(candidate)
    return out


async def _canonical_adapter(db: AsyncSession, company_id: uuid.UUID) -> list[ProjectionCandidate]:
    rows = (await db.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.document_id.is_not(None),
    ))).scalars().all()
    out = []
    for row in rows:
        accounting_scope = _data_entry_scope(row)
        if accounting_scope is None:
            continue
        meta = row.meta or {}
        document_meta = meta.get("document")
        if not isinstance(document_meta, dict):
            document_meta = {}
        kind = str(row.doc_type_id or meta.get("kind") or meta.get("Тип") or "")
        if kind not in PROJECTION_DOCUMENT_KINDS:
            continue
        candidate = ProjectionCandidate(
            company_id=company_id,
            projection_source=str(row.fact_origin or "store"),
            source_kind="canonical_entry",
            source_record_id=str(row.id),
            document_id=row.document_id,
            document_kind=kind,
            priority=400,
            document_role="primary_evidence",
            accounting_group_id=_uuid(
                meta.get("accounting_group_id")
                or document_meta.get("accounting_group_id")
            ),
            station_id=_station(meta.get("station_id") or meta.get("КодАЗС")),
            number=meta.get("number") or meta.get("Номер"),
            document_at=_datetime(meta.get("date") or meta.get("Дата")) or row.created_at,
            counterparty_name=_counterparty(meta.get("supplier"), meta.get("Контрагент")),
            counterparty_inn=meta.get("supplier_inn") or meta.get("ИННКонтрагента"),
            amount=_decimal(meta.get("total_amount") or meta.get("СуммаДокумента")),
            vat_amount=_decimal(meta.get("vat_amount") or meta.get("СуммаНДС")),
            operational_status=row.status,
            sync_status="canonical",
            accounting_status="ready" if row.status in {"verified", "transferred"} else "pending",
            raw_payload_available=True,
            revision=max(1, int(row.revision or 1)),
            content_hash=row.content_hash,
            header={"title": row.title, "layer": row.layer,
                    "fact_origin": row.fact_origin, "accounting_scope": accounting_scope},
        )
        candidate.content_hash = candidate.content_hash or _candidate_hash(candidate)
        out.append(candidate)
    return out


def _accounting_kind(value: str) -> str | None:
    name = value.casefold().replace("ё", "е")
    for needle, kind in (
        ("корректировкапоступления", "return_purchase"),
        ("возвраттоваровпоставщику", "return_purchase"),
        ("поступлен", "purchase"),
        ("отчеторозничныхпродажах", "retail_sale_sidegoods"),
        ("корректировкареализации", "return_sale"),
        ("возвраттоваровотпокупателя", "return_sale"),
        ("инвентаризац", "inventory"),
        ("списани", "writeoff"),
        ("перемещен", "transfer"),
        ("отчетпроизводства", "production_release"),
    ):
        if needle in re.sub(r"[^a-zа-я0-9]", "", name):
            return kind
    return None


def _onec_scope(company: object) -> tuple[datetime | None, frozenset[int]]:
    """С какого дня и по каким станциям берём документы центральной базы.

    В ЦБ лежит вся история сети с 2016 года по всем АЗС. В разделе нужны
    документы станции, перешедшей на наш контур, и только с даты перехода —
    остальное к работе товароведа отношения не имеет. Границы объявляются в
    настройках компании, а не зашиты в код: у следующей станции они свои.
    """
    edge = ((getattr(company, "customization", None) or {}).get("edge") or {})
    начало = _datetime(edge.get("onec_documents_from"))
    станции: set[int] = set()
    for значение in edge.get("onec_documents_stations") or []:
        try:
            станции.add(int(значение))
        except (TypeError, ValueError):
            continue
    return начало, frozenset(станции)


def _onec_in_scope(
    station_id: int | None, document_at: datetime | None,
    начало: datetime | None, станции: frozenset[int],
) -> bool:
    if станции and (station_id is None or station_id not in станции):
        return False
    if начало is not None and (document_at is None or document_at < начало):
        return False
    return True


async def _onec_adapter(db: AsyncSession, company_id: uuid.UUID) -> list[ProjectionCandidate]:
    out: list[ProjectionCandidate] = []
    company = await db.get(Company, company_id)
    начало, станции = _onec_scope(company)
    entries = {row.id: row for row in (await db.execute(select(DataEntry).where(
        DataEntry.company_id == company_id,
        DataEntry.document_id.is_not(None),
    ))).scalars().all()}
    scoped_entries = {
        row.document_id: row for row in entries.values()
        if row.document_id is not None and _data_entry_scope(row) is not None
    }
    source_links = (await db.execute(select(AccountingSourceLink).where(
        AccountingSourceLink.company_id == company_id))).scalars().all()
    confirmed_links = {
        (row.projection_source, row.source_kind, row.source_document_id): row
        for row in source_links if row.canonical_document_id in scoped_entries
    }

    def confirmed(
        projection_source: str, kind: str, source_document_id: uuid.UUID,
    ) -> AccountingSourceLink | None:
        return confirmed_links.get((projection_source, kind, source_document_id))

    inventories = (await db.execute(select(CbInventoryDoc).where(
        CbInventoryDoc.company_id == company_id))).scalars().all()
    for row in inventories:
        source_document_id = _uuid(row.external_ref) or _derived_uuid(
            company_id, "cb_inventory", row.external_ref)
        # Документ центральной базы — самостоятельный факт: он заведён в 1С и
        # проведён в бухгалтерии. Подтверждённая связь склеивает его с нашим
        # документом, когда она есть; без неё документ показывается сам по себе,
        # а не прячется из реестра.
        link = confirmed("onec_legacy", "inventory", source_document_id)
        station_id = _station(row.warehouse_code or row.warehouse_name)
        if not _onec_in_scope(station_id, _datetime(row.doc_date), начало, станции):
            continue
        candidate = ProjectionCandidate(
            company_id=company_id,
            projection_source="onec_legacy", source_kind="onec_inventory",
            source_record_id=str(row.id), source_document_id=source_document_id,
            document_id=(link.canonical_document_id if link else source_document_id),
            document_kind="inventory", priority=200,
            document_role="accounting_derived",
            station_id=_station(row.warehouse_code or row.warehouse_name),
            number=row.number, document_at=_datetime(row.doc_date),
            amount=_decimal(row.net_amount), operational_status="posted" if row.posted else "unposted",
            sync_status="onec_snapshot", accounting_status="accepted" if row.posted else "pending",
            raw_payload_available=False, revision=_revision(row.snapshot_at),
            header={"warehouse": row.warehouse_name, "source": "cb_inventory"},
        )
        candidate.lines, ambiguous = _candidate_lines(row.lines or [])
        _mark_ambiguous_lines(candidate, ambiguous)
        candidate.content_hash = _candidate_hash(candidate)
        out.append(candidate)
    movements = (await db.execute(select(CbMovementDoc).where(
        CbMovementDoc.company_id == company_id))).scalars().all()
    for row in movements:
        if row.kind not in PROJECTION_DOCUMENT_KINDS:
            continue
        source_document_id = _uuid(row.external_ref) or _derived_uuid(
            company_id, "cb_movement", row.external_ref)
        link = confirmed("onec_legacy", row.kind, source_document_id)
        station_id = _station(row.warehouse_code or row.warehouse_name)
        if not _onec_in_scope(station_id, _datetime(row.doc_date), начало, станции):
            continue
        candidate = ProjectionCandidate(
            company_id=company_id,
            projection_source="onec_legacy", source_kind="onec_movement",
            source_record_id=str(row.id), source_document_id=source_document_id,
            document_id=(link.canonical_document_id if link else source_document_id),
            document_kind=row.kind, priority=200,
            document_role="accounting_derived",
            station_id=_station(row.warehouse_code or row.warehouse_name),
            number=row.number, document_at=_datetime(row.doc_date), amount=_decimal(row.total_amount),
            operational_status="posted" if row.posted else "unposted",
            sync_status="onec_snapshot", accounting_status="accepted" if row.posted else "pending",
            raw_payload_available=False, revision=_revision(row.snapshot_at),
            header={"warehouse": row.warehouse_name, "warehouse_to": row.warehouse_to_name,
                    "source": "cb_movement"},
        )
        if row.inventory_ref:
            candidate.relations.append(ProjectionRelationRef(
                "inventory_basis", f"onec_inventory:{row.inventory_ref}",
                _uuid(row.inventory_ref),
            ))
        candidate.lines, ambiguous = _candidate_lines(row.lines or [])
        _mark_ambiguous_lines(candidate, ambiguous)
        candidate.content_hash = _candidate_hash(candidate)
        out.append(candidate)

    docs = (await db.execute(select(AccountingDoc).where(
        AccountingDoc.company_id == company_id,
        AccountingDoc.matched_entry_id.is_not(None),
    ))).scalars().all()
    for row in docs:
        entry = entries.get(row.matched_entry_id)
        kind = _accounting_kind(row.doc_type)
        if (entry is None or entry.document_id is None
                or _data_entry_scope(entry) is None
                or kind not in ACCOUNTING_DOCUMENT_KINDS):
            continue
        source_document_id = _uuid(row.external_id) or _derived_uuid(
            company_id, "bp", row.external_id)
        link = confirmed("bp", kind, source_document_id)
        if not _onec_in_scope(_station(row.warehouse_code), _datetime(row.date),
                              начало, станции):
            continue
        candidate = ProjectionCandidate(
            company_id=company_id,
            projection_source="bp", source_kind="accounting_doc",
            source_record_id=str(row.id), source_document_id=source_document_id,
            document_id=(link.canonical_document_id if link else entry.document_id),
            document_kind=kind, priority=100,
            document_role="accounting_derived",
            station_id=_station(row.warehouse_code), number=row.number,
            document_at=_datetime(row.date), counterparty_name=_counterparty(row.counterparty_name),
            counterparty_inn=row.counterparty_inn, amount=_decimal(row.amount),
            vat_amount=_decimal(row.vat_amount), operational_status=row.status_1c,
            sync_status="accepted", accounting_status="accepted",
            discrepancy_status=row.discrepancy_status,
            requires_attention=row.discrepancy_status not in {"none", "pending", "rounding"},
            raw_payload_available=True, revision=_revision(row.updated_at),
            header={"operation_type": row.operation_type, "period_status": row.period_status,
                    "external_number": row.external_number},
            relations=[ProjectionRelationRef(
                "accounting_result", f"entry:{entry.id}", entry.document_id
            )],
        )
        if isinstance(row.lines, list):
            candidate.lines, ambiguous = _candidate_lines(row.lines)
            _mark_ambiguous_lines(candidate, ambiguous)
        candidate.content_hash = _candidate_hash(candidate)
        out.append(candidate)
    return out


async def _accounting_outbox_adapter(
    db: AsyncSession, company_id: uuid.UUID,
) -> list[ProjectionCandidate]:
    rows = (await db.execute(select(ExportPacket).where(
        ExportPacket.company_id == company_id,
        ExportPacket.kind.in_(("store_accounting_group", "food_accounting_group")),
    ))).scalars().all()
    out = []
    for row in rows:
        payload = row.payload or {}
        if not isinstance(payload, dict):
            continue
        documents = payload.get("Документы") or []
        if not isinstance(documents, list):
            continue
        group_id = _uuid(payload.get("accounting_group_id"))
        for index, document in enumerate(documents):
            if not isinstance(document, dict):
                continue
            kind = str(document.get("Тип") or "").strip()
            if kind not in ACCOUNTING_DOCUMENT_KINDS:
                continue
            document_id = _uuid(
                document.get("document_id") or document.get("ИсточникUUID"))
            if document_id is None:
                continue
            candidate = ProjectionCandidate(
                company_id=company_id,
                projection_source=str(row.fact_origin or "store"),
                source_kind="accounting_packet",
                source_record_id=f"{row.id}:{index}",
                source_document_id=document_id,
                document_id=document_id,
                document_kind=kind,
                priority=250,
                document_role="accounting_derived",
                accounting_group_id=(
                    _uuid(document.get("accounting_group_id")) or group_id),
                station_id=_station(document.get("station_id") or document.get("КодАЗС")),
                organization_id=_uuid(document.get("organization_id")),
                warehouse_id=_uuid(document.get("warehouse_id")),
                number=document.get("Номер"),
                document_at=_datetime(document.get("Дата")) or row.created_at,
                counterparty_name=(document.get("supplier_snapshot") or {}).get("name")
                if isinstance(document.get("supplier_snapshot"), dict) else None,
                counterparty_inn=(document.get("supplier_snapshot") or {}).get("inn")
                if isinstance(document.get("supplier_snapshot"), dict) else None,
                amount=_decimal(document.get("СуммаДокумента") or document.get("total_amount")),
                vat_amount=_decimal(document.get("СуммаНДС") or document.get("vat_amount")),
                operational_status="accounting_outbox",
                sync_status=row.status,
                accounting_status=row.status,
                requires_attention=row.status in {"rejected", "needs_review"},
                raw_payload_available=True,
                revision=max(1, int(row.revision or 1)),
                content_hash=(str(document.get("content_hash") or "").lower()
                              or row.content_hash),
                header={
                    "packet_uuid": str(row.packet_uuid or ""),
                    "packet_kind": row.kind,
                    "contract_version": row.contract_version,
                    "transport_producer": row.transport_producer,
                    "attempt_id": str(row.attempt_id or "") or None,
                    "error_code": row.error_code,
                    "document_index": index,
                },
            )
            candidate.content_hash = candidate.content_hash or _candidate_hash(candidate)
            out.append(candidate)
    return out


ADAPTER_REGISTRY = (
    ("onec_headers", _onec_adapter),
    ("edge_documents", _edge_adapter),
    ("canonical_entries", _canonical_adapter),
    ("accounting_outbox", _accounting_outbox_adapter),
    ("store_receipts", _receipt_adapter),
    ("store_cheques", _cheque_adapter),
)


ROW_FIELDS = (
    "document_id", "accounting_group_id", "shift_no", "projection_source", "source_kind",
    "source_record_id", "source_document_id", "document_kind", "document_role", "station_id",
    "organization_id", "warehouse_id", "number", "document_at", "counterparty_name",
    "counterparty_inn", "amount", "vat_amount", "author", "operational_status",
    "sync_status", "accounting_status", "discrepancy_status", "requires_attention",
    "has_files", "has_fuel", "raw_payload_available", "is_primary", "revision",
    "content_hash", "header",
)


def _row_values(candidate: ProjectionCandidate, *, primary: bool, has_files: bool) -> dict:
    header = dict(candidate.header or {})
    header["rules_version"] = PROJECTION_RULES_VERSION
    return {
        "document_id": candidate.document_id,
        "accounting_group_id": candidate.accounting_group_id,
        "shift_no": candidate.shift_no,
        "projection_source": candidate.projection_source,
        "source_kind": candidate.source_kind,
        "source_record_id": candidate.source_record_id,
        "source_document_id": candidate.source_document_id,
        "document_kind": candidate.document_kind,
        "document_role": candidate.document_role,
        "station_id": candidate.station_id,
        "organization_id": candidate.organization_id,
        "warehouse_id": candidate.warehouse_id,
        "number": candidate.number,
        "document_at": candidate.document_at,
        "counterparty_name": candidate.counterparty_name,
        "counterparty_inn": candidate.counterparty_inn,
        "amount": candidate.amount,
        "vat_amount": candidate.vat_amount,
        "author": candidate.author,
        "operational_status": candidate.operational_status,
        "sync_status": candidate.sync_status,
        "accounting_status": candidate.accounting_status,
        "discrepancy_status": candidate.discrepancy_status,
        "requires_attention": candidate.requires_attention,
        "has_files": has_files,
        "has_fuel": candidate.has_fuel,
        "raw_payload_available": candidate.raw_payload_available,
        "is_primary": primary,
        "revision": candidate.revision,
        "content_hash": candidate.content_hash,
        "header": header,
    }


async def rebuild_store_document_projection(
    db: AsyncSession, company_id: uuid.UUID,
) -> dict:
    await db.execute(ADVISORY_LOCK, {"scope_key": f"store-documents:{company_id}"})
    candidates: list[ProjectionCandidate] = []
    adapter_counts: dict[str, int] = {}
    for name, adapter in ADAPTER_REGISTRY:
        rows = await adapter(db, company_id)
        for row in rows:
            if row.document_kind not in PROJECTION_DOCUMENT_KINDS:
                raise ValueError(f"Adapter {name} вернул запрещённый kind {row.document_kind}")
            if any(key in row.header for key in ("lines", "Товары", "services", "Услуги", "payload")):
                raise ValueError(f"Adapter {name} попытался скопировать payload/строки в проекцию")
        adapter_counts[name] = len(rows)
        candidates.extend(rows)

    source_links = (await db.execute(select(AccountingSourceLink).where(
        AccountingSourceLink.company_id == company_id))).scalars().all()
    links = {
        (link.projection_source, link.source_kind, link.source_document_id): link.canonical_document_id
        for link in source_links
    }
    source_candidates: dict[tuple[str, str, uuid.UUID], list[ProjectionCandidate]] = {}
    for candidate in candidates:
        source_candidates.setdefault(
            (candidate.projection_source, candidate.document_kind,
             candidate.source_document_id), [],
        ).append(candidate)
        candidate.document_id = links.get(
            (candidate.projection_source, candidate.document_kind,
             candidate.source_document_id),
            candidate.document_id,
        )

    by_document: dict[uuid.UUID, list[ProjectionCandidate]] = {}
    by_record: dict[uuid.UUID, ProjectionCandidate] = {}
    for candidate in candidates:
        if candidate.record_id in by_record:
            other = by_record[candidate.record_id]
            if other.content_hash != candidate.content_hash:
                raise ProjectionRevisionConflict(
                    f"Один source-record {candidate.source_kind}:{candidate.source_record_id} "
                    "дал разные документы в одном rebuild"
                )
            continue
        by_record[candidate.record_id] = candidate
        by_document.setdefault(candidate.document_id, []).append(candidate)
    primary_ids = {
        max(rows, key=lambda item: (item.priority, item.revision, str(item.record_id))).record_id
        for rows in by_document.values()
    }

    files = (await db.execute(select(StoreDocFile).where(
        StoreDocFile.company_id == company_id,
        StoreDocFile.tombstoned_at.is_(None),
    ))).scalars().all()
    files_by_record = {row.record_id for row in files if row.record_id is not None}
    files_by_ref = {row.doc_ref for row in files}
    records_with_files = set(files_by_record)
    for candidate in candidates:
        legacy_ref = (
            f"receipt:{candidate.source_record_id}"
            if candidate.source_kind == "receipt"
            else f"station:{candidate.source_record_id}"
            if candidate.source_kind == "edge_document"
            else None
        )
        if legacy_ref and legacy_ref in files_by_ref:
            records_with_files.add(candidate.record_id)
    existing = (await db.execute(select(StoreDocumentProjection).where(
        StoreDocumentProjection.company_id == company_id).with_for_update()
    )).scalars().all()
    existing_by_id = {row.id: row for row in existing}
    created = updated = unchanged = 0
    now = datetime.now(timezone.utc)
    for record_id, candidate in by_record.items():
        values = _row_values(
            candidate, primary=record_id in primary_ids,
            has_files=record_id in records_with_files,
        )
        current = existing_by_id.get(record_id)
        if current is None:
            db.add(StoreDocumentProjection(
                id=record_id, company_id=company_id, rebuilt_at=now, **values))
            created += 1
            continue
        if candidate.revision < current.revision:
            raise ProjectionRevisionConflict(
                f"Source-record {candidate.source_record_id}: revision {candidate.revision} "
                f"меньше сохранённой {current.revision}"
            )
        по_тем_же_правилам = (
            (current.header or {}).get("rules_version") == PROJECTION_RULES_VERSION)
        if (по_тем_же_правилам and candidate.revision == current.revision
                and current.content_hash and candidate.content_hash
                and current.content_hash != candidate.content_hash):
            raise ProjectionRevisionConflict(
                f"Source-record {candidate.source_record_id}: тот же revision с другим hash"
            )
        changed = False
        for key, value in values.items():
            if getattr(current, key) != value:
                setattr(current, key, value)
                changed = True
        if changed:
            current.rebuilt_at = now
            updated += 1
        else:
            unchanged += 1

    stale_ids = set(existing_by_id) - set(by_record)
    if stale_ids:
        await db.execute(delete(StoreDocumentProjection).where(
            StoreDocumentProjection.company_id == company_id,
            StoreDocumentProjection.id.in_(stale_ids),
        ))

    desired_lines: dict[uuid.UUID, tuple[uuid.UUID, ProjectionLineRef]] = {}
    for candidate in by_record.values():
        for line in candidate.lines:
            line_id = uuid.uuid5(
                PROJECTION_NAMESPACE,
                f"line:{candidate.record_id}:{line.section}:{line.source_line_id}",
            )
            desired_lines[line_id] = (candidate.record_id, line)
    existing_lines = (await db.execute(select(StoreDocumentProjectionLine).where(
        StoreDocumentProjectionLine.company_id == company_id))).scalars().all()
    existing_line_map = {row.id: row for row in existing_lines}
    existing_line_ids = set(existing_line_map)
    obsolete_lines = existing_line_ids - set(desired_lines)
    if obsolete_lines:
        await db.execute(delete(StoreDocumentProjectionLine).where(
            StoreDocumentProjectionLine.id.in_(obsolete_lines)))
    for line_id, (record_id, line) in desired_lines.items():
        if line_id not in existing_line_map:
            db.add(StoreDocumentProjectionLine(
                id=line_id, company_id=company_id, record_id=record_id,
                source_section=line.section, source_line_id=line.source_line_id,
                ordinal=line.ordinal,
            ))
        elif existing_line_map[line_id].ordinal != line.ordinal:
            existing_line_map[line_id].ordinal = line.ordinal

    desired_relations: dict[uuid.UUID, tuple[uuid.UUID, ProjectionRelationRef, uuid.UUID | None]] = {}
    primary_by_document = {
        document_id: next(row.record_id for row in rows if row.record_id in primary_ids)
        for document_id, rows in by_document.items()
    }
    for candidate in by_record.values():
        for relation in candidate.relations:
            related = primary_by_document.get(relation.related_document_id)
            relation_id = uuid.uuid5(
                PROJECTION_NAMESPACE,
                f"relation:{candidate.record_id}:{relation.kind}:{relation.target_ref}",
            )
            desired_relations[relation_id] = (candidate.record_id, relation, related)
    for document_id, rows in by_document.items():
        if len(rows) < 2:
            continue
        primary_record = primary_by_document[document_id]
        for candidate in rows:
            if candidate.record_id == primary_record:
                continue
            for source_record, related_record, relation_kind in (
                (primary_record, candidate.record_id, "source_evidence"),
                (candidate.record_id, primary_record, "canonical_view"),
            ):
                target_ref = f"record:{related_record}"
                relation = ProjectionRelationRef(
                    relation_kind, target_ref, document_id,
                    {"source_kind": candidate.source_kind},
                )
                relation_id = uuid.uuid5(
                    PROJECTION_NAMESPACE,
                    f"relation:{source_record}:{relation_kind}:{target_ref}",
                )
                desired_relations[relation_id] = (
                    source_record, relation, related_record,
                )
    by_accounting_group: dict[uuid.UUID, list[ProjectionCandidate]] = {}
    for candidate in by_record.values():
        if candidate.accounting_group_id is not None:
            by_accounting_group.setdefault(candidate.accounting_group_id, []).append(candidate)
    for accounting_group_id, rows in by_accounting_group.items():
        if len(rows) < 2:
            continue
        anchor = max(
            rows, key=lambda item: (item.priority, item.revision, str(item.record_id)))
        for candidate in rows:
            if candidate.record_id == anchor.record_id:
                continue
            for source_record, related_record in (
                (anchor.record_id, candidate.record_id),
                (candidate.record_id, anchor.record_id),
            ):
                target_ref = f"record:{related_record}"
                relation = ProjectionRelationRef(
                    "accounting_group_member", target_ref, candidate.document_id,
                    {"accounting_group_id": str(accounting_group_id)},
                )
                relation_id = uuid.uuid5(
                    PROJECTION_NAMESPACE,
                    f"relation:{source_record}:{relation.kind}:{target_ref}",
                )
                desired_relations[relation_id] = (
                    source_record, relation, related_record,
                )
    for link in source_links:
        target_record = primary_by_document.get(link.canonical_document_id)
        scoped_sources = source_candidates.get(
            (link.projection_source, link.source_kind, link.source_document_id), [])
        if not scoped_sources or target_record is None:
            continue
        source_record = max(
            scoped_sources, key=lambda item: (item.priority, item.revision,
                                              str(item.record_id))).record_id
        if source_record == target_record:
            continue
        relation = ProjectionRelationRef(
            "canonical_source", f"record:{target_record}", link.canonical_document_id,
            {"confirmed_at": link.confirmed_at.isoformat()},
        )
        relation_id = uuid.uuid5(
            PROJECTION_NAMESPACE,
            f"relation:{source_record}:{relation.kind}:{relation.target_ref}",
        )
        desired_relations[relation_id] = (source_record, relation, target_record)
    existing_relations = (await db.execute(select(StoreDocumentRelation).where(
        StoreDocumentRelation.company_id == company_id))).scalars().all()
    existing_relation_map = {row.id: row for row in existing_relations}
    existing_relation_ids = set(existing_relation_map)
    obsolete_relations = existing_relation_ids - set(desired_relations)
    if obsolete_relations:
        await db.execute(delete(StoreDocumentRelation).where(
            StoreDocumentRelation.id.in_(obsolete_relations)))
    for relation_id, (record_id, relation, related) in desired_relations.items():
        if relation_id not in existing_relation_map:
            db.add(StoreDocumentRelation(
                id=relation_id, company_id=company_id, record_id=record_id,
                related_record_id=related, relation_kind=relation.kind,
                target_ref=relation.target_ref, metadata_json=relation.metadata,
            ))
        else:
            current = existing_relation_map[relation_id]
            current.related_record_id = related
            current.metadata_json = relation.metadata
    await db.flush()
    return {
        "created": created, "updated": updated, "unchanged": unchanged,
        "removed": len(stale_ids), "records": len(by_record),
        "line_refs": len(desired_lines), "relations": len(desired_relations),
        "adapters": adapter_counts,
    }


async def normalized_document_payload(
    db: AsyncSession, row: StoreDocumentProjection,
) -> dict:
    if row.source_kind == "receipt":
        receipt = await db.get(StoreReceipt, uuid.UUID(row.source_record_id))
        if receipt is None or receipt.company_id != row.company_id:
            return {"status": "source_missing", "lines": [], "services": []}
        return {
            "status": receipt.status,
            "lines": list(receipt.lines or []),
            "services": list(receipt.services or []),
            "evidence": dict(receipt.evidence or {}),
        }
    if row.source_kind == "edge_document":
        packet_uuid, index_raw = row.source_record_id.rsplit(":", 1)
        packet = (await db.execute(select(EdgePacket).where(
            EdgePacket.company_id == row.company_id,
            EdgePacket.packet_uuid == packet_uuid,
        ))).scalar_one_or_none()
        documents = (packet.payload or {}).get("Документы") or [] if packet else []
        index = int(index_raw)
        return (_projection_edge_document(documents[index])
                if index < len(documents) else {"status": "source_missing"})
    if row.source_kind == "cheque":
        cheque = await db.get(StoreCheque, uuid.UUID(row.source_record_id))
        if cheque is None or cheque.company_id != row.company_id:
            return {"status": "source_missing", "lines": []}
        packet = None
        if cheque.packet_uuid:
            packet = (await db.execute(select(EdgePacket).where(
                EdgePacket.company_id == row.company_id,
                EdgePacket.packet_uuid == cheque.packet_uuid,
                EdgePacket.station_id == cheque.station_id,
            ))).scalar_one_or_none()
        totals = goods_only_cheque_totals(
            cheque_lines_from_catalog(
                cheque_lines_with_legacy_provenance(cheque, packet),
                await load_item_catalog(db)),
            bool(cheque.had_fuel))
        return {
            "status": "quarantined" if totals["quarantined"] else "ready",
            "lines": totals["lines"], "has_fuel": bool(cheque.had_fuel),
            "amount": totals["amount"], "vat_amount": totals["vat_amount"],
            "classification_error": totals["reason"],
        }
    if row.source_kind == "canonical_entry":
        entry = (await db.execute(select(DataEntry).where(
            DataEntry.id == uuid.UUID(row.source_record_id),
            DataEntry.company_id == row.company_id,
        ))).scalar_one_or_none()
        return {"status": entry.status, "metadata": entry.meta or {}} if entry else {
            "status": "source_missing"}
    if row.source_kind == "accounting_doc":
        doc = (await db.execute(select(AccountingDoc).where(
            AccountingDoc.id == uuid.UUID(row.source_record_id),
            AccountingDoc.company_id == row.company_id,
        ))).scalar_one_or_none()
        return {
            "status": doc.status_1c, "external_id": doc.external_id,
            "lines": doc.lines or [], "result": doc.match_details or {},
        } if doc else {"status": "source_missing"}
    if row.source_kind == "accounting_packet":
        packet_id, _, index_raw = row.source_record_id.partition(":")
        packet = (await db.execute(select(ExportPacket).where(
            ExportPacket.id == uuid.UUID(packet_id),
            ExportPacket.company_id == row.company_id,
            ExportPacket.kind.in_(("store_accounting_group", "food_accounting_group")),
        ))).scalar_one_or_none()
        documents = (packet.payload or {}).get("Документы") or [] if packet else []
        try:
            index = int(index_raw)
        except ValueError:
            return {"status": "source_missing"}
        if index < 0 or index >= len(documents):
            return {"status": "source_missing"}
        return {"status": packet.status, "document": documents[index]}
    return {"status": "header_only", "lines": []}


def _safe_line(row: dict) -> dict:
    return {
        key: row.get(key)
        for key in (
            "line_id", "ИдентификаторСтроки", "item_uuid", "Номенклатура",
            "НоменклатураUUID",
            "name", "Наименование", "barcode", "ШтрихКод", "qty", "Количество",
            "qty_expected", "КоличествоЗаявлено", "price", "Цена", "amount", "Сумма",
            "ЦенаБыла", "ЦенаСтала",
            "КоличествоОтправлено", "КоличествоУчет", "Отклонение", "СуммаОтклонения",
            "vat_rate", "СтавкаНДС", "vat_amount", "СуммаНДС", "unit", "Единица",
        )
        if row.get(key) is not None
    }


# Почему источник отдаёт только шапку. Пустой список строк и отсутствие строк —
# разные вещи: карточка обязана называть причину, а не молчать.
HEADER_ONLY_REASON = {
    "onec_inventory": "Документ действующей 1С: центр передаёт только заголовок "
                      "и подтверждённую связь, строки остаются в 1С",
    "onec_movement": "Документ действующей 1С: центр передаёт только заголовок "
                     "и подтверждённую связь, строки остаются в 1С",
    "canonical_entry": "Нормализованный факт: строки живут в исходном документе, "
                       "он показан отдельной записью цепочки",
    "accounting_packet": "Бухгалтерский пакет: состав доступен в исходных данных "
                         "бухгалтеру и суперадминистратору",
}


def safe_document_detail(row: StoreDocumentProjection, payload: dict) -> dict:
    status_value = payload.get("status") or row.operational_status
    if row.source_kind == "receipt":
        return {
            "status": status_value, "detail_mode": "lines",
            "lines": [_safe_line(line) for line in payload.get("lines") or []],
            "services": [_safe_line(line) for line in payload.get("services") or []],
        }
    if row.source_kind == "edge_document":
        sanitized = sanitize_edge_document(
            payload, trusted_station_packet=True)
        return {
            "status": status_value, "detail_mode": "lines",
            "lines": [_safe_line(line) for line in sanitized["lines"]],
            "services": [_safe_line(line) for line in sanitized["services"]],
            "amount": float(sanitized["amount"]),
            "vat_amount": (None if sanitized["vat_amount"] is None
                           else float(sanitized["vat_amount"])),
            "classification_error": sanitized["reason"],
        }
    if row.source_kind == "cheque":
        return {
            "status": status_value, "detail_mode": "lines",
            "lines": [_safe_line(line) for line in payload.get("lines") or []],
            "has_fuel": bool(payload.get("has_fuel")),
            "amount": float(payload.get("amount") or 0),
            "vat_amount": (None if payload.get("vat_amount") is None
                           else float(payload["vat_amount"])),
            "classification_error": payload.get("classification_error"),
        }
    if row.source_kind == "accounting_doc":
        return {
            "status": status_value, "detail_mode": "lines",
            "lines": [_safe_line(line) for line in payload.get("lines") or []],
        }
    return {
        "status": status_value, "detail_mode": "header_only", "lines": [],
        "detail_note": HEADER_ONLY_REASON.get(
            row.source_kind, "Источник передаёт только шапку документа"),
    }
