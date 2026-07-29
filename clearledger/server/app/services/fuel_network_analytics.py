"""
Аналитика СЕТИ АЗС по наливам: оборудование, актив, клиенты, визиты, инсайты.

Перенос приёмов ЭЗС-контура (`overview_insights`, `station_abcxyz`, `charge_visits`,
`charge_clients`) на топливный грейн. Разница в вопросе, на который отвечают эти
блоки: обычные разрезы говорят, СКОЛЬКО сеть продала, а эти — **где сеть не
работает и где на самом деле лежат деньги**.

  • `pumps`    — загрузка ТРК и пистолетов. Выручка станции без нормировки на
    железо обманывает: АЗС с восемью пистолетами выглядит лидером, а на пистолет
    даёт меньше маленькой. У ГИГ 27 ТРК и 337 пистолетов — экрана про них не было.
  • `silent`   — точки без единого налива за период (станция/ТРК/пистолет). Счётчик
    «активных АЗС» такую дыру не показывает: он считает работавших, а не молчавших.
  • `abc_xyz`  — ABC (вклад в выручку) × XYZ (стабильность спроса) по станциям,
    видам топлива и парам «станция × топливо». Тринадцати станций для ABC мало,
    а пар — под сотню, и на них классификация работает как задумано.
  • `clients`  — карты по частоте покупок + движение базы (новые/вернувшиеся/
    ушедшие). На данных ГИГ 1,6 % карт дают больше половины оборота: это меняет
    приоритет с привлечения на удержание.
  • `visits`   — склейка наливов одной карты на одной станции в один приезд.
    Два бака подряд или налив после мойки — это ОДИН визит, а в отчёте два, и
    средний чек занижен ровно на эту склейку.
  • `insights` — те же находки в виде коротких выводов для шапки «Обзора».

Общий контур с `FuelSalesAnalytics` (тот же WHERE, та же разметка видов оплаты,
те же исключения дублей-аналитики) — берём его методы, а не копируем условия:
иначе два экрана про одни продажи разойдутся в цифрах.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FuelTransaction
from app.services.analytics_cache import cached_report
from app.services.fuel_sales_analytics import CARD, FuelSalesAnalytics

T = FuelTransaction


def _station_title(code: int, names: dict[int, str]) -> str:
    """Имя станции для таблиц: код в скобках — только если его нет в названии.

    У ГИГ станции названы «АЗС №208», и приписка «(208)» повторяла тот же номер
    второй раз в каждой строке. Код нужен там, где название его не содержит
    (безымянные и импортированные точки), — тогда скобки остаются.
    """
    name = names.get(code)
    if not name:
        return f"АЗС {code}"
    return name if str(code) in name else f"{name} ({code})"

# ─── ABC-XYZ: пороги и подписи (те же, что у сети ЭЗС) ────────────────────
ABC_LABELS = {"A": "A — лидеры", "B": "B — середина", "C": "C — хвост"}
XYZ_LABELS = {
    "X": "X — стабильный спрос", "Y": "Y — переменный",
    "Z": "Z — рваный", "—": "— мало данных",
}
CELL_HINT = {
    "AX": "Ядро сети: большой оборот при ровном спросе — держать запас и цену, не ломать.",
    "AY": "Крупные, но с колебаниями — сгладить спрос (цена/промо в провалы).",
    "AZ": "Крупные и рваные — разобрать причину скачков: сезон, оптовик, разовые заезды.",
    "BX": "Крепкий середняк со стабильным спросом — опора выручки.",
    "BY": "Середняк с колебаниями — потенциал роста при выравнивании.",
    "BZ": "Середняк с рваным спросом — точечная работа.",
    "CX": "Малый оборот, но ровный — локальная нужда, держать дёшево.",
    "CY": "Малый и переменный — наблюдать.",
    "CZ": "Хвост с рваным спросом — кандидат на пересмотр ассортимента или режима.",
}

# ─── Клиентские когорты: границы по числу покупок за период ───────────────
# Границы взяты по факту базы ГИГ (19 760 карт): разовые и «ядро» разъезжаются
# на порядок по вкладу, промежуточные группы сливать нельзя — теряется переход
# «случайный → постоянный», ради которого когорты и считают.
CLIENT_BUCKETS: list[tuple[str, str, int, int]] = [
    ("once", "Разовые (1 покупка)", 1, 1),
    ("rare", "Редкие (2–3)", 2, 3),
    ("regular", "Регулярные (4–10)", 4, 10),
    ("frequent", "Частые (11–50)", 11, 50),
    ("core", "Ядро (50+)", 51, 10_000_000),
]

# Порог склейки наливов в визит, мин. У ЭЗС 15 мин (переподключение разъёма);
# на АЗС сюжет другой — второй бак, канистра, доливка после кассы, — и разрыв
# короче: дольше 10 минут на колонке машина не стоит, это уже новый заезд.
VISIT_GAP_MIN = 10


def _full_buckets(df: date, dt: date, bucket: str) -> tuple[str, str, int]:
    """Границы ПОЛНЫХ бакетов периода и их число — знаменатель для μ с нулями.

    Края периода почти всегда неполные: «с 1 апреля» начинается посреди недели, и
    такая неделя даёт половину обычной выручки. Если считать её наравне, разброс
    получает добавку из ниоткуда — на первом же прогоне 11 из 41 позиции уехали в
    AZ («крупные и рваные»), хотя рваности там не было. Поэтому неполные крайние
    бакеты в расчёт стабильности не берём, а нули внутри периода — берём: не
    продавали неделю — это и есть рваный спрос.
    """
    if bucket == "month":
        first = df if df.day == 1 else date(df.year + df.month // 12, df.month % 12 + 1, 1)
        nxt_m = date(dt.year + dt.month // 12, dt.month % 12 + 1, 1)
        last_end = nxt_m - timedelta(days=1)
        last = dt if dt == last_end else (date(dt.year, dt.month, 1) - timedelta(days=1))
        if last < first:
            return "", "", 0
        n = (last.year - first.year) * 12 + (last.month - first.month) + 1
        return first.isoformat(), date(last.year, last.month, 1).isoformat(), n
    first = df if df.weekday() == 0 else df + timedelta(days=7 - df.weekday())
    last_start = dt - timedelta(days=dt.weekday())
    last = last_start if dt.weekday() == 6 else last_start - timedelta(days=7)
    if last < first:
        return "", "", 0
    return first.isoformat(), last.isoformat(), int((last - first).days // 7) + 1


def _xyz(cv: float | None) -> str:
    """Класс стабильности по коэффициенту вариации (σ/μ) — пороги как у ЭЗС."""
    if cv is None:
        return "—"
    if cv <= 0.25:
        return "X"
    if cv <= 0.50:
        return "Y"
    return "Z"


# Меньше стольких бакетов жизни — стабильность не считаем. На трёх точках σ/μ
# показывает случайность, а не спрос, и позиция уезжает в «рваные» ни за что.
MIN_LIFE_BUCKETS = 6

# Порог, с которого движение считается трендом, а не колебанием, — рост или
# падение выручки за период относительно средней.
TREND_PCT = 20.0

# Окно, по которому меряется стабильность, в бакетах. Разброс — характеристика
# ТЕКУЩЕГО режима работы, а не всей истории: у ГИГ станции запускались волнами,
# и на горизонте в полгода ряд 208 · ДТ идёт от 0,1 до 5,5 млн ₽ в неделю. Даже
# после снятия линейного тренда такой разгон даёт CV 0,74 — не потому, что спрос
# рваный, а потому что рост нелинейный. По последним 12 неделям тот же ряд
# укладывается в 0,2–0,3, и класс наконец отвечает на вопрос «предсказуем ли
# спрос сейчас». Тренд за весь период при этом показывается отдельной колонкой.
STAB_WINDOW = {"week": 12, "month": 6}


def _bucket_keys(df: date, dt: date, bucket: str) -> list[str]:
    """Ключи ВСЕХ полных бакетов периода — сетка, на которую ложится ряд позиции.

    Нужна, чтобы отличить «неделю не продавали» (ноль внутри жизни, честная
    рваность) от «позиции ещё не существовало» (ноль до первой продажи, который
    раньше засчитывался как провал спроса).
    """
    b_from, b_to, n = _full_buckets(df, dt, bucket)
    if not n:
        return []
    keys: list[str] = []
    cur = date.fromisoformat(b_from)
    last = date.fromisoformat(b_to)
    while cur <= last:
        keys.append(cur.isoformat())
        if bucket == "month":
            cur = date(cur.year + cur.month // 12, cur.month % 12 + 1, 1)
        else:
            cur = cur + timedelta(days=7)
    return keys


def _stability(by_bucket: dict[str, float], grid: list[str], bucket: str = "week") -> dict[str, Any]:
    """Разброс позиции ОТДЕЛЬНО от её тренда + сам тренд как признак.

    Первый прогон на данных ГИГ отправил 44 позиции из 47 в класс Z, а колонка X
    осталась пустой — это был не рваный спрос, а три дефекта расчёта:

    1. **CV мерил рост, а не нестабильность.** У АЗС 208 · ДТ недельная выручка
       росла с 0,9 до 5,4 млн ₽ (корреляция со временем 0,80) — ряд не «рваный»,
       он растущий. Классический XYZ применим к стационарному ряду, поэтому
       разброс считаем по ОСТАТКАМ линейного тренда: 0,79 → 0,47.
    2. **Нули до подключения станции.** АЗС 207 и 210 начали работать в марте:
       20 бакетов из 29. Недостающие девять добивались нулями — как будто спрос
       падал в ноль, — и CV раздувался до 1,33. Считаем от ПЕРВОЙ продажи;
       нули внутри жизни остаются (не продавали неделю — это и есть рваность).
    3. **Мало данных = Z.** Позиция, прожившая две недели, получала худший класс
       автоматически. Теперь у неё честное «—» и пометка короткой истории.

    Тренд при этом не выбрасывается, а становится собственной колонкой: «растёт
    втрое» — это ответ, а не помеха классификации.
    """
    if not by_bucket or len(grid) < 3:
        return {"cv": None, "life": len(by_bucket), "trend_pct": None,
                "trend": "flat", "short": True}

    # Жизнь позиции — от первой продажи до конца периода; нули внутри остаются.
    first = min(by_bucket)
    live = [b for b in grid if b >= first]
    life_vals = [by_bucket.get(b, 0.0) for b in live]
    if len(life_vals) < MIN_LIFE_BUCKETS or sum(life_vals) <= 0:
        return {"cv": None, "life": len(life_vals), "trend_pct": None,
                "trend": "flat", "short": True}

    # Тренд — по всей жизни позиции (ответ «куда идём»), разброс — по свежему
    # окну (ответ «насколько ровно идём сейчас»).
    trend_pct = _slope_pct(life_vals)
    trend = "up" if trend_pct > TREND_PCT else ("down" if trend_pct < -TREND_PCT else "flat")

    win = STAB_WINDOW.get(bucket, 12)
    vals = life_vals[-win:] if len(life_vals) > win else life_vals
    mu = sum(vals) / len(vals) if vals else 0.0
    if mu <= 0:
        return {"cv": None, "life": len(life_vals), "trend_pct": trend_pct,
                "trend": trend, "short": True}

    n = len(vals)
    xs = list(range(n))
    mx = (n - 1) / 2
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = (sum((x - mx) * (v - mu) for x, v in zip(xs, vals)) / sxx) if sxx else 0.0
    resid = [v - (mu + slope * (x - mx)) for x, v in zip(xs, vals)]
    cv = math.sqrt(sum(e * e for e in resid) / n) / mu
    return {"cv": round(cv, 3), "life": len(life_vals), "window": n,
            "trend_pct": trend_pct, "trend": trend, "short": False}


def _slope_pct(vals: list[float]) -> float:
    """Изменение ряда за период в процентах средней — наклон × число шагов."""
    n = len(vals)
    mu = sum(vals) / n if n else 0.0
    if n < 2 or mu <= 0:
        return 0.0
    mx = (n - 1) / 2
    sxx = sum((x - mx) ** 2 for x in range(n))
    if not sxx:
        return 0.0
    slope = sum((x - mx) * (v - mu) for x, v in enumerate(vals)) / sxx
    return round(slope * (n - 1) / mu * 100, 1)



class FuelNetworkAnalytics:
    """Сетевые срезы по наливам. Кешируются версионным кешем компании."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.sales = FuelSalesAnalytics(db)

    async def _base(self, company_id, date_from: date, date_to: date,
                    station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                    segment: str | None = None, channel: str | None = None) -> list:
        """WHERE как у обычных разрезов — цифры обязаны сходиться с «Реализацией»."""
        cls, dups = await self.sales._classification(company_id)
        pay_names = self.sales._pay_filter(cls, segment, channel)
        return self.sales._conds(company_id, date_from, date_to, dups,
                                 station_codes, fuel_codes, pay_names)

    # ─── Оборудование: ТРК и пистолеты ──────────────────────────────────

    @cached_report("fuel:pumps")
    async def pumps(self, company_id, date_from: date, date_to: date,
                    level: str = "nozzle",
                    station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                    segment: str | None = None, channel: str | None = None) -> dict[str, Any]:
        """Загрузка оборудования: наливы/литры/выручка на ТРК или пистолет.

        `level='pos'` — колонка целиком, `'nozzle'` — отдельный пистолет (у него свой
        вид топлива, поэтому именно на этом уровне видно, что «загружен» не пост, а
        один рукав из четырёх).

        Ключевая колонка — не выручка, а **наливов в сутки на единицу**: она
        сравнивает станции разного размера, чего абсолютные цифры не умеют.
        """
        conds = await self._base(company_id, date_from, date_to,
                                 station_codes, fuel_codes, segment, channel)
        keys = [T.station_code, T.pos] + ([T.nozzle] if level == "nozzle" else [])
        rows = (await self.db.execute(
            select(
                *keys,
                func.count().label("fills"),
                func.coalesce(func.sum(T.liters), 0).label("liters"),
                func.coalesce(func.sum(T.amount), 0).label("amount"),
                func.count(distinct(func.date(self.sales._msk()))).label("active_days"),
                func.min(T.dt).label("first_at"),
                func.max(T.dt).label("last_at"),
                func.count(distinct(T.fuel_name)).label("fuels"),
                func.min(T.fuel_name).label("fuel_name"),
            ).where(*conds).group_by(*keys)
        )).all()

        names = await self.sales._station_names(company_id)
        days = max(1, (date_to - date_from).days + 1)
        lines: list[dict[str, Any]] = []
        for r in rows:
            fills = int(r.fills)
            amount = float(r.amount)
            liters = float(r.liters)
            lines.append({
                "station_code": int(r.station_code),
                "station": f"{names.get(int(r.station_code)) or 'АЗС'} ({int(r.station_code)})",
                "pos": int(r.pos) if r.pos is not None else None,
                "nozzle": int(r.nozzle) if level == "nozzle" and r.nozzle is not None else None,
                "fuel_name": r.fuel_name if int(r.fuels or 0) == 1 else None,
                "fuels": int(r.fuels or 0),
                "fills": fills,
                "liters": round(liters, 1),
                "amount": round(amount, 2),
                "avg_fill": round(liters / fills, 2) if fills else 0.0,
                "avg_check": round(amount / fills, 2) if fills else 0.0,
                # Сутки периода, а не «дни с наливами»: простой — это тоже факт
                # работы единицы, и делить на рабочие дни значит его спрятать.
                "fills_per_day": round(fills / days, 2),
                "liters_per_day": round(liters / days, 1),
                "active_days": int(r.active_days or 0),
                "idle_days": days - int(r.active_days or 0),
                "first_at": r.first_at.isoformat() if r.first_at else None,
                "last_at": r.last_at.isoformat() if r.last_at else None,
                "silent": False,
            })

        # Молчащие единицы: были в истории компании, но за период — ни одного налива.
        # Без них список выглядит благополучным: то, чего нет в выборке, не видно.
        hist_keys = [T.station_code, T.pos] + ([T.nozzle] if level == "nozzle" else [])
        hist = (await self.db.execute(
            select(*hist_keys, func.max(T.dt).label("last_at"),
                   func.min(T.fuel_name).label("fuel_name"))
            .where(T.company_id == company_id,
                   T.dt < datetime(date_from.year, date_from.month, date_from.day))
            .group_by(*hist_keys)
        )).all()
        seen = {(l["station_code"], l["pos"], l["nozzle"]) for l in lines}
        for r in hist:
            key = (int(r.station_code),
                   int(r.pos) if r.pos is not None else None,
                   int(r.nozzle) if level == "nozzle" and r.nozzle is not None else None)
            if key in seen:
                continue
            if station_codes and key[0] not in station_codes:
                continue
            lines.append({
                "station_code": key[0],
                "station": f"{names.get(key[0]) or 'АЗС'} ({key[0]})",
                "pos": key[1], "nozzle": key[2],
                "fuel_name": r.fuel_name, "fuels": 1,
                "fills": 0, "liters": 0.0, "amount": 0.0,
                "avg_fill": 0.0, "avg_check": 0.0,
                "fills_per_day": 0.0, "liters_per_day": 0.0,
                "active_days": 0, "idle_days": days,
                "first_at": None,
                "last_at": r.last_at.isoformat() if r.last_at else None,
                "silent": True,
            })

        total_amount = sum(l["amount"] for l in lines)
        by_station: dict[int, float] = {}
        for l in lines:
            by_station[l["station_code"]] = by_station.get(l["station_code"], 0.0) + l["amount"]
        for l in lines:
            st = by_station.get(l["station_code"], 0.0)
            l["share_pct"] = round(l["amount"] / total_amount * 100, 2) if total_amount else 0.0
            # Доля внутри своей станции — на неё и смотрят: перекос между рукавами
            # одной АЗС решается перевешиванием цен и указателей, а не инвестициями.
            l["station_share_pct"] = round(l["amount"] / st * 100, 2) if st else 0.0
        lines.sort(key=lambda x: (-x["fills_per_day"], -x["amount"]))

        active = [l for l in lines if not l["silent"]]
        per_day = sorted(l["fills_per_day"] for l in active)
        median = per_day[len(per_day) // 2] if per_day else 0.0
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "level": level,
            "days": days,
            "lines": lines,
            "totals": {
                "units": len(lines),
                "active": len(active),
                "silent": len(lines) - len(active),
                "stations": len({l["station_code"] for l in lines}),
                "fills": sum(l["fills"] for l in lines),
                "liters": round(sum(l["liters"] for l in lines), 1),
                "amount": round(total_amount, 2),
                "median_fills_per_day": round(float(median), 2),
                "top_fills_per_day": round(active[0]["fills_per_day"], 2) if active else 0.0,
            },
        }

    # ─── Молчащие точки ─────────────────────────────────────────────────

    @cached_report("fuel:silent")
    async def silent(self, company_id, date_from: date, date_to: date,
                     fuel_codes: tuple[int, ...] = ()) -> dict[str, Any]:
        """Станции, ТРК и пистолеты без единого налива за период (но с историей).

        Отдельно от `pumps`, потому что вопрос другой: не «кто сколько отпустил»,
        а «что стоит». Ответ нужен коротким списком, а не строкой в таблице на 337 позиций.

        С выбранным видом топлива вопрос сужается до «кто перестал отпускать ИМЕННО
        этот продукт»: пистолет под ДТ может молчать при живой станции, и увидеть это
        можно только так.
        """
        start = datetime(date_from.year, date_from.month, date_from.day)
        end = datetime(date_to.year, date_to.month, date_to.day, 23, 59, 59)
        fuel_cond = [T.fuel_code.in_(fuel_codes)] if fuel_codes else []

        async def _agg(keys: list) -> tuple[dict, dict]:
            hist = {tuple(r[:len(keys)]): r.last_at for r in (await self.db.execute(
                select(*keys, func.max(T.dt).label("last_at"))
                .where(T.company_id == company_id, T.dt < end, *fuel_cond).group_by(*keys)
            )).all()}
            live = {tuple(r[:len(keys)]) for r in (await self.db.execute(
                select(*keys).where(T.company_id == company_id, T.dt >= start, T.dt <= end,
                                    *fuel_cond)
                .group_by(*keys)
            )).all()}
            return hist, live

        names = await self.sales._station_names(company_id)
        out: dict[str, list[dict[str, Any]]] = {}
        for kind, keys in (("stations", [T.station_code]),
                           ("pumps", [T.station_code, T.pos]),
                           ("nozzles", [T.station_code, T.pos, T.nozzle])):
            hist, live = await _agg(keys)
            rows = []
            for key, last_at in hist.items():
                if key in live:
                    continue
                code = int(key[0])
                rows.append({
                    "station_code": code,
                    "station": f"{names.get(code) or 'АЗС'} ({code})",
                    "pos": int(key[1]) if len(key) > 1 and key[1] is not None else None,
                    "nozzle": int(key[2]) if len(key) > 2 and key[2] is not None else None,
                    "last_at": last_at.isoformat() if last_at else None,
                    "days_idle": (date_to - last_at.date()).days if last_at else None,
                })
            rows.sort(key=lambda x: -(x["days_idle"] or 0))
            out[kind] = rows
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            **out,
            "counts": {k: len(v) for k, v in out.items()},
        }

    # ─── ABC-XYZ ────────────────────────────────────────────────────────

    @cached_report("fuel:abcxyz:v2")
    async def abc_xyz(self, company_id, date_from: date, date_to: date,
                      dimension: str = "station_fuel", bucket: str = "week",
                      measure: str = "amount",
                      station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                      segment: str | None = None, channel: str | None = None) -> dict[str, Any]:
        """ABC (вклад) × XYZ (стабильность) по станциям / топливу / парам.

        Единица классификации у топливной сети — не станция: тринадцать объектов
        на три класса делятся плохо, а пара «станция × вид топлива» даёт под сотню
        позиций, и хвост CZ становится осмысленным (какое топливо на какой АЗС
        возить перестали). `dimension` оставляет обе оптики.
        """
        conds = await self._base(company_id, date_from, date_to,
                                 station_codes, fuel_codes, segment, channel)
        msk = self.sales._msk()
        if dimension == "station":
            keys = [T.station_code]
        elif dimension == "fuel":
            keys = [func.coalesce(T.fuel_name, "—")]
        else:
            keys = [T.station_code, func.coalesce(T.fuel_name, "—")]
        val = func.sum(T.amount if measure == "amount" else T.liters)
        bkt = func.to_char(func.date_trunc("week" if bucket == "week" else "month", msk),
                           "YYYY-MM-DD")

        rows = (await self.db.execute(
            select(*keys, func.count().label("fills"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"),
                   func.coalesce(func.sum(T.liters), 0).label("liters"),
                   func.count(distinct(CARD)).label("cards"))
            .where(*conds).group_by(*keys)
        )).all()
        bkt_rows = (await self.db.execute(
            select(*keys, bkt.label("b"), func.coalesce(val, 0).label("v"))
            .where(*conds).group_by(*keys, bkt)
        )).all()

        names = await self.sales._station_names(company_id)

        def _key(r) -> tuple:
            return tuple(r[:len(keys)])

        def _label(k: tuple) -> str:
            if dimension == "fuel":
                return str(k[0])
            code = int(k[0])
            st = _station_title(code, names)
            return st if dimension == "station" else f"{st} · {k[1]}"

        b_from, b_to, n_b = _full_buckets(date_from, date_to, bucket)
        grid = _bucket_keys(date_from, date_to, bucket)
        # ХВОСТ ПЕРИОДА БЕЗ ДАННЫХ. Период выбирает человек («с 1 января»), а
        # данные приезжают из STS с задержкой: на 29 июля последняя операция была
        # 11-го. Две пустые недели на конце попадали в расчёт как провал спроса —
        # СРАЗУ У ВСЕХ позиций, и вся матрица уезжала в «рваные». Считаем по
        # бакетам, в которых у СЕТИ есть хоть одна операция; чего ещё не было,
        # того не было ни у кого.
        live_grid = {str(r.b) for r in bkt_rows}
        last_data = max(live_grid) if live_grid else None
        if last_data:
            grid = [b for b in grid if b <= last_data]
        # Ряд позиции — упорядоченный по бакетам: без порядка нельзя ни отделить
        # тренд от разброса, ни понять, с какого момента позиция вообще жила.
        series: dict[tuple, dict[str, float]] = {}
        for r in bkt_rows:
            # В расчёт стабильности — только полные бакеты; в выручку и ABC —
            # весь период, как его выбрал пользователь.
            if n_b and b_from <= str(r.b) <= b_to:
                series.setdefault(_key(r), {})[str(r.b)] = float(r.v or 0)

        items = []
        for r in rows:
            k = _key(r)
            amount = float(r.amount)
            liters = float(r.liters)
            m = amount if measure == "amount" else liters
            by_bucket = series.get(k, {})
            stab = _stability(by_bucket, grid, bucket)
            items.append({
                "key": "|".join(str(x) for x in k),
                "label": _label(k),
                "station_code": int(k[0]) if dimension != "fuel" else None,
                # Станция и вид топлива — РАЗДЕЛЬНО, а не одной строкой «АЗС · ДТ»:
                # это две сущности, по каждой сортируют и сравнивают. `label`
                # остаётся для заголовков и выгрузки.
                "station_label": (_station_title(int(k[0]), names)
                                  if dimension != "fuel" else None),
                "fuel_name": str(k[1]) if dimension == "station_fuel" else (
                    str(k[0]) if dimension == "fuel" else None),
                "measure": round(m, 2),
                "amount": round(amount, 2), "liters": round(liters, 1),
                "fills": int(r.fills), "cards": int(r.cards or 0),
                "active_buckets": len(by_bucket),
                # Бакетов ЖИЗНИ позиции (от первой продажи), а не бакетов периода:
                # по ним и считается стабильность.
                "life_buckets": stab["life"],
                "stab_window": stab.get("window"),
                "cv": stab["cv"],
                "xyz": _xyz(stab["cv"]),
                # Тренд — отдельный признак, а не часть разброса (см. _stability).
                "trend_pct": stab["trend_pct"],
                "trend": stab["trend"],
                "short_history": stab["short"],
            })

        items.sort(key=lambda x: -x["measure"])
        total = sum(i["measure"] for i in items)
        cum = 0.0
        for i in items:
            cum += i["measure"]
            i["share_pct"] = round(i["measure"] / total * 100, 2) if total else 0.0
            i["cum_share_pct"] = round(cum / total * 100, 2) if total else 0.0
            i["abc"] = "A" if i["cum_share_pct"] <= 80 else ("B" if i["cum_share_pct"] <= 95 else "C")
            i["class"] = i["abc"] + (i["xyz"] if i["xyz"] != "—" else "")
            i["hint"] = CELL_HINT.get(i["abc"] + i["xyz"], "")

        matrix: dict[str, dict[str, Any]] = {}
        for i in items:
            cell = i["abc"] + i["xyz"]
            m = matrix.setdefault(cell, {"cell": cell, "count": 0, "measure": 0.0,
                                         "hint": CELL_HINT.get(cell, "")})
            m["count"] += 1
            m["measure"] = round(m["measure"] + i["measure"], 2)
        for m in matrix.values():
            m["share_pct"] = round(m["measure"] / total * 100, 2) if total else 0.0

        # Квинтили — та же концентрация, но без классов: короткий ответ на вопрос
        # «сколько даёт верхушка и сколько тянет хвост».
        quintiles = []
        if items:
            size = max(1, len(items) // 5)
            for q in range(5):
                chunk = items[q * size: (q + 1) * size] if q < 4 else items[4 * size:]
                if not chunk:
                    continue
                s = sum(c["measure"] for c in chunk)
                # Номер группы проставляем самой позиции: иначе фронт делил бы
                # список второй раз, своей копией правила, и «Верхние 20 %» в
                # карточке разошлись бы с «Верхними 20 %» в таблице.
                for c in chunk:
                    c["quintile"] = q + 1
                quintiles.append({
                    "quintile": q + 1, "count": len(chunk),
                    "measure": round(s, 2),
                    "share_pct": round(s / total * 100, 2) if total else 0.0,
                })

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "dimension": dimension, "bucket": bucket, "measure_kind": measure,
            "buckets": len(grid),
            # До какого бакета в сети реально есть операции: если период шире,
            # экран обязан это сказать, иначе цифры выглядят провалом продаж.
            "data_through": last_data,
            "period_buckets": n_b,
            "items": items,
            "matrix": sorted(matrix.values(), key=lambda m: m["cell"]),
            "quintiles": quintiles,
            "labels": {"abc": ABC_LABELS, "xyz": XYZ_LABELS},
            "totals": {"count": len(items), "measure": round(total, 2)},
        }

    # ─── Клиенты: когорты и движение базы ───────────────────────────────

    @cached_report("fuel:clients")
    async def clients(self, company_id, date_from: date, date_to: date,
                      station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                      segment: str | None = None, channel: str | None = None) -> dict[str, Any]:
        """Карты по частоте покупок + приток и отток базы.

        Считается по картам: наличные (карты нет) в клиентские метрики не входят —
        человека без идентификатора нельзя ни удержать, ни потерять, и смешивать
        его с картовыми когортами значит размыть обе цифры.
        """
        cls, dups = await self.sales._classification(company_id)
        pay_names = self.sales._pay_filter(cls, segment, channel)
        conds = self.sales._conds(company_id, date_from, date_to, dups,
                                  station_codes, fuel_codes, pay_names)
        valid = CARD.is_not(None) & func.trim(T.card).op("!~")("^0+$")
        rows = (await self.db.execute(
            select(CARD.label("card"), func.count().label("fills"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"),
                   func.coalesce(func.sum(T.liters), 0).label("liters"),
                   func.count(distinct(T.station_code)).label("stations"),
                   func.min(T.dt).label("first_at"), func.max(T.dt).label("last_at"))
            .where(*conds, valid).group_by(CARD)
        )).all()

        buckets = {code: {"code": code, "label": label, "cards": 0, "fills": 0,
                          "amount": 0.0, "liters": 0.0}
                   for code, label, _lo, _hi in CLIENT_BUCKETS}
        for r in rows:
            f = int(r.fills)
            for code, _label, lo, hi in CLIENT_BUCKETS:
                if lo <= f <= hi:
                    b = buckets[code]
                    b["cards"] += 1
                    b["fills"] += f
                    b["amount"] += float(r.amount)
                    b["liters"] += float(r.liters)
                    break
        total_amount = sum(b["amount"] for b in buckets.values())
        total_cards = sum(b["cards"] for b in buckets.values())
        cohorts = []
        for code, label, _lo, _hi in CLIENT_BUCKETS:
            b = buckets[code]
            cohorts.append({
                **b,
                "amount": round(b["amount"], 2), "liters": round(b["liters"], 1),
                "cards_pct": round(b["cards"] / total_cards * 100, 2) if total_cards else 0.0,
                "amount_pct": round(b["amount"] / total_amount * 100, 2) if total_amount else 0.0,
                "avg_check": round(b["amount"] / b["fills"], 2) if b["fills"] else 0.0,
                "avg_card": round(b["amount"] / b["cards"], 2) if b["cards"] else 0.0,
            })

        # Движение базы. «Новая» — та, у которой ПЕРВЫЙ налив вообще пришёлся на
        # период; иначе новичком выглядел бы любой, кто просто не заезжал полгода.
        prev_len = (date_to - date_from).days + 1
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=prev_len - 1)
        first_seen = dict((await self.db.execute(
            select(CARD, func.min(T.dt)).where(T.company_id == company_id, valid).group_by(CARD)
        )).all())
        prev_conds = self.sales._conds(company_id, prev_from, prev_to, dups,
                                       station_codes, fuel_codes, pay_names)
        prev_cards = {r[0] for r in (await self.db.execute(
            select(CARD).where(*prev_conds, valid).group_by(CARD)
        )).all()}
        cur_cards = {r.card for r in rows}
        # `dt` в базе с таймзоной, границы периода — наивные: сравниваем по дате,
        # иначе offset-aware и offset-naive не сравнить вовсе.
        new_cards = {c for c in cur_cards
                     if (first_seen.get(c) is not None
                         and first_seen[c].date() >= date_from)}
        returning = cur_cards - new_cards
        churned = prev_cards - cur_cards
        by_card = {r.card: r for r in rows}
        movement = {
            "active": len(cur_cards),
            "new": len(new_cards),
            "returning": len(returning),
            "churned": len(churned),
            "prev_active": len(prev_cards),
            "retention_pct": round(len(prev_cards & cur_cards) / len(prev_cards) * 100, 2)
            if prev_cards else None,
            "new_amount": round(sum(float(by_card[c].amount) for c in new_cards), 2),
            "returning_amount": round(sum(float(by_card[c].amount) for c in returning), 2),
            "prev_period": {"from": prev_from.isoformat(), "to": prev_to.isoformat()},
        }

        # Концентрация базы — ответ, не зависящий от границ когорт: их пороги
        # («50+ покупок») привязаны к длине периода, и на квартале «ядро» тает,
        # хотя деньги по-прежнему лежат у верхушки. Доли считаем по обороту.
        ordered = sorted((float(r.amount) for r in rows), reverse=True)
        def _head_share(pct: float) -> float:
            n = max(1, int(len(ordered) * pct / 100))
            return round(sum(ordered[:n]) / total_amount * 100, 2) if total_amount else 0.0
        concentration = {
            "top1_pct": _head_share(1), "top5_pct": _head_share(5),
            "top10_pct": _head_share(10), "top20_pct": _head_share(20),
            "cards_top10": max(1, int(len(ordered) * 0.1)),
        }

        # Что берут клиенты. Разные виды топлива — разные клиенты: ДТ возят
        # перевозчики по ведомостям, АИ-95 льют физлица с банковских карт. Без
        # этого разреза когорты не отвечают на вопрос «кого мы теряем».
        # Выражение группировки — ОДИН объект на select и group_by: два одинаковых
        # `coalesce(...)` дают разные bind-параметры, и Postgres не признаёт их
        # тем же выражением («must appear in the GROUP BY clause»).
        fuel_col = func.coalesce(T.fuel_name, "—")
        by_fuel = (await self.db.execute(
            select(fuel_col.label("fuel"),
                   func.count(distinct(CARD)).label("cards"),
                   func.count().label("fills"),
                   func.coalesce(func.sum(T.amount), 0).label("amount"),
                   func.coalesce(func.sum(T.liters), 0).label("liters"))
            .where(*conds, valid).group_by(fuel_col)
        )).all()
        fuels = sorted([{
            "fuel_name": str(r.fuel),
            "cards": int(r.cards or 0), "fills": int(r.fills),
            "amount": round(float(r.amount), 2), "liters": round(float(r.liters), 1),
            "avg_check": round(float(r.amount) / int(r.fills), 2) if r.fills else 0.0,
        } for r in by_fuel], key=lambda x: -x["amount"])
        for f in fuels:
            f["amount_pct"] = round(f["amount"] / total_amount * 100, 2) if total_amount else 0.0

        top = sorted(rows, key=lambda r: -float(r.amount))[:50]
        top_cards = [{
            "card": r.card,
            "fills": int(r.fills), "amount": round(float(r.amount), 2),
            "liters": round(float(r.liters), 1),
            "stations": int(r.stations or 0),
            "avg_check": round(float(r.amount) / int(r.fills), 2) if r.fills else 0.0,
            "first_at": r.first_at.isoformat() if r.first_at else None,
            "last_at": r.last_at.isoformat() if r.last_at else None,
            "is_new": r.card in new_cards,
        } for r in top]

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "cohorts": cohorts,
            "by_fuel": fuels,
            "concentration": concentration,
            "movement": movement,
            "top_cards": top_cards,
            "totals": {"cards": total_cards, "amount": round(total_amount, 2),
                       "fills": sum(b["fills"] for b in buckets.values())},
        }

    # ─── Визиты ─────────────────────────────────────────────────────────

    @cached_report("fuel:visits")
    async def visits(self, company_id, date_from: date, date_to: date,
                     gap_min: int = VISIT_GAP_MIN,
                     station_codes: tuple[int, ...] = (), fuel_codes: tuple[int, ...] = (),
                     segment: str | None = None, channel: str | None = None) -> dict[str, Any]:
        """Приезд вместо налива: склейка соседних наливов одной карты на одной АЗС.

        Считается на лету оконными функциями, без материализации (у ЭЗС визит
        хранится в колонках сессии): на топливе визит нужен только в отчёте, а
        период запроса — месяц-квартал, и полный пересчёт по компании обошёлся бы
        дороже самого ответа.
        """
        conds = await self._base(company_id, date_from, date_to,
                                 station_codes, fuel_codes, segment, channel)
        valid = CARD.is_not(None) & func.trim(T.card).op("!~")("^0+$")
        base = (
            select(
                CARD.label("card"), T.station_code.label("st"), T.dt.label("dt"),
                T.amount.label("amount"), T.liters.label("liters"),
                func.coalesce(T.fuel_name, "—").label("fuel"),
                func.lag(T.dt).over(partition_by=[CARD, T.station_code],
                                    order_by=[T.dt, T.ext_id]).label("prev_dt"),
            ).where(*conds, valid)
        ).subquery("b")
        # Новый визит: первый налив карты на станции либо разрыв больше порога.
        is_new = case(
            (base.c.prev_dt.is_(None), 1),
            (func.extract("epoch", base.c.dt - base.c.prev_dt) / 60.0 > gap_min, 1),
            else_=0,
        )
        grp = select(
            base.c.card, base.c.st, base.c.dt, base.c.amount, base.c.liters, base.c.fuel,
            func.sum(is_new).over(partition_by=[base.c.card, base.c.st],
                                  order_by=[base.c.dt],
                                  rows=(None, 0)).label("vno"),
        ).subquery("g")
        vis = select(
            grp.c.card, grp.c.st, grp.c.vno,
            func.count().label("fills"),
            func.sum(grp.c.amount).label("amount"),
            func.sum(grp.c.liters).label("liters"),
            # Сколько РАЗНЫХ видов топлива в одном приезде: два бака одной машины
            # и заправка «себе + канистра ДТ» — принципиально разные сюжеты.
            func.count(distinct(grp.c.fuel)).label("fuels"),
            func.min(grp.c.fuel).label("fuel"),
        ).group_by(grp.c.card, grp.c.st, grp.c.vno).subquery("v")

        agg = (await self.db.execute(select(
            func.count().label("visits"),
            func.sum(vis.c.fills).label("fills"),
            func.coalesce(func.sum(vis.c.amount), 0).label("amount"),
            func.coalesce(func.sum(vis.c.liters), 0).label("liters"),
            func.count().filter(vis.c.fills > 1).label("multi"),
            func.count().filter(vis.c.fuels > 1).label("multi_fuel"),
        ))).one()
        dist = (await self.db.execute(
            select(vis.c.fills.label("n"), func.count().label("visits"),
                   func.coalesce(func.sum(vis.c.amount), 0).label("amount"))
            .group_by(vis.c.fills).order_by(vis.c.fills)
        )).all()
        by_station = (await self.db.execute(
            select(vis.c.st, func.count().label("visits"),
                   func.count().filter(vis.c.fills > 1).label("multi"),
                   func.coalesce(func.sum(vis.c.amount), 0).label("amount"),
                   func.sum(vis.c.fills).label("fills"))
            .group_by(vis.c.st)
        )).all()

        by_fuel = (await self.db.execute(
            select(vis.c.fuel, func.count().label("visits"),
                   func.coalesce(func.sum(vis.c.amount), 0).label("amount"),
                   func.coalesce(func.sum(vis.c.liters), 0).label("liters"))
            .where(vis.c.fuels == 1).group_by(vis.c.fuel)
        )).all()

        names = await self.sales._station_names(company_id)
        visits_n = int(agg.visits or 0)
        fills_n = int(agg.fills or 0)
        amount = float(agg.amount or 0)
        liters = float(agg.liters or 0)
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "gap_min": gap_min,
            "totals": {
                "visits": visits_n,
                "fills": fills_n,
                "amount": round(amount, 2),
                "liters": round(liters, 1),
                "multi_visits": int(agg.multi or 0),
                "multi_fuel_visits": int(agg.multi_fuel or 0),
                "multi_fuel_pct": round(int(agg.multi_fuel or 0) / visits_n * 100, 2) if visits_n else 0.0,
                "multi_pct": round(int(agg.multi or 0) / visits_n * 100, 2) if visits_n else 0.0,
                "fills_per_visit": round(fills_n / visits_n, 3) if visits_n else 0.0,
                # Ради этой пары цифр всё и считается: чек визита выше чека налива
                # ровно на склейку, и сравнивать с рынком надо именно его.
                "avg_visit_check": round(amount / visits_n, 2) if visits_n else 0.0,
                "avg_fill_check": round(amount / fills_n, 2) if fills_n else 0.0,
                "avg_visit_liters": round(liters / visits_n, 2) if visits_n else 0.0,
            },
            # Однотопливные приезды в разрезе продукта: «чек приезда за ДТ» —
            # то, что сравнивают с конкурентом, а не средняя по всем видам.
            "by_fuel": sorted([{
                "fuel_name": str(f.fuel), "visits": int(f.visits),
                "amount": round(float(f.amount), 2), "liters": round(float(f.liters), 1),
                "avg_visit_check": round(float(f.amount) / int(f.visits), 2) if f.visits else 0.0,
                "avg_visit_liters": round(float(f.liters) / int(f.visits), 2) if f.visits else 0.0,
            } for f in by_fuel], key=lambda x: -x["amount"]),
            "distribution": [{
                "fills": int(d.n), "visits": int(d.visits),
                "amount": round(float(d.amount), 2),
                "share_pct": round(int(d.visits) / visits_n * 100, 2) if visits_n else 0.0,
            } for d in dist],
            "by_station": sorted([{
                "station_code": int(s.st),
                "station": f"{names.get(int(s.st)) or 'АЗС'} ({int(s.st)})",
                "visits": int(s.visits), "fills": int(s.fills or 0),
                "multi": int(s.multi or 0),
                "multi_pct": round(int(s.multi or 0) / int(s.visits) * 100, 2) if s.visits else 0.0,
                "amount": round(float(s.amount), 2),
                "avg_visit_check": round(float(s.amount) / int(s.visits), 2) if s.visits else 0.0,
            } for s in by_station], key=lambda x: -x["amount"]),
        }

    # ─── Инсайты для «Обзора» ───────────────────────────────────────────

    @cached_report("fuel:insights")
    async def insights(self, company_id, date_from: date, date_to: date,
                       fuel_codes: tuple[int, ...] = ()) -> dict[str, Any]:
        """Короткие выводы для шапки обзора: где не работает и где лежат деньги.

        Каждый вывод — уже посчитанная выше цифра, а не новый источник: экран не
        должен спорить с разделом, из которого пришёл.
        """
        out: list[dict[str, Any]] = []

        sil = await self.silent(company_id, date_from, date_to, fuel_codes)
        idle_nozzles = sil["counts"]["nozzles"]
        if idle_nozzles:
            worst = sil["nozzles"][0]
            out.append({
                "key": "silent",
                "tone": "warning",
                "title": f"Молчат {idle_nozzles} пистолетов",
                "text": f"Ни одного налива за период. Дольше всех — {worst['station']}, "
                        f"ТРК {worst['pos']}/{worst['nozzle']}: "
                        f"{worst['days_idle']} дней с последней операции.",
                "link": {"sub": "pumps"},
            })

        pumps = await self.pumps(company_id, date_from, date_to, level="nozzle",
                                 fuel_codes=fuel_codes)
        med = pumps["totals"]["median_fills_per_day"]
        top = pumps["totals"]["top_fills_per_day"]
        if med and top and top > med * 2:
            out.append({
                "key": "pump_spread",
                "tone": "info",
                "title": f"Разброс загрузки пистолетов — {round(top / med, 1)}×",
                "text": f"Лучший рукав отпускает {top} наливов в сутки при медиане {med}. "
                        f"Разница внутри одной станции решается ценником и указателями, "
                        f"а не вложениями в железо.",
                "link": {"sub": "pumps"},
            })

        abc = await self.abc_xyz(company_id, date_from, date_to, dimension="station_fuel",
                                 fuel_codes=fuel_codes)
        q = abc["quintiles"]
        if len(q) >= 5:
            out.append({
                "key": "concentration",
                "tone": "info",
                "title": f"Верхние 20 % позиций дают {q[0]['share_pct']} % выручки",
                "text": f"Нижние 20 % — {q[-1]['share_pct']} %. Средняя по сети такие "
                        f"полюса смешивает: решения принимаются по верхушке и по хвосту, "
                        f"а не по среднему.",
                "link": {"sub": "abcxyz"},
            })
        cz = next((m for m in abc["matrix"] if m["cell"] == "CZ"), None)
        if cz and cz["count"]:
            out.append({
                "key": "cz",
                "tone": "warning",
                "title": f"{cz['count']} позиций в хвосте с рваным спросом",
                "text": f"Класс CZ: {cz['share_pct']} % выручки. Кандидаты на пересмотр "
                        f"ассортимента или режима работы.",
                "link": {"sub": "abcxyz"},
            })

        cl = await self.clients(company_id, date_from, date_to, fuel_codes=fuel_codes)
        conc = cl.get("concentration") or {}
        once = next((c for c in cl["cohorts"] if c["code"] == "once"), None)
        if conc.get("top10_pct"):
            out.append({
                "key": "core_clients",
                "tone": "success",
                "title": f"Верхние 10 % карт дают {conc['top10_pct']} % выручки",
                "text": f"Это {conc['cards_top10']} карт из {cl['totals']['cards']}; "
                        f"на верхний процент приходится {conc['top1_pct']} %. "
                        + (f"Разовых карт {once['cards']} — они приносят {once['amount_pct']} %. "
                           if once else "")
                        + "Приоритет — удержание, а не привлечение.",
                "link": {"sub": "clients"},
            })
        mv = cl["movement"]
        if mv["prev_active"] and mv["churned"]:
            out.append({
                "key": "churn",
                "tone": "warning" if (mv["retention_pct"] or 100) < 60 else "info",
                "title": f"Не вернулись {mv['churned']} карт",
                "text": f"Из {mv['prev_active']} активных в прошлом периоде вернулись "
                        f"{mv['retention_pct']} %. Новых карт за период — {mv['new']}.",
                "link": {"sub": "clients"},
            })

        vis = await self.visits(company_id, date_from, date_to, fuel_codes=fuel_codes)
        t = vis["totals"]
        if t["multi_visits"]:
            out.append({
                "key": "visits",
                "tone": "info",
                "title": f"Чек приезда — {round(t['avg_visit_check'])} ₽ против "
                         f"{round(t['avg_fill_check'])} ₽ по наливам",
                "text": f"{t['multi_pct']} % приездов состоят из нескольких наливов "
                        f"(второй бак, канистра, доливка). По наливам средний чек занижен.",
                "link": {"sub": "visits"},
            })

        return {"period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
                "insights": out}
