"""
Управленческий кокпит ЭЗС (раздел «Управленческий», energy/РусГидро) —
обзор ситуации + конкретные расхождения + рабочие списки для решений.

Сводит ОБЕ стороны энергобаланса на конформной размерности «объект»:
  вход  — входящая э/э по счетам контрагентов (station_energy_periods, реестры);
  отпуск — энергия зарядных сессий (charge_sessions.energy_kwh);
  деньги — стоимость входа (объём × входящий тариф), выручка сессий,
           аренда (постоянная часть) и платёжная дисциплина (settlements).

⚠ Потребление станции ≠ отпуск по сессиям: есть СОБСТВЕННЫЕ НУЖДЫ (СН —
электроника/охлаждение/ожидание) и потери преобразования. Небаланс
(вход − отпуск) декомпозируется:
  СН (оценка)   — эмпирически: медиана входа станции в месяцы БЕЗ сессий
                  (чистые СН); нет своей истории → медиана парка;
  сверхнорматив — небаланс − СН(оценка): вот ЭТО сигнал (проверить счета/учёт).

Выход — «светофор» проблем, каждая проблема = счётчик + рабочий список строк
(объект, показатель, что делать): не заплатили / нет данных / договор истёк /
нет тарифа / простой / сверхнормативный небаланс / сироты реестра.
"""
from __future__ import annotations

from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    ChargeSession,
    Counterparty,
    DataEntry,
    ServiceLocation,
    StationContractSettlement,
    StationEnergyPeriod,
)

# Пороги сигналов (управленческие, не претендуют на точность учёта)
OVER_IMBALANCE_PCT = 0.20      # сверхнорматив > 20% входа → сигнал
OVER_IMBALANCE_MIN_KWH = 100.0 # ... и не меньше 100 кВт·ч (отсечь шум)
TARIFF_ANOMALY_X = 1.5         # тариф выше медианы сети в 1.5 раза
IDLE_MIN_KWH = 30.0            # «станция стоит, но потребляет» — от 30 кВт·ч/мес


def _month(dt) -> str | None:
    if dt is None:
        return None
    return f"{dt.year:04d}-{dt.month:02d}-01"


async def _load(db: AsyncSession, company_id):
    """Общий сбор: объекты, периоды входа, отпуск по месяцам, дисциплина."""
    locs = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.type == "ev_charging"))).scalars().all()
    loc_by_id = {l.id: l for l in locs}

    periods = (await db.execute(select(StationEnergyPeriod).where(
        StationEnergyPeriod.company_id == company_id))).scalars().all()

    # отпуск и выручка сессий по (location, month) — одним агрегатным запросом
    sess_rows = (await db.execute(
        select(
            ChargeSession.location_id,
            func.date_trunc("month", ChargeSession.started_at).label("m"),
            func.sum(ChargeSession.energy_kwh).label("kwh"),
            func.sum(func.coalesce(ChargeSession.client_amount, ChargeSession.amount)).label("rub"),
            func.count().label("n"),
        )
        .where(ChargeSession.company_id == company_id,
               ChargeSession.location_id.is_not(None),
               ChargeSession.started_at.is_not(None))
        .group_by(ChargeSession.location_id, "m")
    )).all()

    settl = (await db.execute(select(StationContractSettlement).where(
        StationContractSettlement.company_id == company_id))).scalars().all()
    return loc_by_id, periods, sess_rows, settl


def _loc_label(loc: ServiceLocation | None) -> dict[str, Any]:
    if loc is None:
        return {"bu": None, "name": "—", "region": None}
    md = loc.extra_metadata or {}
    return {
        "bu": md.get("buNumber") or md.get("number") or loc.station_number,
        "name": loc.name,
        "region": (md.get("federalSubject") or loc.city or "").strip() or None,
    }


def _own_use_estimates(intake: dict[tuple[str, str], float],
                       dispensed: dict[tuple[str, str], float]) -> tuple[dict[str, float], float]:
    """СН по станции: медиана входа в её месяцы без сессий; парковая медиана — фолбэк."""
    idle_by_loc: dict[str, list[float]] = {}
    for (lid, m), kwh in intake.items():
        if kwh and kwh > 0 and dispensed.get((lid, m), 0.0) <= 0.0:
            idle_by_loc.setdefault(lid, []).append(kwh)
    per_loc = {lid: median(v) for lid, v in idle_by_loc.items() if v}
    fleet = median(list(per_loc.values())) if per_loc else 0.0
    return per_loc, fleet


