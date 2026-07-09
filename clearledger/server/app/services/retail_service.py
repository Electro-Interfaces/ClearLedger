"""Розничное направление ЭЗС (ФЛ) — аналитика в разрезе аккаунтов частных лиц.

Аккаунт ФЛ = телефон (`charge_sessions.user_id`), НЕ сматченный на организацию
(`client_name IS NULL`). В отличие от ЮЛ, у ФЛ `amount` — это живая
предоплаченная розничная выручка (без договорной матрицы), поэтому выручка
берётся напрямую из `amount`.

Разрезы (по образцу corporate_service, но группировка по user_id):
  * overview   — KPI розничной базы (аккаунты/активные/новые, выручка/энергия,
                 средний чек, доход на аккаунт);
  * segments   — RFM-сегментация (Recency-Frequency-Monetary) → классы аккаунтов;
  * economics  — Pareto/концентрация выручки + распределение сессий-на-аккаунт;
  * cohorts    — удержание по когортам месяца первой сессии (retention-матрица);
  * geo        — гео-станционная привязка/мобильность (моно- vs мульти-станция).

Телефоны псевдонимизируются (`pii_account`): в ответах — хеш-ID + маска, сырой
номер не отдаётся.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, Region, ServiceLocation
from app.services.pii_account import account_hash, mask_phone

S = ChargeSession


def _retail_conds(company_id) -> list:
    """ФЛ = есть телефон-аккаунт и НЕ корпоратив (не сматчен на организацию)."""
    return [
        S.company_id == company_id,
        S.user_id.is_not(None),
        S.client_name.is_(None),
    ]


def _period(df: date, dt: date) -> tuple[datetime, datetime]:
    return (datetime.combine(df, datetime.min.time()),
            datetime.combine(dt, datetime.max.time()))


class RetailService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── ядро: агрегат по аккаунтам за период ─────────────────────────────
    async def _accounts(self, company_id, df: date, dt: date) -> list[dict[str, Any]]:
        """Одна строка на аккаунт ФЛ за период. Отсюда питаются RFM/экономика/гео."""
        lo, hi = _period(df, dt)
        stmt = select(
            S.user_id.label("phone"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
            func.min(S.started_at).label("first_at"),
            func.max(S.started_at).label("last_at"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("success"),
            func.count(func.distinct(S.location_id)).label("stations"),   # объекты L2 (нормализ.)
            func.count(func.distinct(S.region)).label("regions"),
        ).where(
            *_retail_conds(company_id),
            S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
        ).group_by(S.user_id)
        rows = (await self.db.execute(stmt)).all()
        end = hi
        out: list[dict[str, Any]] = []
        for r in rows:
            sessions = int(r.sessions)
            energy = float(r.energy)
            revenue = float(r.revenue)
            recency = (end - r.last_at).days if r.last_at else None
            out.append({
                "phone": r.phone,
                "account": account_hash(r.phone),
                "masked": mask_phone(r.phone),
                "sessions": sessions,
                "energy_kwh": round(energy, 1),
                "revenue": round(revenue, 2),
                "avg_check": round(revenue / sessions, 2) if sessions else 0.0,
                "avg_kwh": round(energy / sessions, 2) if sessions else 0.0,
                "avg_tariff": round(revenue / energy, 2) if energy else 0.0,
                "first_at": r.first_at.isoformat() if r.first_at else None,
                "last_at": r.last_at.isoformat() if r.last_at else None,
                "recency_days": recency,
                "success_pct": round(int(r.success) / sessions * 100, 1) if sessions else 0.0,
                "stations": int(r.stations),
                "regions": int(r.regions),
            })
        return out

    # ── overview: KPI розничной базы ─────────────────────────────────────
    async def overview(self, company_id, df: date, dt: date) -> dict[str, Any]:
        accts = await self._accounts(company_id, df, dt)
        lo, hi = _period(df, dt)
        # «Новые» = аккаунты, чья ПЕРВАЯ В ИСТОРИИ сессия попала в период.
        new_stmt = select(func.count()).select_from(
            select(S.user_id, func.min(S.started_at).label("f"))
            .where(*_retail_conds(company_id), S.started_at.is_not(None))
            .group_by(S.user_id).having(func.min(S.started_at) >= lo)
            .having(func.min(S.started_at) <= hi).subquery()
        )
        new_accounts = int((await self.db.execute(new_stmt)).scalar() or 0)

        n = len(accts)
        sessions = sum(a["sessions"] for a in accts)
        energy = sum(a["energy_kwh"] for a in accts)
        revenue = sum(a["revenue"] for a in accts)
        return {
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
            "totals": {
                "accounts": n,
                "new_accounts": new_accounts,
                "sessions": sessions,
                "energy_kwh": round(energy, 1),
                "revenue": round(revenue, 2),
                "arpa": round(revenue / n, 2) if n else 0.0,             # доход на аккаунт
                "avg_sessions": round(sessions / n, 1) if n else 0.0,
                "avg_check": round(revenue / sessions, 2) if sessions else 0.0,
                "avg_tariff": round(revenue / energy, 2) if energy else 0.0,
            },
        }

    # ── segments: RFM ────────────────────────────────────────────────────
    @staticmethod
    def _rfm_segment(r_days: int | None, freq: int, monetary: float,
                     r_thr: tuple[float, float], f_thr: tuple[float, float]) -> str:
        """Класс аккаунта по R (давность) и F (частота). M — сумма (для порядка)."""
        recent = r_days is not None and r_days <= r_thr[0]
        lapsing = r_days is not None and r_days > r_thr[1]
        frequent = freq >= f_thr[1]
        occasional = freq >= f_thr[0]
        if freq == 1:
            return "Разовые" if not recent else "Новички"
        if lapsing:
            return "Отток" if frequent else "Уснувшие"
        if recent and frequent:
            return "Чемпионы"
        if recent and occasional:
            return "Лояльные"
        if frequent:
            return "Под риском"
        return "Случайные"

    async def segments(self, company_id, df: date, dt: date) -> dict[str, Any]:
        accts = await self._accounts(company_id, df, dt)
        if not accts:
            return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                    "segments": [], "totals": {"accounts": 0}}

        recencies = sorted(a["recency_days"] for a in accts if a["recency_days"] is not None)
        freqs = sorted(a["sessions"] for a in accts)

        def q(arr: list[float], p: float) -> float:
            if not arr:
                return 0.0
            i = min(len(arr) - 1, int(p * len(arr)))
            return float(arr[i])

        r_thr = (q(recencies, 0.33), q(recencies, 0.66))   # свежие / уснувшие пороги
        f_thr = (q(freqs, 0.50), q(freqs, 0.80))           # частота: медиана / топ-20%

        buckets: dict[str, dict[str, float]] = {}
        for a in accts:
            seg = self._rfm_segment(a["recency_days"], a["sessions"], a["revenue"], r_thr, f_thr)
            b = buckets.setdefault(seg, {"accounts": 0, "sessions": 0, "energy": 0.0, "revenue": 0.0})
            b["accounts"] += 1
            b["sessions"] += a["sessions"]
            b["energy"] += a["energy_kwh"]
            b["revenue"] += a["revenue"]

        total_rev = sum(b["revenue"] for b in buckets.values()) or 1.0
        order = ["Чемпионы", "Лояльные", "Под риском", "Новички", "Случайные", "Разовые", "Уснувшие", "Отток"]
        segs = [{
            "segment": name,
            "accounts": int(b["accounts"]),
            "sessions": int(b["sessions"]),
            "energy_kwh": round(b["energy"], 1),
            "revenue": round(b["revenue"], 2),
            "revenue_pct": round(b["revenue"] / total_rev * 100, 1),
            "avg_check": round(b["revenue"] / b["sessions"], 2) if b["sessions"] else 0.0,
        } for name, b in buckets.items()]
        segs.sort(key=lambda x: (order.index(x["segment"]) if x["segment"] in order else 99))
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "segments": segs, "totals": {"accounts": len(accts)},
                "thresholds": {"recency": r_thr, "frequency": f_thr}}

    # ── economics: Pareto/концентрация ───────────────────────────────────
    async def economics(self, company_id, df: date, dt: date) -> dict[str, Any]:
        accts = await self._accounts(company_id, df, dt)
        n = len(accts)
        if not n:
            return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                    "pareto": [], "session_buckets": [], "totals": {"accounts": 0}}

        by_rev = sorted((a["revenue"] for a in accts), reverse=True)
        total = sum(by_rev) or 1.0
        # Концентрация: топ-X% аккаунтов дают Y% выручки.
        pareto = []
        for pct in (1, 5, 10, 20, 50):
            k = max(1, round(n * pct / 100))
            share = sum(by_rev[:k]) / total * 100
            pareto.append({"top_pct": pct, "accounts": k, "revenue_pct": round(share, 1)})

        # Распределение по числу сессий на аккаунт.
        edges = [(1, 1, "1"), (2, 3, "2–3"), (4, 10, "4–10"), (11, 50, "11–50"), (51, 10**9, "50+")]
        sbuckets = []
        for lo_e, hi_e, label in edges:
            grp = [a for a in accts if lo_e <= a["sessions"] <= hi_e]
            rev = sum(a["revenue"] for a in grp)
            sbuckets.append({
                "bucket": label, "accounts": len(grp),
                "accounts_pct": round(len(grp) / n * 100, 1),
                "revenue": round(rev, 2), "revenue_pct": round(rev / total * 100, 1),
            })
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "pareto": pareto, "session_buckets": sbuckets,
                "totals": {"accounts": n, "revenue": round(total, 2),
                           "arpa": round(total / n, 2)}}

    # ── geo: мобильность/привязка к станциям (НОРМАЛИЗОВАННЫЙ слой) ────────
    async def geo(self, company_id, df: date, dt: date) -> dict[str, Any]:
        """Гео/мобильность на L2-слое: станции считаются по `location_id` (объект
        `service_locations`), регионы — канон `regions.name` (join по location_id).
        Сессии без привязки к объекту (location_id NULL — «сироты») показываются
        отдельной строкой, а не молча отбрасываются."""
        lo, hi = _period(df, dt)
        base = [*_retail_conds(company_id), S.started_at.is_not(None),
                S.started_at >= lo, S.started_at <= hi]

        # Покрытие нормализацией: доля сессий/выручки, привязанных к объекту L2.
        cov = (await self.db.execute(select(
            func.count().label("total"),
            func.count(S.location_id).label("resolved"),
            func.coalesce(func.sum(S.amount), 0).label("rev_total"),
            func.coalesce(func.sum(case((S.location_id.is_not(None), S.amount), else_=0)), 0).label("rev_res"),
        ).where(*base))).one()
        total_s, resolved_s = int(cov.total), int(cov.resolved)
        rev_total, rev_res = float(cov.rev_total), float(cov.rev_res)
        coverage = {
            "sessions_total": total_s, "sessions_resolved": resolved_s,
            "sessions_orphan": total_s - resolved_s,
            "resolved_pct": round(resolved_s / total_s * 100, 1) if total_s else 0.0,
            "revenue_orphan": round(rev_total - rev_res, 2),
            "orphan_revenue_pct": round((rev_total - rev_res) / rev_total * 100, 1) if rev_total else 0.0,
        }

        # Мобильность: distinct объектов L2 на аккаунт. st=0 (все сессии — сироты)
        # → отдельный бакет «без привязки».
        per = select(
            S.user_id.label("uid"),
            func.count(func.distinct(S.location_id)).label("st"),
            func.coalesce(func.sum(S.amount), 0).label("rev"),
        ).where(*base).group_by(S.user_id).subquery()
        rows = (await self.db.execute(select(per.c.uid, per.c.st, per.c.rev))).all()
        n = len(rows)
        def _bucket(st: int) -> str:
            if st == 0: return "без привязки"
            if st == 1: return "1 объект"
            if st <= 3: return "2–3"
            return "4+"
        order = ["1 объект", "2–3", "4+", "без привязки"]
        agg: dict[str, dict[str, float]] = {}
        st_sum = st_cnt = 0
        for r in rows:
            st = int(r.st)
            b = agg.setdefault(_bucket(st), {"accounts": 0, "revenue": 0.0})
            b["accounts"] += 1
            b["revenue"] += float(r.rev)
            if st > 0:
                st_sum += st
                st_cnt += 1
        mobility = [{"bucket": k, "accounts": int(agg[k]["accounts"]),
                     "accounts_pct": round(agg[k]["accounts"] / n * 100, 1) if n else 0.0,
                     "revenue": round(agg[k]["revenue"], 2)}
                    for k in order if k in agg]
        avg_stations = round(st_sum / st_cnt, 2) if st_cnt else 0.0

        # Регионы — КАНОН service_locations→regions (outer-join по location_id;
        # каст uuid→text, т.к. location_id хранится строкой). `reg` — один объект
        # в SELECT и GROUP BY.
        reg = func.coalesce(Region.name, "— (без объекта L2)")
        join = S.__table__.outerjoin(
            ServiceLocation.__table__, cast(ServiceLocation.id, String) == S.location_id,
        ).outerjoin(Region.__table__, Region.id == ServiceLocation.region_id)
        reg_stmt = select(
            reg.label("region"),
            func.count(func.distinct(S.user_id)).label("accounts"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
        ).select_from(join).where(*base).group_by(reg).order_by(func.sum(S.amount).desc()).limit(15)
        regions = [{"region": r.region, "accounts": int(r.accounts),
                    "sessions": int(r.sessions), "revenue": round(float(r.revenue), 2)}
                   for r in (await self.db.execute(reg_stmt)).all()]

        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "mobility": mobility, "avg_stations": avg_stations,
                "coverage": coverage, "regions": regions, "totals": {"accounts": n}}

    # ── cohorts: удержание (вся история, не период) ──────────────────────
    async def cohorts(self, company_id, months: int = 12) -> dict[str, Any]:
        """Retention-матрица: когорта = месяц первой сессии; ячейка = сколько
        аккаунтов когорты были активны через N месяцев. По всей истории."""
        cohort_m = func.date_trunc("month", func.min(S.started_at))
        firsts = select(S.user_id.label("uid"), cohort_m.label("cohort")).where(
            *_retail_conds(company_id), S.started_at.is_not(None)).group_by(S.user_id).subquery()
        # Один объект `am` в SELECT и GROUP BY (иначе разные bind-параметры → GroupingError).
        am = func.date_trunc("month", S.started_at)
        acts = select(
            S.user_id.label("uid"), am.label("m"),
        ).where(*_retail_conds(company_id), S.started_at.is_not(None)).group_by(
            S.user_id, am).subquery()

        stmt = select(
            firsts.c.cohort, acts.c.m,
            func.count(func.distinct(acts.c.uid)).label("cnt"),
        ).select_from(firsts.join(acts, firsts.c.uid == acts.c.uid)).group_by(
            firsts.c.cohort, acts.c.m)
        rows = (await self.db.execute(stmt)).all()

        # Собираем матрицу cohort → {offset: count} в Python.
        def ym(d: datetime) -> tuple[int, int]:
            return (d.year, d.month)

        def off(c: datetime, m: datetime) -> int:
            return (m.year - c.year) * 12 + (m.month - c.month)

        cohorts: dict[tuple[int, int], dict[int, int]] = {}
        base: dict[tuple[int, int], datetime] = {}
        for r in rows:
            ck = ym(r.cohort)
            base.setdefault(ck, r.cohort)
            cohorts.setdefault(ck, {})[off(r.cohort, r.m)] = int(r.cnt)

        keys = sorted(cohorts.keys())[-months:]
        max_off = max((o for ck in keys for o in cohorts[ck]), default=0)
        matrix = []
        for ck in keys:
            row = cohorts[ck]
            size = row.get(0, 0) or 1
            matrix.append({
                "cohort": f"{ck[0]:04d}-{ck[1]:02d}",
                "size": row.get(0, 0),
                "retention": [
                    {"offset": o, "count": row.get(o, 0),
                     "pct": round(row.get(o, 0) / size * 100, 1)}
                    for o in range(0, max_off + 1)
                ],
            })
        return {"cohorts": matrix, "max_offset": max_off}
