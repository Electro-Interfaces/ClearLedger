"""Приложение «Бухгалтерия» пространства: что бухгалтерия знает о наших карточках.

Срез только читает. Сведения бухгалтерии приехали выгруженными отчётами и лежат
строками-источниками (`DataEntry`, слой `raw`) — рабочими карточками пространства они
от этого не становятся. Здесь источник сопоставляется с реестром: договор, контрагент,
площадка. Прямого чтения 1С в этом слое нет и не предполагается: транспорт сменится
(выгрузка → интеграция), а модель сопряжения останется та же.

Три оси различаются и НЕ сводятся в одну галочку:

  сопряжение   `matched` | `related` | `unmatched` | `candidate` — опознана ли запись;
  проверка     какие реквизиты сверены, где расхождения, что не проверяли;
  свежесть     менялась ли карточка после проверки — тогда проверка устарела.

Хеш проверенных значений считается ровно так, как при применении сверки 28.10.2026
(`apply_matched.py`): те же поля, та же сериализация. Сошёлся — проверка в силе,
разошёлся — устарела, и это видно без ручной отметки.

Статус сопряжения берётся ТОЛЬКО из `_accountingReconciliationStatus`. По префиксу
`source_id` (`acct-unmatched:`) его определять нельзя: префикс исторический и стоит
у всех записей партии, включая позднее сопряжённые.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract,
    ContractLocation,
    Counterparty,
    DataEntry,
    ServiceLocation,
)

# Ключ, по которому запись опознаётся как строка бухгалтерского источника.
STATUS_KEY = "_accountingReconciliationStatus"
# Поля карточки договора, которые сверялись при применении (и входят в хеш).
CHECKED_FIELDS = ("number", "date", "counterparty_id", "type_code")

LINK_STATUS_LABEL = {
    "matched": "Сопряжено",
    "related": "Связанный документ",
    "candidate": "Нужна проверка",
    "unmatched": "Не сопряжено",
}
VERIFICATION_LABEL = {
    "verified": "Реквизиты сверены",
    "partial": "Часть реквизитов сверена",
    "differences": "Есть расхождения",
    "not_checked": "Не проверено",
    "stale": "Нужна повторная сверка",
}


def _js(value: Any) -> str:
    """Сериализация, на которой считался хеш проверенных значений."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(_js(value).encode()).hexdigest()


def compact(value: Any) -> str:
    """Номер договора без разделителей и регистра: «41-09/ЭЗС-23» ≡ «41 09 ЭЗС 23».

    Мелкая разница в записи номера не делает договор другим (решение по сверке
    28.10.2026), поэтому расхождением считается только несовпадение значимых знаков.
    """
    return re.sub(r"[^0-9a-zа-я]", "", str(value or "").casefold().replace("ё", "е"))


def _loads(raw: Any) -> Any:
    """`_accountingReconciliations` и соседи лежат сериализованным JSON в строке."""
    if isinstance(raw, (list, dict)):
        return raw
    if not raw:
        return []
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return []


@dataclass
class Link:
    """Одна связь строки источника с карточкой пространства."""
    entity_type: str
    entity_id: str
    relation: str
    status: str
    verification: str           # verified | partial | differences | not_checked
    stale: bool                 # карточка менялась после проверки
    source_number: str
    source_date: str
    checked_hash: str
    current_hash: str
    checked_values: dict[str, Any]
    current_values: dict[str, Any]
    differences: list[dict[str, Any]]
    location_ids: list[str]
    subject_status: str
    snapshot_at: str
    exists: bool                # карточка ещё существует в реестре
    # Что при сверке НЕ проверяли: сопряжение и проверка реквизитов — разные признаки.
    inn_kpp_checked: bool
    original_document_checked: bool


