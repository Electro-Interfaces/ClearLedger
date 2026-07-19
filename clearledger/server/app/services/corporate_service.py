"""Корпоративное направление ЭЗС (ЮЛ) — реестр клиентов + метрики/гэп/биллинг.

Изолировано от analytics_service. Источник: `corporate_clients` (реестр из
справочника) LEFT JOIN агрегаты `charge_sessions` (ЮЛ, период). Ключевое —
двойная цена сессии: розница станции (tariff/amount) vs договор ЮЛ
(client_tariff/client_amount) → скидка/наценка направления.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, CorporateClient
from app.services.analytics_cache import cached_report


class CorporateService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _metrics_by_client(self, company_id, df: date, dt: date) -> dict[str, Any]:
        """Агрегаты сессий по client_name (период). corp = client_amount (договор),
        retail = energy×tariff (розница-эквивалент)."""
        S = ChargeSession
        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        stmt = select(
            S.client_name.label("name"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(S.client_amount), 0).label("corp"),
            func.coalesce(func.sum(S.energy_kwh * S.tariff), 0).label("retail"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("success"),
        ).where(
            S.company_id == company_id, S.client_name.is_not(None),
            S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
        ).group_by(S.client_name)
        return {r.name: r for r in (await self.db.execute(stmt)).all()}

    @staticmethod
    def _line(c: CorporateClient, m) -> dict[str, Any]:
        sessions = int(m.sessions) if m else 0
        energy = float(m.energy) if m else 0.0
        corp = float(m.corp) if m else 0.0
        retail = float(m.retail) if m else 0.0
        success = int(m.success) if m else 0
        return {
            "name": c.name, "phone": c.phone, "ext_id": c.ext_id,
            "mode": c.mode, "rate": float(c.rate) if c.rate is not None else None,
            "matrix": c.matrix, "contract_start": c.contract_start,
            "status": c.status, "users": c.users,
            "sessions": sessions, "energy_kwh": round(energy, 1),
            "corp_revenue": round(corp, 2), "retail_revenue": round(retail, 2),
            "discount": round(corp - retail, 2),                                  # <0 = скидка ЮЛ
            "discount_pct": round((corp - retail) / retail * 100, 1) if retail else 0.0,
            "avg_tariff": round(corp / energy, 2) if energy else 0.0,
            "success_pct": round(success / sessions * 100, 1) if sessions else 0.0,
        }

    @staticmethod
    def _totals(lines: list[dict[str, Any]]) -> dict[str, Any]:
        def s(k: str) -> float:
            return sum(x[k] for x in lines)
        energy, corp, retail = s("energy_kwh"), s("corp_revenue"), s("retail_revenue")
        return {
            "clients": len(lines),
            "active_clients": sum(1 for x in lines if x["sessions"] > 0),
            "sessions": int(s("sessions")), "energy_kwh": round(energy, 1),
            "corp_revenue": round(corp, 2), "retail_revenue": round(retail, 2),
            "discount": round(corp - retail, 2),
            "discount_pct": round((corp - retail) / retail * 100, 1) if retail else 0.0,
            "avg_tariff": round(corp / energy, 2) if energy else 0.0,
        }

    @cached_report("corp:clients")
    async def clients(self, company_id, df: date, dt: date) -> dict[str, Any]:
        """Полная строка по каждому клиенту реестра: договор + метрики + гэп. Питает
        табы Клиенты / Тарифы / Рентабельность / Биллинг."""
        regs = (await self.db.execute(
            select(CorporateClient).where(CorporateClient.company_id == company_id)
            .order_by(CorporateClient.name))).scalars().all()
        metrics = await self._metrics_by_client(company_id, df, dt)
        lines = [self._line(c, metrics.get(c.name)) for c in regs]
        lines.sort(key=lambda x: -x["corp_revenue"])
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "clients": lines, "totals": self._totals(lines)}

    @cached_report("corp:billing")
    async def billing(self, company_id, df: date, dt: date, client: str | None = None,
                      vat_rate: float = 20.0) -> dict[str, Any]:
        """Данные под УПД: сводка на клиента + детализация-номенклатура (по договорному
        тарифу). Тариф «НДС в том числе» → выделяем НДС из суммы с НДС (gross)."""
        S = ChargeSession
        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        conds = [
            S.company_id == company_id, S.client_name.is_not(None),
            S.client_amount.is_not(None),
            S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
        ]
        if client:
            conds.append(S.client_name == client)
        stmt = select(
            S.client_name, S.client_tariff,
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(S.client_amount), 0).label("gross"),
        ).where(*conds).group_by(S.client_name, S.client_tariff).order_by(S.client_name)
        raw = (await self.db.execute(stmt)).all()

        vf = vat_rate / (100.0 + vat_rate)   # доля НДС в сумме с НДС
        def split(gross: float) -> tuple[float, float]:
            vat = round(gross * vf, 2)
            return vat, round(gross - vat, 2)   # (НДС, без НДС)

        detail: list[dict[str, Any]] = []
        summ: dict[str, dict[str, float]] = {}
        for r in raw:
            name = r.client_name
            tariff = float(r.client_tariff or 0)
            sessions = int(r.sessions)
            energy = float(r.energy)
            gross = float(r.gross)
            vat, net = split(gross)
            detail.append({"client": name, "tariff": tariff, "sessions": sessions,
                           "energy_kwh": round(energy, 3), "gross": round(gross, 2),
                           "vat": vat, "net": net})
            s = summ.setdefault(name, {"sessions": 0.0, "energy": 0.0, "gross": 0.0})
            s["sessions"] += sessions
            s["energy"] += energy
            s["gross"] += gross

        summary: list[dict[str, Any]] = []
        for name, s in summ.items():
            vat, net = split(s["gross"])
            summary.append({"client": name, "sessions": int(s["sessions"]),
                            "energy_kwh": round(s["energy"], 3), "gross": round(s["gross"], 2),
                            "vat": vat, "net": net,
                            "avg_tariff": round(s["gross"] / s["energy"], 2) if s["energy"] else 0.0})
        summary.sort(key=lambda x: -x["gross"])
        detail.sort(key=lambda x: (x["client"], -x["gross"]))
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "vat_rate": vat_rate, "summary": summary, "detail": detail}

    @cached_report("corp:client-card")
    async def client_card(self, company_id, client: str, df: date, dt: date,
                          history_months: int = 0) -> dict[str, Any]:
        """Карточка одного ЮЛ: помесячная реализация за период + профиль потребления.

        Отвечает на вопрос «как развиваются отношения»: растёт ли выборка,
        расширяется ли парк карт, где и когда клиент заряжается, сколько ему
        стоит скидка. Помесячная разбивка — основа: у корпоратива годовой
        договор, но управляют им по месяцам (акт, счёт, лимит).

        Даты первой/последней сессии берутся по ВСЕЙ истории, а не по периоду:
        «клиент с нами с апреля 2023» и «последняя зарядка 40 дней назад» —
        факты о клиенте, которые контур не должен обрезать. Всё остальное
        считается строго внутри выбранного периода.

        `history_months` расширяет ТОЛЬКО помесячный ряд (N месяцев до конца
        периода): на контуре в три недели динамики не видно, а именно она —
        предмет разговора о клиенте. Итоги, средние и разрезы при этом остаются
        по контуру, иначе карточка молча покажет не то, что заявлено в шапке.
        """
        S = ChargeSession
        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        scope = [S.company_id == company_id, S.client_name == client,
                 S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi]

        # Горизонт помесячного ряда: либо контур, либо N месяцев до его конца.
        m_from = df
        if history_months > 0:
            first = date(dt.year, dt.month, 1)
            back = history_months - 1
            m_from = date(first.year - (back // 12) - (1 if first.month <= back % 12 else 0),
                          (first.month - back % 12 - 1) % 12 + 1, 1)
        m_lo = datetime.combine(m_from, datetime.min.time())
        m_scope = [S.company_id == company_id, S.client_name == client,
                   S.started_at.is_not(None), S.started_at >= m_lo, S.started_at <= hi]

        reg = (await self.db.execute(
            select(CorporateClient).where(CorporateClient.company_id == company_id,
                                          CorporateClient.name == client))).scalar_one_or_none()

        # ── помесячно: ядро карточки ───────────────────────────────────────
        month = func.date_trunc("month", S.started_at).label("month")
        rows = (await self.db.execute(
            select(
                month,
                func.count().label("sessions"),
                func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
                func.coalesce(func.sum(S.client_amount), 0).label("corp"),
                func.coalesce(func.sum(S.energy_kwh * S.tariff), 0).label("retail"),
                func.count(func.distinct(S.user_id)).label("drivers"),
                func.count(func.distinct(S.station_code)).label("stations"),
            ).where(*m_scope).group_by(month).order_by(month))).all()

        months: list[dict[str, Any]] = []
        for r in rows:
            energy = float(r.energy or 0)
            corp = float(r.corp or 0)
            retail = float(r.retail or 0)
            mstart = r.month.date() if r.month else None
            # Крайние месяцы период обычно режет: «1–18 июля» против полного
            # июня даст −59% на ровном месте. Считаем покрытие и помечаем —
            # иначе падение границы периода читается как падение клиента.
            partial = False
            days_covered = days_in_month = 0
            if mstart:
                nxt = date(mstart.year + (mstart.month == 12),
                           mstart.month % 12 + 1, 1)
                days_in_month = (nxt - mstart).days
                days_covered = (min(dt, nxt - timedelta(days=1)) - max(m_from, mstart)).days + 1
                partial = days_covered < days_in_month
            months.append({
                "month": mstart.isoformat() if mstart else None,
                "sessions": int(r.sessions or 0),
                "energy_kwh": round(energy, 1),
                "corp_revenue": round(corp, 2),
                "retail_revenue": round(retail, 2),
                "discount": round(corp - retail, 2),
                "avg_tariff": round(corp / energy, 2) if energy else 0.0,
                "drivers": int(r.drivers or 0),
                "stations": int(r.stations or 0),
                "partial": partial,
                "days_covered": days_covered,
                "days_in_month": days_in_month,
            })
        # Δ выручки к предыдущему месяцу — считаем здесь, а не в UI: одна
        # реализация вместо повторов в каждой карточке. Для неполных месяцев
        # Δ не даём: сравнивать 18 дней с 30 нельзя, а «−59%» выглядит как факт.
        for i, m in enumerate(months):
            prev = months[i - 1] if i else None
            m["revenue_delta_pct"] = (
                round((m["corp_revenue"] - prev["corp_revenue"]) / prev["corp_revenue"] * 100, 1)
                if prev and prev["corp_revenue"] and not m["partial"] and not prev["partial"]
                else None)

        # ── разрезы потребления ────────────────────────────────────────────
        async def top(col, limit: int = 8, label=None) -> list[dict[str, Any]]:
            res = (await self.db.execute(
                select(
                    (label if label is not None else col).label("label"),
                    func.count().label("sessions"),
                    func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
                    func.coalesce(func.sum(S.client_amount), 0).label("corp"),
                ).where(*scope, col.is_not(None))
                .group_by(label if label is not None else col)
                .order_by(func.coalesce(func.sum(S.client_amount), 0).desc())
                .limit(limit))).all()
            return [{"label": str(x.label), "sessions": int(x.sessions or 0),
                     "energy_kwh": round(float(x.energy or 0), 1),
                     "corp_revenue": round(float(x.corp or 0), 2)} for x in res]

        stations = await top(S.station_code,
                             label=func.coalesce(S.station_name, S.station_code))
        regions = await top(S.region, limit=6)
        connectors = await top(S.connector_type, limit=6)
        drivers = await top(S.user_id, limit=10)

        # ── когда заряжаются: будни/выходные и пиковый час ────────────────
        # Характер парка: развозной транспорт даёт будни-день, такси — круглые
        # сутки, служебный — утро и вечер. Это подсказка к переговорам о тарифе.
        dow = func.extract("isodow", S.started_at)
        wk = (await self.db.execute(
            select(
                func.coalesce(func.sum(case((dow <= 5, 1), else_=0)), 0).label("weekday"),
                func.coalesce(func.sum(case((dow > 5, 1), else_=0)), 0).label("weekend"),
            ).where(*scope))).one()
        hour = func.extract("hour", S.started_at).label("hour")
        hours = (await self.db.execute(
            select(hour, func.count().label("sessions"))
            .where(*scope).group_by(hour).order_by(hour))).all()

        # ── история отношений: за пределами периода ───────────────────────
        life = (await self.db.execute(
            select(func.min(S.started_at).label("first"),
                   func.max(S.started_at).label("last"),
                   func.count().label("sessions"),
                   func.coalesce(func.sum(S.client_amount), 0).label("corp"))
            .where(S.company_id == company_id, S.client_name == client,
                   S.started_at.is_not(None)))).one()

        totals = self._line(reg, None) if reg else {"name": client}
        agg = await self._metrics_by_client(company_id, df, dt)
        if reg:
            totals = self._line(reg, agg.get(client))
        else:
            # Клиента нет в реестре договоров, но сессии на его имя есть —
            # показываем метрики без карточки договора, а не пустой экран.
            m = agg.get(client)
            totals = self._line(CorporateClient(name=client), m) if m else totals

        # Средние — строго по контуру (totals), а НЕ по ряду месяцев: при
        # расширенном горизонте ряд содержит месяцы вне периода, и деление
        # контурной выручки на его сессии давало средний чек в 14 раз меньше.
        sessions_total = totals.get("sessions", 0)
        energy_total = totals.get("energy_kwh", 0.0)
        months_in_scope = sum(1 for m in months
                              if m["month"] and m["month"] >= df.replace(day=1).isoformat())
        return {
            "client": client,
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
            # Горизонт ряда месяцев: равен контуру, пока его явно не расширили.
            "months_period": {"from": m_from.isoformat(), "to": dt.isoformat()},
            "history_months": history_months,
            "profile": {
                "phone": reg.phone if reg else None,
                "ext_id": reg.ext_id if reg else None,
                "mode": reg.mode if reg else None,
                "rate": float(reg.rate) if reg and reg.rate is not None else None,
                "matrix": reg.matrix if reg else None,
                "contract_start": reg.contract_start if reg else None,
                "status": reg.status if reg else None,
                "users": reg.users if reg else None,
                "in_registry": reg is not None,
            },
            "totals": totals,
            "averages": {
                "avg_check": round(totals["corp_revenue"] / sessions_total, 2) if sessions_total else 0.0,
                "avg_kwh": round(energy_total / sessions_total, 1) if sessions_total else 0.0,
                "sessions_per_month": round(sessions_total / months_in_scope, 1) if months_in_scope else 0.0,
            },
            "months": months,
            "stations": stations,
            "regions": regions,
            "connectors": connectors,
            "drivers": drivers,
            "when": {
                "weekday": int(wk.weekday or 0), "weekend": int(wk.weekend or 0),
                "hours": [{"hour": int(h.hour), "sessions": int(h.sessions)} for h in hours],
            },
            "lifetime": {
                "first_session": life.first.date().isoformat() if life.first else None,
                "last_session": life.last.date().isoformat() if life.last else None,
                "sessions": int(life.sessions or 0),
                "corp_revenue": round(float(life.corp or 0), 2),
            },
        }

    @cached_report("corp:overview")
    async def overview(self, company_id, df: date, dt: date) -> dict[str, Any]:
        """Стратегический слой ЮЛ: KPI + топ-клиенты + алерты."""
        data = await self.clients(company_id, df, dt)
        lines: list[dict[str, Any]] = data["clients"]
        top = [x for x in lines if x["corp_revenue"] > 0][:5]
        alerts: list[dict[str, str]] = []
        inactive = [x for x in lines if (x["status"] or "").strip().lower() not in ("действующая", "")]
        if inactive:
            alerts.append({"level": "warn",
                           "message": f"Договор не «Действующая»: {len(inactive)} — {', '.join(x['name'] for x in inactive[:3])}"})
        deep = [x for x in lines if x["corp_revenue"] > 0 and x["discount_pct"] <= -20]
        if deep:
            alerts.append({"level": "warn",
                           "message": f"Глубокая скидка (≤−20%): {len(deep)} клиент(ов) — {', '.join(x['name'] for x in deep[:3])}"})
        idle = [x for x in lines if x["sessions"] == 0]
        if idle:
            alerts.append({"level": "info",
                           "message": f"Без сессий за период: {len(idle)} клиент(ов)"})
        return {"period": data["period"], "totals": data["totals"],
                "top_clients": top, "alerts": alerts}
