"""Проект ЭЗС: документы, техприсоединение, бюджет, портфель.

Волны 4–8 (`docs/SITES_PROJECT_LIFECYCLE.md`). Проект — это площадка
(`ezs_sites`) с номером, этапами и тремя спутниками:

  • документы (`ezs_site_docs`) — доказательная база; часть пунктов гейта
    закрывается именно приложенным файлом, а не галочкой;
  • техприсоединение (`ezs_tech_connections`) — со своим циклом и сроками:
    именно оно определяет срок всего проекта, а не стройка;
  • бюджет (`ezs_site_costs`) — план и факт по статьям.

Отдельно — «Ждёт учёта»: мост в бухгалтерию. Система показывает, что пора
завести в учёт, но записи создаёт человек: бухгалтерский контур не должен
наполняться побочным эффектом смены статуса.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Contract, EzsSite, EzsSiteCost, EzsSiteDoc, EzsSiteEquipment, EzsTechConnection,
    ServiceLocation, User,
)
from app.services.ezs_site_work import log_event
from app.services.ezs_sites import (
    PHASE_LABELS, PHASES, STAGE_LABELS, STAGE_ORDER, STAGE_PHASE,
)

# ── Документы ──────────────────────────────────────────────────────────────
DOC_KINDS = [
    {"key": "egrn", "label": "Выписка ЕГРН"},
    {"key": "site_plan", "label": "Схема участка"},
    {"key": "photo", "label": "Фото места"},
    {"key": "offer", "label": "Коммерческое предложение"},
    {"key": "contract", "label": "Договор на землю"},
    {"key": "tu", "label": "Технические условия"},
    {"key": "tp_contract", "label": "Договор техприсоединения"},
    {"key": "project", "label": "Проектная документация"},
    {"key": "act_mount", "label": "Акт монтажа"},
    {"key": "act", "label": "Акт приёмки / ввода"},
    {"key": "equipment_doc", "label": "Документы на оборудование"},
    {"key": "other", "label": "Прочее"},
]
DOC_LABELS = {d["key"]: d["label"] for d in DOC_KINDS}


async def list_docs(db: AsyncSession, company_id, site_id) -> list[dict[str, Any]]:
    from app.models import SourceFile
    rows = (await db.execute(
        select(EzsSiteDoc, SourceFile.file_name, SourceFile.size, User.name, User.email)
        .outerjoin(SourceFile, SourceFile.id == EzsSiteDoc.file_id)
        .outerjoin(User, User.id == EzsSiteDoc.uploaded_by)
        .where(EzsSiteDoc.company_id == company_id, EzsSiteDoc.site_id == site_id)
        .order_by(EzsSiteDoc.created_at.desc()))).all()
    return [{
        "id": str(d.id), "kind": d.kind, "kindLabel": DOC_LABELS.get(d.kind, d.kind),
        "title": d.title, "note": d.note, "stage": d.stage,
        "stageLabel": STAGE_LABELS.get(d.stage or "", d.stage),
        "fileId": str(d.file_id) if d.file_id else None, "fileName": fname,
        "fileSize": size, "uploadedBy": name or email,
        "createdAt": d.created_at.isoformat() if d.created_at else None,
    } for d, fname, size, name, email in rows]


async def add_doc(db: AsyncSession, company_id, site: EzsSite, *, file_id, kind: str,
                  title: str | None, note: str | None, user: User | None) -> dict[str, Any]:
    doc = EzsSiteDoc(
        company_id=company_id, site_id=site.id,
        file_id=_uuid.UUID(str(file_id)) if file_id else None,
        kind=kind if kind in DOC_LABELS else "other",
        title=title, note=note, stage=site.stage,
        uploaded_by=user.id if user is not None else None,
    )
    db.add(doc)
    await db.flush()
    await log_event(db, site, "doc", user=user,
                    text=f"Приложен документ: {DOC_LABELS.get(doc.kind, doc.kind)}"
                         + (f" — {title}" if title else ""))
    return {"id": str(doc.id)}


async def delete_doc(db: AsyncSession, company_id, site: EzsSite, doc_id, user: User | None) -> bool:
    doc = (await db.execute(select(EzsSiteDoc).where(
        EzsSiteDoc.company_id == company_id, EzsSiteDoc.site_id == site.id,
        EzsSiteDoc.id == doc_id))).scalar_one_or_none()
    if doc is None:
        return False
    await log_event(db, site, "doc", user=user,
                    text=f"Удалён документ: {DOC_LABELS.get(doc.kind, doc.kind)}")
    await db.delete(doc)
    return True


# ── Техприсоединение ───────────────────────────────────────────────────────
TC_STATUSES = [
    {"key": "draft", "label": "Не начато"},
    {"key": "applied", "label": "Заявка подана"},
    {"key": "specs", "label": "ТУ получены"},
    {"key": "contract", "label": "Договор ТП"},
    {"key": "in_progress", "label": "Мероприятия идут"},
    {"key": "done", "label": "Присоединение исполнено"},
    {"key": "rejected", "label": "Отказ сетевой"},
]
TC_LABELS = {s["key"]: s["label"] for s in TC_STATUSES}
TC_FIELDS = {"status", "grid_operator", "application_no", "application_date", "specs_no",
             "specs_date", "contract_no", "contract_date", "power_kwt", "voltage", "cost",
             "due_date", "done_date", "needs_reconstruction", "note"}
_TC_NUM = {"power_kwt", "cost"}


def _tc_out(tc: EzsTechConnection) -> dict[str, Any]:
    overdue = bool(tc.due_date and not tc.done_date and tc.due_date < date.today().isoformat()
                   and tc.status not in ("done", "rejected"))
    return {
        "id": str(tc.id), "siteId": str(tc.site_id),
        "status": tc.status, "statusLabel": TC_LABELS.get(tc.status, tc.status),
        "gridOperator": tc.grid_operator,
        "applicationNo": tc.application_no, "applicationDate": tc.application_date,
        "specsNo": tc.specs_no, "specsDate": tc.specs_date,
        "contractNo": tc.contract_no, "contractDate": tc.contract_date,
        "powerKwt": tc.power_kwt, "voltage": tc.voltage,
        "cost": float(tc.cost) if tc.cost is not None else None,
        "dueDate": tc.due_date, "doneDate": tc.done_date,
        "needsReconstruction": tc.needs_reconstruction, "note": tc.note,
        "overdue": overdue,
    }


async def get_tech_connection(db: AsyncSession, company_id, site_id) -> dict[str, Any] | None:
    tc = (await db.execute(select(EzsTechConnection).where(
        EzsTechConnection.company_id == company_id,
        EzsTechConnection.site_id == site_id))).scalars().first()
    return _tc_out(tc) if tc else None


async def upsert_tech_connection(db: AsyncSession, company_id, site: EzsSite,
                                 patch: dict[str, Any], user: User | None) -> dict[str, Any]:
    tc = (await db.execute(select(EzsTechConnection).where(
        EzsTechConnection.company_id == company_id,
        EzsTechConnection.site_id == site.id))).scalars().first()
    created = tc is None
    if tc is None:
        tc = EzsTechConnection(company_id=company_id, site_id=site.id)
        db.add(tc)
    prev_status = tc.status
    for f, v in patch.items():
        if f not in TC_FIELDS:
            continue
        if v in ("", None):
            setattr(tc, f, None)
        elif f in _TC_NUM:
            try:
                setattr(tc, f, float(str(v).replace(",", ".").replace(" ", "")))
            except ValueError:
                pass
        elif f == "needs_reconstruction":
            setattr(tc, f, bool(v))
        else:
            setattr(tc, f, str(v))
    tc.updated_at = datetime.now(timezone.utc)
    await db.flush()
    if created:
        await log_event(db, site, "note", text="Заведено техприсоединение", user=user)
    elif prev_status != tc.status:
        await log_event(db, site, "note", user=user,
                        text=f"Техприсоединение: {TC_LABELS.get(prev_status, prev_status)} → "
                             f"{TC_LABELS.get(tc.status, tc.status)}")
    return _tc_out(tc)


async def tech_connections_report(db: AsyncSession, company_id) -> dict[str, Any]:
    """Реестр присоединений по проектам: статусы, сроки, просрочки, стоимость."""
    rows = (await db.execute(
        select(EzsTechConnection, EzsSite.project_no, EzsSite.title, EzsSite.region_norm,
               EzsSite.region, EzsSite.city, EzsSite.address, EzsSite.stage)
        .join(EzsSite, EzsSite.id == EzsTechConnection.site_id)
        .where(EzsTechConnection.company_id == company_id)
        .order_by(EzsTechConnection.due_date.nulls_last()))).all()
    items = []
    by_status: dict[str, int] = {}
    overdue = 0
    cost_sum = 0.0
    for tc, pno, title, rnorm, rraw, city, addr, stage in rows:
        out = _tc_out(tc)
        out.update({"projectNo": pno, "title": title, "region": rnorm or rraw,
                    "city": city, "address": addr, "stage": stage,
                    "stageLabel": STAGE_LABELS.get(stage, stage)})
        items.append(out)
        by_status[tc.status] = by_status.get(tc.status, 0) + 1
        overdue += 1 if out["overdue"] else 0
        cost_sum += out["cost"] or 0
    return {
        "total": len(items), "overdue": overdue, "costSum": round(cost_sum, 2),
        "byStatus": [{"key": s["key"], "label": s["label"], "count": by_status.get(s["key"], 0)}
                     for s in TC_STATUSES],
        "items": items,
    }


# ── Оборудование проекта ───────────────────────────────────────────────────
EQ_STATUSES = [
    {"key": "planned", "label": "Запланировано"},
    {"key": "ordered", "label": "Заказано"},
    {"key": "supplied", "label": "Поставлено"},
    {"key": "installed", "label": "Смонтировано"},
    {"key": "cancelled", "label": "Отменено"},
]
EQ_LABELS = {s["key"]: s["label"] for s in EQ_STATUSES}
EQ_FIELDS = {"status", "title", "manufacturer", "power_kwt", "connectors", "qty", "supplier",
             "price", "order_date", "due_date", "supplied_date", "installed_date", "note"}
_EQ_NUM = {"power_kwt", "price"}


def _eq_out(e: EzsSiteEquipment) -> dict[str, Any]:
    overdue = bool(e.due_date and not e.supplied_date and e.status in ("planned", "ordered")
                   and e.due_date < date.today().isoformat())
    return {
        "id": str(e.id), "siteId": str(e.site_id), "status": e.status,
        "statusLabel": EQ_LABELS.get(e.status, e.status),
        "title": e.title, "manufacturer": e.manufacturer, "powerKwt": e.power_kwt,
        "connectors": e.connectors, "qty": e.qty, "supplier": e.supplier,
        "price": float(e.price) if e.price is not None else None,
        "orderDate": e.order_date, "dueDate": e.due_date,
        "suppliedDate": e.supplied_date, "installedDate": e.installed_date,
        "note": e.note, "overdue": overdue,
    }


async def list_equipment(db: AsyncSession, company_id, site_id) -> dict[str, Any]:
    rows = (await db.execute(select(EzsSiteEquipment).where(
        EzsSiteEquipment.company_id == company_id, EzsSiteEquipment.site_id == site_id)
        .order_by(EzsSiteEquipment.created_at))).scalars().all()
    items = [_eq_out(e) for e in rows]
    active = [i for i in items if i["status"] != "cancelled"]
    return {
        "items": items,
        "priceTotal": round(sum((i["price"] or 0) * (i["qty"] or 1) for i in active), 2),
        # Гейт «Оборудование поставлено» закрывается, когда всё нужное приехало.
        "allSupplied": bool(active) and all(i["status"] in ("supplied", "installed") for i in active),
        "allInstalled": bool(active) and all(i["status"] == "installed" for i in active),
    }


async def upsert_equipment(db: AsyncSession, company_id, site: EzsSite, payload: dict[str, Any],
                           user: User | None) -> dict[str, Any]:
    eid = payload.get("id")
    row = None
    if eid:
        row = (await db.execute(select(EzsSiteEquipment).where(
            EzsSiteEquipment.company_id == company_id, EzsSiteEquipment.site_id == site.id,
            EzsSiteEquipment.id == _uuid.UUID(str(eid))))).scalar_one_or_none()
    created = row is None
    if row is None:
        row = EzsSiteEquipment(company_id=company_id, site_id=site.id)
        db.add(row)
    prev_status = row.status
    for f, v in payload.items():
        if f not in EQ_FIELDS:
            continue
        if v in ("", None):
            setattr(row, f, None)
        elif f in _EQ_NUM:
            try:
                setattr(row, f, float(str(v).replace(",", ".").replace(" ", "")))
            except ValueError:
                pass
        elif f == "qty":
            try:
                row.qty = max(1, int(float(str(v).replace(",", "."))))
            except ValueError:
                pass
        else:
            setattr(row, f, str(v))
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()
    if created:
        await log_event(db, site, "note", user=user,
                        text=f"Оборудование в план: {row.title or '—'} × {row.qty}")
    elif prev_status != row.status:
        await log_event(db, site, "note", user=user,
                        text=f"Оборудование «{row.title or '—'}»: "
                             f"{EQ_LABELS.get(prev_status, prev_status)} → {EQ_LABELS.get(row.status, row.status)}")
    return _eq_out(row)


async def delete_equipment(db: AsyncSession, company_id, site_id, eq_id) -> bool:
    row = (await db.execute(select(EzsSiteEquipment).where(
        EzsSiteEquipment.company_id == company_id, EzsSiteEquipment.site_id == site_id,
        EzsSiteEquipment.id == eq_id))).scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    return True


async def equipment_report(db: AsyncSession, company_id) -> dict[str, Any]:
    """Сводный реестр потребности в оборудовании по всем проектам."""
    rows = (await db.execute(
        select(EzsSiteEquipment, EzsSite.project_no, EzsSite.title, EzsSite.city,
               EzsSite.address, EzsSite.stage)
        .join(EzsSite, EzsSite.id == EzsSiteEquipment.site_id)
        .where(EzsSiteEquipment.company_id == company_id)
        .order_by(EzsSiteEquipment.due_date.nulls_last()))).all()
    items, by_status, overdue, total_price, total_qty = [], {}, 0, 0.0, 0
    for e, pno, title, city, addr, stage in rows:
        out = _eq_out(e)
        out.update({"projectNo": pno, "projectTitle": title, "city": city, "address": addr,
                    "stage": stage, "stageLabel": STAGE_LABELS.get(stage, stage)})
        items.append(out)
        by_status[e.status] = by_status.get(e.status, 0) + 1
        overdue += 1 if out["overdue"] else 0
        if e.status != "cancelled":
            total_price += (out["price"] or 0) * (e.qty or 1)
            total_qty += e.qty or 1
    return {
        "total": len(items), "overdue": overdue, "qty": total_qty,
        "priceTotal": round(total_price, 2),
        "byStatus": [{"key": s["key"], "label": s["label"], "count": by_status.get(s["key"], 0)}
                     for s in EQ_STATUSES],
        "items": items,
    }


# ── Бюджет ─────────────────────────────────────────────────────────────────
COST_KINDS = [
    {"key": "tp", "label": "Техприсоединение"},
    {"key": "equipment", "label": "Оборудование"},
    {"key": "smr", "label": "СМР и монтаж"},
    {"key": "design", "label": "Проектирование"},
    {"key": "rent", "label": "Аренда (за период стройки)"},
    {"key": "other", "label": "Прочее"},
]
COST_LABELS = {c["key"]: c["label"] for c in COST_KINDS}


async def list_costs(db: AsyncSession, company_id, site_id) -> dict[str, Any]:
    rows = (await db.execute(select(EzsSiteCost).where(
        EzsSiteCost.company_id == company_id, EzsSiteCost.site_id == site_id)
        .order_by(EzsSiteCost.created_at))).scalars().all()
    items = [{
        "id": str(c.id), "kind": c.kind, "kindLabel": COST_LABELS.get(c.kind, c.kind),
        "title": c.title, "docRef": c.doc_ref, "note": c.note,
        "plan": float(c.plan_amount) if c.plan_amount is not None else None,
        "fact": float(c.fact_amount) if c.fact_amount is not None else None,
    } for c in rows]
    return {
        "items": items,
        "planTotal": round(sum(i["plan"] or 0 for i in items), 2),
        "factTotal": round(sum(i["fact"] or 0 for i in items), 2),
    }


async def upsert_cost(db: AsyncSession, company_id, site: EzsSite, payload: dict[str, Any],
                      user: User | None) -> dict[str, Any]:
    cid = payload.get("id")
    row = None
    if cid:
        row = (await db.execute(select(EzsSiteCost).where(
            EzsSiteCost.company_id == company_id, EzsSiteCost.site_id == site.id,
            EzsSiteCost.id == _uuid.UUID(str(cid))))).scalar_one_or_none()
    if row is None:
        row = EzsSiteCost(company_id=company_id, site_id=site.id)
        db.add(row)
    row.kind = str(payload.get("kind") or "other")
    row.title = payload.get("title") or None
    row.doc_ref = payload.get("doc_ref") or None
    row.note = payload.get("note") or None
    for f, key in (("plan_amount", "plan"), ("fact_amount", "fact")):
        v = payload.get(key)
        if v in ("", None):
            setattr(row, f, None)
        else:
            try:
                setattr(row, f, float(str(v).replace(",", ".").replace(" ", "")))
            except ValueError:
                setattr(row, f, None)
    await db.flush()
    return {"id": str(row.id)}


async def delete_cost(db: AsyncSession, company_id, site_id, cost_id) -> bool:
    row = (await db.execute(select(EzsSiteCost).where(
        EzsSiteCost.company_id == company_id, EzsSiteCost.site_id == site_id,
        EzsSiteCost.id == cost_id))).scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    return True


# ── Субсидия: требования программы как чек-лист ────────────────────────────
SUBSIDY_MIN_POWER_KWT = 149.0
SUBSIDY_MIN_SPOTS = 2
SUBSIDY_YEARS = 5


def subsidy_check(site: EzsSite) -> dict[str, Any]:
    """Соответствие требованиям господдержки — проверяется до закупки, а не после.

    Требования программы: мощность от 149 кВт, круглосуточный доступ, не менее
    двух машино-мест, на трассе — в составе МФЗ/АЗС с сервисом; после ввода —
    обязательство эксплуатировать пять лет.
    """
    power = site.planned_power_kwt
    items = [
        {"key": "power", "label": f"Мощность от {SUBSIDY_MIN_POWER_KWT:.0f} кВт",
         "done": bool(power and power >= SUBSIDY_MIN_POWER_KWT),
         "value": f"{power:.0f} кВт" if power else None},
        {"key": "spots", "label": f"Машино-мест для зарядки: от {SUBSIDY_MIN_SPOTS}",
         "done": bool(site.parking_spots and site.parking_spots >= SUBSIDY_MIN_SPOTS),
         "value": str(site.parking_spots) if site.parking_spots else None},
        {"key": "access", "label": "Круглосуточный доступ", "done": bool(site.access_24x7),
         "value": None},
        {"key": "ports", "label": "Несколько разъёмов",
         "done": sum(1 for p in (site.ports_gbt, site.ports_ccs, site.ports_chademo,
                                 site.ports_type) if p) >= 2, "value": None},
        {"key": "service", "label": "На трассе — сервис рядом (магазин, кафе)",
         "done": site.place_kind != "трасса" or bool(site.dop_service), "value": site.dop_service},
    ]
    obligation_until = None
    if site.commissioned_on:
        try:
            y, m, d = (int(x) for x in site.commissioned_on.split("-")[:3])
            obligation_until = f"{y + SUBSIDY_YEARS:04d}-{m:02d}-{d:02d}"
        except (ValueError, TypeError):
            obligation_until = None
    return {
        "planned": bool(site.subsidy_planned),
        "amount": float(site.subsidy_amount) if site.subsidy_amount is not None else None,
        "items": items,
        "done": sum(1 for i in items if i["done"]), "total": len(items),
        "eligible": all(i["done"] for i in items),
        "commissionedOn": site.commissioned_on,
        "obligationUntil": obligation_until,
        "obligationYears": SUBSIDY_YEARS,
    }


# ── Портфель и мост в учёт ─────────────────────────────────────────────────
async def portfolio(db: AsyncSession, company_id) -> dict[str, Any]:
    """Обзор портфеля: этапы, сроки, бюджет, риски."""
    S = EzsSite
    by_stage = {r.stage: int(r.n) for r in (await db.execute(
        select(S.stage, func.count().label("n")).where(S.company_id == company_id)
        .group_by(S.stage))).all()}
    phases = []
    for p in PHASES:
        phases.append({"key": p["key"], "label": p["label"], "hint": p["hint"],
                       "count": sum(by_stage.get(s, 0) for s in p["stages"]),
                       "stages": [{"stage": s, "label": STAGE_LABELS[s],
                                   "count": by_stage.get(s, 0)} for s in p["stages"]]})

    money = (await db.execute(text("""
        select coalesce(sum(plan_amount), 0) plan, coalesce(sum(fact_amount), 0) fact
        from ezs_site_costs where company_id = :cid
    """), {"cid": company_id})).mappings().one()

    tc = (await db.execute(text("""
        select count(*) total,
               count(*) filter (where status = 'done') done,
               count(*) filter (where due_date is not null and done_date is null
                                and due_date < to_char(now(), 'YYYY-MM-DD')
                                and status not in ('done','rejected')) overdue
        from ezs_tech_connections where company_id = :cid
    """), {"cid": company_id})).mappings().one()

    # Сколько проектов дошло до работающей станции — главный KPI развития.
    realized = (await db.execute(select(func.count()).select_from(S).where(
        S.company_id == company_id, S.location_id.is_not(None)))).scalar_one()

    docs = (await db.execute(select(func.count()).select_from(EzsSiteDoc)
                             .where(EzsSiteDoc.company_id == company_id))).scalar_one()

    eq = (await db.execute(text("""
        select count(*) total,
               count(*) filter (where status in ('supplied','installed')) supplied,
               count(*) filter (where due_date is not null and supplied_date is null
                                and status in ('planned','ordered')
                                and due_date < to_char(now(), 'YYYY-MM-DD')) overdue
        from ezs_site_equipment where company_id = :cid
    """), {"cid": company_id})).mappings().one()

    return {
        "phases": phases,
        "active": sum(by_stage.get(s, 0) for s in STAGE_ORDER),
        "total": sum(by_stage.values()),
        "realized": int(realized or 0),
        "budget": {"plan": float(money["plan"] or 0), "fact": float(money["fact"] or 0)},
        "techConnections": {"total": int(tc["total"] or 0), "done": int(tc["done"] or 0),
                            "overdue": int(tc["overdue"] or 0)},
        "docs": int(docs or 0),
        "equipment": {"total": int(eq["total"] or 0), "supplied": int(eq["supplied"] or 0),
                      "overdue": int(eq["overdue"] or 0)},
    }


async def phase_durations(db: AsyncSession, company_id) -> dict[str, Any]:
    """Сколько проекты стоят на этапах — по датам входа в стадию из истории.

    Берём разницу между соседними сменами стадий: сколько проект реально провёл
    в каждой, а не сколько числится сейчас. Для текущей стадии — время с момента
    входа до сегодня, такие записи помечены `open`.
    """
    rows = (await db.execute(text("""
        with moves as (
            select e.site_id, e.to_stage as stage, e.created_at,
                   lead(e.created_at) over (partition by e.site_id order by e.created_at) as next_at
            from ezs_site_events e
            where e.company_id = :cid and e.kind = 'stage' and e.to_stage is not null
        )
        select stage,
               count(*) as n,
               percentile_cont(0.5) within group (
                   order by extract(epoch from (coalesce(next_at, now()) - created_at)) / 86400) as median_days,
               count(*) filter (where next_at is null) as still_open
        from moves group by stage
    """), {"cid": company_id})).mappings().all()
    by_stage = {r["stage"]: {"count": int(r["n"]),
                             "medianDays": round(float(r["median_days"] or 0), 1),
                             "open": int(r["still_open"])} for r in rows}
    return {
        "stages": [{"stage": s, "label": STAGE_LABELS[s], **by_stage.get(s, {"count": 0, "medianDays": 0, "open": 0})}
                   for s in STAGE_ORDER],
        "note": "медиана по фактическим переходам в истории; текущие стадии считаются до сегодня",
    }


async def export_portfolio_xlsx(db: AsyncSession, company_id) -> bytes:
    """Выгрузка портфеля: проекты с этапом, ведением, ТП, бюджетом и субсидией."""
    import io

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font

    rows = (await db.execute(text("""
        select s.project_no, s.title, coalesce(s.region_norm, s.region) as region, s.city,
               coalesce(s.address, s.full_address, s.install_place) as address,
               s.stage, s.stage_since, s.owner, u.name as owner_user,
               s.next_action, s.next_action_due,
               s.control_form, s.contract_start, s.contract_end,
               s.planned_power_kwt, s.parking_spots, s.subsidy_planned, s.commissioned_on,
               tc.status as tc_status, tc.grid_operator, tc.due_date as tc_due, tc.done_date as tc_done,
               tc.cost as tc_cost,
               (select coalesce(sum(c.plan_amount), 0) from ezs_site_costs c where c.site_id = s.id) as plan_amount,
               (select coalesce(sum(c.fact_amount), 0) from ezs_site_costs c where c.site_id = s.id) as fact_amount,
               (select count(*) from ezs_site_docs d where d.site_id = s.id) as docs
        from ezs_sites s
        left join users u on u.id = s.owner_user_id
        left join ezs_tech_connections tc on tc.site_id = s.id
        where s.company_id = :cid and s.stage = any(:active)
        order by s.project_no
    """), {"cid": company_id, "active": STAGE_ORDER})).mappings().all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Проекты"
    headers = [
        "Проект", "Название", "Регион", "Город", "Адрес", "Этап", "Стадия", "В стадии с",
        "Собственник", "Ответственный", "Следующий шаг", "Срок",
        "Форма контроля", "Договор с", "Договор по",
        "Мощность, кВт", "Машино-мест", "Субсидия", "Введён",
        "ТП статус", "Сетевая", "ТП срок", "ТП факт", "ТП стоимость",
        "Бюджет план", "Бюджет факт", "Документов",
    ]
    ws.append(headers)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.alignment = Alignment(vertical="center", wrap_text=True)
    for r in rows:
        ws.append([
            r["project_no"], r["title"], r["region"], r["city"], r["address"],
            PHASE_LABELS.get(STAGE_PHASE.get(r["stage"], ""), ""),
            STAGE_LABELS.get(r["stage"], r["stage"]), r["stage_since"],
            r["owner"], r["owner_user"], r["next_action"], r["next_action_due"],
            r["control_form"], r["contract_start"], r["contract_end"],
            float(r["planned_power_kwt"] or 0) or None, r["parking_spots"],
            "да" if r["subsidy_planned"] else "", r["commissioned_on"],
            TC_LABELS.get(r["tc_status"] or "", ""), r["grid_operator"],
            r["tc_due"], r["tc_done"], float(r["tc_cost"] or 0) or None,
            float(r["plan_amount"] or 0) or None, float(r["fact_amount"] or 0) or None,
            int(r["docs"] or 0),
        ])
    widths = [16, 24, 22, 18, 40, 14, 16, 12, 26, 20, 30, 12, 18, 12, 12, 14, 12, 10, 12,
              18, 22, 12, 12, 14, 14, 14, 12]
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def awaiting_accounting(db: AsyncSession, company_id) -> dict[str, Any]:
    """«Ждёт учёта» — где проект ушёл вперёд, а бухгалтерия про это не знает."""
    S = EzsSite

    no_contract = (await db.execute(
        select(S).where(S.company_id == company_id, S.contract_id.is_(None),
                        S.contract_start.is_not(None)))).scalars().all()
    no_location = (await db.execute(
        select(S).where(S.company_id == company_id, S.location_id.is_(None),
                        S.stage.in_(["commissioning", "live"])))).scalars().all()
    no_supply = (await db.execute(text("""
        select s.id, s.project_no, s.city, s.address
        from ezs_sites s
        where s.company_id = :cid and s.stage in ('construction','commissioning','live')
          and not exists (select 1 from ezs_supply_documents d where d.company_id = s.company_id)
        limit 200
    """), {"cid": company_id})).mappings().all()

    def brief(s: EzsSite) -> dict[str, Any]:
        return {"id": str(s.id), "projectNo": s.project_no, "title": s.title,
                "region": s.region_norm or s.region, "city": s.city,
                "address": s.address or s.full_address, "stage": s.stage,
                "stageLabel": STAGE_LABELS.get(s.stage, s.stage)}

    return {
        "contractMissing": [brief(s) for s in no_contract],
        "locationMissing": [brief(s) for s in no_location],
        "supplyMissing": [{"id": str(r["id"]), "projectNo": r["project_no"],
                           "city": r["city"], "address": r["address"]} for r in no_supply],
    }


async def link_contract(db: AsyncSession, company_id, site: EzsSite, contract_id,
                        user: User | None) -> dict[str, Any]:
    """Привязать существующий договор учёта к проекту (создавать — руками в учёте)."""
    c = (await db.execute(select(Contract).where(
        Contract.company_id == company_id,
        Contract.id == _uuid.UUID(str(contract_id))))).scalar_one_or_none()
    if c is None:
        return {"ok": False, "message": "Договор не найден"}
    site.contract_id = c.id
    await log_event(db, site, "note", user=user,
                    text=f"Привязан договор № {c.number} от {c.date}"
                         + (f" ({c.basis})" if c.basis else ""))
    return {"ok": True, "contract": {"id": str(c.id), "number": c.number, "date": c.date,
                                     "basis": c.basis, "validUntil": c.valid_until}}


async def link_location(db: AsyncSession, company_id, site: EzsSite, location_id,
                        user: User | None) -> dict[str, Any]:
    """Связать проект с объектом сети — цикл замкнут, площадка стала станцией."""
    loc = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.id == str(location_id)))).scalar_one_or_none()
    if loc is None:
        return {"ok": False, "message": "Объект не найден"}
    site.location_id = loc.id
    if not site.commissioned_on:
        site.commissioned_on = date.today().isoformat()
    await log_event(db, site, "note", user=user, text=f"Связан объект сети: {loc.name}")
    return {"ok": True, "location": {"id": str(loc.id), "name": loc.name, "code": loc.code}}


async def project_context(db: AsyncSession, company_id, site: EzsSite) -> dict[str, Any]:
    """Всё, что показывает карточка проекта сверх паспорта."""
    contract = None
    if site.contract_id:
        c = (await db.execute(select(Contract).where(Contract.id == site.contract_id))).scalar_one_or_none()
        if c:
            contract = {"id": str(c.id), "number": c.number, "date": c.date,
                        "basis": c.basis, "validUntil": c.valid_until, "type": c.type}
    location = None
    if site.location_id:
        loc = (await db.execute(select(ServiceLocation).where(
            ServiceLocation.id == str(site.location_id)))).scalar_one_or_none()
        if loc:
            location = {"id": str(loc.id), "name": loc.name, "code": loc.code,
                        "status": loc.operational_status}
    return {
        "phase": STAGE_PHASE.get(site.stage, "select"),
        "phases": [{"key": p["key"], "label": p["label"], "hint": p["hint"],
                    "stages": [{"stage": s, "label": STAGE_LABELS[s]} for s in p["stages"]]}
                   for p in PHASES],
        "techConnection": await get_tech_connection(db, company_id, site.id),
        "equipment": await list_equipment(db, company_id, site.id),
        "costs": await list_costs(db, company_id, site.id),
        "subsidy": subsidy_check(site),
        "contract": contract,
        "location": location,
        "docKinds": DOC_KINDS,
        "tcStatuses": TC_STATUSES,
        "eqStatuses": EQ_STATUSES,
        "costKinds": COST_KINDS,
    }