@dataclass
class Record:
    """Строка бухгалтерского источника вместе с её сопряжениями."""
    id: str
    status: str
    counterparty_name: str
    contract_label: str
    kind: str                   # «Тип по бухгалтерии» / «Предмет»
    reason: str                 # основание сопряжения или разбора
    source_file: str
    source_sheet: str
    source_rows: str
    source_period: str
    source_as_of: str
    source_sha256: str
    source_key: str
    source_key_type: str
    batch_id: str
    entry_status: str
    layer: str
    station_hint: str           # номера ЭЗС из бухгалтерии (подсказка ВПР)
    candidates: str
    links: list[Link] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    created_at: Any = None

    @property
    def verification(self) -> str:
        """Проверка строки: худшее из её связей; устаревшая важнее частичной."""
        if not self.links:
            return "not_checked"
        if any(l.stale for l in self.links):
            return "stale"
        order = ("differences", "not_checked", "partial", "verified")
        for state in order:
            if any(l.verification == state for l in self.links):
                return state
        return "not_checked"

    @property
    def location_ids(self) -> list[str]:
        out: list[str] = []
        for link in self.links:
            for loc in link.location_ids:
                if loc not in out:
                    out.append(loc)
        return out


@dataclass
class Slice:
    """Готовый срез: записи источника плюс карточки пространства, на которые они легли."""
    records: list[Record]
    contracts: dict[str, Contract]
    counterparties: dict[str, Counterparty]
    locations: dict[str, ServiceLocation]
    contract_locations: dict[str, list[str]]
    space_contracts_total: int
    space_counterparties_total: int
    space_locations_total: int


def _contract_values(c: Contract) -> dict[str, Any]:
    return {
        "number": c.number,
        "date": c.date,
        "counterparty_id": str(c.counterparty_id),
        "type_code": c.type_code,
    }


def _link_differences(source_number: str, source_date: str,
                      current: dict[str, Any]) -> list[dict[str, Any]]:
    """Расхождения источника и карточки по сверявшимся реквизитам.

    Пустое значение источника — не расхождение, а отсутствие сведений: в выгрузке
    дата встречается не всегда, и «неизвестно» нельзя показывать как конфликт.
    """
    out: list[dict[str, Any]] = []
    if source_number and compact(source_number) != compact(current.get("number")):
        out.append({"field": "number", "label": "Номер",
                    "source": source_number, "space": current.get("number") or ""})
    if source_date and source_date != (current.get("date") or ""):
        out.append({"field": "date", "label": "Дата",
                    "source": source_date, "space": current.get("date") or ""})
    return out


