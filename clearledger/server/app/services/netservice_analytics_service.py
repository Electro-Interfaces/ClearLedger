"""
Аналитика Сервисного центра (netservice) — агрегаты по hubex_tasks (3-я линия).

Все метрики считаются SQL'ом по синхронизированной таблице hubex_tasks (синк —
hubex_sync.py), не дёргая HubEx на каждый запрос. Разрезы (регион/точка/тип/
подрядчик) применяются единым WHERE-билдером. SLA — из 6 timestamp полей timesheet.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class NetServiceFilter:
    company_id: uuid.UUID
    date_from: date
    date_to: date
    region: str | None = None  # название региона (= extra_metadata.federalSubject)
    location_id: str | None = None
    location_type: str | None = None
    contractor: str | None = None
    line: str | None = None  # задел: l1|l2|l3 (MVP — только HubEx 3-я линия)


def _conds(f: NetServiceFilter, *, period: bool) -> tuple[str, dict[str, Any]]:
    """Общие условия разрезов. period=True добавляет фильтр по ts_created."""
    conds = ["t.company_id = :cid"]
    p: dict[str, Any] = {"cid": str(f.company_id)}
    if f.region:
        conds.append(
            "t.location_id IN (SELECT id FROM service_locations "
            "WHERE company_id = :cid AND extra_metadata->>'federalSubject' = :region)")
        p["region"] = f.region
    if f.location_id:
        conds.append("t.location_id = :location_id")
        p["location_id"] = f.location_id
    if f.location_type:
        conds.append(
            "t.location_id IN (SELECT id FROM service_locations "
            "WHERE company_id = :cid AND type = :ltype)")
        p["ltype"] = f.location_type
    if f.contractor:
        conds.append("t.contractor_company = :contractor")
        p["contractor"] = f.contractor
    if period:
        # CAST(...) вместо ::date — двойное двоеточие конфликтует с bind-параметрами text().
        # Передаём date-объекты (asyncpg при CAST AS timestamp требует date/datetime, не str).
        conds.append("t.ts_created >= CAST(:df AS timestamp) "
                     "AND t.ts_created < (CAST(:dt AS date) + 1)")
        p["df"] = f.date_from
        p["dt"] = f.date_to
    return " AND ".join(conds), p


class NetServiceAnalytics:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def network_health(self, f: NetServiceFilter) -> dict[str, Any]:
        """Снимок состояния сети: открытые/просроченные + воронка + срезы + карта.

        Период НАМЕРЕННО не применяется к открытым заявкам: фильтр по ts_created
        скрыл бы давно открытые (а именно они — проблема). Чтобы селектор периода
        не выглядел работающим вхолостую, отдаём это явно в `period.applied=false`
        и добавляем period-зависимую метрику `createdInPeriod`.
        """
        where, p = _conds(f, period=False)
        base = f"FROM hubex_tasks t WHERE {where}"
        where_p, p_period = _conds(f, period=True)

        kpi = (await self.db.execute(text(
            f"SELECT count(*) total, "
            f"count(*) FILTER (WHERE t.ts_closed IS NULL) open, "
            f"count(*) FILTER (WHERE t.ts_closed IS NULL AND t.ts_deadline < now()) overdue, "
            f"count(*) FILTER (WHERE t.ts_closed IS NULL AND t.assignee IS NULL) unassigned "
            f"{base}"), p)).mappings().one()

        created_in_period = (await self.db.execute(text(
            f"SELECT count(*) FROM hubex_tasks t WHERE {where_p}"), p_period)).scalar_one()

        funnel = (await self.db.execute(text(
            f"SELECT coalesce(t.stage,'—') stage, count(*) n {base} "
            f"AND t.ts_closed IS NULL GROUP BY t.stage ORDER BY n DESC"), p)).mappings().all()

        by_type = (await self.db.execute(text(
            f"SELECT coalesce(t.task_type,'—') name, count(*) n {base} "
            f"AND t.ts_closed IS NULL GROUP BY t.task_type ORDER BY n DESC"), p)).mappings().all()

        by_crit = (await self.db.execute(text(
            f"SELECT coalesce(t.criticality,'—') name, max(t.criticality_color) color, count(*) n "
            f"{base} AND t.ts_closed IS NULL GROUP BY t.criticality ORDER BY n DESC"), p)).mappings().all()

        by_region = (await self.db.execute(text(
            f"SELECT coalesce(r.name,'— без региона') name, count(*) n "
            f"FROM hubex_tasks t LEFT JOIN regions r ON r.id = t.region_id "
            f"WHERE {where} AND t.ts_closed IS NULL GROUP BY r.name ORDER BY n DESC"), p)).mappings().all()

        # Точки для карты: координаты из raw.location.coordinate ("lat:lng").
        pts = (await self.db.execute(text(
            f"SELECT t.hubex_id, t.number, t.asset_name, t.status, t.status_color, "
            f"t.raw->'location'->>'coordinate' coord {base} "
            f"AND t.ts_closed IS NULL AND t.raw->'location'->>'coordinate' IS NOT NULL "
            f"LIMIT 1000"), p)).mappings().all()
        points = []
        for row in pts:
            coord = (row["coord"] or "").split(":")
            if len(coord) != 2:
                continue
            try:
                lat, lng = float(coord[0]), float(coord[1])
            except ValueError:
                continue
            points.append({
                "id": row["hubex_id"], "number": row["number"], "name": row["asset_name"],
                "status": row["status"], "color": row["status_color"], "lat": lat, "lng": lng,
            })

        return {
            # applied=false — все блоки ниже, кроме createdInPeriod, считаны «на сейчас».
            "period": {
                "from": f.date_from.isoformat(), "to": f.date_to.isoformat(),
                "applied": False,
                "note": "Снимок открытых заявок на текущий момент — период создания "
                        "не применяется (иначе выпадут давно открытые). "
                        "По периоду считается только «Создано за период».",
            },
            "kpi": {**dict(kpi), "createdInPeriod": int(created_in_period)},
            "funnel": [dict(r) for r in funnel],
            "byType": [dict(r) for r in by_type],
            "byCriticality": [dict(r) for r in by_crit],
            "byRegion": [dict(r) for r in by_region],
            "points": points,
        }

    async def sla(self, f: NetServiceFilter, breakdown: str = "criticality") -> dict[str, Any]:
        """SLA по timesheet за период (по ts_created)."""
        where, p = _conds(f, period=True)
        base = f"FROM hubex_tasks t WHERE {where}"
        col = {
            "criticality": "coalesce(t.criticality,'—')",
            "contractor": "coalesce(t.contractor_company,'—')",
            "task_type": "coalesce(t.task_type,'—')",
        }.get(breakdown, "coalesce(t.criticality,'—')")

        agg_cols = (
            "count(*) n, "
            "count(*) FILTER (WHERE t.ts_completed IS NOT NULL) completed, "
            "count(*) FILTER (WHERE t.ts_completed IS NOT NULL AND t.ts_deadline IS NOT NULL "
            "                 AND t.ts_completed <= t.ts_deadline) in_sla, "
            "avg(EXTRACT(EPOCH FROM (t.ts_assigned - t.ts_requested))) avg_reaction, "
            "avg(EXTRACT(EPOCH FROM (t.ts_completed - t.ts_assigned))) avg_work, "
            "percentile_cont(0.5) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (t.ts_completed - t.ts_assigned))) p50_work, "
            "percentile_cont(0.9) WITHIN GROUP (ORDER BY EXTRACT(EPOCH FROM (t.ts_completed - t.ts_assigned))) p90_work"
        )
        totals = (await self.db.execute(text(f"SELECT {agg_cols} {base}"), p)).mappings().one()
        rows = (await self.db.execute(text(
            f"SELECT {col} name, {agg_cols} {base} GROUP BY {col} ORDER BY n DESC LIMIT 30"),
            p)).mappings().all()

        def _shape(m: dict) -> dict:
            completed = m["completed"] or 0
            in_sla = m["in_sla"] or 0
            return {
                **{k: m[k] for k in ("name",) if k in m},
                "total": m["n"], "completed": completed,
                "slaPct": round(in_sla / completed * 100, 1) if completed else None,
                "avgReactionSec": round(m["avg_reaction"]) if m["avg_reaction"] is not None else None,
                "avgWorkSec": round(m["avg_work"]) if m["avg_work"] is not None else None,
                "p50WorkSec": round(m["p50_work"]) if m["p50_work"] is not None else None,
                "p90WorkSec": round(m["p90_work"]) if m["p90_work"] is not None else None,
            }

        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "breakdown": breakdown,
            "totals": _shape(dict(totals)),
            "rows": [_shape(dict(r)) for r in rows],
        }

    async def asset_reliability(self, f: NetServiceFilter, top: int = 10) -> dict[str, Any]:
        """Надёжность: топ проблемных объектов + распределение видов работ."""
        where, p = _conds(f, period=True)
        p["top"] = top
        problem = (await self.db.execute(text(
            f"SELECT t.asset_id, max(t.asset_name) asset_name, t.location_id, "
            f"count(*) total, "
            f"count(*) FILTER (WHERE t.task_type ILIKE '%авар%') incidents "
            f"FROM hubex_tasks t WHERE {where} AND t.asset_id IS NOT NULL "
            f"GROUP BY t.asset_id, t.location_id ORDER BY total DESC LIMIT :top"), p)).mappings().all()
        by_work = (await self.db.execute(text(
            f"SELECT coalesce(t.work_type,'—') name, count(*) n "
            f"FROM hubex_tasks t WHERE {where} GROUP BY t.work_type ORDER BY n DESC LIMIT 20"),
            p)).mappings().all()
        return {
            "period": {"from": f.date_from.isoformat(), "to": f.date_to.isoformat()},
            "topProblematic": [dict(r) for r in problem],
            "byWorkType": [dict(r) for r in by_work],
        }

    async def tasks_list(self, f: NetServiceFilter, *, status: str = "all",
                         q: str | None = None, limit: int = 50, offset: int = 0) -> dict[str, Any]:
        """Рабочий список заявок с фильтрами и пагинацией.

        Период применяется по ts_created (раньше принимался и выбрасывался — селектор
        периода не делал ничего). Исключение — status=open/overdue: незакрытая заявка
        живёт вне периода создания, отсечь её по ts_created значило бы спрятать самое
        проблемное. Что применено фактически — в `period.applied` ответа.
        """
        period_applied = status not in ("open", "overdue")
        where, p = _conds(f, period=period_applied)
        extra = ""
        if status == "open":
            extra += " AND t.ts_closed IS NULL"
        elif status == "closed":
            extra += " AND t.ts_closed IS NOT NULL"
        elif status == "overdue":
            extra += " AND t.ts_closed IS NULL AND t.ts_deadline < now()"
        if q:
            extra += (" AND (t.number ILIKE :q OR t.asset_name ILIKE :q "
                      "OR t.assignee ILIKE :q OR t.contractor_company ILIKE :q)")
            p["q"] = f"%{q}%"
        base = f"FROM hubex_tasks t WHERE {where}{extra}"
        total = (await self.db.execute(text(f"SELECT count(*) {base}"), p)).scalar_one()
        p["lim"] = limit
        p["off"] = offset
        rows = (await self.db.execute(text(
            f"SELECT t.hubex_id, t.number, t.status, t.status_color, t.stage, "
            f"t.task_type, t.work_type, t.criticality, t.criticality_color, "
            f"t.asset_id, t.asset_name, t.location_id, t.contractor_company, t.assignee, "
            f"t.ts_created, t.ts_deadline, t.ts_closed, t.is_overdue "
            f"{base} ORDER BY t.ts_created DESC NULLS LAST LIMIT :lim OFFSET :off"),
            p)).mappings().all()
        return {
            "period": {
                "from": f.date_from.isoformat(), "to": f.date_to.isoformat(),
                "applied": period_applied,
                "note": None if period_applied else
                        "Незакрытые заявки показаны вне периода создания — "
                        "иначе давно открытые выпадут из списка.",
            },
            "total": total,
            "rows": [dict(r) for r in rows],
        }
