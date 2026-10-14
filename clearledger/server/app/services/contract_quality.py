"""Качество договоров пространства — что мешает договору работать разрезом учёта.

Каждая проверка — список того, что надо поправить, а не цифра: человек идёт по нему
и закрывает строку за строкой (тот же принцип, что «Разбор данных» оборудования).
Договор-ссылка ведёт в «Договоры» на этот договор, станция — к станции.
"""
import uuid
from datetime import date

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContractLink
from app.services.contract_usage import usage_by_contract

_LIMIT = 300

_CONTRACT_COLS = ("SELECT c.id::text AS id, c.number, c.date, c.valid_until, c.type, cp.name AS counterparty"
                  " FROM contracts c LEFT JOIN counterparties cp ON cp.id = c.counterparty_id WHERE c.company_id = :co")

_CHECKS: list[tuple[str, str, str, str]] = [
    ("no_stations", "Договор «на станциях», но станции не выбраны",
     "Охват задан станциями, а ни одной не отмечено — договор не попадает ни в одну карточку станции.",
     _CONTRACT_COLS + " AND c.scope_type = 'locations'"
     " AND NOT EXISTS (SELECT 1 FROM contract_locations l WHERE l.contract_id = c.id)"),
    ("unassigned", "Охват не распределён",
     "Не указано, к станциям договор или ко всей компании.",
     _CONTRACT_COLS + " AND COALESCE(c.scope_type, 'unassigned') = 'unassigned'"),
    ("expired_open", "Срок истёк, договор не закрыт",
     "Либо договор продлён (нужно доп. соглашение с новым сроком), либо его пора закрыть.",
     _CONTRACT_COLS + " AND COALESCE(c.valid_until, '') <> '' AND c.valid_until < :today AND NOT c.is_closed"),
    ("no_date", "Нет даты договора",
     "Без даты договор не встаёт в историю и не сверяется с 1С.",
     _CONTRACT_COLS + " AND COALESCE(c.date, '') = ''"),
    ("bad_date", "Дата не в формате ГГГГ-ММ-ДД",
     "Дата пришла текстом (например «28.11.2023»): сортировка и сроки по ней работают неверно.",
     _CONTRACT_COLS + " AND COALESCE(c.date, '') <> '' AND c.date !~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'"),
]


async def contract_quality(db: AsyncSession, cid: uuid.UUID) -> dict:
    params = {"co": cid, "today": date.today().isoformat()}
    sections = []
    for key, label, hint, sql in _CHECKS:
        rows = [dict(r) for r in (await db.execute(text(sql + " ORDER BY cp.name, c.date"), params)).mappings().all()]
        sections.append({"key": key, "label": label, "hint": hint, "count": len(rows), "kind": "contract", "items": rows[:_LIMIT]})

    # Ни к чему не относится: не используется ни одним приложением и не привязан.
    used = await usage_by_contract(db, cid)
    linked = set((await db.execute(select(ContractLink.contract_id).where(ContractLink.company_id == cid))).scalars())
    rows = [dict(r) for r in (await db.execute(text(_CONTRACT_COLS + " ORDER BY cp.name, c.date"), params)).mappings().all()
            if uuid.UUID(r["id"]) not in used and uuid.UUID(r["id"]) not in linked]
    sections.append({"key": "orphan", "label": "Договор ни к чему не относится",
                     "hint": "Ни расчётов, ни документов, ни привязки к приложению или проекту — непонятно, чей это договор.",
                     "count": len(rows), "kind": "contract", "items": rows[:_LIMIT]})

    rows = [dict(r) for r in (await db.execute(text(
        "SELECT s.id, s.code, s.name, s.address FROM service_locations s"
        " WHERE s.company_id = :co AND s.type = 'ev_charging' AND COALESCE(s.status, 'active') = 'active'"
        " AND NOT EXISTS (SELECT 1 FROM contract_locations l WHERE l.location_id = s.id) ORDER BY s.code"), params)).mappings().all()]
    sections.append({"key": "stations_no_contract", "label": "Действующая ЭЗС без адресного договора",
                     "hint": "Ни аренды, ни энергоснабжения на станцию — расходы площадки не к чему отнести.",
                     "count": len(rows), "kind": "location", "items": rows[:_LIMIT]})

    rows = [dict(r) for r in (await db.execute(text(
        "SELECT cp.id::text AS id, cp.name, count(c.id) AS contracts FROM counterparties cp"
        " JOIN contracts c ON c.counterparty_id = cp.id WHERE cp.company_id = :co AND COALESCE(cp.inn, '') = ''"
        " GROUP BY cp.id, cp.name ORDER BY count(c.id) DESC, cp.name"), params)).mappings().all()]
    sections.append({"key": "cp_no_inn", "label": "Контрагент с договорами без ИНН",
                     "hint": "Без ИНН контрагента не сопоставить с 1С и выпиской банка.",
                     "count": len(rows), "kind": "counterparty", "items": rows[:_LIMIT]})
    return {"sections": sections}
