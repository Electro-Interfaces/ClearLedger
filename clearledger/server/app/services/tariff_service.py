"""Тарифная аналитика ЭЗС — ценообразование сети (розница).

Изолировано от analytics_service. Даёт то, чего нет в общих разрезах:
  • price_grid — тарифная сетка регион × коннектор (преобладающий тариф + диапазон);
  • fact_vs_nominal — реальная цена (выручка÷энергия) vs номинал (tariff) по разрезу.
Договорные тарифы ЮЛ — в corporate_service; здесь — розница/публичная цена.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession
from app.services.analytics_cache import cached_report

_GROUP_COLS = {
    "region": ChargeSession.region,
    "station": ChargeSession.station_code,
    "connector": ChargeSession.connector_type,
    "user_type": ChargeSession.user_type,
}


class TariffService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _range(df: date, dt: date):
        return datetime.combine(df, datetime.min.time()), datetime.combine(dt, datetime.max.time())

    def _base_conds(self, company_id, lo, hi, user_type: str | None):
        S = ChargeSession
        conds = [S.company_id == company_id, S.started_at.is_not(None),
                 S.started_at >= lo, S.started_at <= hi, S.energy_kwh > 0]
        if user_type:
            conds.append(S.user_type == user_type)
        return conds

    @cached_report("tariff:grid")
    async def price_grid(self, company_id, df: date, dt: date, by: str = "region",
                         user_type: str | None = None) -> dict[str, Any]:
        """Тарифная сетка: <разрез by> × коннектор → преобладающий тариф (mode),
        диапазон, сессии/энергия/факт.цена. by = region | station. Фронт пивотит в матрицу."""
        S = ChargeSession
        lo, hi = self._range(df, dt)
        # Строка сетки: станция ТОЛЬКО по коду (имя — подпись после агрегации,
        # свежайшее из сессий; имя в ключе группировки двоило строку при
        # переименованиях CPO — «идентичность станции = код»), либо регион.
        if by == "station":
            rowdim = func.coalesce(S.station_code, "—")
        else:
            rowdim = func.coalesce(S.region, "—")
        stmt = select(
            rowdim.label("row"),
            func.coalesce(S.connector_type, "—").label("connector"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            # факт.выручка = корп-выручка (client_amount) для ЮЛ, иначе розница (amount).
            func.coalesce(func.sum(func.coalesce(S.client_amount, S.amount)), 0).label("amount"),
            func.min(S.tariff).label("tmin"),
            func.max(S.tariff).label("tmax"),
            func.mode().within_group(S.tariff.asc()).label("tmode"),
        ).where(*self._base_conds(company_id, lo, hi, user_type)).group_by("row", "connector")
        raw = (await self.db.execute(stmt)).all()

        # подпись станции: свежайшее имя из сессий + код
        label_of: dict[str, str] = {}
        if by == "station":
            fresh = (await self.db.execute(
                select(S.station_code, S.station_name)
                .where(S.company_id == company_id, S.station_name.is_not(None))
                .distinct(S.station_code)
                .order_by(S.station_code, S.started_at.desc())
            )).all()
            label_of = {str(c): f"{n} ({c})" for c, n in fresh if c is not None}

        cells: list[dict[str, Any]] = []
        rows_vol: dict[str, int] = {}
        connectors: dict[str, int] = {}
        for r in raw:
            energy = float(r.energy)
            amount = float(r.amount)
            tmin, tmax = float(r.tmin or 0), float(r.tmax or 0)
            row_label = label_of.get(str(r.row), str(r.row)) if by == "station" else r.row
            cells.append({
                "row": row_label, "connector": r.connector,
                "sessions": int(r.sessions), "energy_kwh": round(energy, 1),
                "tariff": round(float(r.tmode or 0), 2),        # преобладающий (mode)
                "tariff_min": round(tmin, 2), "tariff_max": round(tmax, 2),
                "varies": abs(tmax - tmin) > 0.01,
                "realized": round(amount / energy, 2) if energy else 0.0,   # факт: ₽/кВтч
            })
            rows_vol[row_label] = rows_vol.get(row_label, 0) + int(r.sessions)
            connectors[r.connector] = connectors.get(r.connector, 0) + int(r.sessions)
        # порядок строк/коннекторов — по объёму (сессиям)
        row_order = [k for k, _ in sorted(rows_vol.items(), key=lambda x: -x[1])]
        conn_order = [k for k, _ in sorted(connectors.items(), key=lambda x: -x[1])]
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()}, "by": by,
                "rows": row_order, "connectors": conn_order, "cells": cells}

    @cached_report("tariff:fact_vs_nominal")
    async def fact_vs_nominal(self, company_id, df: date, dt: date, group_by: str = "region",
                              user_type: str | None = None) -> dict[str, Any]:
        """По разрезу: номинал (энерговзвеш. tariff) vs факт (выручка÷энергия) + отклонение."""
        S = ChargeSession
        gcol = _GROUP_COLS.get(group_by, S.region)
        lo, hi = self._range(df, dt)
        stmt = select(
            func.coalesce(gcol, "—").label("g"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(func.coalesce(S.client_amount, S.amount)), 0).label("amount"),
            func.coalesce(func.sum(S.energy_kwh * S.tariff), 0).label("nominal_rev"),
        ).where(*self._base_conds(company_id, lo, hi, user_type)).group_by("g")
        rows = (await self.db.execute(stmt)).all()

        lines: list[dict[str, Any]] = []
        tot_e = tot_a = tot_n = 0.0
        for r in rows:
            energy = float(r.energy)
            amount = float(r.amount)
            nominal_rev = float(r.nominal_rev)
            nominal = nominal_rev / energy if energy else 0.0
            realized = amount / energy if energy else 0.0
            lines.append({
                "label": r.g, "sessions": int(r.sessions), "energy_kwh": round(energy, 1),
                "nominal": round(nominal, 2), "realized": round(realized, 2),
                "delta": round(realized - nominal, 2),
                "delta_pct": round((realized - nominal) / nominal * 100, 1) if nominal else 0.0,
            })
            tot_e += energy
            tot_a += amount
            tot_n += nominal_rev
        lines.sort(key=lambda x: -x["energy_kwh"])
        totals = {
            "energy_kwh": round(tot_e, 1),
            "nominal": round(tot_n / tot_e, 2) if tot_e else 0.0,
            "realized": round(tot_a / tot_e, 2) if tot_e else 0.0,
            "delta": round((tot_a - tot_n) / tot_e, 2) if tot_e else 0.0,
        }
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "group_by": group_by, "lines": lines, "totals": totals}
