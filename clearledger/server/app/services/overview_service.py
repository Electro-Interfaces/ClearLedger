"""Executive-обзор сети ЭЗС (energy, РусГидро) — стратегический слой поверх
операционных пунктов (Сессии / Тарифы / Корпоратив).

Изолирован: НЕ трогает contended `analytics_service.py` / `analytics_router.py`
(их правит параллельная работа) — только ВЫЗЫВАЕТ готовый `AnalyticsService`
и `CorporateService`. Собирает единый ответ для дашборда «Обзор»:
KPI с Δ% к прошлому периоду + спарклайны, гейджи, тренд с оверлеем, доли,
топ/дно станций, корпоратив, алерты, meta. Полные количественные разрезы по
всем измерениям фронт берёт отдельно через существующий /charge-sessions.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import and_, case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession
from app.services.analytics_cache import cached_report
from app.services.analytics_service import AnalyticsService, PeriodFilter
from app.services.corporate_service import CorporateService
from app.services.charge_payment_state import effective_paid_at
from app.services.session_scope import session_scope_conds


def _dpct(cur: float, prev: float) -> float | None:
    """Δ% (cur−prev)/prev. None — если базы нет (нельзя посчитать рост)."""
    if prev:
        return round((cur - prev) / prev * 100, 1)
    return None if not cur else 100.0


def _dir(delta: float | None) -> str:
    if delta is None:
        return "flat"
    if delta > 0.05:
        return "up"
    if delta < -0.05:
        return "down"
    return "flat"


def _util_accent(v: float) -> str:
    return "success" if v >= 15 else "warning" if v >= 10 else "danger"


def _succ_accent(v: float) -> str:
    return "success" if v >= 85 else "warning" if v >= 70 else "danger"


def _unpaid_accent(v: float) -> str:
    return "success" if v <= 3 else "warning" if v <= 10 else "danger"


class OverviewService:
    """Собирает executive-дашборд одним запросом; дельты считает сервер."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.a = AnalyticsService(db)
        self.corp = CorporateService(db)

    @staticmethod
    def _bucket_for(days: int) -> str:
        """Авто-гранулярность тренда/спарклайнов под длину периода."""
        if days <= 60:
            return "day"
        if days <= 250:
            return "week"
        return "month"

    async def _bucket_series(self, f: PeriodFilter, bucket: str) -> tuple[list[str], dict]:
        """Один скан `_cs_aggregate_2d(bucket)` → (ось бакетов, суммы по бакету).
        Из него выводятся ВСЕ спарклайны и тренд — вместо 5+ отдельных
        timeseries-запросов (каждый = полнотабличный скан того же периода)."""
        rows = await self.a._cs_aggregate_2d(
            f.company_id, f.date_from, f.date_to, bucket, None,
            f.station_codes, f.regions, f.dim_by, f.dim_val)
        by = {r.b: r for r in rows}
        axis = self.a._cs_bucket_axis(f.date_from, f.date_to, bucket)
        return axis, by

    def _series(self, axis: list[str], by: dict, metric: str) -> list[float | None]:
        """Значения метрики по оси бакетов (пустой бакет → null для ratio, иначе 0).
        Семантика идентична `charge_timeseries` (series_by=None)."""
        empty = None if self.a._cs_is_ratio(metric) else 0
        out: list[float | None] = []
        for b in axis:
            r = by.get(b)
            out.append(
                self.a._cs_metric_from_sums(metric, r.cnt, r.energy, r.amount, r.duration, r.success)
                if r is not None else empty)
        return out

    async def _segments(self, f: PeriodFilter) -> dict[str, dict]:
        """Каноническая сегментация выручки/сессий/оплат ОДНИМ сканом:
          corp   — ЮЛ (client_name задан, сматчен на организацию);
          retail — ФЛ (есть телефон-аккаунт, не корп);
          anon   — без телефона.
        Совпадает с corporate_service (client_name) и retail_service (user_id) —
        поэтому Обзор смыкается с панелями «Корпоратив»/«Частные лица»."""
        S = ChargeSession
        paid_at = effective_paid_at(S)
        seg = case(
            (S.client_name.is_not(None), "corp"),
            (S.user_id.is_not(None), "retail"),
            else_="anon",
        ).label("seg")
        stmt = select(
            seg,
            func.count().label("cnt"),
            func.coalesce(func.sum(func.coalesce(S.client_amount, S.amount)), 0).label("amount"),
            func.coalesce(func.sum(case((paid_at.is_not(None), 1), else_=0)), 0).label("paid"),
            # Отдельно — сессии, где ток ПОШЁЛ, и оплаченные среди них. Долг бывает
            # только за отпущенную энергию: за сорвавшуюся попытку платить не за что,
            # а без этого «Без оплаты» бил тревогу на 3,7 % при нулевой задолженности.
            func.coalesce(func.sum(case((S.energy_kwh > 0, 1), else_=0)), 0).label("charged"),
            func.coalesce(func.sum(case(
                (and_(S.energy_kwh > 0, paid_at.is_not(None)), 1), else_=0)), 0).label("charged_paid"),
        ).where(*self.a._cs_conds(f.company_id, f.date_from, f.date_to, f.station_codes, f.regions)).group_by(seg)
        out = {k: {"amount": 0.0, "sessions": 0, "paid": 0, "charged": 0, "charged_paid": 0}
               for k in ("corp", "retail", "anon")}
        for r in (await self.db.execute(stmt)).all():
            out[r.seg] = {"amount": float(r.amount), "sessions": int(r.cnt), "paid": int(r.paid),
                          "charged": int(r.charged), "charged_paid": int(r.charged_paid)}
        return out

    @cached_report("ezs:overview")
    async def overview(self, company_id: Any, df: date, dt: date, compare: str = "prev",
                       today: date | None = None,
                       stations: list[str] | None = None,
                       regions: list[str] | None = None,
                       tz: str = "msk") -> dict[str, Any]:
        period_days = (dt - df).days + 1
        prev_to = df - timedelta(days=1)
        prev_from = prev_to - timedelta(days=period_days - 1)
        bucket = self._bucket_for(period_days)

        # Сужение по сети из контура (регион/станции) — обзор обязан ему подчиняться,
        # иначе KPI и инсайты показывают всю сеть при выбранной области.
        f_cur = PeriodFilter(company_id=company_id, date_from=df, date_to=dt,
                             station_codes=stations, regions=regions)
        f_prev = PeriodFilter(company_id=company_id, date_from=prev_from, date_to=prev_to,
                              station_codes=stations, regions=regions)

        # ─── тоталы текущего/прошлого периода (разрез station → заодно активные ЭЗС) ───
        cur = await self.a.charge_sessions(f_cur, "station")
        prev = await self.a.charge_sessions(f_prev, "station")
        tc, tp = cur["totals"], prev["totals"]
        stations_lines = cur["lines"]
        active_cur = len(stations_lines)
        active_prev = len(prev["lines"])
        # База для сравнения есть только если в прошлом периоде реально были сессии.
        # Иначе (данные начались позже) все дельты — фиктивные «+100%»; честнее null.
        has_prev = tp["sessions"] > 0

        # ─── спарклайны + тренд из ОДНОГО скана на период (было 5 timeseries + 2) ───
        cur_axis, cur_by = await self._bucket_series(f_cur, bucket)
        spark_amount = self._series(cur_axis, cur_by, "amount")
        spark_sessions = self._series(cur_axis, cur_by, "sessions")
        spark_energy = self._series(cur_axis, cur_by, "energy")
        spark_price = self._series(cur_axis, cur_by, "price_per_kwh")

        # ─── успех на уровне ВИЗИТОВ (а не сырых сессий) ───
        # CPO пишет каждое касание разъёма отдельной сессией, поэтому «успешных
        # сессий» отвечает на вопрос «сколько раз сработал разъём», а не «сколько
        # людей уехало заряженными». Для обзора сети верен второй вопрос: клиент,
        # зарядившийся с третьей попытки, — успех, а не 2/3 брака.
        # Разбор самих повторов — «Надёжность» → «Повторные попытки».
        from app.services.charge_visits import (
            visit_success, visit_success_by_station, visit_success_series,
        )
        vc = await visit_success(self.db, company_id, df, dt, f_cur.station_codes, regions=f_cur.regions)
        vp = await visit_success(self.db, company_id, prev_from, prev_to, f_prev.station_codes, regions=f_prev.regions)
        v_by_bucket = await visit_success_series(
            self.db, company_id, df, dt, bucket, f_cur.station_codes, regions=f_cur.regions)
        # Успех — доля: пустой бакет → null (ноль в ней читался бы как «все ушли
        # ни с чем»). Визиты — счётчик: пустой бакет → 0, это честный ноль.
        spark_success = [(v_by_bucket[b]["success_pct"] if b in v_by_bucket else None) for b in cur_axis]
        spark_visits = [(v_by_bucket[b]["visits"] if b in v_by_bucket else 0) for b in cur_axis]

        def kpi(key, label, value, prev_value, fmt, unit, spark=None, accent=None):
            d = _dpct(float(value), float(prev_value)) if has_prev else None
            item = {
                "key": key, "label": label, "value": round(float(value), 2),
                "prev": round(float(prev_value), 2), "fmt": fmt, "unit": unit,
                "delta_pct": d, "dir": _dir(d),
            }
            if spark is not None:
                item["spark"] = spark
            if accent is not None:
                item["accent"] = accent
            # для метрик, где рост = хорошо (все 7), знак дельты задаёт цвет
            item["good"] = "higher"
            return item

        kpis = [
            kpi("revenue", "Выручка", tc["amount"], tp["amount"], "moneyShort", "₽", spark_amount),
            # Визиты идут ПЕРЕД сессиями: визит — это один заезд клиента (единица, в
            # которой считается успех), сессия — техническая строка CPO. Без визита
            # на экране «Зарядились 89,3%» не с чем соотнести: рядом стоит 122 336
            # сессий, и доля выглядит взявшейся из воздуха.
            kpi("visits", "Визиты", vc["visits"], vp["visits"], "int", "", spark_visits),
            kpi("sessions", "Сессии", tc["sessions"], tp["sessions"], "int", "", spark_sessions),
            kpi("energy_kwh", "Энергия", tc["energy_kwh"], tp["energy_kwh"], "kwh", "кВтч", spark_energy),
            kpi("utilization_pct", "Загрузка", tc["utilization_pct"], tp["utilization_pct"], "pct", "%",
                None, _util_accent(tc["utilization_pct"])),
            kpi("visit_success_pct", "Зарядились", vc["success_pct"], vp["success_pct"], "pct", "%",
                spark_success, _succ_accent(vc["success_pct"])),
            kpi("price_per_kwh", "Цена", tc["price_per_kwh"], tp["price_per_kwh"], "price", "₽/кВтч", spark_price),
            kpi("active_stations", "Активных ЭЗС", active_cur, active_prev, "int", ""),
        ]

        # ─── корпоратив (ЮЛ) ───
        corp = await self.corp.overview(company_id, df, dt,
                                        stations=f_cur.station_codes, regions=f_cur.regions)
        corp_rev = corp["totals"]["corp_revenue"]
        total_rev = tc["amount"] or 0.0
        corp_share = round(corp_rev / total_rev * 100, 1) if total_rev else 0.0

        # ─── гейджи-кольца (доля от 100%) ───
        gauges = [
            {"key": "utilization_pct", "label": "Загрузка портов", "value": tc["utilization_pct"],
             "unit": "%", "accent": _util_accent(tc["utilization_pct"]),
             "hint": f"{int(tc['ports'])} портов"},
            {"key": "visit_success_pct", "label": "Клиенты зарядились", "value": vc["success_pct"],
             "unit": "%", "accent": _succ_accent(vc["success_pct"]),
             "hint": f"{vc['charged']:,} из {vc['visits']:,} визитов".replace(",", " ")},
            {"key": "corp_share", "label": "Доля ЮЛ (выручка)", "value": corp_share,
             "unit": "%", "accent": "info"},
        ]

        # ─── тренд выручки с оверлеем прошлого периода (текущий ряд = spark_amount,
        #     без повторного скана; прошлый период — один доп. скан) ───
        prev_vals: list[float | None] = []
        if has_prev:
            prev_axis, prev_by = await self._bucket_series(f_prev, bucket)
            prev_vals = self._series(prev_axis, prev_by, "amount")
        n = len(cur_axis)
        prev_aligned = (prev_vals + [None] * n)[:n]  # паддинг/усечение под текущую ось
        trend = {
            "bucket": bucket,
            "points": [
                {"label": cur_axis[i], "current": spark_amount[i], "previous": prev_aligned[i]}
                for i in range(n)
            ],
        }

        # ─── доли: коннекторы (донат) + каноническая сегментация (донат + алерт) ───
        conn = await self.a.charge_sessions(f_cur, "connector", with_totals=False)
        seg = await self._segments(f_cur)

        def share_rows(lines: list[dict], top: int = 6) -> list[dict]:
            rows = [{"label": l["label"], "amount": l["amount"], "sessions": l["sessions"],
                     "energy_kwh": l["energy_kwh"], "share_pct": l["share_pct"]} for l in lines[:top]]
            rest = lines[top:]
            if rest:
                rows.append({
                    "label": "Прочие",
                    "amount": round(sum(l["amount"] for l in rest), 2),
                    "sessions": sum(l["sessions"] for l in rest),
                    "energy_kwh": round(sum(l["energy_kwh"] for l in rest), 1),
                    "share_pct": round(sum(l["share_pct"] for l in rest), 2),
                })
            return rows

        # каноническая сегментация выручки (corp/retail/anon) — донат «По сегменту».
        # Анонимные выделены отдельно (раньше подмешивались в «Розницу ФЛ»).
        seg_total = sum(v["amount"] for v in seg.values()) or 0.0

        def seg_row(label: str, key: str) -> dict:
            v = seg[key]
            return {"label": label, "amount": round(v["amount"], 2), "sessions": v["sessions"],
                    "share_pct": round(v["amount"] / seg_total * 100, 1) if seg_total else 0.0}

        by_segment = [seg_row("Корпоратив (ЮЛ)", "corp"), seg_row("Розница (ФЛ)", "retail")]
        if seg["anon"]["sessions"] > 0:
            by_segment.append(seg_row("Анонимные", "anon"))
        shares = {
            "connector": share_rows(conn["lines"]),
            "by_segment": by_segment,
        }

        # ─── топ/дно станций по загрузке (порт-нормировано; фильтр по объёму) ───
        MIN_SESS = 30
        qualified = [l for l in stations_lines if l["sessions"] >= MIN_SESS]
        by_util = sorted(qualified, key=lambda l: -l["utilization_pct"])

        def st_row(l: dict) -> dict:
            return {"label": l["label"], "sessions": l["sessions"], "energy_kwh": l["energy_kwh"],
                    "amount": l["amount"], "utilization_pct": l["utilization_pct"],
                    "success_pct": l["success_pct"], "throughput_port": l["throughput_port"]}

        stations = {
            "top": [st_row(l) for l in by_util[:5]],
            "bottom": [st_row(l) for l in by_util[-5:][::-1]] if len(by_util) > 5 else [],
            "by_revenue": [st_row(l) for l in sorted(stations_lines, key=lambda l: -l["amount"])[:5]],
            "qualified": len(qualified), "min_sessions": MIN_SESS,
        }

        # ─── профиль активности: по часам суток (0-23) + по дням недели (1=Пн..7=Вс) ───
        # tz='local' → профиль по местному времени станций (сдвиг на часовой пояс).
        hourly_raw = await self.a.charge_sessions(f_cur, "hour", with_totals=False, tz=tz)
        hmap: dict[int, dict] = {}
        for l in hourly_raw["lines"]:
            try:
                hmap[int(str(l["label"])[:2])] = l
            except (ValueError, TypeError):
                continue
        hourly = [{"hour": h, "label": f"{h:02d}:00",
                   "sessions": hmap[h]["sessions"] if h in hmap else 0,
                   "amount": hmap[h]["amount"] if h in hmap else 0.0} for h in range(24)]

        wd_raw = await self.a.charge_sessions(f_cur, "weekday", with_totals=False, tz=tz)
        _WD = {1: "Пн", 2: "Вт", 3: "Ср", 4: "Чт", 5: "Пт", 6: "Сб", 7: "Вс"}
        wdm: dict[int, dict] = {}
        for l in wd_raw["lines"]:
            try:
                wdm[int(float(l["label"]))] = l
            except (ValueError, TypeError):
                continue
        wd_days = [{"weekday": w, "label": _WD[w],
                    "amount": wdm[w]["amount"] if w in wdm else 0.0,
                    "sessions": wdm[w]["sessions"] if w in wdm else 0,
                    "energy_kwh": wdm[w]["energy_kwh"] if w in wdm else 0.0} for w in range(1, 8)]
        _nz = [x for x in wd_days if x["amount"] > 0]
        weekday = {
            "days": wd_days,
            "best": max(_nz, key=lambda x: x["amount"])["weekday"] if _nz else None,
            "worst": min(_nz, key=lambda x: x["amount"])["weekday"] if _nz else None,
        }

        # ─── состояние сети: где не работает и где лежат деньги ───
        # Эти блоки отвечают не «сколько заработали», а «что с активом»:
        # простаивающие станции, концентрация выручки, ядро клиентов, регионы,
        # сходимость с реестрами. Данные те же, вывод — другой.
        from app.services.charge_unpaid import unpaid_report
        from app.services.overview_insights import (
            client_segments, energy_reconciliation, region_extremes,
            revenue_concentration, silent_stations,
        )
        silent = await silent_stations(self.db, company_id, df, dt,
                                       stations=f_cur.station_codes, regions=f_cur.regions)
        concentration = await revenue_concentration(self.db, company_id, df, dt,
                                                    stations=f_cur.station_codes, regions=f_cur.regions)
        segments = await client_segments(self.db, company_id, df, dt,
                                         stations=f_cur.station_codes, regions=f_cur.regions)
        regions_x = await region_extremes(self.db, company_id, df, dt,
                                          stations=f_cur.station_codes, regions=f_cur.regions)
        energy_recon = await energy_reconciliation(self.db, company_id, df, dt,
                                                   stations=f_cur.station_codes, regions=f_cur.regions)
        unpaid = await unpaid_report(self.db, company_id, df.isoformat(), dt.isoformat(), top=1,
                                     stations=f_cur.station_codes, regions=f_cur.regions)

        # Run-rate: линейная экстраполяция темпа на полный месяц. Честна только
        # внутри незакрытого месяца — за прошедший период прогнозировать нечего.
        run_rate = None
        # today — параметр (входит в ключ кэша через cached_report). Иначе run_rate
        # застревал бы на прошлой дате в пределах TTL/версии при переходе через
        # полночь: цифра прогноза «прыгала» бы без действий пользователя.
        today = today or date.today()
        freshness_stmt = select(func.max(ChargeSession.started_at)).where(
            *self.a._cs_conds(
                company_id, df, dt, f_cur.station_codes, f_cur.regions,
            )
        )
        if f_cur.regions:
            freshness_stmt = self.a._apply_region_join(freshness_stmt)
        last_session_at = (await self.db.execute(freshness_stmt)).scalar_one_or_none()
        freshness_ref = min(dt, today)
        data_lag_days = (
            max(0, (freshness_ref - last_session_at.date()).days)
            if last_session_at is not None else None
        )
        if df.year == dt.year and df.month == dt.month and dt >= today:
            days_done = (min(dt, today) - df).days + 1
            days_in_month = (date(df.year + (df.month // 12), df.month % 12 + 1, 1)
                             - date(df.year, df.month, 1)).days
            if 0 < days_done < days_in_month:
                run_rate = {
                    "days_done": days_done, "days_in_month": days_in_month,
                    "projected_revenue": round(tc["amount"] / days_done * days_in_month, 2),
                    "current_revenue": round(tc["amount"], 2),
                }

        network = {
            "silent": {k: v for k, v in silent.items() if k != "stations"},
            "concentration": concentration,
            "segments": segments,
            "regions": regions_x,
            "energy_recon": energy_recon,
            # Дебиторка ЮЛ — деньги между отпуском и счётом. Живёт в «Без оплаты»,
            # но руководителю нужна на первом экране.
            "receivable": {
                "amount": unpaid["totals"]["postpaid"]["amount"],
                "sessions": unpaid["totals"]["postpaid"]["sessions"],
                "kwh": unpaid["totals"]["postpaid"]["kwh"],
                "retail_debt": unpaid["totals"]["debt"]["amount"],
                "retail_debt_sessions": unpaid["totals"]["debt"]["sessions"],
            },
            "run_rate": run_rate,
        }

        # ─── алерты (пороги сети + корпоратив) ───
        alerts: list[dict[str, str]] = []
        if data_lag_days is not None and data_lag_days > 1:
            alerts.append({
                "level": "warn",
                "message": f"Данные загружены по {last_session_at:%d.%m.%Y} — "
                           f"отставание {data_lag_days} дн.",
            })
        # Простой парка — самая крупная потеря, поэтому первым алертом.
        if silent["silent"]:
            alerts.append({
                "level": "warn",
                "message": (f"Молчат {silent['silent']} ЭЗС из {silent['total']} "
                            f"({silent['silent_pct']:.0f}% парка) — ни одной сессии за период"
                            + (f"; из них {silent['never_worked']} не работали никогда"
                               if silent["never_worked"] else "")),
            })
        if vc["success_pct"] < 85:
            alerts.append({"level": "warn",
                           "message": f"Зарядились {vc['success_pct']:.1f}% клиентов — "
                                      f"{vc['visits'] - vc['charged']:,} визитов закончились ничем".replace(",", " ")})
        # Повторные попытки — отдельный сигнал: клиент уехал заряженным, но
        # боролся с оборудованием. В успех он попал, в качество сети — нет.
        if vc["charged"] and vc["retried"] / vc["charged"] > 0.2:
            alerts.append({"level": "warn",
                           "message": f"{vc['retried']:,} клиентов зарядились не с первой попытки "
                                      f"({vc['retried'] / vc['charged'] * 100:.0f}% успешных) — "
                                      f"разбор в «Надёжность → Повторные попытки»".replace(",", " ")})
        if tc["utilization_pct"] < 15:
            alerts.append({"level": "warn",
                           "message": f"Загрузка сети {tc['utilization_pct']:.1f}% — ниже порога безубыточности (15%)"})
        # «Без оплаты» — только по не-постоплатным (розница+аноним): у ЮЛ постоплата,
        # paid_at штатно пуст → не считаем их неоплаченными (иначе ложный алерт).
        # Считаем только заправки с отпуском: попытка без тока — не долг.
        noncorp_sess = seg["retail"]["charged"] + seg["anon"]["charged"]
        noncorp_paid = seg["retail"]["charged_paid"] + seg["anon"]["charged_paid"]
        noncorp_unpaid = noncorp_sess - noncorp_paid
        noncorp_unpaid_pct = round(noncorp_unpaid / noncorp_sess * 100, 1) if noncorp_sess else 0.0
        if noncorp_unpaid > 0 and noncorp_unpaid_pct > 3:
            alerts.append({"level": "warn",
                           "message": f"Без оплаты {noncorp_unpaid} заправок розницы "
                                      f"({noncorp_unpaid_pct:.1f}%)"})

        # Расхождение с эквайрингом. Разрыв между начисленным по сессиям и списанным
        # банком — не погрешность отчёта: там сидят битые строки вроде 10 341 кВт·ч
        # за 11 секунд. Разбор — «Платежи и чеки» → «Сверка с сессиями».
        recon = None
        try:
            from app.services.charge_reconciliation import reconciliation
            recon = await reconciliation(self.db, company_id, df, dt)
            gap, billed = recon["totals"]["gap"], recon["totals"]["amount"]
            broken = next((k for k in recon["kinds"] if k["key"] == "impossible"), None)
            if broken and broken["count"]:
                alerts.append({"level": "warn",
                               "message": f"{broken['count']} сессий противоречат физике "
                                          f"(мощность выше 400 кВт) на {broken['amount']:,.0f} ₽ — "
                                          f"разбор в «Платежи и чеки → Сверка с сессиями»".replace(",", " ")})
            elif billed and abs(gap) / billed > 0.05:
                alerts.append({"level": "warn",
                               "message": f"Начислено по сессиям и списано банком расходятся на "
                                          f"{gap:,.0f} ₽ ({abs(gap) / billed * 100:.1f} %)".replace(",", " ")})
        except Exception:  # noqa: BLE001 — сверка не повод ронять обзор
            recon = None

        # Станции риска — тоже по визитам: станция, где люди уезжают незаряженными,
        # а не где сорвалось касание разъёма.
        v_stations = await visit_success_by_station(
            self.db, company_id, df, dt, f_cur.station_codes, min_visits=MIN_SESS,
            regions=f_cur.regions)
        risky = [s for s in v_stations if s["success_pct"] < 70]
        if risky:
            names = ", ".join(s["label"] for s in sorted(risky, key=lambda s: s["success_pct"])[:3])
            alerts.append({"level": "warn",
                           "message": f"Станции риска (зарядились <70%): {len(risky)} — {names}"})
        alerts.extend(corp.get("alerts", []))

        return {
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
            "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
            "has_baseline": has_prev,
            "compare": compare,
            "period_days": period_days,
            "kpis": kpis,
            "gauges": gauges,
            "trend": trend,
            "shares": shares,
            "stations": stations,
            "hourly": hourly,
            "weekday": weekday,
            # Сверка с эквайрингом — свод, чтобы разрыв был виден на первом экране,
            # а не только в «Платежах». None, если сверка не посчиталась.
            "reconciliation": ({
                "billed": recon["totals"]["amount"],
                "paid": recon["totals"]["paid"],
                "gap": recon["totals"]["gap"],
                "kinds": [{"key": k["key"], "label": k["label"], "count": k["count"],
                           "gap": k["gap"]} for k in recon["kinds"] if k["count"]],
            } if recon else None),
            "corporate": {
                "corp_revenue": round(corp_rev, 2),
                "retail_revenue": round(corp["totals"]["retail_revenue"], 2),
                "discount": corp["totals"]["discount"],
                "discount_pct": corp["totals"]["discount_pct"],
                "active_clients": corp["totals"]["active_clients"],
                "clients": corp["totals"]["clients"],
                "corp_share_pct": corp_share,
                "top_clients": corp["top_clients"],
            },
            "alerts": alerts,
            "network": network,
            "meta": {
                "active_stations": active_cur,
                "ports": int(tc["ports"]),
                "sessions": tc["sessions"],
                "last_session_at": last_session_at.isoformat() if last_session_at else None,
                "data_lag_days": data_lag_days,
                "is_stale": data_lag_days is not None and data_lag_days > 1,
            },
        }

    @cached_report("ezs:station_metrics")
    async def station_metrics(self, company_id: Any, df: date, dt: date,
                              stations: list[str] | None = None,
                              regions: list[str] | None = None) -> dict[str, Any]:
        """Агрегаты сессий по станции (location_id) за период — для раскраски/размера
        точек на карте. Джойн с координатами делает фронт по location_id (= ServiceLocation.id).
        Учитываются только сопоставленные сессии (location_id проставлен при загрузке)."""
        S = ChargeSession
        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        days = (dt - df).days + 1
        stmt = select(
            S.location_id.label("loc"),
            func.count().label("cnt"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy"),
            func.coalesce(func.sum(func.coalesce(S.client_amount, S.amount)), 0).label("amount"),
            func.coalesce(func.sum(S.duration_min), 0).label("dur"),
            func.coalesce(func.sum(case((S.result == "Complete", 1), else_=0)), 0).label("succ"),
            func.count(distinct(S.connector_no)).label("ports"),
        ).where(
            S.company_id == company_id, S.location_id.is_not(None),
            S.started_at.is_not(None), S.started_at >= lo, S.started_at <= hi,
            *session_scope_conds(company_id, stations, regions),
        ).group_by(S.location_id)
        rows = (await self.db.execute(stmt)).all()
        metrics = []
        for r in rows:
            cnt = int(r.cnt)
            ports = int(r.ports or 0)
            port_min = ports * days * 1440
            metrics.append({
                "location_id": r.loc,
                "sessions": cnt,
                "energy_kwh": round(float(r.energy), 1),
                "amount": round(float(r.amount), 2),
                "success_pct": round(int(r.succ) / cnt * 100, 1) if cnt else 0.0,
                "utilization_pct": round(float(r.dur) / port_min * 100, 1) if port_min else 0.0,
            })
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()}, "metrics": metrics}

    async def _dimension_breakdown(self, company_id: Any, df: date, dt: date,
                                   class_expr: str, order: tuple[str, ...],
                                   labels: dict[str, str]) -> list[dict[str, Any]]:
        """Разрез парка ЭЗС по произвольному признаку станции (владелец, скорость…).

        `class_expr` — SQL-выражение класса по `service_locations` (алиас sl.);
        по каждому классу: станций в парке / работают, активные и молчащие за
        период, сессии/энергия/выручка и надёжность по визитам. Считается по
        всему company-скоупу (как карточки обзора). Надёжность — через location_id
        (station_code партнёров/CPO не совпадает — канон CLAUDE.md)."""
        from sqlalchemy import text

        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        park = (await self.db.execute(text(f"""
            select {class_expr} as cls,
                   count(*) as stations,
                   count(*) filter (where sl.operational_status = 'working') as working
            from service_locations sl
            where sl.company_id = :cid and sl.type = 'ev_charging'
              and coalesce(sl.is_test, false) = false
              and coalesce(sl.operational_status, '') <> 'decommissioned'
            group by 1
        """), {"cid": company_id})).mappings().all()
        act = (await self.db.execute(text(f"""
            select {class_expr} as cls,
                   count(*) as sessions,
                   count(distinct cs.location_id) as active,
                   coalesce(sum(cs.energy_kwh), 0) as energy,
                   coalesce(sum(coalesce(cs.client_amount, cs.amount)), 0) as amount
            from charge_sessions cs
            join service_locations sl on sl.id = cs.location_id
            where cs.company_id = :cid
              and cs.started_at >= :lo and cs.started_at <= :hi
            group by 1
        """), {"cid": company_id, "lo": lo, "hi": hi})).mappings().all()
        act_by = {r["cls"]: r for r in act}
        rel = (await self.db.execute(text(f"""
            with v as (
                select visit_key, min(cs.location_id) as loc,
                       bool_or(cs.visit_charged) as charged
                from charge_sessions cs
                where cs.company_id = :cid and cs.visit_key is not null
                  and cs.started_at >= :lo and cs.started_at <= :hi
                group by visit_key
            )
            select {class_expr} as cls,
                   count(*) as visits,
                   count(*) filter (where v.charged) as charged
            from v join service_locations sl on sl.id = v.loc
            group by 1
        """), {"cid": company_id, "lo": lo, "hi": hi})).mappings().all()
        rel_by = {r["cls"]: r for r in rel}

        out = []
        for cls in order:
            p = next((r for r in park if r["cls"] == cls), None)
            a = act_by.get(cls)
            stations_n = int(p["stations"]) if p else 0
            if stations_n == 0 and not a:
                continue
            active = int(a["active"]) if a else 0
            rr = rel_by.get(cls)
            visits = int(rr["visits"]) if rr else 0
            charged = int(rr["charged"]) if rr else 0
            out.append({
                "cls": cls, "label": labels[cls],
                "stations": stations_n,
                "working": int(p["working"]) if p else 0,
                "active": active,
                "silent": max(0, stations_n - active),
                "silent_pct": round((stations_n - active) / stations_n * 100, 1) if stations_n else 0.0,
                "sessions": int(a["sessions"]) if a else 0,
                "energy_kwh": round(float(a["energy"]), 1) if a else 0.0,
                "amount": round(float(a["amount"]), 2) if a else 0.0,
                "visits": visits, "charged": charged,
                "success_pct": round(charged / visits * 100, 1) if visits else 0.0,
            })
        return out

    async def owners_breakdown(self, company_id: Any, df: date, dt: date,
                               stations: list[str] | None = None,
                               regions: list[str] | None = None,
                               tz: str = "msk") -> dict[str, Any]:
        """Разрез парка по владельцу: свои (РусГидро) vs партнёрские (СНК)."""
        from app.services.station_owner import CLASS_LABELS, owner_class_sql
        out = await self._dimension_breakdown(
            company_id, df, dt, owner_class_sql("sl.owner"),
            ("own", "partner", "unknown"), CLASS_LABELS)
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()}, "owners": out}

    async def speed_breakdown(self, company_id: Any, df: date, dt: date,
                              stations: list[str] | None = None,
                              regions: list[str] | None = None) -> dict[str, Any]:
        """Разрез парка по скорости: медленные (AC) vs быстрые (DC)."""
        from app.services.station_speed import SPEED_LABELS, SPEED_ORDER, speed_class_sql
        out = await self._dimension_breakdown(
            company_id, df, dt, speed_class_sql("sl."), SPEED_ORDER, SPEED_LABELS)
        return {"period": {"from": df.isoformat(), "to": dt.isoformat()}, "speed": out}

    async def _dimension_stations(self, company_id: Any, df: date, dt: date, cls: str,
                                  class_expr: str, labels: dict[str, str]) -> dict[str, Any]:
        """Список станций одного класса (владелец/скорость) с их работой за период —
        раскрывается по клику с карточки разреза. Молчащие вперёд (0 сессий сверху)."""
        from sqlalchemy import text

        if cls not in labels:
            cls = "unknown"
        lo = datetime.combine(df, datetime.min.time())
        hi = datetime.combine(dt, datetime.max.time())
        rows = (await self.db.execute(text(f"""
            with sess as (
                select location_id,
                       count(*) as sessions,
                       coalesce(sum(energy_kwh), 0) as energy,
                       coalesce(sum(coalesce(client_amount, amount)), 0) as amount,
                       max(started_at) as last_at
                from charge_sessions
                where company_id = :cid and location_id is not null
                  and started_at >= :lo and started_at <= :hi
                group by location_id
            ),
            vis as (
                select loc, count(*) as visits,
                       count(*) filter (where charged) as charged
                from (
                    select min(location_id) as loc, bool_or(visit_charged) as charged
                    from charge_sessions
                    where company_id = :cid and visit_key is not null
                      and started_at >= :lo and started_at <= :hi
                    group by visit_key
                ) t
                group by loc
            )
            select sl.id, sl.code, sl.name, sl.city, sl.owner, sl.operational_status,
                   coalesce(s.sessions, 0) as sessions,
                   coalesce(s.energy, 0) as energy,
                   coalesce(s.amount, 0) as amount,
                   s.last_at,
                   coalesce(v.visits, 0) as visits,
                   coalesce(v.charged, 0) as charged
            from service_locations sl
            left join sess s on s.location_id = sl.id
            left join vis v on v.loc = sl.id
            where sl.company_id = :cid and sl.type = 'ev_charging'
              and coalesce(sl.is_test, false) = false
              and coalesce(sl.operational_status, '') <> 'decommissioned'
              and ({class_expr}) = :cls
            order by coalesce(s.sessions, 0) asc, sl.name asc
        """), {"cid": company_id, "lo": lo, "hi": hi, "cls": cls})).mappings().all()

        out = []
        for r in rows:
            visits = int(r["visits"])
            charged = int(r["charged"])
            sess_n = int(r["sessions"])
            out.append({
                "id": r["id"], "code": r["code"], "name": r["name"], "city": r["city"],
                "owner": (r["owner"] or "").strip() or None,
                "operational_status": r["operational_status"],
                "sessions": sess_n,
                "energy_kwh": round(float(r["energy"]), 1),
                "amount": round(float(r["amount"]), 2),
                "success_pct": round(charged / visits * 100, 1) if visits else None,
                "last_at": r["last_at"].isoformat() if r["last_at"] else None,
            })
        return {
            "period": {"from": df.isoformat(), "to": dt.isoformat()},
            "cls": cls, "label": labels[cls],
            "total": len(out),
            "active": sum(1 for s in out if s["sessions"] > 0),
            "silent": sum(1 for s in out if s["sessions"] == 0),
            "stations": out,
        }

    async def owner_stations(self, company_id: Any, df: date, dt: date, cls: str) -> dict[str, Any]:
        """Список станций одного владельца (own|partner|unknown) — по клику с карточки."""
        from app.services.station_owner import CLASS_LABELS, owner_class_sql
        return await self._dimension_stations(
            company_id, df, dt, cls, owner_class_sql("sl.owner"), CLASS_LABELS)

    async def speed_stations(self, company_id: Any, df: date, dt: date, cls: str) -> dict[str, Any]:
        """Список станций одной скорости (fast|slow|unknown) — по клику с карточки."""
        from app.services.station_speed import SPEED_LABELS, speed_class_sql
        return await self._dimension_stations(
            company_id, df, dt, cls, speed_class_sql("sl."), SPEED_LABELS)