def _apply_region(loc_by_id, periods, sess_rows, settl, region: str | None):
    """Список регионов + фильтрация всех наборов по выбранному региону."""
    regions = sorted({r for l in loc_by_id.values() if (r := _loc_label(l)["region"])})
    if region:
        keep = {lid for lid, l in loc_by_id.items() if _loc_label(l)["region"] == region}
        loc_by_id = {lid: l for lid, l in loc_by_id.items() if lid in keep}
        periods = [p for p in periods if p.location_id in keep]
        sess_rows = [r for r in sess_rows if r.location_id in keep]
        settl = [s for s in settl if s.location_id in keep]
    return regions, loc_by_id, periods, sess_rows, settl


async def ops_overview(db: AsyncSession, company_id, region: str | None = None) -> dict[str, Any]:
    loc_by_id, periods, sess_rows, settl = await _load(db, company_id)
    regions, loc_by_id, periods, sess_rows, settl = _apply_region(
        loc_by_id, periods, sess_rows, settl, region)

    intake: dict[tuple[str, str], float] = {}
    tariff: dict[tuple[str, str], float] = {}
    for p in periods:
        if p.intake_kwh is not None:
            intake[(p.location_id, p.period)] = float(p.intake_kwh)
        if p.tariff_rub_kwh is not None:
            tariff[(p.location_id, p.period)] = float(p.tariff_rub_kwh)
    # актуальный/средний тариф станции (для оценки стоимости в месяцы без сетки)
    last_tariff: dict[str, float] = {}
    for (lid, m), t in sorted(tariff.items(), key=lambda kv: kv[0][1]):
        last_tariff[lid] = t
    settl_by_role: dict[str, dict[str, StationContractSettlement]] = {"energy": {}, "rent": {}, "service": {}}
    for s in settl:
        settl_by_role.setdefault(s.role, {})[s.location_id] = s
    avg_tariff_reestr: dict[str, float] = {}
    for lid, s in settl_by_role.get("energy", {}).items():
        t = (s.extra or {}).get("avgTariff")
        if isinstance(t, (int, float)) and t > 0:
            avg_tariff_reestr[lid] = float(t)

    dispensed: dict[tuple[str, str], float] = {}
    revenue: dict[tuple[str, str], float] = {}
    for r in sess_rows:
        m = _month(r.m)
        if m is None:
            continue
        dispensed[(r.location_id, m)] = float(r.kwh or 0)
        revenue[(r.location_id, m)] = float(r.rub or 0)

    own_per_loc, own_fleet = _own_use_estimates(intake, dispensed)

    def own_use(lid: str) -> float:
        return own_per_loc.get(lid, own_fleet)

    def t_of(lid: str, m: str) -> float | None:
        return tariff.get((lid, m)) or avg_tariff_reestr.get(lid) or last_tariff.get(lid)

    # ── помесячная серия сети (вход/отпуск/СН/сверхнорматив/деньги) ──
    months_all = sorted({m for (_, m) in intake} | {m for (_, m) in dispensed})
    series = []
    for m in months_all:
        lids = {lid for (lid, mm) in intake if mm == m}
        in_kwh = sum(intake[(lid, m)] for lid in lids)
        disp_at_in = sum(dispensed.get((lid, m), 0.0) for lid in lids)   # отпуск ТОЛЬКО по станциям с входом
        disp_kwh = sum(v for (lid, mm), v in dispensed.items() if mm == m)
        own = sum(min(own_use(lid), intake[(lid, m)]) for lid in lids)
        imbalance = in_kwh - disp_at_in
        # сверхнорматив сети = Σ ПООБЪЕКТНЫХ превышений (сальдо сети схлопывало бы
        # небаланс одной станции профицитом другой)
        over = sum(
            max(0.0, intake[(lid, m)] - dispensed.get((lid, m), 0.0)
                - min(own_use(lid), intake[(lid, m)]))
            for lid in lids
        )
        cost = sum(intake[(lid, m)] * t for lid in lids if (t := t_of(lid, m)))
        rev = sum(v for (lid, mm), v in revenue.items() if mm == m)
        series.append({
            "period": m,
            "intakeKwh": round(in_kwh, 1), "intakeStations": len(lids),
            "dispensedKwh": round(disp_kwh, 1),
            "dispensedAtIntakeKwh": round(disp_at_in, 1),
            "ownUseEstKwh": round(own, 1),
            "imbalanceKwh": round(imbalance, 1),
            "overImbalanceKwh": round(over, 1),
            "overImbalancePct": round(over / in_kwh * 100, 1) if in_kwh else 0.0,
            "costEst": round(cost) if cost else None,
            "revenue": round(rev) if rev else None,
        })

    # опорный месяц анализа: последний, где вход покрывает ≥50% станций от максимума
    ref = None
    if series:
        max_st = max(s["intakeStations"] for s in series)
        good = [s for s in series if s["intakeStations"] >= max(3, max_st * 0.5)]
        ref = good[-1]["period"] if good else series[-1]["period"]

    # ── проблемы (светофор + рабочие списки) ──
    issues: list[dict[str, Any]] = []

    def add_issue(key, label, severity, hint, rows, unit=""):
        # полный рабочий список (cap 300) — фронт показывает top и модалку «все»
        issues.append({
            "key": key, "label": label, "severity": severity, "hint": hint,
            "count": len(rows), "unit": unit,
            "rows": sorted(rows, key=lambda r: -(r.get("value") or 0))[:300],
        })

    net_ids = {l.id for l in loc_by_id.values()
               if not l.is_test and (l.operational_status or "") != "decommissioned"}

    if ref:
        # 1) продажи есть — счетов на вход НЕТ (нет данных от контрагента)
        rows = []
        for lid in net_ids:
            d = dispensed.get((lid, ref), 0.0)
            if d > 0 and (lid, ref) not in intake:
                rows.append({"locationId": lid, **_loc_label(loc_by_id.get(lid)),
                             "value": round(d, 1),
                             "note": "отпуск за месяц есть, входа по счетам нет"})
        add_issue("no_intake", f"Нет данных по входу э/э ({ref[:7]})", "red",
                  "Запросить счета/показания у поставщика — без входа не считаются стоимость и небаланс.",
                  rows, "кВт·ч отпуска")

        # 2) сверхнормативный небаланс (вход − отпуск − СН)
        rows = []
        for lid in net_ids:
            i = intake.get((lid, ref))
            if not i:
                continue
            d = dispensed.get((lid, ref), 0.0)
            over = i - d - min(own_use(lid), i)
            if d > 0 and over > max(OVER_IMBALANCE_MIN_KWH, i * OVER_IMBALANCE_PCT):
                rows.append({"locationId": lid, **_loc_label(loc_by_id.get(lid)),
                             "value": round(over, 1),
                             "note": f"вход {round(i)} − отпуск {round(d)} − СН≈{round(min(own_use(lid), i))}"})
        add_issue("over_imbalance", f"Сверхнормативный небаланс ({ref[:7]})", "red",
                  "Проверить счета поставщика и учёт станции: небаланс сверх собственных нужд.",
                  rows, "кВт·ч")

        # 3) отпуск больше входа (аномалия данных/недовыставленные счета)
        rows = []
        for lid in net_ids:
            i = intake.get((lid, ref))
            d = dispensed.get((lid, ref), 0.0)
            if i and d > i * 1.1 and d - i > 50:
                rows.append({"locationId": lid, **_loc_label(loc_by_id.get(lid)),
                             "value": round(d - i, 1),
                             "note": f"отпуск {round(d)} > вход {round(i)}"})
        add_issue("negative_imbalance", f"Отпуск больше входа ({ref[:7]})", "amber",
                  "Счета выставлены не полностью либо ошибка учёта — сверить с поставщиком.",
                  rows, "кВт·ч")

        # 4) станция потребляет, но не продаёт (простой)
        rows = []
        for lid in net_ids:
            i = intake.get((lid, ref), 0.0)
            d = dispensed.get((lid, ref), 0.0)
            if i >= IDLE_MIN_KWH and d <= 0:
                cost = i * (t_of(lid, ref) or 0)
                rows.append({"locationId": lid, **_loc_label(loc_by_id.get(lid)),
                             "value": round(i, 1),
                             "note": f"расход без сессий{f' ≈{round(cost)} ₽' if cost else ''}"})
        add_issue("idle_consuming", f"Простой: потребляет без продаж ({ref[:7]})", "amber",
                  "Станция стоит, но жжёт э/э и аренду: ремонт/перенос/отключение.",
                  rows, "кВт·ч")

    # 5) вход есть — тарифа нет (стоимость неточна)
    lids_intake = {lid for (lid, _m) in intake}
    rows = [{"locationId": lid, **_loc_label(loc_by_id.get(lid)),
             "value": round(sum(v for (l2, _m), v in intake.items() if l2 == lid), 1),
             "note": "нет входящего тарифа — стоимость по оценке"}
            for lid in lids_intake if not (avg_tariff_reestr.get(lid) or last_tariff.get(lid))]
    add_issue("no_tariff", "Объёмы без входящего тарифа", "amber",
              "Запросить тариф у контрагента (файл «Тарифы Электроэнергия_Входящие»).",
              rows, "кВт·ч всего")

    # 6) аномально дорогой тариф
    all_t = [t for t in ({**avg_tariff_reestr, **last_tariff}).values() if t > 0]
    med_t = median(all_t) if all_t else 0
    rows = []
    if med_t:
        for lid, t in {**avg_tariff_reestr, **last_tariff}.items():
            if t > med_t * TARIFF_ANOMALY_X:
                rows.append({"locationId": lid, **_loc_label(loc_by_id.get(lid)),
                             "value": round(t, 2),
                             "note": f"медиана сети {round(med_t, 2)} ₽/кВт·ч"})
    add_issue("tariff_anomaly", "Аномально дорогой входящий тариф", "amber",
              "Проверить договор энергоснабжения: тариф в 1,5+ раза выше медианы сети.",
              rows, "₽/кВт·ч")

    # 7-8) аренда: истёкшие / не оплачено / нет информации
    from datetime import date
    today = date.today().isoformat()
    rows_exp, rows_unpaid, rows_nodocs = [], [], []
    for role in ("rent", "energy"):
        for lid, s in settl_by_role.get(role, {}).items():
            lbl = _loc_label(loc_by_id.get(lid))
            if role == "rent" and s.contract_end and s.contract_end < today:
                rows_exp.append({"locationId": lid, **lbl,
                                 "value": (s.amount_gross or s.amount_net or 0),
                                 "note": f"истёк {s.contract_end}"})
            if s.payment_status == "unpaid":
                rows_unpaid.append({"locationId": lid, **lbl,
                                    "value": (s.amount_gross or s.amount_net or 0),
                                    "note": ("аренда" if role == "rent" else "э/э") + " — не оплачено"})
            elif s.payment_status == "unknown" and lid in net_ids and dispensed.get((lid, ref or ""), 0) > 0:
                rows_nodocs.append({"locationId": lid, **lbl, "value": 0,
                                    "note": ("аренда" if role == "rent" else "э/э") + " — нет данных об оплате/документов"})
    add_issue("rent_expired", "Договор аренды истёк", "red",
              "Пролонгировать/перезаключить: юридический риск размещения.", rows_exp, "₽/мес")
    add_issue("unpaid", "Не оплачено (по реестру)", "red",
              "Оплатить/закрыть задолженность, запросить акты.", rows_unpaid, "₽/мес")
    add_issue("no_docs", "Нет данных об оплате/документах", "amber",
              "Запросить документы у контрагента: статус оплаты неизвестен по работающей станции.",
              rows_nodocs)

    # 9) сироты реестров (строки без объекта) — счётчик из L1
    orphans_raw = (await db.execute(select(func.count(DataEntry.id)).where(
        DataEntry.company_id == company_id, DataEntry.layer == "raw",
        DataEntry.source_label.like("reestr-rh-%"),
        DataEntry.meta["_match"]["resolved"].astext == "false"))).scalar() or 0
    issues.append({"key": "orphans", "label": "Строки реестров без объекта", "severity": "amber",
                   "hint": "Загрузить свежий справочник станций и «Обработать все» в канале реестров.",
                   "count": int(orphans_raw), "unit": "", "rows": []})

    # ── интегральные KPI ──
    rent_rows = [s for s in settl_by_role.get("rent", {}).values()
                 if (s.amount_gross or s.amount_net)]
    rent_monthly = sum((s.amount_gross or s.amount_net or 0) for s in rent_rows)
    last = series[-1] if series else None
    refrow = next((s for s in series if s["period"] == ref), None) if ref else None
    kpis = {
        "refPeriod": ref,
        "energyCostRef": (refrow or {}).get("costEst"),
        "revenueRef": (refrow or {}).get("revenue"),
        "rentMonthly": round(rent_monthly),
        "rentContractsWithAmount": len(rent_rows),
        "overImbalancePctRef": (refrow or {}).get("overImbalancePct"),
        "ownUseFleetMedianKwh": round(own_fleet, 1),
        "issuesRed": sum(1 for i in issues if i["severity"] == "red" and i["count"]),
        "issuesTotal": sum(i["count"] for i in issues),
        "lastPeriod": (last or {}).get("period"),
    }
    return {"series": series[-18:], "kpis": kpis, "issues": issues,
            "regions": regions, "region": region}