async def load_slice(db: AsyncSession, company_id: uuid.UUID,
                     organization_id: str | None = None) -> Slice:
    """Читает все строки бухгалтерского источника компании и их окружение.

    ponytail: срез целиком в память — на 28.10.2026 это 395 строк и 901 договор.
    Числа плиток, списков и выгрузки обязаны происходить из одного отбора, а один
    проход это гарантирует дешевле, чем пять согласованных SQL. Когда источников
    станет десятки тысяч строк, отбор уедет в SQL с теми же правилами.
    """
    rows = (await db.execute(
        select(DataEntry)
        .where(DataEntry.company_id == company_id, DataEntry.meta.has_key(STATUS_KEY))
        # Вторым ключом — id: вся партия приехала одной транзакцией с одинаковым
        # `created_at`, и без него порядок строк между запросами плавает, а страницы
        # теряют и повторяют записи.
        .order_by(DataEntry.created_at, DataEntry.id)
    )).scalars().all()

    records: list[Record] = []
    contract_ids: set[str] = set()
    for e in rows:
        m = e.meta or {}
        rec = Record(
            id=str(e.id),
            status=str(m.get(STATUS_KEY) or ""),
            counterparty_name=str(m.get("Контрагент в бухгалтерии") or ""),
            contract_label=str(m.get("Договор или основание") or ""),
            kind=str(m.get("Тип по бухгалтерии") or m.get("Предмет") or ""),
            reason=str(m.get("Основание сопряжения") or m.get("Основание разбора") or ""),
            source_file=str(m.get("Файл источника") or ""),
            source_sheet=str(m.get("Лист источника") or ""),
            source_rows=str(m.get("Строки источника") or ""),
            source_period=str(m.get("Период источника") or ""),
            source_as_of=str(m.get("_accountingSourceAsOf") or ""),
            source_sha256=str(m.get("_accountingSourceSha256") or ""),
            source_key=str(m.get("_accountingSourceKey") or ""),
            source_key_type=str(m.get("_accountingSourceKeyType") or ""),
            batch_id=str(m.get("_accountingBatchId") or ""),
            entry_status=e.status,
            layer=e.layer,
            station_hint=str(m.get("Номера ЭЗС из бухгалтерии") or ""),
            candidates=str(m.get("Кандидаты в пространстве") or ""),
            meta=m,
            created_at=e.created_at,
        )
        for raw in _loads(m.get("_accountingReconciliations")):
            if not isinstance(raw, dict):
                continue
            entity_id = str(raw.get("entity_id") or "")
            if raw.get("entity_type") == "contract" and entity_id:
                contract_ids.add(entity_id)
            rec.links.append(Link(
                entity_type=str(raw.get("entity_type") or ""),
                entity_id=entity_id,
                relation=str(raw.get("relation") or ""),
                status=str(raw.get("status") or rec.status),
                verification=str(raw.get("verification_status") or "not_checked"),
                stale=False,
                source_number=str(raw.get("source_number") or ""),
                source_date=str(raw.get("source_date") or ""),
                checked_hash=str(raw.get("target_checked_hash") or ""),
                current_hash="",
                checked_values=raw.get("target_values") or {},
                current_values={},
                differences=[],
                location_ids=[str(x) for x in (raw.get("location_ids") or [])],
                subject_status=str(raw.get("subject_status") or ""),
                snapshot_at=str(raw.get("snapshot_at") or ""),
                exists=False,
                inn_kpp_checked=bool(raw.get("inn_kpp_checked")),
                original_document_checked=bool(raw.get("original_document_checked")),
            ))
        records.append(rec)

    contracts: dict[str, Contract] = {}
    if contract_ids:
        valid = [uuid.UUID(x) for x in contract_ids if _is_uuid(x)]
        if valid:
            stmt = select(Contract).where(Contract.company_id == company_id,
                                          Contract.id.in_(valid))
            if organization_id and _is_uuid(organization_id):
                stmt = stmt.where(Contract.organization_id == uuid.UUID(organization_id))
            for c in (await db.execute(stmt)).scalars().all():
                contracts[str(c.id)] = c

    cp_ids = {str(c.counterparty_id) for c in contracts.values()}
    counterparties: dict[str, Counterparty] = {}
    if cp_ids:
        valid_cp = [uuid.UUID(x) for x in cp_ids if _is_uuid(x)]
        if valid_cp:
            for cp in (await db.execute(select(Counterparty).where(
                    Counterparty.company_id == company_id,
                    Counterparty.id.in_(valid_cp)))).scalars().all():
                counterparties[str(cp.id)] = cp

    # Текущее состояние карточки против проверенного: расхождения и устаревшая проверка.
    for rec in records:
        for link in rec.links:
            c = contracts.get(link.entity_id)
            if c is None:
                continue
            link.exists = True
            link.current_values = _contract_values(c)
            link.current_hash = digest(link.current_values)
            link.stale = bool(link.checked_hash) and link.checked_hash != link.current_hash
            link.differences = _link_differences(link.source_number, link.source_date,
                                                 link.current_values)

    contract_locations: dict[str, list[str]] = {}
    for contract_id, location_id in (await db.execute(
        select(ContractLocation.contract_id, ContractLocation.location_id)
        .where(ContractLocation.company_id == company_id)
    )).all():
        contract_locations.setdefault(str(contract_id), []).append(str(location_id))

    loc_ids = {loc for ids in contract_locations.values() for loc in ids}
    locations: dict[str, ServiceLocation] = {}
    if loc_ids:
        for loc in (await db.execute(select(ServiceLocation).where(
                ServiceLocation.company_id == company_id,
                ServiceLocation.id.in_(loc_ids)))).scalars().all():
            locations[str(loc.id)] = loc

    totals = (await db.execute(select(
        select(func.count()).select_from(Contract)
        .where(Contract.company_id == company_id).scalar_subquery(),
        select(func.count()).select_from(Counterparty)
        .where(Counterparty.company_id == company_id).scalar_subquery(),
        select(func.count()).select_from(ServiceLocation)
        .where(ServiceLocation.company_id == company_id).scalar_subquery(),
    ))).one()

    return Slice(
        records=records, contracts=contracts, counterparties=counterparties,
        locations=locations, contract_locations=contract_locations,
        space_contracts_total=int(totals[0] or 0),
        space_counterparties_total=int(totals[1] or 0),
        space_locations_total=int(totals[2] or 0),
    )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def contract_brief(slice_: Slice, contract_id: str) -> dict[str, Any]:
    """Карточка договора так, как её видит бухгалтерский экран (сторона пространства)."""
    c = slice_.contracts.get(contract_id)
    if c is None:
        # Карточку удалили или она вне выбранного юрлица — молча не исчезаем.
        return {"id": contract_id, "exists": False}
    cp = slice_.counterparties.get(str(c.counterparty_id))
    locs = slice_.contract_locations.get(contract_id, [])
    return {
        "id": contract_id, "exists": True,
        "number": c.number, "date": c.date, "title": c.title,
        "type": c.type, "type_code": c.type_code, "basis": c.basis,
        "valid_until": c.valid_until,
        "signed": c.signed, "signed_at": c.signed_at,
        "counterparty_id": str(c.counterparty_id),
        "counterparty_name": cp.name if cp else "",
        "counterparty_inn": (cp.inn if cp else None) or "",
        "counterparty_kpp": (cp.kpp if cp else None) or "",
        "organization_id": str(c.organization_id),
        "locations": [{
            "id": loc,
            "code": slice_.locations[loc].code if loc in slice_.locations else "",
            "name": slice_.locations[loc].name if loc in slice_.locations else "",
        } for loc in locs],
    }


