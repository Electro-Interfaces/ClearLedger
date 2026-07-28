"""Банк ЗУ — приоритизация площадок и экономика (Волна 3).

Отвечает на вопрос «что брать, что расшивать, что отклонить» двумя осями, а не
одним баллом:

  • ПРИВЛЕКАТЕЛЬНОСТЬ — стоит ли здесь стоять: дыра в собственной сети, спрос
    региона по НАШИМ фактическим сессиям, тип места и якорь;
  • ИСПОЛНИМОСТЬ — можно ли это сделать: свободная мощность, стоимость и срок
    техприсоединения, расстояние до ТП, определённость права и ставка аренды.

Четыре квадранта → четыре разных действия (делать сейчас / расшивать узкое место /
дешёвый опцион / отклонить).

⚠ Главный принцип: **не выдумывать балл там, где нет данных.** У большинства
площадок банка заполнено две-три колонки из пятидесяти. Поэтому вместе с баллом
считается УВЕРЕННОСТЬ — доля факторов, по которым данные есть. Балл при нулевой
уверенности не показываем как оценку: «не хватает данных» честнее середины шкалы.

Экономика — оценка, а не смета: прогноз выработки берём из фактических сессий
сети (медиана кВт·ч на станцию в месяц по региону), маржу — из фактических
тарифов. Все допущения возвращаются рядом с числом, чтобы их можно было оспорить.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import EzsSite
from app.services.ezs_sites import STAGE_LABELS, STAGE_ORDER

# Ниже этого расстояния до собственной станции новая площадка скорее делит
# трафик с уже работающей, чем добавляет покрытие.
CANNIBAL_KM = 0.5
NEAR_KM = 2.0
# Дальше этого — «белое пятно»: сеть сюда не дотягивается.
GAP_KM = 15.0
# Горизонт для бенчмарка спроса.
BENCHMARK_MONTHS = 6
# Минимум станций, чтобы считать региональный бенчмарк представительным.
# По одной станции регион давал «спрос 7× сети» и выносил площадку в топ —
# это не спрос региона, это одна удачная точка.
MIN_REGION_STATIONS = 3
# Ориентир мощности площадки, если план не задан (типовая быстрая ЭЗС сети).
DEFAULT_POWER_KWT = 150.0


# ── Спрос сети: сколько реально возит станция в этом регионе ────────────────
async def region_benchmarks(db: AsyncSession, company_id) -> dict[str, Any]:
    """Медиана кВт·ч на станцию в месяц и средний тариф по регионам — из наших сессий.

    Медиана, а не среднее: пара станций-рекордсменов иначе поднимает планку всему
    региону, и любая новая площадка выглядит недотягивающей.
    """
    rows = (await db.execute(text("""
        with per_station as (
            select sl.region_id,
                   cs.location_id,
                   sum(cs.energy_kwh) as kwh,
                   sum(coalesce(cs.client_amount, cs.amount)) as amount,
                   count(distinct date_trunc('month', cs.started_at)) as months
            from charge_sessions cs
            join service_locations sl on sl.id = cs.location_id
            where cs.company_id = :cid
              and cs.started_at >= (select max(started_at) from charge_sessions
                                    where company_id = :cid) - make_interval(months => :m)
              and cs.energy_kwh > 0
            group by 1, 2
        )
        select r.name as region,
               percentile_cont(0.5) within group (order by kwh / greatest(months, 1)) as kwh_month,
               percentile_cont(0.75) within group (order by kwh / greatest(months, 1)) as kwh_p75,
               sum(amount) / nullif(sum(kwh), 0) as tariff,
               count(*) as stations
        from per_station p
        join regions r on r.id = p.region_id
        group by 1
    """), {"cid": company_id, "m": BENCHMARK_MONTHS})).mappings().all()

    net = (await db.execute(text("""
        with per_station as (
            select cs.location_id,
                   sum(cs.energy_kwh) as kwh,
                   sum(coalesce(cs.client_amount, cs.amount)) as amount,
                   count(distinct date_trunc('month', cs.started_at)) as months
            from charge_sessions cs
            where cs.company_id = :cid and cs.location_id is not null
              and cs.started_at >= (select max(started_at) from charge_sessions
                                    where company_id = :cid) - make_interval(months => :m)
              and cs.energy_kwh > 0
            group by 1
        )
        select percentile_cont(0.5) within group (order by kwh / greatest(months, 1)) as kwh_month,
               percentile_cont(0.75) within group (order by kwh / greatest(months, 1)) as kwh_p75,
               sum(amount) / nullif(sum(kwh), 0) as tariff,
               count(*) as stations
        from per_station
    """), {"cid": company_id, "m": BENCHMARK_MONTHS})).mappings().one()

    by_region = {r["region"]: {"kwhMonth": _f(r["kwh_month"]), "kwhP75": _f(r["kwh_p75"]),
                               "tariff": _f(r["tariff"]), "stations": int(r["stations"] or 0)}
                 for r in rows}
    return {
        "byRegion": by_region,
        "network": {"kwhMonth": _f(net["kwh_month"]), "kwhP75": _f(net["kwh_p75"]),
                    "tariff": _f(net["tariff"]), "stations": int(net["stations"] or 0)},
        "months": BENCHMARK_MONTHS,
    }


def _f(v: Any) -> float | None:
    return None if v is None else float(v)


def _region_bench(bench: dict[str, Any], region: str | None) -> dict[str, Any] | None:
    """Бенчмарк региона, если он представителен. Иначе None — считаем по сети."""
    if not region:
        return None
    reg = (bench.get("byRegion") or {}).get(region)
    if reg and reg.get("stations", 0) >= MIN_REGION_STATIONS:
        return reg
    return None


async def nearest_station_km(db: AsyncSession, company_id) -> dict[str, float]:
    """Расстояние от площадки до ближайшей СВОЕЙ работающей станции, км."""
    rows = (await db.execute(text("""
        with s as (select id, lat, lon from ezs_sites
                   where company_id = :cid and lat is not null),
             l as (select latitude lat, longitude lon from service_locations
                   where company_id = :cid and type = 'ev_charging'
                     and coalesce(is_test, false) = false
                     and coalesce(operational_status, '') <> 'decommissioned'
                     and latitude is not null)
        select s.id, d.km from s
        left join lateral (
            select min(111.0 * sqrt(power(s.lat - l.lat, 2)
                   + power((s.lon - l.lon) * cos(radians(s.lat)), 2))) as km from l
        ) d on true
    """), {"cid": company_id})).all()
    return {str(i): float(km) for i, km in rows if km is not None}


# ── Скоринг ────────────────────────────────────────────────────────────────
def _norm(value: float, best: float, worst: float) -> float:
    """0..100 по линейной шкале; best может быть меньше worst (чем меньше — тем лучше)."""
    if best == worst:
        return 50.0
    x = (value - worst) / (best - worst)
    return max(0.0, min(1.0, x)) * 100.0


def score_site(site: EzsSite, *, near_km: float | None, bench: dict[str, Any]) -> dict[str, Any]:
    """Две оси, уверенность и рекомендация. Фактор без данных не занижает и не
    завышает балл — он просто не участвует, а уверенность падает."""
    attract: list[tuple[str, float, float]] = []   # (фактор, балл, вес)
    feasible: list[tuple[str, float, float]] = []
    unknown: list[str] = []

    # ── привлекательность ──
    if near_km is not None:
        # Впритык к своей станции — делёж трафика; далеко — новое покрытие.
        attract.append(("Покрытие сети", _norm(near_km, best=GAP_KM, worst=0.0), 2.0))
    else:
        unknown.append("нет координат — не понять, дыра это или дубль")

    region = site.region_norm or site.region
    reg = _region_bench(bench, region)
    net = bench.get("network") or {}
    if reg and reg.get("kwhMonth") and net.get("kwhMonth"):
        ratio = reg["kwhMonth"] / net["kwhMonth"]
        attract.append(("Спрос региона", _norm(ratio, best=1.8, worst=0.4), 2.0))
    else:
        unknown.append(f"в регионе меньше {MIN_REGION_STATIONS} наших станций — "
                       "спрос не с чем сравнить")

    if site.place_kind:
        attract.append(("Тип места", 70.0 if site.place_kind == "трасса" else 60.0, 0.5))
    if site.install_place:
        attract.append(("Якорь (ТЦ, отель, АЗС)", 75.0, 1.0))
    if site.dop_service:
        attract.append(("Доп. сервис на месте", 70.0, 0.5))

    # ── исполнимость ──
    need_power = site.planned_power_kwt or DEFAULT_POWER_KWT
    if site.free_power_num:
        attract_ratio = site.free_power_num / need_power
        feasible.append(("Свободная мощность", _norm(attract_ratio, best=1.5, worst=0.3), 2.5))
    else:
        unknown.append("не известна свободная мощность")

    cost = _num(site.tp_cost) or _num(site.connection_cost)
    if cost:
        feasible.append(("Стоимость подключения", _norm(cost, best=0.0, worst=3_000_000.0), 2.0))
    else:
        unknown.append("не посчитано подключение")

    if site.tp_term_months:
        feasible.append(("Срок мероприятий", _norm(site.tp_term_months, best=2.0, worst=12.0), 1.0))
    if site.distance_to_tp_m:
        feasible.append(("Расстояние до ТП", _norm(site.distance_to_tp_m, best=20.0, worst=500.0), 1.0))
    if site.control_form:
        feasible.append(("Форма контроля определена", 80.0, 1.5))
    else:
        unknown.append("не определена форма контроля участка")
    rent = _num(site.rent_rate) or _num(site.rent_cost_month)
    if rent is not None:
        feasible.append(("Ставка аренды", _norm(rent, best=0.0, worst=50_000.0), 1.0))

    a_score, a_conf = _weighted(attract, max_weight=6.0)
    f_score, f_conf = _weighted(feasible, max_weight=9.0)
    conf = round((a_conf + f_conf) / 2)

    return {
        "attract": a_score, "feasible": f_score, "confidence": conf,
        "quadrant": _quadrant(a_score, f_score, conf),
        "factors": {
            "attract": [{"name": n, "score": round(s)} for n, s, _ in attract],
            "feasible": [{"name": n, "score": round(s)} for n, s, _ in feasible],
        },
        "unknown": unknown,
        "nearestStationKm": round(near_km, 2) if near_km is not None else None,
        "cannibalization": (near_km is not None and near_km <= CANNIBAL_KM),
    }


def _weighted(items: list[tuple[str, float, float]], max_weight: float) -> tuple[int | None, int]:
    if not items:
        return (None, 0)
    w = sum(x[2] for x in items)
    score = sum(s * wt for _, s, wt in items) / w
    return (round(score), round(min(1.0, w / max_weight) * 100))


def _quadrant(a: int | None, f: int | None, conf: int) -> str:
    """Что делать с площадкой. При низкой уверенности — не решать, а дособрать данные."""
    if a is None or f is None or conf < 34:
        return "need_data"
    hi_a, hi_f = a >= 55, f >= 55
    if hi_a and hi_f:
        return "do_now"
    if hi_a and not hi_f:
        return "unblock"
    if not hi_a and hi_f:
        return "option"
    return "drop"


QUADRANTS = {
    "do_now": {"label": "Делать сейчас", "hint": "спрос есть и реализуемо"},
    "unblock": {"label": "Расшивать узкое место", "hint": "место хорошее, мешает техника или право"},
    "option": {"label": "Дешёвый опцион", "hint": "сделать легко, но спрос слабый"},
    "drop": {"label": "Кандидат на отказ", "hint": "и спрос слабый, и делать тяжело"},
    "need_data": {"label": "Не хватает данных", "hint": "сначала добрать факты, потом решать"},
}


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Экономика площадки ─────────────────────────────────────────────────────
def economics(site: EzsSite, bench: dict[str, Any],
              capex_budget: float | None = None) -> dict[str, Any]:
    """Оценка окупаемости на фактических данных сети. Возвращает и допущения."""
    region = site.region_norm or site.region
    reg = _region_bench(bench, region)
    net = bench.get("network") or {}
    assumptions: list[str] = []

    kwh = (reg or {}).get("kwhMonth") or net.get("kwhMonth")
    if kwh is None:
        return {"ok": False, "message": "нет фактических сессий для бенчмарка",
                "assumptions": assumptions}
    if reg:
        assumptions.append(f"выработка — медиана станции в регионе «{region}» "
                           f"({reg['stations']} станций, {bench['months']} мес)")
    else:
        assumptions.append(f"выработка — медиана по всей сети ({net.get('stations', 0)} станций): "
                           f"в этом регионе меньше {MIN_REGION_STATIONS} наших станций")
    assumptions.append("месяцы без сессий у станции в медиану не входят — "
                       "это выработка работающей точки, а не среднее по календарю")

    tariff = (reg or {}).get("tariff") or net.get("tariff") or 0.0
    assumptions.append(f"тариф — фактический средний {tariff:.2f} ₽/кВт·ч")

    # Входная цена: своя, если известна из банка, иначе оценка как доля тарифа.
    input_price = _input_price(site)
    if input_price is None:
        input_price = round(tariff * 0.45, 2)
        assumptions.append(f"входная цена не известна — принята как 45% тарифа ({input_price} ₽)")
    else:
        assumptions.append(f"входная цена из карточки {input_price} ₽/кВт·ч")

    margin_kwh = max(tariff - input_price, 0.0)
    rent = _num(site.rent_rate) or _num(site.rent_cost_month) or 0.0
    if rent == 0:
        assumptions.append("аренда не указана — принята нулевой")

    # Бюджет проекта полнее паспорта: в нём и подключение, и оборудование, и СМР.
    # Пока его не завели — считаем по графам подключения, как раньше.
    if capex_budget:
        capex = capex_budget
        assumptions.append("капитальные затраты — из бюджета проекта (все статьи капвложений)")
    else:
        capex = _num(site.connection_cost) or _num(site.tp_cost)
        if capex is None:
            assumptions.append("капитальные затраты не посчитаны — срок окупаемости не считается")
        assumptions.append("стоимость оборудования и СМР в расчёт не входит — только подключение: "
                           "заведите бюджет проекта, чтобы окупаемость считалась по нему")

    # Выработка станций сети распределена крайне неравномерно (медиана 164,
    # верхняя четверть 500+ кВт·ч/мес). Одна цифра тут врёт в обе стороны,
    # поэтому считаем вилку: базовый сценарий по медиане, хороший — по p75.
    kwh_hi = (reg or {}).get("kwhP75") or net.get("kwhP75") or kwh
    scenarios = {}
    for key, k in (("base", kwh), ("good", kwh_hi)):
        revenue = k * tariff
        energy_cost = k * input_price
        monthly = revenue - energy_cost - rent
        scenarios[key] = {
            "kwhMonth": round(k),
            "revenueMonth": round(revenue),
            "energyCostMonth": round(energy_cost),
            "marginMonth": round(monthly),
            "paybackMonths": round(capex / monthly, 1) if capex and monthly > 0 else None,
        }
    assumptions.append("базовый сценарий — медиана выработки, хороший — верхняя "
                       "четверть станций (p75)")

    return {
        "ok": True,
        "tariff": round(tariff, 2),
        "inputPrice": input_price,
        "marginPerKwh": round(margin_kwh, 2),
        "rentMonth": round(rent),
        "capex": round(capex) if capex else None,
        "base": scenarios["base"],
        "good": scenarios["good"],
        # Плоские поля базового сценария — для таблиц и совместимости.
        "kwhMonth": scenarios["base"]["kwhMonth"],
        "revenueMonth": scenarios["base"]["revenueMonth"],
        "energyCostMonth": scenarios["base"]["energyCostMonth"],
        "marginMonth": scenarios["base"]["marginMonth"],
        "paybackMonths": scenarios["base"]["paybackMonths"],
        "assumptions": assumptions,
        "benchmarkSource": "region" if reg else "network",
    }


def _input_price(site: EzsSite) -> float | None:
    """Входная цена ₽/кВт·ч — колонка файла «Входная стоимость» лежит в raw."""
    raw = site.raw or {}
    for k, v in raw.items():
        if "входная стоимость" in str(k).lower():
            n = _num(str(v).replace(",", ".").replace("р.", "").replace("₽", "").strip())
            if n and 0 < n < 100:
                return round(n, 2)
    return None


# ── Матрица приоритетов и разрывы покрытия ─────────────────────────────────
async def priority_matrix(db: AsyncSession, company_id, *, stage: str | None = None,
                          region: str | None = None) -> dict[str, Any]:
    """Скоринг активных площадок + раскладка по квадрантам."""
    from sqlalchemy import select

    bench = await region_benchmarks(db, company_id)
    near = await nearest_station_km(db, company_id)

    conds = [EzsSite.company_id == company_id]
    conds.append(EzsSite.stage == stage if stage else EzsSite.stage.in_(STAGE_ORDER))
    if region:
        from sqlalchemy import func
        conds.append(func.coalesce(EzsSite.region_norm, EzsSite.region) == region)
    sites = (await db.execute(select(EzsSite).where(*conds))).scalars().all()

    items, buckets = [], {k: 0 for k in QUADRANTS}
    for s in sites:
        sc = score_site(s, near_km=near.get(str(s.id)), bench=bench)
        buckets[sc["quadrant"]] += 1
        items.append({
            "id": str(s.id), "projectNo": s.project_no, "title": s.title,
            "stage": s.stage, "stageLabel": STAGE_LABELS.get(s.stage, s.stage),
            "region": s.region_norm or s.region, "city": s.city,
            "address": s.address or s.full_address or s.install_place,
            "owner": s.owner, "ownerUserId": str(s.owner_user_id) if s.owner_user_id else None,
            **{k: sc[k] for k in ("attract", "feasible", "confidence", "quadrant",
                                  "nearestStationKm", "cannibalization")},
            "unknown": sc["unknown"],
        })
    # Сортировка по полезности решения, а не по баллу: площадка с одним известным
    # фактором даёт «привлекательность 100» и иначе занимала бы верх списка, хотя
    # решать по ней нечего. Сначала то, где есть на чём решать.
    order = {"do_now": 0, "unblock": 1, "option": 2, "drop": 3, "need_data": 4}
    items.sort(key=lambda x: (order.get(x["quadrant"], 9), -(x["attract"] or 0),
                              -(x["feasible"] or 0), -x["confidence"]))
    return {
        "total": len(items),
        "quadrants": [{"key": k, **QUADRANTS[k], "count": buckets[k]} for k in QUADRANTS],
        "items": items,
        "benchmark": bench,
        "thresholds": {"cannibalKm": CANNIBAL_KM, "nearKm": NEAR_KM, "gapKm": GAP_KM},
    }


async def coverage_gaps(db: AsyncSession, company_id) -> dict[str, Any]:
    """Где сеть есть, а пайплайна нет — и наоборот. Плюс риск каннибализации."""
    regions = (await db.execute(text("""
        select coalesce(r.region, s.region) as region,
               coalesce(r.stations, 0) as stations,
               coalesce(s.sites, 0) as sites
        from (select rg.name as region, count(*) as stations
              from service_locations sl join regions rg on rg.id = sl.region_id
              where sl.company_id = :cid and sl.type = 'ev_charging'
                and coalesce(sl.is_test, false) = false
                and coalesce(sl.operational_status, '') <> 'decommissioned'
              group by 1) r
        full join (select coalesce(region_norm, region) as region, count(*) as sites
                   from ezs_sites
                   where company_id = :cid and stage = any(:active)
                   group by 1) s
             -- Сопоставляем по «ядру» названия: в банке встречается «Новгородская
             -- обл.» там, где в справочнике сети «Новгородская область».
             on regexp_replace(lower(trim(r.region)),
                    '\\s*(область|обл\\.?|край|республика|респ\\.?|автономный округ|ао)\\s*$', '')
              = regexp_replace(lower(trim(s.region)),
                    '\\s*(область|обл\\.?|край|республика|респ\\.?|автономный округ|ао)\\s*$', '')
        order by coalesce(r.stations, 0) desc
    """), {"cid": company_id, "active": STAGE_ORDER})).mappings().all()

    near = await nearest_station_km(db, company_id)
    from sqlalchemy import select
    sites = (await db.execute(select(EzsSite).where(
        EzsSite.company_id == company_id, EzsSite.stage.in_(STAGE_ORDER),
        EzsSite.lat.is_not(None)))).scalars().all()
    cannibal = [{"id": str(s.id), "region": s.region_norm or s.region, "city": s.city,
                 "address": s.address or s.full_address, "stage": s.stage,
                 "stageLabel": STAGE_LABELS.get(s.stage, s.stage),
                 "km": round(near[str(s.id)], 2)}
                for s in sites if near.get(str(s.id)) is not None and near[str(s.id)] <= CANNIBAL_KM]
    cannibal.sort(key=lambda x: x["km"])

    return {
        "regions": [{"region": r["region"], "stations": int(r["stations"]),
                     "sites": int(r["sites"])} for r in regions if r["region"]],
        "networkNoPipeline": [{"region": r["region"], "stations": int(r["stations"])}
                              for r in regions if r["region"] and r["stations"] and not r["sites"]],
        "pipelineNoNetwork": [{"region": r["region"], "sites": int(r["sites"])}
                              for r in regions if r["region"] and r["sites"] and not r["stations"]],
        "cannibalization": cannibal,
        "withoutCoords": sum(1 for s in sites if s.lat is None),
        "thresholds": {"cannibalKm": CANNIBAL_KM, "gapKm": GAP_KM},
    }
