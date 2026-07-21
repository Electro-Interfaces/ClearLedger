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

from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import String, case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, Region, ServiceLocation
from app.services.analytics_cache import cached_report
from app.services.pii_account import account_hash, mask_phone
from app.services.session_scope import session_scope_conds
from app.services.tz_offsets import shifted_started_at

S = ChargeSession


def _retail_conds(company_id) -> list:
    """ФЛ = есть телефон-аккаунт и НЕ корпоратив (не сматчен на организацию)."""
    return [
        S.company_id == company_id,
        S.user_id.is_not(None),
        S.client_name.is_(None),
    ]


def _net(company_id, stations: list[str] | None, regions: list[str] | None) -> list:
    """Контурное сужение сети (станции/регионы) для ФЛ-запросов. Регион —
    нормализованно через справочник (см. session_scope). Пусто = весь контур."""
    return session_scope_conds(company_id, stations, regions)


def _period(df: date, dt: date) -> tuple[datetime, datetime]:
    return (datetime.combine(df, datetime.min.time()),
            datetime.combine(dt, datetime.max.time()))


class RetailService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── ядро: агрегат по аккаунтам за период ─────────────────────────────
    @cached_report("retail:_accounts", copy_rows=True)
    async def _accounts(self, company_id, df: date, dt: date, *,
                        region: str | None = None, station: str | None = None,
                        stations: list[str] | None = None,
                        regions: list[str] | None = None) -> list[dict[str, Any]]:
        """Одна строка на аккаунт ФЛ за период. Отсюда питаются RFM/экономика/гео/
        список аккаунтов/профиль. Опц. drill-down: region (канон S.region) / station
        (location_id объекта L2). Опц. контур: stations (коды) / regions (имена,
        нормализованно) — общий фильтр рабочей области."""
        lo, hi = _period(df, dt)
        conds = [*_retail_conds(company_id),
                 S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
                 *_net(company_id, stations, regions)]
        if region:
            conds.append(S.region == region)
        if station:
            conds.append(S.location_id == station)
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
        ).where(*conds).group_by(S.user_id)
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
    @cached_report("retail:overview")
    async def overview(self, company_id, df: date, dt: date,
                       stations: list[str] | None = None,
                       regions: list[str] | None = None) -> dict[str, Any]:
        accts = await self._accounts(company_id, df, dt, stations=stations, regions=regions)
        lo, hi = _period(df, dt)
        # «Новые» = аккаунты, чья ПЕРВАЯ В ИСТОРИИ сессия попала в период.
        new_stmt = select(func.count()).select_from(
            select(S.user_id, func.min(S.started_at).label("f"))
            .where(*_retail_conds(company_id), S.started_at.is_not(None),
                   *_net(company_id, stations, regions))
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

    SEG_ORDER = ["Чемпионы", "Лояльные", "Под риском", "Новички", "Случайные", "Разовые", "Уснувшие", "Отток"]

    @staticmethod
    def _rfm_thresholds(accts: list[dict[str, Any]]) -> tuple[tuple[float, float], tuple[float, float]]:
        """Пороги R (давность) и F (частота) по квантилям набора аккаунтов."""
        recencies = sorted(a["recency_days"] for a in accts if a["recency_days"] is not None)
        freqs = sorted(a["sessions"] for a in accts)

        def q(arr: list[float], p: float) -> float:
            if not arr:
                return 0.0
            return float(arr[min(len(arr) - 1, int(p * len(arr)))])

        return ((q(recencies, 0.33), q(recencies, 0.66)),   # свежие / уснувшие
                (q(freqs, 0.50), q(freqs, 0.80)))           # медиана / топ-20%

    def _tag_segments(self, accts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Проставить RFM-класс каждому аккаунту (по порогам всего набора)."""
        if not accts:
            return accts
        r_thr, f_thr = self._rfm_thresholds(accts)
        for a in accts:
            a["segment"] = self._rfm_segment(a["recency_days"], a["sessions"], a["revenue"], r_thr, f_thr)
        return accts

    @cached_report("retail:segments")
    async def segments(self, company_id, df: date, dt: date,
                       stations: list[str] | None = None,
                       regions: list[str] | None = None) -> dict[str, Any]:
        accts = await self._accounts(company_id, df, dt, stations=stations, regions=regions)
        if not accts:
            return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                    "segments": [], "totals": {"accounts": 0}}

        r_thr, f_thr = self._rfm_thresholds(accts)

        buckets: dict[str, dict[str, float]] = {}
        for a in accts:
            seg = self._rfm_segment(a["recency_days"], a["sessions"], a["revenue"], r_thr, f_thr)
            b = buckets.setdefault(seg, {"accounts": 0, "sessions": 0, "energy": 0.0, "revenue": 0.0})
            b["accounts"] += 1
            b["sessions"] += a["sessions"]
            b["energy"] += a["energy_kwh"]
            b["revenue"] += a["revenue"]

        total_rev = sum(b["revenue"] for b in buckets.values()) or 1.0
        order = self.SEG_ORDER
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
    @cached_report("retail:economics")
    async def economics(self, company_id, df: date, dt: date,
                        stations: list[str] | None = None,
                        regions: list[str] | None = None) -> dict[str, Any]:
        accts = await self._accounts(company_id, df, dt, stations=stations, regions=regions)
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
    @cached_report("retail:geo")
    async def geo(self, company_id, df: date, dt: date,
                  stations: list[str] | None = None,
                  regions: list[str] | None = None) -> dict[str, Any]:
        """Гео/мобильность на L2-слое: станции считаются по `location_id` (объект
        `service_locations`), регионы — канон `regions.name` (join по location_id).
        Сессии без привязки к объекту (location_id NULL — «сироты») показываются
        отдельной строкой, а не молча отбрасываются."""
        lo, hi = _period(df, dt)
        base = [*_retail_conds(company_id), S.started_at.is_not(None),
                S.started_at >= lo, S.started_at <= hi,
                *_net(company_id, stations, regions)]

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
    @cached_report("retail:cohorts")
    async def cohorts(self, company_id, months: int = 12,
                      stations: list[str] | None = None,
                      regions: list[str] | None = None) -> dict[str, Any]:
        """Retention-матрица: когорта = месяц первой сессии; ячейка = сколько
        аккаунтов когорты были активны через N месяцев. По всей истории."""
        net = _net(company_id, stations, regions)
        cohort_m = func.date_trunc("month", func.min(S.started_at))
        firsts = select(S.user_id.label("uid"), cohort_m.label("cohort")).where(
            *_retail_conds(company_id), S.started_at.is_not(None), *net).group_by(S.user_id).subquery()
        # Один объект `am` в SELECT и GROUP BY (иначе разные bind-параметры → GroupingError).
        am = func.date_trunc("month", S.started_at)
        acts = select(
            S.user_id.label("uid"), am.label("m"),
        ).where(*_retail_conds(company_id), S.started_at.is_not(None), *net).group_by(
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

    # ── accounts: список аккаунтов с фильтрами/отборами/сортировкой ───────
    _SORTABLE = {"revenue", "sessions", "energy_kwh", "avg_check", "avg_kwh",
                 "avg_tariff", "recency_days", "success_pct", "stations", "last_at"}

    @staticmethod
    def _pub(a: dict[str, Any]) -> dict[str, Any]:
        """Публичная строка аккаунта — БЕЗ сырого телефона (только хеш+маска)."""
        return {k: v for k, v in a.items() if k != "phone"}

    @cached_report("retail:accounts")
    async def accounts(self, company_id, df: date, dt: date, *, region: str | None = None,
                       station: str | None = None, segment: str | None = None,
                       min_sessions: int = 0, search: str | None = None,
                       sort: str = "revenue", order: str = "desc", limit: int = 200,
                       stations: list[str] | None = None,
                       regions: list[str] | None = None) -> dict[str, Any]:
        """Реестр аккаунтов ФЛ с фильтрами (сегмент/регион/станция/мин-сессий/поиск)
        и сортировкой. Регион/станция сужают агрегацию (только их сессии). Телефон
        не отдаётся — только хеш-ID + маска."""
        rows = self._tag_segments(await self._accounts(
            company_id, df, dt, region=region, station=station,
            stations=stations, regions=regions))
        if segment:
            rows = [a for a in rows if a.get("segment") == segment]
        if min_sessions and min_sessions > 1:
            rows = [a for a in rows if a["sessions"] >= min_sessions]
        if search and search.strip():
            s = search.strip()
            rows = [a for a in rows if s in (a["masked"] or "") or s in (a["account"] or "")]

        key = sort if sort in self._SORTABLE else "revenue"
        reverse = order != "asc"
        def _sk(a: dict[str, Any]):
            v = a.get(key)
            if key == "last_at":
                return a.get("last_at") or ""
            return v if v is not None else -1
        ordered = sorted(rows, key=_sk, reverse=reverse)

        n = len(rows)
        tot_sessions = sum(a["sessions"] for a in rows)
        tot_rev = sum(a["revenue"] for a in rows)
        tot_energy = sum(a["energy_kwh"] for a in rows)
        return {
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
            "accounts": [self._pub(a) for a in ordered[:limit]],
            "total": n, "returned": min(n, limit),
            "totals": {"accounts": n, "sessions": tot_sessions,
                       "revenue": round(tot_rev, 2), "energy_kwh": round(tot_energy, 1),
                       "avg_check": round(tot_rev / tot_sessions, 2) if tot_sessions else 0.0,
                       "arpa": round(tot_rev / n, 2) if n else 0.0},
        }

    # ── dimensions: справочники фильтров (регионы/станции) ────────────────
    @cached_report("retail:dimensions")
    async def dimensions(self, company_id, df: date, dt: date,
                         stations: list[str] | None = None,
                         regions: list[str] | None = None) -> dict[str, Any]:
        """Списки регионов и станций (с числом аккаунтов/сессий) для селектов фильтра."""
        lo, hi = _period(df, dt)
        base = [*_retail_conds(company_id), S.started_at.is_not(None),
                S.started_at >= lo, S.started_at <= hi,
                *_net(company_id, stations, regions)]
        reg = func.coalesce(S.region, "— (без региона)")
        reg_rows = (await self.db.execute(select(
            reg.label("region"), func.count(func.distinct(S.user_id)).label("accounts"),
            func.count().label("sessions"),
        ).where(*base).group_by(reg).order_by(func.count().desc()))).all()
        regions = [{"region": r.region, "accounts": int(r.accounts), "sessions": int(r.sessions)}
                   for r in reg_rows]

        st_rows = (await self.db.execute(select(
            S.location_id.label("loc"), func.count(func.distinct(S.user_id)).label("accounts"),
            func.count().label("sessions"),
        ).where(*base, S.location_id.is_not(None)).group_by(S.location_id)
         .order_by(func.count().desc()))).all()
        loc_ids = [r.loc for r in st_rows]
        meta: dict[str, tuple] = {}
        if loc_ids:
            join = ServiceLocation.__table__.outerjoin(
                Region.__table__, Region.id == ServiceLocation.region_id)
            for sl in (await self.db.execute(select(
                ServiceLocation.id, ServiceLocation.name, ServiceLocation.station_number,
                Region.name.label("region"),
            ).select_from(join).where(ServiceLocation.id.in_(loc_ids)))).all():
                meta[str(sl.id)] = (sl.name, sl.station_number, sl.region)
        stations = [{"location_id": r.loc,
                     "name": (meta.get(str(r.loc)) or (None, None, None))[0] or r.loc,
                     "number": (meta.get(str(r.loc)) or (None, None, None))[1],
                     "region": (meta.get(str(r.loc)) or (None, None, None))[2],
                     "accounts": int(r.accounts), "sessions": int(r.sessions)}
                    for r in st_rows]
        return {"regions": regions, "stations": stations}

    # ── profile: клиенты по станции/региону + профиль времени ────────────
    _WD = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

    @cached_report("retail:profile")
    async def profile(self, company_id, df: date, dt: date, *,
                      station: str | None = None, region: str | None = None,
                      stations: list[str] | None = None,
                      regions: list[str] | None = None,
                      tz: str = "msk") -> dict[str, Any]:
        """Разрез по конкретной станции ИЛИ региону: KPI + профиль по часам суток и
        дням недели + топ аккаунтов этого разреза. tz='local' — профиль по местному
        времени станции (сдвиг started_at на часовой пояс региона)."""
        lo, hi = _period(df, dt)
        conds = [*_retail_conds(company_id), S.started_at.is_not(None),
                 S.started_at >= lo, S.started_at <= hi,
                 *_net(company_id, stations, regions)]
        scope: dict[str, Any] = {"kind": None, "label": "Вся розница ФЛ"}
        if station:
            conds.append(S.location_id == station)
            # company_id обязателен: station приходит из query — без него утекало
            # имя/номер чужого объекта.
            sl = (await self.db.execute(select(
                ServiceLocation.name, ServiceLocation.station_number).where(
                ServiceLocation.id == station,
                ServiceLocation.company_id == company_id))).first()
            scope = {"kind": "station", "value": station,
                     "label": (sl.name if sl else None) or station,
                     "number": (sl.station_number if sl else None)}
        elif region:
            conds.append(S.region == region)
            scope = {"kind": "region", "value": region, "label": region}

        tot = (await self.db.execute(select(
            func.count(func.distinct(S.user_id)).label("accounts"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
        ).where(*conds))).one()
        sessions, revenue, energy = int(tot.sessions), float(tot.revenue), float(tot.energy)
        totals = {"accounts": int(tot.accounts), "sessions": sessions,
                  "revenue": round(revenue, 2), "energy_kwh": round(energy, 1),
                  "avg_check": round(revenue / sessions, 2) if sessions else 0.0,
                  "avg_kwh": round(energy / sessions, 2) if sessions else 0.0}

        # tz='local' → час/день недели по местному времени станции. Нужен сдвиг
        # started_at на regions.msk_offset → join сессия→объект→регион.
        ts = shifted_started_at(S.started_at, Region.msk_offset, tz)
        tz_join = (S.__table__
                   .outerjoin(ServiceLocation.__table__, ServiceLocation.id == S.location_id)
                   .outerjoin(Region.__table__, Region.id == ServiceLocation.region_id))

        he = func.extract("hour", ts)
        h_stmt = select(
            he.label("h"), func.count().label("sessions"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
        ).where(*conds).group_by(he)
        if tz == "local":
            h_stmt = h_stmt.select_from(tz_join)
        hrows = (await self.db.execute(h_stmt)).all()
        hmap = {int(r.h): (int(r.sessions), float(r.revenue)) for r in hrows if r.h is not None}
        hourly = [{"hour": hh, "sessions": hmap.get(hh, (0, 0.0))[0],
                   "revenue": round(hmap.get(hh, (0, 0.0))[1], 2)} for hh in range(24)]

        we = func.extract("isodow", ts)   # 1=Пн … 7=Вс
        w_stmt = select(
            we.label("d"), func.count().label("sessions"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
        ).where(*conds).group_by(we)
        if tz == "local":
            w_stmt = w_stmt.select_from(tz_join)
        wrows = (await self.db.execute(w_stmt)).all()
        wmap = {int(r.d): (int(r.sessions), float(r.revenue)) for r in wrows if r.d is not None}
        weekday = [{"dow": i + 1, "label": self._WD[i],
                    "sessions": wmap.get(i + 1, (0, 0.0))[0],
                    "revenue": round(wmap.get(i + 1, (0, 0.0))[1], 2)} for i in range(7)]

        accts = self._tag_segments(await self._accounts(
            company_id, df, dt, region=region, station=station,
            stations=stations, regions=regions))
        accts.sort(key=lambda a: -a["revenue"])
        top = [self._pub(a) for a in accts[:25]]

        return {"period": {"from": df.isoformat(), "to": dt.isoformat()},
                "scope": scope, "totals": totals, "hourly": hourly,
                "weekday": weekday, "top_accounts": top}

    # ── account: подробная карточка одного аккаунта ──────────────────────
    @cached_report("retail:account")
    async def account(self, company_id, df: date, dt: date, account_hash: str,
                      stations: list[str] | None = None,
                      regions: list[str] | None = None) -> dict[str, Any]:
        """Детализация одного аккаунта ФЛ (по хеш-ID): сводка + разбивки по станциям/
        месяцам/часам/коннекторам + последние сессии. Хеш резолвится в телефон
        сканом distinct user_id (телефон в ответ НЕ уходит)."""
        accts = self._tag_segments(await self._accounts(company_id, df, dt,
                                                        stations=stations, regions=regions))
        me = next((a for a in accts if a["account"] == account_hash), None)
        if not me:
            return {"found": False}
        phone = me["phone"]
        lo, hi = _period(df, dt)
        base = [S.company_id == company_id, S.user_id == phone,
                S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
                *_net(company_id, stations, regions)]

        # По станциям (объект L2 + имя)
        loc_rows = (await self.db.execute(select(
            S.location_id.label("loc"), func.count().label("sessions"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
        ).where(*base).group_by(S.location_id).order_by(func.count().desc()))).all()
        loc_ids = [r.loc for r in loc_rows if r.loc]
        names: dict[str, tuple] = {}
        if loc_ids:
            for sl in (await self.db.execute(select(
                ServiceLocation.id, ServiceLocation.name, ServiceLocation.station_number,
            ).where(ServiceLocation.id.in_(loc_ids)))).all():
                names[str(sl.id)] = (sl.name, sl.station_number)
        by_station = [{"name": (names.get(str(r.loc), (None, None))[0] if r.loc else None) or "— без объекта",
                       "number": names.get(str(r.loc), (None, None))[1] if r.loc else None,
                       "sessions": int(r.sessions), "revenue": round(float(r.revenue), 2),
                       "energy_kwh": round(float(r.energy), 1)} for r in loc_rows]

        # По месяцам
        mm = func.date_trunc("month", S.started_at)
        mrows = (await self.db.execute(select(
            mm.label("m"), func.count().label("sessions"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
        ).where(*base).group_by(mm).order_by(mm))).all()
        by_month = [{"month": r.m.strftime("%Y-%m"), "sessions": int(r.sessions),
                     "revenue": round(float(r.revenue), 2)} for r in mrows]

        # По часам суток
        he = func.extract("hour", S.started_at)
        hrows = (await self.db.execute(select(
            he.label("h"), func.count().label("sessions"),
        ).where(*base).group_by(he))).all()
        hmap = {int(r.h): int(r.sessions) for r in hrows if r.h is not None}
        hourly = [{"hour": hh, "sessions": hmap.get(hh, 0)} for hh in range(24)]

        # По коннекторам
        cc = func.coalesce(S.connector_type, "—")
        crows = (await self.db.execute(select(
            cc.label("c"), func.count().label("sessions"),
        ).where(*base).group_by(cc).order_by(func.count().desc()))).all()
        connectors = [{"type": r.c, "sessions": int(r.sessions)} for r in crows]

        # Последние сессии
        recent_rows = (await self.db.execute(select(S).where(*base)
            .order_by(S.started_at.desc()).limit(15))).scalars().all()
        recent = [{"started_at": s.started_at.isoformat() if s.started_at else None,
                   "station": s.station_name or s.station_code,
                   "connector": s.connector_type, "energy_kwh": round(float(s.energy_kwh or 0), 1),
                   "amount": round(float(s.amount or 0), 2), "result": s.result} for s in recent_rows]

        return {"found": True, "period": {"from": df.isoformat(), "to": dt.isoformat()},
                "account": self._pub(me), "by_station": by_station, "by_month": by_month,
                "hourly": hourly, "connectors": connectors, "recent": recent}

    # ── marketing: B2C-KPI розничной базы + автоматические выводы ─────────
    @cached_report("retail:marketing")
    async def marketing(self, company_id, df: date, dt: date,
                        stations: list[str] | None = None,
                        regions: list[str] | None = None) -> dict[str, Any]:
        """Маркетинговая витрина частных клиентов (B2C): повторные/разовые, ядро
        лояльности, зона оттока, концентрация выручки, retention когорт, AOV/частота
        + авто-выводы (принятые в потребительском маркетинге разрезы)."""
        net = _net(company_id, stations, regions)
        accts = self._tag_segments(await self._accounts(company_id, df, dt,
                                                        stations=stations, regions=regions))
        n = len(accts)
        if not n:
            return {"period": {"from": df.isoformat(), "to": dt.isoformat()}, "kpis": {}, "insights": []}
        total_rev = sum(a["revenue"] for a in accts) or 1.0
        total_sessions = sum(a["sessions"] for a in accts)

        lo, hi = _period(df, dt)
        new_accounts = int((await self.db.execute(select(func.count()).select_from(
            select(S.user_id, func.min(S.started_at).label("f"))
            .where(*_retail_conds(company_id), S.started_at.is_not(None), *net)
            .group_by(S.user_id).having(func.min(S.started_at) >= lo)
            .having(func.min(S.started_at) <= hi).subquery()))).scalar() or 0)
        returning = max(0, n - new_accounts)

        repeat = sum(1 for a in accts if a["sessions"] > 1)
        one_time = sum(1 for a in accts if a["sessions"] == 1)
        one_time_rev = sum(a["revenue"] for a in accts if a["sessions"] == 1)

        core = [a for a in accts if a["segment"] in ("Чемпионы", "Лояльные")]
        risk = [a for a in accts if a["segment"] in ("Под риском", "Уснувшие", "Отток")]
        core_rev = sum(a["revenue"] for a in core)
        risk_rev = sum(a["revenue"] for a in risk)

        by_rev = sorted((a["revenue"] for a in accts), reverse=True)
        def top_share(pct: float) -> float:
            k = max(1, round(n * pct / 100))
            return round(sum(by_rev[:k]) / total_rev * 100, 1)
        top10, top20 = top_share(10), top_share(20)

        coh = (await self.cohorts(company_id, months=12,
                                  stations=stations, regions=regions))["cohorts"]
        def avg_ret(offset: int) -> float | None:
            elig = coh[:len(coh) - offset] if len(coh) > offset else []   # исключаем молодые когорты
            num = sum(next((x["count"] for x in c["retention"] if x["offset"] == offset), 0) for c in elig)
            den = sum(c["size"] for c in elig)
            return round(num / den * 100, 1) if den else None
        r1, r3 = avg_ret(1), avg_ret(3)

        def pf(x: float) -> float:
            return round(x / n * 100, 1)
        def rf(x: float) -> float:
            return round(x / total_rev * 100, 1)
        kpis = {
            "accounts": n, "new_accounts": new_accounts, "returning_accounts": returning,
            "new_share": pf(new_accounts),
            "repeat_rate": pf(repeat), "one_time_share": pf(one_time), "one_time_revenue_share": rf(one_time_rev),
            "aov": round(total_rev / total_sessions, 2) if total_sessions else 0.0,
            "frequency": round(total_sessions / n, 1), "arpa": round(total_rev / n, 2),
            "core_accounts_share": pf(len(core)), "core_revenue_share": rf(core_rev),
            "risk_accounts_share": pf(len(risk)), "risk_revenue": round(risk_rev, 2), "risk_revenue_share": rf(risk_rev),
            "top10_revenue_share": top10, "top20_revenue_share": top20,
            "retention_m1": r1, "retention_m3": r3,
        }

        # Автоматические выводы (потребительский маркетинг).
        ins: list[dict[str, str]] = []
        def add(level: str, text: str) -> None:
            ins.append({"level": level, "text": text})
        f1 = lambda v: f"{v:.1f}".replace(".", ",")
        mm = lambda v: f"{round(v):,}".replace(",", " ")
        add("warn" if top20 >= 75 else "info",
            f"Концентрация: топ-20% клиентов дают {f1(top20)}% выручки (топ-10% — {f1(top10)}%). "
            + ("База сильно зависит от ядра — приоритет удержания Чемпионов/Лояльных."
               if top20 >= 75 else "Выручка распределена относительно равномерно."))
        add("good" if kpis["repeat_rate"] >= 60 else "warn",
            f"Повторно заряжаются {f1(kpis['repeat_rate'])}% клиентов; разовых — {f1(kpis['one_time_share'])}% "
            f"({f1(kpis['one_time_revenue_share'])}% выручки). "
            + ("Здоровая возвращаемость." if kpis["repeat_rate"] >= 60 else "Резерв — перевод разовых в повторные (welcome-механики)."))
        add("good",
            f"Ядро лояльности (Чемпионы+Лояльные) — {f1(kpis['core_accounts_share'])}% базы формирует "
            f"{f1(kpis['core_revenue_share'])}% выручки. Удержание ядра — приоритет №1.")
        add("warn" if kpis["risk_revenue_share"] >= 15 else "info",
            f"В зоне риска (Под риском/Уснувшие/Отток) — {f1(kpis['risk_accounts_share'])}% клиентов и "
            f"{mm(risk_rev)} ₽ ({f1(kpis['risk_revenue_share'])}% выручки). Цель — ре-активация (push/скидка).")
        if r1 is not None:
            add("good" if (r1 or 0) >= 40 else "warn",
                f"Удержание когорт: M1 {f1(r1)}%" + (f", M3 {f1(r3)}%" if r3 is not None else "")
                + (" — здоровый уровень для сети ЭЗС." if (r1 or 0) >= 40 else " — низкое: усилить онбординг и удержание в 1-й месяц."))
        add("info",
            f"Средняя частота {f1(kpis['frequency'])} зарядок/клиент · средний чек {mm(kpis['aov'])} ₽ · ARPA {mm(kpis['arpa'])} ₽.")
        add("info",
            f"Новых за период {mm(new_accounts)} ({f1(kpis['new_share'])}%), возвращающихся {mm(returning)}.")

        return {"period": {"from": df.isoformat(), "to": dt.isoformat()}, "kpis": kpis, "insights": ins}

    # ── dashboard: собранная BI-витрина «Обзора ФЛ» ──────────────────────
    @cached_report("retail:dashboard")
    async def dashboard(self, company_id, df: date, dt: date,
                        stations: list[str] | None = None,
                        regions: list[str] | None = None) -> dict[str, Any]:
        """Расширенная витрина: динамика базы+выручки и Δ к прошлому периоду,
        retention-кривая, CLV/LTV, тепловая карта 7×24, поведение (коннекторы/
        оплата/качество), концентрация (Лоренц/Джини) + распределения."""
        net = _net(company_id, stations, regions)
        accts = self._tag_segments(await self._accounts(company_id, df, dt,
                                                        stations=stations, regions=regions))
        n = len(accts)
        empty = {"period": {"from": df.isoformat(), "to": dt.isoformat()}}
        if not n:
            return {**empty, "dynamics": [], "deltas": {}, "retention_curve": [], "clv": {},
                    "heatmap": [], "connectors": [], "payment": {}, "success": {}, "concentration": {}}
        lo, hi = _period(df, dt)
        total_rev = sum(a["revenue"] for a in accts) or 1.0
        total_sessions = sum(a["sessions"] for a in accts)
        months_span = (dt.year - df.year) * 12 + (dt.month - df.month) + 1

        # ── Динамика: активность (аккаунт, месяц) за всю историю ──
        amh = func.date_trunc("month", S.started_at)
        act_rows = (await self.db.execute(select(S.user_id.label("u"), amh.label("m"))
            .where(*_retail_conds(company_id), S.started_at.is_not(None), *net).group_by(S.user_id, amh))).all()
        active_by_user: dict[str, set] = defaultdict(set)
        for r in act_rows:
            active_by_user[r.u].add((r.m.year, r.m.month))
        first_month = {u: min(ms) for u, ms in active_by_user.items()}
        rev_rows = (await self.db.execute(select(amh.label("m"),
            func.coalesce(func.sum(S.amount), 0).label("rev"), func.count().label("sess"))
            .where(*_retail_conds(company_id), S.started_at.is_not(None),
                   S.started_at >= lo, S.started_at <= hi, *net).group_by(amh))).all()
        rev_by_m = {(r.m.year, r.m.month): (float(r.rev), int(r.sess)) for r in rev_rows}
        period_months: list[tuple] = []
        y, mo = df.year, df.month
        while (y, mo) <= (dt.year, dt.month):
            period_months.append((y, mo))
            mo, y = (1, y + 1) if mo == 12 else (mo + 1, y)
        dynamics = []
        for ym in period_months:
            new = ret = react = 0
            for u, ms in active_by_user.items():
                if ym not in ms:
                    continue
                if first_month[u] == ym:
                    new += 1
                else:
                    prev = (ym[0], ym[1] - 1) if ym[1] > 1 else (ym[0] - 1, 12)
                    ret, react = (ret + 1, react) if prev in ms else (ret, react + 1)
            rev, _sess = rev_by_m.get(ym, (0.0, 0))
            dynamics.append({"month": f"{ym[0]:04d}-{ym[1]:02d}", "new": new, "returning": ret,
                             "reactivated": react, "active": new + ret + react, "revenue": round(rev, 2)})

        # ── Δ к прошлому периоду равной длины ──
        span_days = (dt - df).days + 1
        prev = await self.overview(company_id, df - timedelta(days=span_days), df - timedelta(days=1),
                                   stations=stations, regions=regions)
        pt = prev["totals"]
        cur = {"accounts": n, "revenue": round(total_rev, 2), "arpa": round(total_rev / n, 2),
               "avg_check": round(total_rev / total_sessions, 2) if total_sessions else 0.0,
               "sessions": total_sessions}
        def dlt(key):
            c, pv = cur[key], (pt.get(key, 0) or 0)
            return {"cur": c, "prev": pv, "delta_pct": round((c - pv) / pv * 100, 1) if pv else None}
        deltas = {k: dlt(k) for k in ("accounts", "revenue", "arpa", "avg_check", "sessions")}

        # ── Retention-кривая ──
        coh = (await self.cohorts(company_id, months=12,
                                  stations=stations, regions=regions))["cohorts"]
        def avg_ret(offset):
            elig = coh[:len(coh) - offset] if len(coh) > offset else []
            num = sum(next((x["count"] for x in c["retention"] if x["offset"] == offset), 0) for c in elig)
            den = sum(c["size"] for c in elig)
            return round(num / den * 100, 1) if den else None
        max_off = max((c["retention"][-1]["offset"] for c in coh), default=0) if coh else 0
        retention_curve = [{"offset": o, "pct": avg_ret(o)} for o in range(0, max_off + 1)]

        # ── CLV / LTV = месячный ARPU × площадь под retention-кривой ──
        expected_months = sum((p["pct"] or 0) / 100 for p in retention_curve) or 1.0
        monthly_arpu = total_rev / n / max(1, months_span)
        seg_agg: dict[str, list] = defaultdict(lambda: [0, 0.0])
        for a in accts:
            g = seg_agg[a["segment"]]; g[0] += 1; g[1] += a["revenue"]
        by_seg = []
        for name in self.SEG_ORDER:
            if name in seg_agg:
                cnt, rev = seg_agg[name]
                m_arpu = rev / cnt / max(1, months_span)
                by_seg.append({"segment": name, "accounts": int(cnt),
                               "monthly_arpu": round(m_arpu, 2), "ltv": round(m_arpu * expected_months, 2)})
        lifespans = [((datetime.fromisoformat(a["last_at"]) - datetime.fromisoformat(a["first_at"])).days / 30.44 + 1)
                     for a in accts if a["first_at"] and a["last_at"]]
        clv = {"monthly_arpu": round(monthly_arpu, 2), "expected_months": round(expected_months, 1),
               "ltv": round(monthly_arpu * expected_months, 2),
               "avg_lifetime_months": round(sum(lifespans) / len(lifespans), 1) if lifespans else 0.0,
               "by_segment": by_seg}

        # ── Тепловая карта 7×24 ──
        hd, hh = func.extract("isodow", S.started_at), func.extract("hour", S.started_at)
        hm_rows = (await self.db.execute(select(hd.label("d"), hh.label("h"), func.count().label("s"))
            .where(*_retail_conds(company_id), S.started_at.is_not(None),
                   S.started_at >= lo, S.started_at <= hi, *net).group_by(hd, hh))).all()
        heatmap = [{"dow": int(r.d), "hour": int(r.h), "sessions": int(r.s)}
                   for r in hm_rows if r.d is not None and r.h is not None]

        # ── Поведение: коннекторы / оплата / качество ──
        base = [*_retail_conds(company_id), S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi, *net]
        cc = func.coalesce(S.connector_type, "—")
        conn_rows = (await self.db.execute(select(cc.label("c"), func.count().label("s"),
            func.coalesce(func.sum(S.amount), 0).label("rev")).where(*base).group_by(cc)
            .order_by(func.count().desc()))).all()
        connectors = [{"type": r.c, "sessions": int(r.s), "revenue": round(float(r.rev), 2)} for r in conn_rows]
        pay = (await self.db.execute(select(
            func.count().label("total"),
            func.coalesce(func.sum(case((S.rfid.is_not(None), 1), else_=0)), 0).label("rfid"),
            func.coalesce(func.sum(case((S.amount <= 0, 1), else_=0)), 0).label("unpaid"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("success"),
        ).where(*base))).one()
        ptot = int(pay.total) or 1
        payment = {"rfid_pct": round(int(pay.rfid) / ptot * 100, 1),
                   "app_pct": round((ptot - int(pay.rfid)) / ptot * 100, 1),
                   "unpaid_pct": round(int(pay.unpaid) / ptot * 100, 1)}
        sm_rows = (await self.db.execute(select(amh.label("mon"), func.count().label("tot"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("ok"))
            .where(*base).group_by(amh).order_by(amh))).all()
        success = {"pct": round(int(pay.success) / ptot * 100, 1),
                   "by_month": [{"month": f"{r.mon.year:04d}-{r.mon.month:02d}",
                                 "pct": round(int(r.ok) / int(r.tot) * 100, 1) if r.tot else 0.0} for r in sm_rows]}

        # ── Концентрация: Лоренц + Джини + распределения ──
        rev_sorted = sorted(a["revenue"] for a in accts)
        tot = sum(rev_sorted) or 1.0
        lorenz = [{"pop": 0.0, "rev": 0.0}]
        step = max(1, n // 20)
        running = 0.0
        for i, v in enumerate(rev_sorted, 1):
            running += v
            if i % step == 0 or i == n:
                lorenz.append({"pop": round(i / n * 100, 1), "rev": round(running / tot * 100, 1)})
        gini = round(sum((2 * i - n - 1) * v for i, v in enumerate(rev_sorted, 1)) / (n * tot), 3)

        def buckets(edges, valuef):
            return [{"bucket": lab, "accounts": sum(1 for a in accts if loe <= valuef(a) <= hie),
                     "accounts_pct": round(sum(1 for a in accts if loe <= valuef(a) <= hie) / n * 100, 1)}
                    for loe, hie, lab in edges]
        concentration = {
            "gini": gini, "lorenz": lorenz,
            "session_buckets": buckets([(1, 1, "1"), (2, 3, "2–3"), (4, 10, "4–10"),
                                        (11, 50, "11–50"), (51, 10**9, "50+")], lambda a: a["sessions"]),
            "spend_buckets": buckets([(0, 500, "<500 ₽"), (500, 2000, "0.5–2 тыс"), (2000, 5000, "2–5 тыс"),
                                      (5000, 20000, "5–20 тыс"), (20000, 10**12, "20 тыс+")], lambda a: a["revenue"]),
        }

        return {**empty, "dynamics": dynamics, "deltas": deltas, "retention_curve": retention_curve,
                "clv": clv, "heatmap": heatmap, "connectors": connectors, "payment": payment,
                "success": success, "concentration": concentration}