async def ops_balance(db: AsyncSession, company_id, period: str | None,
                      region: str | None = None) -> dict[str, Any]:
    """Пообъектный энергобаланс за месяц: вход · отпуск · СН · сверхнорматив ·
    стоимость · выручка · валовая маржа энергии. Формирует «где конкретно
    расхождения» — сортировка по сверхнормативу."""
    loc_by_id, periods, sess_rows, settl = await _load(db, company_id)
    regions, loc_by_id, periods, sess_rows, settl = _apply_region(
        loc_by_id, periods, sess_rows, settl, region)

    intake: dict[tuple[str, str], float] = {}
    tariff: dict[tuple[str, str], float] = {}
    for p in periods:
        if p.intake_kwh is not None:
            intake[(p.location_id, p.period)] = float(p.intake_kwh)
        if p.tariff_rub_kwh is not None:
            tariff[(p.location_id, p.period)] = float(p.tariff_rub_kwh)
    dispensed: dict[tuple[str, str], float] = {}
    revenue: dict[tuple[str, str], float] = {}
    sessions_n: dict[tuple[str, str], int] = {}
    for r in sess_rows:
        m = _month(r.m)
        if m is None:
            continue
        dispensed[(r.location_id, m)] = float(r.kwh or 0)
        revenue[(r.location_id, m)] = float(r.rub or 0)
        sessions_n[(r.location_id, m)] = int(r.n or 0)

    months = sorted({m for (_, m) in intake})
    if not months:
        return {"period": None, "months": [], "rows": []}
    if not period or period not in months:
        # дефолт — последний месяц с ПОЛНЫМИ данными входа (как ref в overview):
        # свежий месяц часто заполнен частично (счета ещё не выставлены)
        cnt = {m: sum(1 for (_, mm) in intake if mm == m) for m in months}
        max_st = max(cnt.values())
        good = [m for m in months if cnt[m] >= max(3, max_st * 0.5)]
        period = good[-1] if good else months[-1]

    own_per_loc, own_fleet = _own_use_estimates(intake, dispensed)
    avg_tariff_reestr: dict[str, float] = {}
    for s in settl:
        if s.role == "energy":
            t = (s.extra or {}).get("avgTariff")
            if isinstance(t, (int, float)) and t > 0:
                avg_tariff_reestr[s.location_id] = float(t)
    last_tariff: dict[str, float] = {}
    for (lid, m), t in sorted(tariff.items(), key=lambda kv: kv[0][1]):
        last_tariff[lid] = t

    lids = {lid for (lid, m) in intake if m == period} | \
           {lid for (lid, m) in dispensed if m == period and lid in loc_by_id}
    rows = []
    for lid in lids:
        i = intake.get((lid, period))
        d = dispensed.get((lid, period), 0.0)
        own = min(own_per_loc.get(lid, own_fleet), i) if i else None
        imb = (i - d) if i is not None else None
        over = max(0.0, imb - (own or 0)) if imb is not None else None
        t = tariff.get((lid, period)) or avg_tariff_reestr.get(lid) or last_tariff.get(lid)
        cost = round(i * t) if (i and t) else None
        rev = revenue.get((lid, period))
        rows.append({
            "locationId": lid, **_loc_label(loc_by_id.get(lid)),
            "intakeKwh": round(i, 1) if i is not None else None,
            "dispensedKwh": round(d, 1),
            "sessions": sessions_n.get((lid, period), 0),
            "ownUseEstKwh": round(own, 1) if own is not None else None,
            "imbalanceKwh": round(imb, 1) if imb is not None else None,
            "overImbalanceKwh": round(over, 1) if over is not None else None,
            "overImbalancePct": round(over / i * 100, 1) if (over is not None and i) else None,
            "tariff": round(t, 2) if t else None,
            "costEst": cost,
            "revenue": round(rev) if rev is not None else None,
            "marginEst": round(rev - cost) if (rev is not None and cost is not None) else None,
        })
    rows.sort(key=lambda r: -(r["overImbalanceKwh"] or 0))
    return {"period": period, "months": months, "rows": rows,
            "ownUseFleetMedianKwh": round(own_fleet, 1),
            "regions": regions, "region": region}


