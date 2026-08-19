"""Обязательный контроль объектов (СТО п. 14.2).

Норма перечисляет пять проверок и требует, чтобы результаты оформлялись, а
расхождения устранялись в срок (п. 14.3). Данные для всех пяти уже есть — они
накопились при разделении уровней; не хватало места, где это видно человеку.

Контроль не заменяет инвентаризацию (п. 14.1) и ничего не исправляет сам:
он только называет расхождение и объект. Автоматическое «исправление» здесь было
бы худшим из решений — половина случаев означает, что неверна не система, а
запись в ней, и разбирает это человек.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

# Код проверки → как объяснить расхождение тому, кто будет его устранять.
CHECKS: dict[str, str] = {
    "no_inventory": "эксплуатируется без инвентарного номера",
    "no_commissioned": "состояние «эксплуатируется», дата ввода не указана",
    "no_decommissioned": "состояние «выведена», дата вывода не указана",
    "duplicate_number": "номер объекта повторяется",
    "not_mapped": "нет соответствия ни в одной внешней системе",
    "worked_after_retirement": "сессии после даты вывода",
}


async def run(db: AsyncSession, company_id) -> dict[str, Any]:
    """Все проверки одним проходом. Возвращает счётчики и строки расхождений."""
    rows = (await db.execute(text("""
        with obj as (
            select l.id, l.code, l.name, l.status, l.operational_status,
                   l.station_number, l.is_test,
                   k.child_id as station_id
            from core.service_locations l
            left join core.object_links k
                   on k.company_id = l.company_id and k.relation = 'placed_at'
                  and k.parent_type = 'point_of_service' and k.parent_id = l.id
                  and k.valid_to is null
            where l.company_id = :cid and l.type = 'ev_charging'
              and l.is_test = false
        )
        select o.id, o.code, o.name, o.status, o.operational_status, o.station_number,
               u.inventory_number, u.commissioned_on, u.decommissioned_on, u.state,
               (select count(*) from core.object_links x
                 where x.company_id = :cid and x.relation = 'external_id'
                   and x.parent_id in (o.id, coalesce(o.station_id, o.id))) as ext_ids,
               (select count(*) from core.service_locations d
                 where d.company_id = :cid and d.type = 'ev_charging'
                   and d.is_test = false and d.id <> o.id
                   and (d.code = o.code
                        or (d.station_number is not null
                            and d.station_number = o.station_number))) as same_number,
               (select max(s.started_at)::date from core.charge_sessions s
                 where s.company_id = :cid and s.location_id = o.id) as last_session
        from obj o
        left join core.ezs_equipment_units u on u.id::text = o.station_id
        order by o.code
    """), {"cid": company_id})).all()

    findings: list[dict[str, str]] = []

    def add(row, check: str) -> None:
        findings.append({
            "code": row.code, "name": row.name,
            "check": check, "reason": CHECKS[check],
        })

    for r in rows:
        retired = (r.status == "closed" or r.operational_status == "decommissioned"
                   or bool(r.decommissioned_on))
        in_service = not retired

        if in_service and not r.inventory_number:
            add(r, "no_inventory")
        if in_service and not r.commissioned_on:
            add(r, "no_commissioned")
        if retired and not r.decommissioned_on:
            add(r, "no_decommissioned")
        if r.same_number:
            add(r, "duplicate_number")
        if not r.ext_ids:
            add(r, "not_mapped")
        if (retired and r.decommissioned_on and r.last_session
                and str(r.last_session) > str(r.decommissioned_on)):
            add(r, "worked_after_retirement")

    counters = {code: sum(1 for f in findings if f["check"] == code) for code in CHECKS}
    return {
        "objects": len(rows),
        "counters": counters,
        "total": len(findings),
        # Объектов с расхождениями меньше, чем расхождений: у одного их бывает
        # несколько, и руководителю нужно и то, и другое число.
        "objects_with_findings": len({f["code"] for f in findings}),
        "findings": findings,
    }