def record_row(rec: Record, slice_: Slice) -> dict[str, Any]:
    """Строка списка: сведения источника плюс чем они легли в пространство."""
    cards = [contract_brief(slice_, l.entity_id) for l in rec.links
             if l.entity_type == "contract"]
    return {
        "id": rec.id,
        "status": rec.status,
        "status_label": LINK_STATUS_LABEL.get(rec.status, rec.status),
        "verification": rec.verification,
        "verification_label": VERIFICATION_LABEL.get(rec.verification, rec.verification),
        "counterparty_name": rec.counterparty_name,
        "contract_label": rec.contract_label,
        "kind": rec.kind,
        "reason": rec.reason,
        "entry_status": rec.entry_status,
        "layer": rec.layer,
        "source_file": rec.source_file,
        "source_sheet": rec.source_sheet,
        "source_rows": rec.source_rows,
        "source_period": rec.source_period,
        "source_as_of": rec.source_as_of,
        "batch_id": rec.batch_id,
        "station_hint": rec.station_hint,
        "candidates": rec.candidates,
        "links_count": len(rec.links),
        "differences_count": sum(len(l.differences) for l in rec.links),
        "stale_count": sum(1 for l in rec.links if l.stale),
        "location_ids": rec.location_ids,
        "cards": cards,
        "card_labels": [
            (f"{c.get('number', '')} от {c.get('date', '')}" if c.get("exists")
             else "карточка не найдена") for c in cards
        ],
    }