async def ops_station(db: AsyncSession, company_id, location_id: str) -> dict[str, Any]:
    """Карточка объекта для drill-down модалки: паспорт + помесячный энергобаланс
    + договорные контуры (э/э / аренда / сервис) с контрагентами и оплатами."""
    loc = (await db.execute(select(ServiceLocation).where(
        ServiceLocation.company_id == company_id,
        ServiceLocation.id == location_id))).scalar_one_or_none()
    if loc is None:
        return {"found": False}
    md = loc.extra_metadata or {}

    periods = (await db.execute(select(StationEnergyPeriod).where(
        StationEnergyPeriod.company_id == company_id,
        StationEnergyPeriod.location_id == location_id))).scalars().all()
    sess_rows = (await db.execute(
        select(
            func.date_trunc("month", ChargeSession.started_at).label("m"),
            func.sum(ChargeSession.energy_kwh).label("kwh"),
            func.sum(func.coalesce(ChargeSession.client_amount, ChargeSession.amount)).label("rub"),
            func.count().label("n"),
        )
        .where(ChargeSession.company_id == company_id,
               ChargeSession.location_id == location_id,
               ChargeSession.started_at.is_not(None))
        .group_by("m")
    )).all()

    intake = {p.period: float(p.intake_kwh) for p in periods if p.intake_kwh is not None}
    tariffs = {p.period: float(p.tariff_rub_kwh) for p in periods if p.tariff_rub_kwh is not None}
    disp = {}
    rev = {}
    ses_n = {}
    for r in sess_rows:
        m = _month(r.m)
        if m:
            disp[m] = float(r.kwh or 0)
            rev[m] = float(r.rub or 0)
            ses_n[m] = int(r.n or 0)

    settl = (await db.execute(select(StationContractSettlement).where(
        StationContractSettlement.company_id == company_id,
        StationContractSettlement.location_id == location_id))).scalars().all()
    avg_tariff = None
    for s in settl:
        if s.role == "energy":
            t = (s.extra or {}).get("avgTariff")
            if isinstance(t, (int, float)) and t > 0:
                avg_tariff = float(t)

    # СН объекта: медиана его собственных idle-месяцев
    idle = [v for m, v in intake.items() if v > 0 and disp.get(m, 0.0) <= 0.0]
    own = median(idle) if idle else None

    months = sorted(set(intake) | set(disp))[-24:]
    last_t = None
    series = []
    for m in months:
        i = intake.get(m)
        t = tariffs.get(m) or avg_tariff or last_t
        if tariffs.get(m):
            last_t = tariffs[m]
        d = disp.get(m, 0.0)
        imb = (i - d) if i is not None else None
        over = max(0.0, imb - own) if (imb is not None and own is not None) else None
        series.append({
            "period": m, "intakeKwh": i, "dispensedKwh": round(d, 1),
            "sessions": ses_n.get(m, 0),
            "imbalanceKwh": round(imb, 1) if imb is not None else None,
            "overImbalanceKwh": round(over, 1) if over is not None else None,
            "tariff": round(t, 2) if t else None,
            "costEst": round(i * t) if (i and t) else None,
            "revenue": round(rev[m]) if m in rev else None,
        })

    # договорные контуры с именами контрагентов/номерами договоров
    cp_ids = []
    for s in settl:
        if s.counterparty_id:
            try:
                cp_ids.append(_as_uuid(s.counterparty_id))
            except ValueError:
                pass
    cp_names: dict[str, str] = {}
    if cp_ids:
        for cp in (await db.execute(select(Counterparty).where(
                Counterparty.id.in_(cp_ids)))).scalars().all():
            cp_names[str(cp.id)] = cp.name
    contracts_map: dict = {}
    contract_ids = [s.contract_id for s in settl if s.contract_id]
    if contract_ids:
        from app.models import Contract
        for c in (await db.execute(select(Contract).where(
                Contract.id.in_(contract_ids)))).scalars().all():
            contracts_map[c.id] = c.number
    contours = [{
        "role": s.role,
        "counterpartyName": cp_names.get(s.counterparty_id or ""),
        "contractNumber": contracts_map.get(s.contract_id),
        "basis": s.basis,
        "paymentStatus": s.payment_status,
        "paidThrough": s.paid_through,
        "amountGross": s.amount_gross, "amountNet": s.amount_net,
        "vatPct": s.vat_pct,
        "contractStart": s.contract_start, "contractEnd": s.contract_end,
        "comment": s.comment,
        "extra": s.extra,
    } for s in sorted(settl, key=lambda x: {"energy": 0, "rent": 1, "service": 2}.get(x.role, 9))]

    return {
        "found": True,
        "locationId": loc.id,
        **_loc_label(loc),
        "address": loc.address or " ".join(filter(None, [md.get("cityName"), md.get("street"), str(md.get("houseNumber") or "")])).strip() or None,
        "status": loc.operational_status,
        "stage": md.get("stage"),
        "powerKw": loc.power_kwt or md.get("maxPowerKw"),
        "connectors": loc.connectors_count or md.get("connectorCount"),
        "serial": loc.serial_number or md.get("serialNumber"),
        "zoi": md.get("zoi1"),
        "ownUseEstKwh": round(own, 1) if own is not None else None,
        "avgTariff": avg_tariff,
        "series": series,
        "contours": contours,
    }