def record_card(rec: Record, slice_: Slice) -> dict[str, Any]:
    """Карточка строки: обе стороны, перечень сверенных полей и расшифровка до источника."""
    row = record_row(rec, slice_)
    row["source_side"] = {
        "counterparty": rec.counterparty_name,
        "contract": rec.contract_label,
        "kind": rec.kind,
        "period": rec.source_period,
        "as_of": rec.source_as_of,
        "file": rec.source_file,
        "sheet": rec.source_sheet,
        "rows": rec.source_rows,
        "sha256": rec.source_sha256,
        "key": rec.source_key,
        "key_type": rec.source_key_type,
        "record_kind": str(rec.meta.get("_accountingRecordKind") or ""),
        "station_hint": rec.station_hint,
        # Признака проведения документа выгрузка не содержит — показываем неизвестным.
        "posted": None,
        "original_document": None,
    }
    row["links"] = [{
        "entity_type": l.entity_type,
        "entity_id": l.entity_id,
        "relation": l.relation,
        "status": l.status,
        "status_label": LINK_STATUS_LABEL.get(l.status, l.status),
        "verification": "stale" if l.stale else l.verification,
        "verification_label": VERIFICATION_LABEL.get(
            "stale" if l.stale else l.verification, l.verification),
        "stale": l.stale,
        "subject_status": l.subject_status,
        "snapshot_at": l.snapshot_at,
        "checked_fields": sorted(k for k in l.checked_values) if l.checked_values else [],
        "checked_values": l.checked_values,
        "current_values": l.current_values,
        "checked_hash": l.checked_hash,
        "current_hash": l.current_hash,
        "differences": l.differences,
        # Что НЕ проверялось — отдельными признаками: сопряжение не означает ни сверки
        # ИНН/КПП, ни проверки по оригиналу документа.
        "inn_kpp_checked": l.inn_kpp_checked,
        "original_document_checked": l.original_document_checked,
        "card": contract_brief(slice_, l.entity_id),
        "location_ids": l.location_ids,
    } for l in rec.links]
    return row


def summary(slice_: Slice) -> dict[str, Any]:
    """Плитки обзора: что загружено, насколько разобрано и что требует внимания."""
    recs = slice_.records
    by_status: dict[str, int] = {}
    by_verification: dict[str, int] = {}
    for r in recs:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        by_verification[r.verification] = by_verification.get(r.verification, 0) + 1

    linked_contracts = {l.entity_id for r in recs for l in r.links
                        if l.entity_type == "contract" and l.entity_id}
    missing_cards = {l.entity_id for r in recs for l in r.links if not l.exists and l.entity_id}
    linked_locations = {loc for r in recs for loc in r.location_ids}
    return {
        "source_rows": len(recs),
        "by_status": by_status,
        "by_verification": by_verification,
        "differences": sum(1 for r in recs if r.verification == "differences"),
        "stale": sum(1 for r in recs if r.verification == "stale"),
        "linked_contracts": len(linked_contracts),
        "linked_locations": len(linked_locations),
        "missing_cards": len(missing_cards),
        "counterparties_in_source": len({r.counterparty_name for r in recs if r.counterparty_name}),
        "contracts_in_source": len({r.contract_label for r in recs if r.contract_label}),
        "space": {
            "contracts": slice_.space_contracts_total,
            "counterparties": slice_.space_counterparties_total,
            "locations": slice_.space_locations_total,
            "contracts_without_source": max(slice_.space_contracts_total - len(linked_contracts), 0),
        },
        "periods": sorted({r.source_period for r in recs if r.source_period}),
        "as_of": sorted({r.source_as_of for r in recs if r.source_as_of}),
        # Периметр выгрузки уже ограничен: в отчёт попали только расчёты за 9 месяцев
        # 2026. «Нет в бухгалтерии» для остальных карточек значит «нет сведений для
        # сравнения», а не отсутствие договора в учёте.
        "scope": ("Выгрузка охватывает расчёты за указанный период. Договор пространства "
                  "без строки источника не значит, что его нет в бухгалтерии: вне периметра "
                  "выгрузки сведений для сравнения нет."),
    }


def sources(slice_: Slice) -> list[dict[str, Any]]:
    """Журнал источников: файл, партия, период, SHA-256 и что из него разобрано."""
    groups: dict[tuple, dict[str, Any]] = {}
    for r in slice_.records:
        key = (r.batch_id, r.source_file, r.source_sheet, r.source_period,
               r.source_as_of, r.source_sha256)
        g = groups.setdefault(key, {
            "batch_id": r.batch_id, "file": r.source_file, "sheet": r.source_sheet,
            "period": r.source_period, "as_of": r.source_as_of,
            "sha256": r.source_sha256, "key_type": r.source_key_type,
            "rows": 0, "by_status": {}, "loaded_at": None,
            # Дату выгрузки из 1С источник не сообщает: «на 30.09» — дата данных,
            # не дата формирования файла. Не выдумываем её.
            "exported_at": None,
        })
        g["rows"] += 1
        g["by_status"][r.status] = g["by_status"].get(r.status, 0) + 1
        if r.created_at and (g["loaded_at"] is None or r.created_at < g["loaded_at"]):
            g["loaded_at"] = r.created_at
    return sorted(groups.values(), key=lambda g: (g["file"], g["batch_id"]))


def objects_report(slice_: Slice) -> list[dict[str, Any]]:
    """Отчёт по объекту: на каких основаниях стоит площадка и что об этом знает учёт.

    Аренда земли и получение электроэнергии — первый предметный контур: именно они
    отвечают на вопрос «чем обоснована площадка». Техприсоединение сюда не
    приравнивается — это отдельное основание.
    """
    # Договор → строки источника, которые на него легли.
    by_contract: dict[str, list[tuple[Record, Link]]] = {}
    for r in slice_.records:
        for l in r.links:
            if l.entity_type == "contract" and l.entity_id:
                by_contract.setdefault(l.entity_id, []).append((r, l))

    out: list[dict[str, Any]] = []
    for loc_id, loc in slice_.locations.items():
        contracts = [cid for cid, locs in slice_.contract_locations.items()
                     if loc_id in locs and cid in slice_.contracts]
        if not contracts:
            continue
        rent, energy, other = [], [], []
        for cid in contracts:
            c = slice_.contracts[cid]
            item = {
                "contract": contract_brief(slice_, cid),
                "source": [{
                    "record_id": r.id, "status": r.status,
                    "status_label": LINK_STATUS_LABEL.get(r.status, r.status),
                    "verification": "stale" if l.stale else l.verification,
                    "counterparty": r.counterparty_name,
                    "contract_label": r.contract_label,
                    "file": r.source_file, "rows": r.source_rows,
                    "as_of": r.source_as_of,
                } for r, l in by_contract.get(cid, [])],
            }
            (rent if c.type_code == "rent" else
             energy if c.type_code == "energy_supply" else other).append(item)
        items = rent + energy + other
        linked = sum(1 for i in items if i["source"])
        unchecked = sum(1 for i in items for s in i["source"]
                        if s["verification"] in ("not_checked", "stale", "differences"))
        out.append({
            "id": loc_id, "code": loc.code, "name": loc.name,
            "address": loc.address or "", "status": loc.status,
            "rent": rent, "energy": energy, "other": other,
            "contracts_count": len(items),
            "with_source": linked,
            "without_source": len(items) - linked,
            "unchecked": unchecked,
            "has_rent": bool(rent), "has_energy": bool(energy),
        })
    return sorted(out, key=lambda o: (o["code"] or "", o["name"] or ""))


def entity_links(slice_: Slice, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
    """Сопряжения конкретной карточки — для бейджа в её собственном экране.

    Общая механика живёт здесь, а не внутри страницы «Бухгалтерия»: карточке договора
    нужен тот же ответ «что об этом знает бухгалтерия», что и очереди разбора.
    """
    out: list[dict[str, Any]] = []
    for r in slice_.records:
        for l in r.links:
            if l.entity_type != entity_type or l.entity_id != entity_id:
                continue
            out.append({
                "record_id": r.id,
                "status": l.status,
                "status_label": LINK_STATUS_LABEL.get(l.status, l.status),
                "verification": "stale" if l.stale else l.verification,
                "verification_label": VERIFICATION_LABEL.get(
                    "stale" if l.stale else l.verification, l.verification),
                "stale": l.stale,
                "relation": l.relation,
                "checked_fields": sorted(l.checked_values) if l.checked_values else [],
                "differences": l.differences,
                "source": {
                    "counterparty": r.counterparty_name,
                    "contract": r.contract_label,
                    "file": r.source_file, "sheet": r.source_sheet,
                    "rows": r.source_rows, "period": r.source_period,
                    "as_of": r.source_as_of,
                },
            })
    return out