def _as_uuid(v: str):
    import uuid as _u
    return _u.UUID(str(v))


async def ops_completeness(db: AsyncSession, company_id,
                           date_from: str | None, date_to: str | None,
                           region: str | None = None) -> dict[str, Any]:
    """«Полнота данных»: каких документов/данных не хватает за период анализа.

    Матрица «вид данных × месяц» (expected/have/%) + по каждому виду список
    недостающего (станция → какие месяцы). Виды:
      помесячные — счета за вход э/э, входящие тарифы, данные сессий,
                    подтверждение оплаты э/э и аренды («оплачено по» ≥ месяц);
      статические — договор э/э, договор/разрешение аренды (+истёкшие),
                     ИНН и контакты контрагентов, строки-сироты реестров.
    Ожидание (expected) честное: счета ждём только от станций, которые в этом
    месяце РАБОТАЛИ (есть отпуск по сессиям); тарифы — только где есть счета."""
    loc_by_id, periods, sess_rows, settl = await _load(db, company_id)
    regions, loc_by_id, periods, sess_rows, settl = _apply_region(
        loc_by_id, periods, sess_rows, settl, region)

    intake: dict[tuple[str, str], float] = {}
    tariff: dict[tuple[str, str], float] = {}
    for p in periods:
        if p.intake_kwh is not None:
            intake[(p.location_id, p.period)] = float(p.intake_kwh)
        if p.tariff_rub_kwh is not None:
            tariff[(p.location_id, p.period)] = float(p.tariff_rub_kwh)
    dispensed: dict[tuple[str, str], float] = {}
    for r in sess_rows:
        m = _month(r.m)
        if m and float(r.kwh or 0) > 0:
            dispensed[(r.location_id, m)] = float(r.kwh)

    months_all = sorted({m for (_, m) in intake} | {m for (_, m) in dispensed})
    if not months_all:
        return {"months": [], "kinds": [], "regions": regions, "region": region,
                "from": None, "to": None}
    lo = date_from if date_from in months_all else None
    hi = date_to if date_to in months_all else None
    if lo is None or hi is None or lo > hi:
        # дефолт: последние 6 ЗАКРЫТЫХ месяцев (текущий календарный не закончился —
        # счета за него не могли прийти, 0% пугал бы зря)
        from datetime import date
        cur = date.today().isoformat()[:7] + "-01"
        closed = [m for m in months_all if m < cur] or months_all
        hi = closed[-1]
        idx = months_all.index(hi)
        lo = months_all[max(0, idx - 5)]
    months = [m for m in months_all if lo <= m <= hi]

    net_ids = {l.id for l in loc_by_id.values()
               if not l.is_test and (l.operational_status or "") != "decommissioned"}
    active_in_period = {lid for (lid, m) in dispensed if m in months and lid in net_ids}

    settl_by_role: dict[str, dict[str, StationContractSettlement]] = {}
    for s in settl:
        settl_by_role.setdefault(s.role, {})[s.location_id] = s

    kinds: list[dict[str, Any]] = []

    def month_kind(key, label, doc, expected_of, have_of, note_of=None, hint=""):
        """Помесячный вид: expected_of(m) → set станций, have_of(m) → set станций."""
        per_month = []
        missing: dict[str, list[str]] = {}
        for m in months:
            exp = expected_of(m)
            hav = have_of(m) & exp
            per_month.append({
                "period": m, "have": len(hav), "expected": len(exp),
                "pct": round(len(hav) / len(exp) * 100, 1) if exp else None,
            })
            for lid in exp - hav:
                missing.setdefault(lid, []).append(m)
        rows = [{
            "locationId": lid, **_loc_label(loc_by_id.get(lid)),
            "months": ms,
            "note": note_of(lid) if note_of else f"нет за {len(ms)} мес.",
        } for lid, ms in missing.items()]
        rows.sort(key=lambda r: -len(r["months"]))
        total_e = sum(p["expected"] for p in per_month)
        total_h = sum(p["have"] for p in per_month)
        kinds.append({
            "key": key, "label": label, "doc": doc, "monthly": True, "hint": hint,
            "perMonth": per_month,
            "pct": round(total_h / total_e * 100, 1) if total_e else None,
            "missingCount": len(rows), "rows": rows[:300],
        })

    def static_kind(key, label, doc, rows, expected, hint=""):
        """Статический вид (на период): rows = недостающее."""
        rows.sort(key=lambda r: (r.get("bu") is None, str(r.get("bu") or "")))
        kinds.append({
            "key": key, "label": label, "doc": doc, "monthly": False, "hint": hint,
            "perMonth": [],
            "pct": round((expected - len(rows)) / expected * 100, 1) if expected else None,
            "missingCount": len(rows), "rows": rows[:300],
        })

    # 1) счета за вход э/э: ждём от станций, работавших в месяце
    month_kind(
        "intake_bills", "Счета за электроэнергию (вход)", "счёт/акт поставщика э/э",
        lambda m: {lid for (lid, mm) in dispensed if mm == m and lid in net_ids},
        lambda m: {lid for (lid, mm) in intake if mm == m},
        hint="Станция работала (есть отпуск), но входа по счетам нет — запросить документы у поставщика.",
    )
    # 2) входящие тарифы: ждём там, где есть счета
    month_kind(
        "tariffs", "Входящие тарифы э/э", "тарифная сетка (файл «Тарифы…»)",
        lambda m: {lid for (lid, mm) in intake if mm == m},
        lambda m: {lid for (lid, mm) in tariff if mm == m},
        hint="Объём есть, тарифа за месяц нет — стоимость закупки считается по оценке.",
    )
    # 3) подтверждение оплаты: «оплачено по» ≥ месяц (по контурам реестра)
    def paid_kind(role: str, label: str, doc: str):
        conts = settl_by_role.get(role, {})
        def expected_of(m):
            return {lid for lid in conts if lid in active_in_period}
        def have_of(m):
            return {lid for lid, s in conts.items()
                    if s.payment_status == "paid" and (s.paid_through or "") >= m}
        def note_of(lid):
            s = conts.get(lid)
            if s is None:
                return None
            if s.payment_status == "unknown":
                return "нет данных об оплате (реестр)"
            if s.payment_status == "unpaid":
                return "не оплачено (реестр)"
            if s.paid_through:
                return f"оплачено только по {s.paid_through[:7]}"
            return "особый порядок/без даты"
        month_kind(f"{role}_paid", label, doc, expected_of, have_of, note_of,
                   hint="«Оплачено по» из реестра не покрывает месяц — закрыть оплату или запросить подтверждение.")
    paid_kind("energy", "Подтверждение оплаты э/э", "отметка «оплачено по» в реестре")
    paid_kind("rent", "Подтверждение оплаты аренды", "отметка «оплачено по» в реестре")

    # 4) договор энергоснабжения / аренды у работавших станций
    for role, label, doc in (
        ("energy", "Договор энергоснабжения", "договор с поставщиком э/э"),
        ("rent", "Договор/разрешение аренды", "договор аренды / разрешение на размещение"),
    ):
        conts = settl_by_role.get(role, {})
        miss = [{"locationId": lid, **_loc_label(loc_by_id.get(lid)), "months": [],
                 "note": "нет записи в реестре"}
                for lid in active_in_period if lid not in conts]
        if role == "rent":
            for lid, s in conts.items():
                if lid in active_in_period and s.contract_end and s.contract_end < months[-1]:
                    miss.append({"locationId": lid, **_loc_label(loc_by_id.get(lid)),
                                 "months": [], "note": f"договор истёк {s.contract_end}"})
        static_kind(f"{role}_contract", label, doc, miss, len(active_in_period),
                    hint="Работавшие в периоде станции без договора (или с истёкшим) — юридический риск.")

    # 5) НСИ контрагентов: ИНН и контакты (по контрагентам контуров периода)
    cp_ids = {s.counterparty_id for s in settl if s.counterparty_id
              and s.location_id in active_in_period}
    cps = []
    uu = []
    for v in cp_ids:
        try:
            uu.append(_as_uuid(v))
        except ValueError:
            pass
    if uu:
        cps = (await db.execute(select(Counterparty).where(
            Counterparty.id.in_(uu)))).scalars().all()
    no_inn = [{"locationId": "", "bu": None, "name": c.name, "region": None,
               "months": [], "note": "нет ИНН"} for c in cps if not (c.inn or "").strip()]
    no_contact = [{"locationId": "", "bu": None, "name": c.name, "region": None,
                   "months": [], "note": "нет контактов"}
                  for c in cps if not (c.phone or "").strip()
                  and not ((c.raw or {}).get("reestrContacts"))]
    static_kind("cp_inn", "ИНН контрагентов", "реквизиты для документооборота",
                no_inn, len(cps),
                hint="Без ИНН не сопоставить с 1С/платежами — запросить реквизиты.")
    static_kind("cp_contacts", "Контакты контрагентов", "телефон/способ обмена (лист «Контакты»)",
                no_contact, len(cps),
                hint="Некому направить запрос — заполнить контакты в реестре.")

    # 6) сироты реестров (строки без объекта)
    orphan_rows = []
    raws = (await db.execute(select(DataEntry.meta).where(
        DataEntry.company_id == company_id, DataEntry.layer == "raw",
        DataEntry.source_label.like("reestr-rh-%")))).scalars().all()
    seen = set()
    for meta in raws:
        mm = (meta or {}).get("_match") or {}
        if mm and not mm.get("resolved"):
            bu = str((meta or {}).get("bu") or (meta or {}).get("zoi") or "").strip()
            if bu and bu not in seen:
                seen.add(bu)
                orphan_rows.append({"locationId": "", "bu": bu, "region": None,
                                    "name": str((meta or {}).get("bu_name") or (meta or {}).get("object") or "")[:80],
                                    "months": [], "note": "строка реестра без объекта"})
    static_kind("orphans", "Сопоставление реестров с объектами", "справочник станций",
                orphan_rows, len(seen) + len(loc_by_id),
                hint="Строки реестров без объекта — обновить справочник станций и «Обработать все».")

    return {"months": months, "monthsAll": months_all, "from": lo, "to": hi,
            "kinds": kinds, "regions": regions, "region": region}
