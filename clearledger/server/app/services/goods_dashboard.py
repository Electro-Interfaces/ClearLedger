"""
Агрегатор дашборда «Обзор магазина» (сопутка + общепит) — аналог fuel_dashboard,
но источник = DataEntry(layer='clean', doc_type_id='retail_sale_sidegoods') из
канала ЦБ ЭЛСИ.АЗК. Данные лежат в meta (JSONB): meta.Секции.продажа_сопутка /
продажа_общепит (строки SKU + суммы + НДС), meta.Секции.оплаты, meta.Смена (станция/дата).

KPI на имеющихся данных (продажи): выручка (всего/сопутка/общепит), НДС, число
позиций/единиц, число смен, средний чек ≈, структура категорий, оплаты (нал/безнал),
дневная динамика, разрез по АЗС, Δ% к прошлому периоду.

Для общепита экономика собирается отдельным мостом: выручка, возвраты, НДС,
фактическая/оценочная стоимость ингредиентов, списания и недостачи.
"""
import calendar
import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DataEntry, CbNomenclature, CbRef, CbBarcode, StockOnHand,
    CbInventoryDoc, CbMovementDoc, StorePlan, StoreStockBalance, TobaccoMrc,
    StoreCheque, StoreRecipeVersion,
)

# секция meta → категория UI
_SECTIONS = (("продажа_сопутка", "Сопутка"), ("продажа_общепит", "Общепит"))

# Минимальное покрытие ТТК для «costed»-блюда (OB-3/К-5): доля ингредиентов с
# известной закупочной себестоимостью. При меньшем покрытии food-cost занижен
# (считается по части состава) → блюдо «предварительное», вне сводной маржи.
_TTK_COVERAGE_MIN = 0.9


def _num(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _week_of(value: str | date) -> str:
    day = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
    return (day - timedelta(days=day.weekday())).isoformat()


def _edge_cost_by_dish(meta: dict) -> dict[str, dict]:
    """Себестоимость смены из CostEvidence, без пересчёта по текущей ТТК."""
    evidence = ((meta.get("Edge") or {}).get("CostEvidence") or {})
    production: dict[str, float] = defaultdict(float)
    for row in evidence.get("production") or []:
        dish = str(row.get("dish_uuid") or "")
        if dish:
            production[dish] += _num(row.get("quantity_millis")) / 1000
    result: dict[str, dict] = defaultdict(
        lambda: {"cost": 0.0, "exact": 0.0, "estimated": 0.0,
                 "qty": 0.0, "ingredients": 0})
    for row in evidence.get("ingredients") or []:
        dish = str(row.get("dish_uuid") or "")
        if not dish:
            continue
        amount = _num(row.get("required_amount_micros")) / 1_000_000
        item = result[dish]
        item["cost"] += amount
        item["ingredients"] += 1
        if row.get("status") == "known":
            item["exact"] += amount
        else:
            item["estimated"] += amount
    for dish, item in result.items():
        item["qty"] = production.get(dish, 0.0)
        item["status"] = "exact" if item["estimated"] == 0 and item["ingredients"] else "estimate"
    return dict(result)


def _catering_sale_facts(metas: list[dict]) -> dict[str, dict]:
    facts: dict[str, dict] = defaultdict(lambda: {
        "qty": 0.0, "gross": 0.0, "vat": 0.0, "returns": 0.0,
        "return_vat": 0.0, "vat_missing": 0, "daily": defaultdict(
            lambda: {"qty": 0.0, "rev": 0.0}),
        "ings": defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "known": False}),
        "edge_cost": 0.0, "edge_exact": 0.0, "edge_estimated": 0.0,
        "edge_statuses": set(),
    })
    for meta in metas:
        day = _day(meta.get("Смена") or {})
        section = ((meta.get("Секции") or {}).get("продажа_общепит") or {})
        for line in section.get("строки") or []:
            dish = str(line.get("Номенклатура") or "")
            if not dish:
                continue
            fact = facts[dish]
            qty, gross = _num(line.get("Количество")), _num(line.get("Сумма"))
            fact["qty"] += qty
            fact["gross"] += gross
            if line.get("СуммаНДС") is None:
                fact["vat_missing"] += 1
            else:
                fact["vat"] += _num(line.get("СуммаНДС"))
            fact["daily"][day]["qty"] += qty
            fact["daily"][day]["rev"] += gross
            for ingredient in line.get("Ингредиенты") or []:
                item_uuid = str(ingredient.get("Номенклатура") or "")
                if item_uuid:
                    fact["ings"][item_uuid]["qty"] += _num(ingredient.get("Количество"))
        for dish, cost in _edge_cost_by_dish(meta).items():
            fact = facts[dish]
            fact["edge_cost"] += cost["cost"]
            fact["edge_exact"] += cost["exact"]
            fact["edge_estimated"] += cost["estimated"]
            fact["edge_statuses"].add(cost["status"])

    for meta in metas:
        for line in (((meta.get("Секции") or {}).get("возвраты") or {}).get("строки") or []):
            dish = str(line.get("Номенклатура") or "")
            fact = facts[dish]
            fact["returns"] += abs(_num(line.get("Сумма")))
            if line.get("СуммаНДС") is None:
                fact["vat_missing"] += 1
            else:
                fact["return_vat"] += abs(_num(line.get("СуммаНДС")))
    return facts


def _merge_customer_returns(facts: dict[str, dict], returned: dict[str, dict]) -> None:
    for dish, value in returned.items():
        facts[dish]["returns"] += value.get("returns", 0)
        facts[dish]["return_vat"] += value.get("return_vat", 0)
        facts[dish]["vat_missing"] += value.get("vat_missing", 0)


def _day(smena: dict) -> str:
    """Дата смены для группировки — по закрытию (фолбэк — открытие)."""
    return str(smena.get("Закрытие") or smena.get("Открытие") or "")[:10]


def _warehouse_in_stations(code: str | None, stations: list[str] | None) -> bool:
    if not stations:
        return True
    value = str(code or "").strip()
    return any(value == station or value.startswith(f"{station}000") for station in stations)


def _station_of_warehouse(code: str | None, stations: list[str]) -> str | None:
    """Определить АЗС по коду её склада, предпочитая самый длинный код станции."""
    matches = [station for station in stations if _warehouse_in_stations(code, [station])]
    return max(matches, key=len) if matches else None


def _поток_смены(station: str, internal_no, чеки: dict, заправки: dict) -> dict:
    """Чеки с товаром, заправки и конверсия магазина за смену.

    Ключ — внутренний номер смены кассы: печатный строится из даты открытия и на
    смене через полночь указывает на вчера. Смена без внутреннего номера (старая
    выгрузка 1С) потока не получает — врать нулём здесь нельзя, ноль читается
    как «никто не купил».
    """
    try:
        код, номер = int(station), int(internal_no or 0)
    except (TypeError, ValueError):
        код, номер = 0, 0
    if not код or not номер:
        return {"cheques": None, "fuel_ops": None, "conversion": None}
    ч = чеки.get((код, номер))
    з = заправки.get((код, номер))
    if ч is None and з is None:
        return {"cheques": None, "fuel_ops": None, "conversion": None}
    ч = ч or 0
    # Заправок не может быть меньше, чем чеков с топливом; если топливный контур
    # отстал, честнее показать прочерк, чем конверсию больше ста процентов.
    конверсия = round(ч / з * 100, 1) if з else None
    return {"cheques": ч, "fuel_ops": з,
            "conversion": конверсия if конверсия is None or конверсия <= 100 else None}


def _одна_смена_один_раз(rows: list[DataEntry]) -> list[DataEntry]:
    """Свернуть повторные проекции одной и той же смены внутри одного источника.

    Станция пересобирает и присылает смену заново. Приёмник помечает прежнюю
    запись `superseded`, только если узнал её — а узнаёт по времени закрытия;
    пересборка двигает его на секунду (23:52:31 → 23:52:30), и обе записи
    остаются `verified`.

    Ключ — ВНУТРЕННИЙ номер смены кассы (7046, 7051…): он уникален на станции и
    переживает пересборку. Печатного номера мало — он строится из даты открытия,
    и смена, открытая 30.07 в 23:59 и закрытая 31.07, носит номер за 30 июля;
    по нему две разные смены слиплись бы в одну, а из выручки пропал бы день.
    Из копий остаётся последняя присланная.
    """
    def ключ(row: DataEntry) -> tuple | None:
        shift = (row.meta or {}).get("Смена") or {}
        внутр = str(shift.get("НомерСменыВнутр") or "").strip()
        if not внутр:
            # Проекции без внутреннего номера (выгрузка 1С) различаем печатным
            # номером вместе с закрытием: без закрытия склеятся соседние смены.
            печатный = str(shift.get("ОСЭНомер") or shift.get("НомерСмены") or "").strip()
            if not печатный:
                return None
            return (row.source, str(shift.get("КодАЗС") or ""), печатный, _day(shift))
        return (row.source, str(shift.get("КодАЗС") or ""), внутр)

    def свежесть(row: DataEntry):
        return (row.revision or 0, row.updated_at or row.created_at)

    последние: dict[tuple, DataEntry] = {}
    прочие: list[DataEntry] = []
    for row in rows:
        k = ключ(row)
        if k is None:
            прочие.append(row)
            continue
        было = последние.get(k)
        if было is None or свежесть(row) > свежесть(было):
            последние[k] = row
    return list(последние.values()) + прочие


def _prefer_edge_sales(rows: list[DataEntry]) -> list[DataEntry]:
    """Не считать параллельные oneC- и Edge-проекции одной смены дважды."""
    rows = _одна_смена_один_раз(rows)
    edge = [row for row in rows if row.source == "edge"]
    if not edge:
        return rows

    def marks(row: DataEntry) -> tuple[tuple[str, str], tuple[str, str], tuple[str, str]]:
        shift = (row.meta or {}).get("Смена") or {}
        station = str(shift.get("КодАЗС") or "")
        number = str(shift.get("ОСЭНомер") or shift.get("НомерСмены") or "")
        opened = str(shift.get("Открытие") or "")[:16]
        return (station, number), (station, opened), (station, _day(shift))

    exact = {marks(row)[0] for row in edge}
    opened = {marks(row)[1] for row in edge if marks(row)[1][1]}
    edge_days: dict[tuple[str, str], int] = defaultdict(int)
    onec_days: dict[tuple[str, str], int] = defaultdict(int)
    for row in edge:
        edge_days[marks(row)[2]] += 1
    for row in rows:
        if row.source == "oneC":
            onec_days[marks(row)[2]] += 1

    result = list(edge)
    for row in rows:
        if row.source == "edge":
            continue
        by_number, by_opened, by_day = marks(row)
        duplicate = by_number in exact or (by_opened[1] and by_opened in opened)
        duplicate = duplicate or (edge_days[by_day] == 1 and onec_days[by_day] == 1)
        if not duplicate:
            result.append(row)
    return result


def _prefer_edge_documents(rows: list[DataEntry]) -> list[DataEntry]:
    """Предпочесть Edge при точном совпадении номера/дня/станции/суммы документа."""
    def key(row: DataEntry) -> tuple[str, str, str, str, float]:
        meta = row.meta or {}
        shift = meta.get("Смена") or {}
        doc = meta.get("Документ") or {}
        return (
            str(row.doc_type_id or ""),
            str(shift.get("КодАЗС") or ""),
            _day(shift),
            str(doc.get("Номер") or "").strip().casefold(),
            round(float(doc.get("СуммаДокумента") or 0), 2),
        )

    # Внутри одного источника документ тоже приезжает повторно — тем же номером
    # на той же станции. Дню и сумме в ключе доверять нельзя: пересборка сдвигает
    # время закрытия смены, и копия перестаёт узнаваться. Смены в ключе тоже нет:
    # одна приёмка приезжает в пакетах разных смен и размножилась бы. Источник
    # входит в ключ: сворачивать копии — да, выбирать между контурами — нет,
    # это делает предпочтение Edge ниже.
    def номер(row: DataEntry) -> tuple | None:
        meta = row.meta or {}
        смена = meta.get("Смена") or {}
        н = str((meta.get("Документ") or {}).get("Номер") or "").strip().casefold()
        if not н:
            return None
        return (str(row.source or ""), str(row.doc_type_id or ""),
                str(смена.get("КодАЗС") or ""), н)

    последние: dict[tuple, DataEntry] = {}
    без_номера: list[DataEntry] = []
    for row in rows:
        k = номер(row)
        if k is None:
            без_номера.append(row)
            continue
        было = последние.get(k)
        свежее = (row.revision or 0, row.updated_at or row.created_at)
        if было is None or свежее > (было.revision or 0, было.updated_at or было.created_at):
            последние[k] = row
    rows = list(последние.values()) + без_номера

    edge_keys = {key(row) for row in rows if row.source == "edge" and key(row)[3]}
    return [row for row in rows if row.source == "edge" or key(row) not in edge_keys]


def _cost_doubt(cost_unit: float | None, price: float | None, buy_unit: float | None) -> str | None:
    """Верить ли партийной себестоимости остатка. Причина словами или None.

    Партийный регистр на рознице смешанный (пересорт, старые партии), поэтому у части
    позиций цифра мусорная: то выше розничной цены (маржа уходит в минус), то вдвое ниже
    реальной закупки (экран рисует маржу 65% там, где её 23%). Обе проверки — грубые, но
    ловят именно эти два случая; порог 1,4 взят с запасом на нормальный разброс партий.
    """
    if cost_unit is None:
        return None
    if price is not None and cost_unit > price:
        return "выше розничной цены"
    if buy_unit and (cost_unit < buy_unit * 0.6 or cost_unit > buy_unit * 1.4):
        return f"расходится с закупкой ({round(buy_unit, 2)})"
    return None


class GoodsDashboardService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    async def _load(self) -> list[DataEntry]:
        """Все clean-продажи сопутки/общепита компании (объём мал — фильтр по дате в
        Python). Мемоизация на инстанс — метод зовётся многократно за запрос (К-27)."""
        if getattr(self, "_sales_cache", None) is None:
            rows = (await self.session.execute(select(DataEntry).where(
                DataEntry.company_id == self.company_id,
                DataEntry.layer == "clean",
                DataEntry.doc_type_id == "retail_sale_sidegoods",
                # Вытесненные документы — та же смена из второго источника
                # (выгрузка ЦБ против пакета станции). В витринах их быть не
                # должно: иначе выручка считается дважды.
                DataEntry.status != "superseded",
            ))).scalars().all()
            self._sales_cache = _prefer_edge_sales(rows)
        return self._sales_cache

    @staticmethod
    def _snap(rows) -> str | None:
        """Дата последнего снимка данных (max snapshot_at) — для индикации свежести
        движения товара/остатков в витринах (F3): движение/остатки наполняются
        отдельным пуллом и отстают от продаж; пользователь должен видеть, на какую
        дату актуальны цифры."""
        ts = [getattr(r, "snapshot_at", None) for r in rows]
        ts = [t for t in ts if t is not None]
        return max(ts).isoformat() if ts else None

    @staticmethod
    def _purch_net(doc: dict, ln: dict) -> float:
        """Net-себестоимость строки ПТУ (закуп без НДС). F8: если документ помечен
        СуммаВключаетНДС=Ложь — Сумма уже без НДС, повторно вычитать НельзяДважды.
        Отсутствие флага (старые пакеты до досбора) трактуем как «включает НДС»
        (проверено на текущих данных, K-1) — обратная совместимость."""
        amt = float(ln.get("Сумма") or 0)
        if doc.get("СуммаВключаетНДС") is False:
            return amt
        return amt - float(ln.get("СуммаНДС") or 0)

    @staticmethod
    def _is_active_doc(m: dict) -> bool:
        """Документ учитывается в деньгах: НЕ помечен на удаление и (если флаг
        Проведён присутствует) проведён. Зеркало эталона ВыбратьСмены (F5):
        помеченные/непроведённые документы ЦБ в витрины не попадают. Отсутствие
        флага (старые пакеты до досбора) трактуем как «учитывать» — не теряем
        историю; инвентаризаций это не касается (posted=false у них норма, свой
        путь CbInventoryDoc)."""
        d = m.get("Документ") or {}
        if d.get("ПометкаУдаления") is True:
            return False
        if d.get("Проведен") is False:
            return False
        return True

    def _select(self, rows: list[DataEntry], df: date, dt: date,
                stations: list[str] | None) -> list[dict]:
        """Отобрать meta записей в периоде/станциях (без непроведённых/удалённых)."""
        df_iso, dt_iso = df.isoformat(), dt.isoformat()
        out = []
        for e in rows:
            m = e.meta or {}
            smena = m.get("Смена") or {}
            d = _day(smena)
            if not (df_iso <= d <= dt_iso):
                continue
            if stations and str(smena.get("КодАЗС") or "") not in stations:
                continue
            if not self._is_active_doc(m):
                continue
            out.append(m)
        return out

    def _kpis(self, metas: list[dict]) -> dict:
        cat = defaultdict(lambda: {"revenue": 0.0, "vat": 0.0, "positions": 0, "units": 0.0})
        pay = defaultdict(float)      # cash / card (сводно)
        pay_detail = defaultdict(float)  # по фактической форме оплаты (К-8)
        returns_sum = 0.0
        shifts = len(metas)
        for m in metas:
            sec = m.get("Секции") or {}
            for key, catname in _SECTIONS:
                s = sec.get(key) or {}
                lines = s.get("строки") or []
                cat[catname]["revenue"] += float(s.get("сумма") or 0)
                cat[catname]["vat"] += float(s.get("сумма_ндс") or 0)
                cat[catname]["positions"] += len(lines)
                cat[catname]["units"] += sum(float(ln.get("Количество") or 0) for ln in lines)
            returns_sum += float((sec.get("возвраты") or {}).get("сумма") or 0)
            for o in (sec.get("оплаты") or {}).get("строки") or []:
                kanon = str(o.get("ФормаОплатыКанон") or o.get("ФормаОплаты") or "—")
                amt = float(o.get("Сумма") or 0)
                pay["cash" if "Наличн" in kanon else "card"] += amt
                pay_detail[kanon] += amt

        total_rev = sum(c["revenue"] for c in cat.values())
        total_vat = sum(c["vat"] for c in cat.values())
        total_pos = sum(c["positions"] for c in cat.values())
        total_units = sum(c["units"] for c in cat.values())
        by_category = [{
            "category": name,
            "revenue": round(d["revenue"], 2),
            "positions": d["positions"],
            "units": round(d["units"], 3),
            "percent": round(100 * d["revenue"] / total_rev, 1) if total_rev else 0.0,
        } for name, d in sorted(cat.items(), key=lambda x: -x[1]["revenue"]) if d["revenue"] or d["positions"]]

        return {
            "financial": {
                "total_revenue": round(total_rev, 2),
                "returns": round(returns_sum, 2),
                "vat": round(total_vat, 2),
                "net_revenue": round(total_rev - total_vat, 2),
                "avg_check_approx": round(total_rev / shifts, 2) if shifts else 0.0,
                "payments": {"cash": round(pay.get("cash", 0.0), 2), "card": round(pay.get("card", 0.0), 2)},
                "payments_detail": [{"name": k, "value": round(v, 2)}
                                    for k, v in sorted(pay_detail.items(), key=lambda x: -x[1]) if v],
            },
            "units": {
                "total_positions": total_pos,
                "total_units": round(total_units, 3),
                "by_category": by_category,
            },
            "operational": {"shifts_count": shifts},
        }

    def _charts(self, metas: list[dict], df: date, dt: date) -> dict:
        day_agg = {}
        d = df
        while d <= dt:
            day_agg[d.isoformat()] = {"date": d.isoformat(), "revenue": 0.0, "soputka": 0.0, "obshepit": 0.0}
            d += timedelta(days=1)
        for m in metas:
            key = _day(m.get("Смена") or {})
            g = day_agg.get(key)
            if g is None:
                continue
            sec = m.get("Секции") or {}
            sop = float((sec.get("продажа_сопутка") or {}).get("сумма") or 0)
            obsh = float((sec.get("продажа_общепит") or {}).get("сумма") or 0)
            g["soputka"] += sop
            g["obshepit"] += obsh
            g["revenue"] += sop + obsh
        daily = [{
            "date": v["date"], "revenue": round(v["revenue"], 2),
            "soputka": round(v["soputka"], 2), "obshepit": round(v["obshepit"], 2),
        } for v in sorted(day_agg.values(), key=lambda x: x["date"])]
        return {"daily": daily}

    def _by_station(self, metas: list[dict]) -> list[dict]:
        agg = defaultdict(lambda: {"revenue": 0.0, "positions": 0, "shifts": 0})
        for m in metas:
            st = str((m.get("Смена") or {}).get("КодАЗС") or "—")
            sec = m.get("Секции") or {}
            rev = pos = 0.0
            for key, _ in _SECTIONS:
                s = sec.get(key) or {}
                rev += float(s.get("сумма") or 0)
                pos += len(s.get("строки") or [])
            agg[st]["revenue"] += rev
            agg[st]["positions"] += int(pos)
            agg[st]["shifts"] += 1
        out = [{
            "station": st, "revenue": round(d["revenue"], 2),
            "positions": d["positions"], "shifts": d["shifts"],
        } for st, d in agg.items()]
        out.sort(key=lambda x: -x["revenue"])
        return out

    def _trends(self, cur: dict, prev: dict) -> dict:
        def tr(c, p):
            delta = c - p
            pct = (delta / p * 100) if p else (100.0 if c > 0 else 0.0)
            return {
                "current": round(c, 2), "previous": round(p, 2), "delta": round(delta, 2),
                "percent": round(pct, 1),
                "direction": "up" if pct > 0.5 else ("down" if pct < -0.5 else "neutral"),
            }
        return {
            "revenue": tr(cur["financial"]["total_revenue"], prev["financial"]["total_revenue"]),
            "shifts": tr(cur["operational"]["shifts_count"], prev["operational"]["shifts_count"]),
            "avg_check": tr(cur["financial"]["avg_check_approx"], prev["financial"]["avg_check_approx"]),
        }

    async def compute(self, date_from: date, date_to: date,
                      stations: list[str] | None = None, compare: bool = False) -> dict:
        rows = await self._load()
        metas = self._select(rows, date_from, date_to, stations)
        kpis = self._kpis(metas)
        result = {
            "period": {
                "from": date_from.isoformat(), "to": date_to.isoformat(),
                "days": (date_to - date_from).days + 1,
            },
            **kpis,
            "charts": self._charts(metas, date_from, date_to),
            "by_station": self._by_station(metas),
        }
        result["operational"]["stations_count"] = len(result["by_station"])
        # Поток людей рядом с выручкой: без него «238 682 ₽ за период» не
        # говорит, плохо продавали или мало кто заезжал. Заправка — тоже визит:
        # человек прошёл мимо витрины и ничего не взял, и это ровно тот
        # потенциал, ради которого магазин на станции и держат.
        result["visits"] = await self._visits(date_from, date_to, stations)
        # Маржа в шапке обзора. Раздел заявлен про то, где зарабатывается
        # прибыль, а полоса показывала одну выручку и обещала маржу «следующим
        # блоком» — при том, что «Маржа и наценка» её уже считает. Берём ту же
        # сводку, а не свой счёт: два экрана обязаны сходиться до копейки.
        result["margin"] = (await self.pricing_analysis(
            date_from, date_to, stations=stations))["summary"]
        if compare:
            days = (date_to - date_from).days + 1
            cmp_to = date_from - timedelta(days=1)
            cmp_from = cmp_to - timedelta(days=days - 1)
            c_metas = self._select(rows, cmp_from, cmp_to, stations)
            result["trends"] = self._trends(kpis, self._kpis(c_metas))
        return result

    async def _visits(self, date_from: date, date_to: date,
                      stations: list[str] | None) -> dict:
        """Посещения станций за период и конверсия магазина.

        Считается из двух контуров, потому что они и ведутся раздельно:
        заправки — в реестре топлива, покупки — в чеках станции. Смешанный чек
        в топливном контуре уже посчитан, поэтому к посещениям добавляются
        только чеки БЕЗ топлива, иначе один визит удвоился бы.

        Контуры покрывают разное: топливо приходит по всей сети и с апреля, чеки
        едут только с тех станций, где стоит агент, и только за последние дни.
        Делить одно на другое напрямую нельзя — на ГИГ это давало «конверсия
        1 %» и «49 225 уехали без покупки», то есть заправки одиннадцати чужих
        станций против чеков одной 208 за шесть дней. Поэтому знаменатель
        считается только по тем суткам и станциям, где чеки ЕСТЬ, а чем
        ограничился базис — сказано в ответе.
        """
        p: dict = {"cid": self.company_id, "d1": date_from, "d2": date_to}
        коды = [int(s) for s in (stations or []) if str(s).isdigit()]
        ф_ч = " AND station_id = ANY(:st)" if коды else ""
        if коды:
            p["st"] = коды

        ч = (await self.session.execute(text(f"""
            SELECT count(*) AS cheques,
                   count(*) FILTER (WHERE had_fuel) AS mixed,
                   count(*) FILTER (WHERE NOT had_fuel) AS shop_only,
                   coalesce(sum(total), 0) AS amount,
                   count(DISTINCT station_id) AS stations,
                   count(DISTINCT at::date) AS days,
                   count(DISTINCT (station_id, shift_number)) AS shifts,
                   min(at)::date AS d1, max(at)::date AS d2
            FROM store_cheques
            WHERE company_id = :cid{ф_ч} AND at::date BETWEEN :d1 AND :d2
        """), p)).mappings().first() or {}
        # Заправки — только тех СМЕН, чеки которых у нас есть. Смена, а не
        # сутки: она открывается в полночь с минутами и закрывается в 23:47,
        # ровно её и считает станция. По суткам в знаменатель попадала смена
        # 7065, чеки которой ещё не поднимали, и конверсия падала с 21,5 % до
        # 18,9 % — та же болезнь, только мельче. Реестр смен считает так же.
        заправок = (await self.session.execute(text(f"""
            WITH базис AS (
                SELECT DISTINCT station_id, shift_number
                FROM store_cheques
                WHERE company_id = :cid{ф_ч} AND at::date BETWEEN :d1 AND :d2
            )
            SELECT count(*) FROM fuel_transactions f
            JOIN базис b ON b.station_id = f.station_code
                        AND b.shift_number = f.shift_number
            WHERE f.company_id = :cid
        """), p)).scalar() or 0

        чеков = int(ч.get("cheques") or 0)
        смешанных = int(ч.get("mixed") or 0)
        # Смешанный чек — доказательство заправки. Если топливный контур отстал
        # (реализации приезжают позже чеков), заправок в реестре меньше, чем
        # было на самом деле, и без этой поправки конверсия уходит за 100 %.
        заправок = max(int(заправок), смешанных)
        посещений = заправок + int(ч.get("shop_only") or 0)
        выручка = float(ч.get("amount") or 0)
        дней_в_периоде = (date_to - date_from).days + 1
        дней = int(ч.get("days") or 0)
        return {
            "visits": посещений,
            "fuel_ops": заправок,
            "shop_cheques": чеков,
            "mixed": смешанных,
            "fuel_only": max(заправок - смешанных, 0),
            "conversion": round(чеков / посещений * 100, 1) if посещений else 0.0,
            "revenue": round(выручка, 2),
            "per_visit": round(выручка / посещений, 2) if посещений else 0.0,
            "avg_cheque": round(выручка / чеков, 2) if чеков else 0.0,
            # Чем ограничен счёт: пока чеки едут не отовсюду и не за всё время,
            # цифра относится к части периода, и молчать об этом нельзя.
            "basis": {
                "days": дней, "period_days": дней_в_периоде,
                "shifts": int(ч.get("shifts") or 0),
                "stations": int(ч.get("stations") or 0),
                "from": ч.get("d1").isoformat() if ч.get("d1") else None,
                "to": ч.get("d2").isoformat() if ч.get("d2") else None,
                "partial": bool(дней and дней < дней_в_периоде),
            },
        }

    async def visits(self, date_from: date, date_to: date,
                     stations: list[str] | None = None) -> dict:
        return await self._visits(date_from, date_to, stations)

    # ── SKU-аналитика: реестр товаров с маржой + ABC (Ассортимент/Цены/Номенклатура) ──

    async def _load_purchases(self, df: date, dt: date, stations: list[str] | None) -> list[dict]:
        if getattr(self, "_purch_cache", None) is None:  # мемоизация сырых строк (К-27)
            rows = (await self.session.execute(select(DataEntry).where(
                DataEntry.company_id == self.company_id, DataEntry.layer == "clean",
                DataEntry.doc_type_id == "purchase"))).scalars().all()
            self._purch_cache = _prefer_edge_documents(rows)
        # F1 (P0): один ПТУ прицеплен к двум смежным сменам (дневное окно прицепки —
        # зеркало эталона) → две DataEntry с общим Документ.ИсточникUUID; витрины
        # суммировали обе. Дедуп по ИсточникUUID: считаем документ один раз (пакет
        # БП дедуплится на приёмнике, здесь — только чтение). Строки без UUID
        # (старые/ручные) не схлопываем — ключ по id записи.
        selected = self._select(self._purch_cache, df, dt, stations)
        out: list[dict] = []
        seen: set[str] = set()
        for i, m in enumerate(selected):
            uid = str((m.get("Документ") or {}).get("ИсточникUUID") or "") or f"__row{i}"
            if uid in seen:
                continue
            seen.add(uid)
            out.append(m)
        return out

    async def _load_returns(self) -> list[dict]:
        """Возвраты поставщику (F2) all-time, дедуп по ИсточникUUID — как _load_purchases.
        Вычитаются из закупочной базы себестоимости (иначе возвращённый товар завышает
        закупленное количество и искажает удельную закупку). Возвраты часто 0."""
        if getattr(self, "_ret_cache", None) is None:
            rows = (await self.session.execute(select(DataEntry).where(
                DataEntry.company_id == self.company_id, DataEntry.layer == "clean",
                DataEntry.doc_type_id == "return_purchase"))).scalars().all()
            self._ret_cache = _prefer_edge_documents(rows)
        selected = self._select(self._ret_cache, date(2000, 1, 1), date(2100, 1, 1), None)
        out: list[dict] = []
        seen: set[str] = set()
        for i, m in enumerate(selected):
            uid = str((m.get("Документ") or {}).get("ИсточникUUID") or "") or f"__ret{i}"
            if uid in seen:
                continue
            seen.add(uid)
            out.append(m)
        return out

    async def _release_agg(self, df: date, dt: date,
                           stations: list[str] | None) -> dict[str, list[float]]:
        """Выпуск блюд за период: ref → [сумма себестоимости, количество порций].

        Это готовая себестоимость от самой 1С, посчитанная по тем же техкартам и по
        правилам списания — то есть ровно то, чем закрывается смена. Сборка по ТТК из
        средних закупок остаётся запасным путём: она даёт нижнюю границу и рвётся целиком,
        если хоть у одного ингредиента нет ни одной накладной за период (сироп на два
        грамма обнулял себестоимость всего капучино).

        Дедуп документов по `ИсточникUUID` — как в `_load_purchases`: один документ мог
        прицепиться к двум смежным сменам.
        """
        if getattr(self, "_release_cache", None) is None:
            self._release_cache = (await self.session.execute(select(DataEntry).where(
                DataEntry.company_id == self.company_id, DataEntry.layer == "clean",
                DataEntry.doc_type_id == "production_release",
                DataEntry.source == "oneC"))).scalars().all()
        selected = self._select(self._release_cache, df, dt, stations)
        agg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])   # ref → [сумма, кол-во]
        seen: set[str] = set()
        for i, m in enumerate(selected):
            doc = m.get("Документ") or {}
            uid = str(doc.get("ИсточникUUID") or "") or f"__rel{i}"
            if uid in seen:
                continue
            seen.add(uid)
            for ln in doc.get("ВыпускБлюд") or []:
                ref = str(ln.get("Номенклатура") or "")
                qty = float(ln.get("Количество") or 0)
                if not ref or qty <= 0:
                    continue
                agg[ref][0] += float(ln.get("Сумма") or 0)
                agg[ref][1] += qty
        return agg

    async def _shift_index(self, date_from: date, date_to: date,
                           stations: list[str] | None = None) -> dict[str, list[dict]]:
        """Смены периода по станции: {станция: [{key, number, open, close, day}, …]}.

        Источник — сменные отчёты ЦБ: только в них есть номер смены и её окно.
        """
        idx: dict[str, list[dict]] = defaultdict(list)
        for m in self._select(await self._load(), date_from, date_to, stations):
            smena = m.get("Смена") or {}
            day = _day(smena)
            station = str(smena.get("КодАЗС") or "—")
            idx[station].append({
                "key": str(smena.get("Смена") or f"{day}|{station}"),
                "number": smena.get("НомерСмены") or smena.get("Номер"),
                "open": smena.get("Открытие"), "close": smena.get("Закрытие"),
                "day": day, "station": station,
            })
        for lst in idx.values():
            lst.sort(key=lambda x: str(x["open"] or ""))
        return idx

    @staticmethod
    def _shift_of(shifts: list[dict], day: str, station: str | None = None) -> dict:
        """Смены дня, к которым относится документ.

        Витринные документы (инвентаризация, списания, перемещения) несут только дату,
        без времени, поэтому смена определяется днём. В день с двумя сменами документ
        относится к обеим — приписать его одной значило бы соврать, а прочерк спрятал бы
        связь, которая есть. Так же устроен и учётный контур ЦБ: документ попадает в
        смену по интервалу «НачалоДня(Открытие)…КонецДня(Закрытие)», а не по ссылке.
        """
        same_day = [
            sh for sh in shifts
            if sh["day"] == day and (station is None or sh.get("station") == station)
        ]
        if station is None and len({sh.get("station") for sh in same_day}) > 1:
            return {
                "key": None, "number": None, "count": 0,
                "reason": "не удалось определить станцию документа",
            }
        if not same_day:
            # Сменные отчёты загружены за более короткий период, чем документы движения:
            # у документа просто нет смены в данных. Догружается обменом, не кодом.
            return {"key": None, "number": None, "count": 0, "reason": "нет сменного отчёта"}
        numbers = [str(sh["number"]) for sh in same_day if sh["number"]]
        return {
            "key": same_day[0]["key"] if len(same_day) == 1 else None,
            "number": ", ".join(numbers) if numbers else None,
            "count": len(same_day),
            "reason": "в этот день две смены" if len(same_day) > 1 else None,
        }

    async def _release_cost_unit(self, df: date, dt: date,
                                 stations: list[str] | None) -> dict[str, float]:
        """Себестоимость порции блюда: Σ(Сумма)/Σ(Количество) выпуска за период."""
        return {ref: s / q for ref, (s, q) in (await self._release_agg(df, dt, stations)).items() if q > 0}

    async def _names(self) -> dict:
        if getattr(self, "_names_cache", None) is not None:
            return self._names_cache
        self._names_cache = {n.external_ref: n for n in (await self.session.execute(select(CbNomenclature).where(
            CbNomenclature.company_id == self.company_id))).scalars().all()}
        return self._names_cache

    async def _cost_unit_map(self, stations: list[str] | None = None) -> dict[str, tuple[float, str, float]]:
        """Удельная себестоимость (закуп. NET, без НДС) за единицу закупки по GUID:
        {ref: (unit_cost_net, source, purch_qty_all)}.

        База — средняя закупка net за ВСЁ время (Σ(Сумма−СуммаНДС)/ΣКоличество из ПТУ;
        ⚠ проверено: Сумма ПТУ включает НДС → net корректен, К-1). Даёт корректную маржу
        (табак ~6%) и убирает margin=None узкого окна. Партийную StockOnHand.cost_unit НЕ
        используем для маржи продаж: на розничных АЗС партийный регистр отрицательно-
        смешанный (пересорт) → удельная себест. по нему ненадёжна. Кеш в инстансе (К-27)."""
        cache_key = tuple(sorted(stations or []))
        cache = getattr(self, "_ccache", {})
        if cache_key in cache:
            return cache[cache_key]
        agg: dict[str, list] = defaultdict(lambda: [0.0, 0.0])
        for m in await self._load_purchases(date(2000, 1, 1), date(2100, 1, 1), stations):
            doc = m.get("Документ") or {}
            for ln in doc.get("Товары") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                agg[g][0] += self._purch_net(doc, ln)
                agg[g][1] += float(ln.get("Количество") or 0)
        # F2: возвраты поставщику уменьшают чистую закупку (net + количество). Так
        # удельная закупка = (Σзакуп − Σвозврат)/(Σкол − Σвозврат) не завышена.
        for m in await self._load_returns():
            shift = m.get("Смена") or {}
            if stations and str(shift.get("КодАЗС") or "") not in stations:
                continue
            doc = m.get("Документ") or {}
            for ln in doc.get("Товары") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                agg[g][0] -= self._purch_net(doc, ln)
                agg[g][1] -= float(ln.get("Количество") or 0)
        cm: dict[str, tuple[float, str, float]] = {}
        for g, v in agg.items():
            if v[1] and (v[0] / v[1]) > 0:
                cm[g] = (v[0] / v[1], "purchase", v[1])
        # Блюдо не закупают — его выпускают: у ГИГ общепит продаётся как сопутствующий
        # товар, а себестоимость 1С формирует по рецептуре в момент продажи (документ
        # выпуска идёт порция в порцию с чеком — проверено, 1077 = 1077 за 29 дней).
        # Для товарных экранов это и есть себестоимость SKU; без неё блюда (у ГИГ 30 шт,
        # 166 тыс ₽ — 16% оборота) шли в «Ассортименте», «Ценах и марже», ABC-XYZ и
        # карточке товара вовсе без маржи. Выпуск перекрывает закупку: у блюда с обоими
        # источниками верна себестоимость производства, а не цена разовой перепродажи.
        for g, (amt, qty) in (await self._release_agg(
                date(2000, 1, 1), date(2100, 1, 1), stations)).items():
            if qty > 0 and amt > 0:
                cm[g] = (amt / qty, "release", qty)
        cache[cache_key] = cm
        self._ccache = cache
        return cm

    async def sku_analytics(self, date_from: date, date_to: date,
                            stations: list[str] | None = None) -> dict:
        sale_metas = self._select(await self._load(), date_from, date_to, stations)
        purch_metas = await self._load_purchases(date_from, date_to, stations)
        nom = await self._names()

        sku: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "revenue_net": 0.0, "qty": 0.0, "category": None})
        for m in sale_metas:
            sec = m.get("Секции") or {}
            for key, catname in _SECTIONS:
                for ln in (sec.get(key) or {}).get("строки") or []:
                    g = ln.get("Номенклатура")
                    if not g:
                        continue
                    summ = float(ln.get("Сумма") or 0)
                    vat = float(ln.get("СуммаНДС") or 0)
                    s = sku[g]
                    s["revenue"] += summ
                    s["revenue_net"] += summ - vat
                    s["qty"] += float(ln.get("Количество") or 0)
                    s["category"] = catname

        purch: dict[str, dict] = defaultdict(lambda: {"cost_net": 0.0, "qty": 0.0})
        for m in purch_metas:
            doc = m.get("Документ") or {}
            for ln in doc.get("Товары") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                purch[g]["cost_net"] += self._purch_net(doc, ln)   # F8: учёт СуммаВключаетНДС
                purch[g]["qty"] += float(ln.get("Количество") or 0)

        cost_map = await self._cost_unit_map(stations)  # единая себест.: партии→закупка (К-2)
        rows = []
        for g, s in sku.items():
            n = nom.get(g)
            p = purch.get(g)
            pq = p["qty"] if p else 0.0
            cu = cost_map.get(g)
            avg_cost = cu[0] if cu else None
            cost_source = cu[1] if cu else None
            purch_all = cu[2] if cu else 0.0
            is_weighed = bool(n and n.weighed)
            cogs = (avg_cost * s["qty"]) if avg_cost is not None else None
            margin = (s["revenue_net"] - cogs) if cogs is not None else None
            # достоверность себест.: надёжна, если закупали объёмом ≥ половины проданного и
            # товар не весовой (у весовых/блочных единицы закупки≠продажи → выброс, К-3/К-4)
            cost_reliable = (avg_cost is not None and not is_weighed and purch_all >= 0.5 * s["qty"])
            rows.append({
                "guid": g,
                "name": (n.name if n else g[:8]),
                "article": (n.article if n else None),
                "vat": (n.vat if n else None),
                "marked": bool(n.marked) if n else False,
                "weighed": bool(n.weighed) if n else False,
                "category": s["category"],
                "revenue": round(s["revenue"], 2),
                "revenue_net": round(s["revenue_net"], 2),
                "qty": round(s["qty"], 3),
                "avg_price": round(s["revenue"] / s["qty"], 2) if s["qty"] else 0.0,
                "cost_net": round(avg_cost, 4) if avg_cost is not None else None,
                "cost_source": cost_source,
                "cost_reliable": cost_reliable,
                "cogs": round(cogs, 2) if cogs is not None else None,
                "margin": round(margin, 2) if margin is not None else None,
                "margin_pct": round(100 * margin / s["revenue_net"], 1) if margin is not None and s["revenue_net"] else None,
                "markup_pct": round(100 * margin / cogs, 1) if margin is not None and cogs else None,
                "purch_qty": round(pq, 3),
                "stock_est": round(pq - s["qty"], 3),
            })

        # ABC по выручке (накопительная доля)
        rows.sort(key=lambda x: -x["revenue"])
        total_rev = sum(r["revenue"] for r in rows) or 1.0
        cum = 0.0
        abc = {c: {"count": 0, "revenue": 0.0} for c in ("A", "B", "C")}
        for r in rows:
            cum += r["revenue"]
            share = 100 * cum / total_rev
            cls = "A" if share <= 80 else ("B" if share <= 95 else "C")
            r["abc"] = cls
            abc[cls]["count"] += 1
            abc[cls]["revenue"] += r["revenue"]
        for c in abc.values():
            c["share"] = round(100 * c["revenue"] / total_rev, 1) if total_rev else 0.0
            c["revenue"] = round(c["revenue"], 2)

        costed = [r for r in rows if r["margin"] is not None]
        net_costed = sum(r["revenue_net"] for r in costed)
        margin_costed = sum(r["margin"] for r in costed)
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "summary": {
                "sku_count": len(rows),
                "sku_costed": len(costed),
                "revenue": round(sum(r["revenue"] for r in rows), 2),
                "revenue_net": round(sum(r["revenue_net"] for r in rows), 2),
                "cogs_costed": round(sum(r["cogs"] for r in costed), 2),
                "margin_costed": round(margin_costed, 2),
                "margin_pct_costed": round(100 * margin_costed / net_costed, 1) if net_costed else None,
                "marked_count": sum(1 for r in rows if r["marked"]),
            },
            "abc": abc,
            "skus": rows,
        }

    async def _refs(self, kind: str) -> dict:
        return {r.external_ref: r.name for r in (await self.session.execute(select(CbRef).where(
            CbRef.company_id == self.company_id, CbRef.kind == kind))).scalars().all()}

    # ── Цены и маржа: сегмент (сопутка/общепит/всё) + группы + реестр SKU ──
    async def _обогатить_ценой(self, skus: list[dict],
                               stations: list[str] | None) -> None:
        """Добрать позициям цену на полке, остаток и владельца цены.

        Цена по сети не одна: на разных АЗС она своя, и «средняя цена сети» —
        число, которого нет ни на одной полке. Поэтому отдаём диапазон: когда
        min и max сходятся, экран показывает одну цифру, когда расходятся —
        видно, что позиция стоит по-разному, и это отдельный разговор.
        """
        soh = (await self.session.execute(select(StockOnHand).where(
            StockOnHand.company_id == self.company_id))).scalars().all()
        цены: dict[str, dict] = {}
        for r in soh:
            if not _warehouse_in_stations(r.warehouse_code, stations):
                continue
            узел = цены.setdefault(r.nomenclature_ref, {"min": None, "max": None,
                                                        "qty": 0.0})
            узел["qty"] += float(r.quantity or 0)
            цена = float(r.retail_price) if r.retail_price is not None else None
            if цена and цена > 0:
                узел["min"] = цена if узел["min"] is None else min(узел["min"], цена)
                узел["max"] = цена if узел["max"] is None else max(узел["max"], цена)

        # Владелец цены живёт в справочнике сети, а не в остатках: пока центр не
        # разложил ассортимент по владельцам, там пусто — и это не запрет, а
        # «правило не задано». Так же читает станция.
        владельцы: dict[str, str] = {}
        try:
            for uid, owner in (await self.session.execute(text(
                "SELECT external_uuid::text, coalesce(price_owner, '')"
                " FROM edge.item WHERE external_uuid IS NOT NULL"
            ))).all():
                владельцы[str(uid)] = str(owner or "")
        except Exception:  # noqa: BLE001 — схемы edge может не быть (пространство без станций)
            владельцы = {}

        for s in skus:
            узел = цены.get(s["guid"])
            s["price_min"] = узел["min"] if узел else None
            s["price_max"] = узел["max"] if узел else None
            s["stock_qty"] = round(узел["qty"], 3) if узел else 0.0
            s["price_owner"] = владельцы.get(s["guid"], "")
            # Фудкост — доля себестоимости в цене: у кухни разговор идёт в нём, а
            # не в марже. Это та же цифра с другой стороны, поэтому считаем её
            # здесь, а не заводим второй источник.
            s["food_cost_pct"] = (round(100 - s["margin_pct"], 1)
                                  if s["category"] == "Общепит" and s["margin_pct"] is not None
                                  else None)

    async def pricing_analysis(self, date_from: date, date_to: date, *,
                               category: str = "all", stations: list[str] | None = None) -> dict:
        """Анализ цен и маржи: сегмент (all|soputka|obshepit), разбивки по категории и
        виду номенклатуры (какие группы сколько маржи приносят) + реестр SKU. Детализация
        по товару — sku_detail (модалка)."""
        data = await self.sku_analytics(date_from, date_to, stations)
        kinds = await self._refs("nom_kind")
        nom = await self._names()
        skus = data["skus"]
        for s in skus:
            nn = nom.get(s["guid"])
            s["kind"] = (kinds.get(nn.kind_ref) or "— вид не указан") if (nn and nn.kind_ref) else "— вид не указан"

        # общепит: себестоимость блюда — по ингредиентам ТТК (напрямую не закупается),
        # иначе маржа сегмента «Общепит» пустая. Реюз логики catering, покрытие ≥90% (К-5).
        avgc = {g: c[0] for g, c in (await self._cost_unit_map(stations)).items()}
        dishc: dict[str, dict] = defaultdict(lambda: {"cost": 0.0, "ings": set(), "known": set()})
        for m in self._select(await self._load(), date_from, date_to, stations):
            for ln in (((m.get("Секции") or {}).get("продажа_общепит")) or {}).get("строки") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                for ing in ln.get("Ингредиенты") or []:
                    ig = ing.get("Номенклатура")
                    if not ig:
                        continue
                    dishc[g]["ings"].add(ig)
                    if ig in avgc:
                        dishc[g]["cost"] += float(ing.get("Количество") or 0) * avgc[ig]
                        dishc[g]["known"].add(ig)
        for s in skus:
            if s["category"] == "Общепит" and s["margin"] is None:
                dc = dishc.get(s["guid"])
                coverage = (len(dc["known"]) / len(dc["ings"])) if (dc and dc["ings"]) else 0.0
                if dc and coverage >= _TTK_COVERAGE_MIN:   # OB-3/К-5
                    cogs = round(dc["cost"], 2)
                    s["cost_net"] = round(dc["cost"] / s["qty"], 4) if s["qty"] else None
                    s["cogs"] = cogs
                    s["margin"] = round(s["revenue_net"] - cogs, 2)
                    s["margin_pct"] = round(100 * s["margin"] / s["revenue_net"], 1) if s["revenue_net"] else None
                    s["markup_pct"] = round(100 * s["margin"] / cogs, 1) if cogs else None
                    s["cost_source"] = "recipe"
                    s["cost_reliable"] = True

        # Цена на полке, остаток и владелец цены — рядом с маржой, как на станции.
        #
        # Без цены таблица отвечает «сколько заработали», но не «с чего»: маржа
        # 11 % на позиции за 90 ₽ и за 900 ₽ — разговор о разном. Остаток тут же
        # показывает, есть ли чем зарабатывать дальше. Владелец цены снимает
        # главный вопрос сетевого товароведа: эту цену правит центр или станция —
        # то есть могу ли я вообще её тронуть отсюда.
        await self._обогатить_ценой(skus, stations)

        catmap = {"soputka": "Сопутка", "obshepit": "Общепит"}
        if category in catmap:
            skus = [s for s in skus if s["category"] == catmap[category]]

        def _group(items: list[dict], keyfn) -> list[dict]:
            agg: dict[str, dict] = defaultdict(lambda: {"rev": 0.0, "net": 0.0, "cogs": 0.0, "margin": 0.0, "mk_net": 0.0, "qty": 0.0, "sku": 0})
            for s in items:
                a = agg[keyfn(s)]
                a["rev"] += s["revenue"]; a["net"] += s["revenue_net"]; a["qty"] += s["qty"]; a["sku"] += 1
                if s["margin"] is not None and s.get("cost_reliable"):  # групповая маржа — только надёжные (К-3)
                    a["margin"] += s["margin"]; a["cogs"] += s["cogs"]; a["mk_net"] += s["revenue_net"]
            tot = sum(a["rev"] for a in agg.values()) or 1.0
            rows = [{
                "group": g, "revenue": round(a["rev"], 2), "revenue_net": round(a["net"], 2),
                "qty": round(a["qty"], 3), "sku_count": a["sku"], "share": round(100 * a["rev"] / tot, 1),
                "margin": round(a["margin"], 2) if a["mk_net"] else None,
                "margin_pct": round(100 * a["margin"] / a["mk_net"], 1) if a["mk_net"] else None,
            } for g, a in agg.items()]
            rows.sort(key=lambda x: -x["revenue"])
            return rows

        costed = [s for s in skus if s["margin"] is not None and s.get("cost_reliable")]
        net_costed = sum(s["revenue_net"] for s in costed)
        margin_costed = sum(s["margin"] for s in costed)
        cogs_costed = sum(s["cogs"] for s in costed)
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "category": category,
            "summary": {
                "sku_count": len(skus), "sku_costed": len(costed),
                "revenue": round(sum(s["revenue"] for s in skus), 2),
                "revenue_net": round(sum(s["revenue_net"] for s in skus), 2),
                "cogs": round(cogs_costed, 2), "margin": round(margin_costed, 2),
                "margin_pct": round(100 * margin_costed / net_costed, 1) if net_costed else None,
                "markup_pct": round(100 * margin_costed / cogs_costed, 1) if cogs_costed else None,
                "loss_makers": sum(1 for s in costed if (s["margin_pct"] or 0) < 0),
            },
            "by_category": _group(skus, lambda s: s["category"] or "—"),
            "by_kind": _group(skus, lambda s: s["kind"]),
            "skus": sorted(skus, key=lambda s: -s["revenue"]),
        }

    # ── Детализация товара (модалка): метрики + история цен + продажи + закупки + остаток ──
    async def sku_detail(self, guid: str, date_from: date, date_to: date,
                         stations: list[str] | None = None) -> dict:
        nom = await self._names()
        n = nom.get(guid)
        cparty = await self._refs("counterparty")
        kinds = await self._refs("nom_kind")

        purch_metas = await self._load_purchases(date_from, date_to, stations)
        # OB-4/K-2: единая база себестоимости ингредиента — all-time _cost_unit_map,
        # как в catering_menu/pricing (раньше карточка считала по _avg_cost окна →
        # тот же food-cost блюда расходился между меню и карточкой, а в узком окне
        # без закупок терялся).
        avgc = {g: c[0] for g, c in (await self._cost_unit_map(stations)).items()}

        # продажи (сопутка+общепит) — итоги + дневная динамика; для общепита копим
        # себестоимость по ингредиентам ТТК.
        daily: dict[str, dict] = defaultdict(lambda: {"qty": 0.0, "rev": 0.0})
        qty = rev = revnet = 0.0
        ing_cost = 0.0
        ing_known = False
        category = None
        for m in self._select(await self._load(), date_from, date_to, stations):
            day = _day(m.get("Смена") or {})
            for sk, catname in _SECTIONS:
                for ln in (((m.get("Секции") or {}).get(sk)) or {}).get("строки") or []:
                    if ln.get("Номенклатура") != guid:
                        continue
                    q = float(ln.get("Количество") or 0)
                    su = float(ln.get("Сумма") or 0)
                    vt = float(ln.get("СуммаНДС") or 0)
                    qty += q; rev += su; revnet += su - vt; category = catname
                    dd = daily[day]; dd["qty"] += q; dd["rev"] += su
                    for ing in ln.get("Ингредиенты") or []:
                        ig = ing.get("Номенклатура")
                        if ig in avgc:
                            ing_cost += float(ing.get("Количество") or 0) * avgc[ig]
                            ing_known = True

        # закупки (последние цены/поставщики) — прямая закупка товара
        purchases = []
        pq = pc = 0.0
        for m in purch_metas:
            d = m.get("Документ") or {}
            for ln in d.get("Товары") or []:
                if ln.get("Номенклатура") != guid:
                    continue
                q = float(ln.get("Количество") or 0)
                net = self._purch_net(d, ln)   # F8: учёт СуммаВключаетНДС
                purchases.append({
                    "date": str(d.get("Дата") or "")[:10],
                    "supplier": cparty.get(d.get("Контрагент")) or (d.get("Контрагент") or "—"),
                    "qty": round(q, 3), "price_net": round(net / q, 2) if q else None,
                    "amount_net": round(net, 2),
                })
                pq += q; pc += net
        purchases.sort(key=lambda x: x["date"])
        # себестоимость: прямая закупка (сопутка) или по ингредиентам (общепит)
        if pq:
            avg_cost = pc / pq
            cogs = avg_cost * qty
        elif ing_known:
            cogs = ing_cost
            avg_cost = (ing_cost / qty) if qty else None
        else:
            avg_cost = cogs = None
        margin = (revnet - cogs) if cogs is not None else None

        # история цен — из переоценок (CbMovementDoc kind=revaluation)
        revs = (await self.session.execute(select(CbMovementDoc).where(
            CbMovementDoc.company_id == self.company_id,
            CbMovementDoc.deleted.is_(False), CbMovementDoc.posted.is_(True),
            CbMovementDoc.kind == "revaluation"))).scalars().all()
        revs = self._by_period(revs, date_from, date_to)
        if stations:
            revs = [r for r in revs if _warehouse_in_stations(r.warehouse_code, stations)]
        history = []
        for r in revs:
            for ln in (r.lines or []):
                if ln.get("ref") == guid:
                    history.append({"date": r.doc_date, "old": ln.get("old"), "new": ln.get("new"),
                                    "delta": ln.get("delta"), "pct": ln.get("pct")})
        history.sort(key=lambda x: (x["date"] or ""))

        # остаток по складам
        soh = (await self.session.execute(select(StockOnHand).where(
            StockOnHand.company_id == self.company_id,
            StockOnHand.nomenclature_ref == guid))).scalars().all()
        if stations:
            soh = [r for r in soh if _warehouse_in_stations(r.warehouse_code, stations)]
        stock = [{
            "warehouse": r.warehouse_name or r.warehouse_code,
            "qty": float(r.quantity or 0),
            "retail_price": float(r.retail_price) if r.retail_price is not None else None,
            "cost_unit": float(r.cost_unit) if r.cost_unit is not None else None,
        } for r in soh]

        return {
            "guid": guid, "name": (n.name if n else guid[:8]),
            "article": (n.article if n else None), "vat": (n.vat if n else None),
            "marked": bool(n and n.marked), "weighed": bool(n and n.weighed),
            "unit": (n.unit if n else None), "full_name": (n.full_name if n else None),
            "main_supplier": (n.main_supplier if n else None),
            "kind": (kinds.get(n.kind_ref) if (n and n.kind_ref) else None), "category": category,
            "metrics": {
                "qty": round(qty, 3), "revenue": round(rev, 2), "revenue_net": round(revnet, 2),
                "avg_price": round(rev / qty, 2) if qty else None,
                "avg_cost": round(avg_cost, 4) if avg_cost is not None else None,
                "cogs": round(cogs, 2) if cogs is not None else None,
                "margin": round(margin, 2) if margin is not None else None,
                "margin_pct": round(100 * margin / revnet, 1) if margin is not None and revnet else None,
                "markup_pct": round(100 * margin / cogs, 1) if margin is not None and cogs else None,
                "purch_qty": round(pq, 3),
            },
            "daily": [{"date": d, "qty": round(v["qty"], 2), "revenue": round(v["rev"], 2)}
                      for d, v in sorted(daily.items())],
            "purchases": purchases,
            "price_history": history,
            "stock": stock,
        }

    async def sku_card(self, guid: str, date_from: date, date_to: date,
                       stations: list[str] | None = None) -> dict:
        """Полная карточка номенклатуры для товароведа: паспорт НСИ + штрихкоды +
        цена/остаток + продажи + поставщики + движение + рецептура ТТК + МРЦ.
        = sku_detail (метрики/продажи/закупки/цены/остаток) + тяжёлые расширения
        (движение по SKU, все ШК), считается только при открытии карточки."""
        base = await self.sku_detail(guid, date_from, date_to, stations)
        nom = await self._names()
        n = nom.get(guid)
        groups = await self._refs("nom_group")

        base["group"] = (groups.get(n.group_ref) if (n and n.group_ref) else None)

        # штрихкоды (в регистре ЦБ owner_ref пуст → матч по owner_name)
        barcodes: list[dict] = []
        if n and n.name:
            for b in (await self.session.execute(select(CbBarcode).where(
                    CbBarcode.company_id == self.company_id,
                    CbBarcode.owner_name == n.name))).scalars().all():
                barcodes.append({"barcode": b.barcode, "type": b.btype, "main": bool(b.main)})
        # основной — вперёд, затем EAN13, EAN8, ручные
        _ord = {"EAN13": 0, "EAN8": 1}
        barcodes.sort(key=lambda x: (not x["main"], _ord.get(x["type"] or "", 9), x["barcode"] or ""))
        base["barcodes"] = barcodes

        # МРЦ табака (если задана) + факт нарушения по текущей рознице
        mrc_row = (await self.session.execute(select(TobaccoMrc).where(
            TobaccoMrc.company_id == self.company_id,
            TobaccoMrc.nomenclature_ref == guid))).scalar_one_or_none()
        price_now = max((s["retail_price"] for s in base["stock"] if s["retail_price"] is not None), default=None)
        base["mrc"] = None
        if mrc_row:
            base["mrc"] = {
                "mrc": round(float(mrc_row.mrc), 2), "retail_price": price_now,
                "over": price_now is not None and price_now > float(mrc_row.mrc) + 0.001,
            }

        # рецептура ТТК (если блюдо) — ингредиенты из строк продаж общепита
        recipe: list[dict] = []
        for m in self._select(await self._load(), date_from, date_to, stations):
            for ln in ((m.get("Секции") or {}).get("продажа_общепит") or {}).get("строки") or []:
                if ln.get("Номенклатура") == guid and (ln.get("Ингредиенты") or []):
                    for ing in ln["Ингредиенты"]:
                        ig = nom.get(ing.get("Номенклатура"))
                        recipe.append({"name": (ig.name if ig else str(ing.get("Номенклатура"))[:8]),
                                       "qty": round(float(ing.get("Количество") or 0), 3)})
                    break
            if recipe:
                break
        base["recipe"] = recipe

        # Движение по SKU за тот же период и по тем же станциям, что продажи.
        movement: list[dict] = []
        for kind in ("writeoff", "transfer"):
            movement_docs = (await self.session.execute(select(CbMovementDoc).where(
                CbMovementDoc.company_id == self.company_id,
                CbMovementDoc.deleted.is_(False), CbMovementDoc.posted.is_(True),
                CbMovementDoc.kind == kind))).scalars().all()
            movement_docs = self._by_period(movement_docs, date_from, date_to)
            if stations:
                movement_docs = [
                    r for r in movement_docs
                    if _warehouse_in_stations(r.warehouse_code, stations)
                    or (kind == "transfer" and _warehouse_in_stations(r.warehouse_to_code, stations))
                ]
            for r in movement_docs:
                for ln in (r.lines or []):
                    if ln.get("ref") == guid:
                        movement.append({"kind": kind, "date": r.doc_date, "number": r.number,
                                         "qty": ln.get("qty"), "amount": ln.get("amount"),
                                         "reason": r.reason})
                        break
        inventory_docs = (await self.session.execute(select(CbInventoryDoc).where(
            CbInventoryDoc.company_id == self.company_id,
            CbInventoryDoc.deleted.is_(False)))).scalars().all()
        inventory_docs = self._by_period(inventory_docs, date_from, date_to)
        if stations:
            inventory_docs = [
                r for r in inventory_docs if _warehouse_in_stations(r.warehouse_code, stations)
            ]
        for r in inventory_docs:
            for ln in (r.lines or []):
                # lines теперь полная ТЧ — движение по SKU только из строк-отклонений
                if ln.get("ref") == guid and ln.get("dev"):
                    movement.append({"kind": "inventory", "date": r.doc_date, "number": r.number,
                                     "qty": ln.get("dev"), "amount": ln.get("amount_dev"),
                                     "reason": "отклонение факт−учёт"})
                    break
        movement.sort(key=lambda x: (x["date"] or ""), reverse=True)
        base["movement"] = movement
        return base

    # ── Ассортимент: ABC×XYZ + оборачиваемость/запасы (реальный остаток) + GMROI ──
    async def assortment_analysis(self, date_from: date, date_to: date, *,
                                  category: str = "all", stations: list[str] | None = None) -> dict:
        """Управление ассортиментом: матрица ABC (вклад в выручку) × XYZ (стабильность
        спроса, CV дневных продаж), оборачиваемость (дни запаса на реальном остатке),
        GMROI, дефицит/неликвиды и action-list по SKU."""
        data = await self.sku_analytics(date_from, date_to, stations)
        skus = data["skus"]
        nom = await self._names()
        catmap = {"soputka": "Сопутка", "obshepit": "Общепит"}
        # реальный остаток из StockOnHand выбранных станций
        soh = (await self.session.execute(select(StockOnHand).where(
            StockOnHand.company_id == self.company_id))).scalars().all()
        stk: dict[str, dict] = defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "retail": 0.0})
        for r in soh:
            if _warehouse_in_stations(r.warehouse_code, stations):
                q = float(r.quantity or 0)
                a = stk[r.nomenclature_ref]; a["qty"] += q
                if r.cost_unit is not None:
                    a["cost"] += q * float(r.cost_unit)
                if r.retail_price is not None:
                    a["retail"] += q * float(r.retail_price)

        # продажи по SKU по дням → недельные корзины ПО ФАКТИЧЕСКОМУ окну данных.
        # ⚠ период может быть шире данных (данные только апрель) — пустые недели
        # вне окна ломают XYZ (всё → Z) и оборачиваемость (всё → затоварка). Берём
        # реальный диапазон дат продаж (span), а не запрошенный период.
        dsku: dict[str, dict] = defaultdict(lambda: defaultdict(float))
        sale_dates: set = set()
        ingredient_refs: set = set()  # ингредиенты ТТК — не считать неликвидом (расходуются)
        for m in self._select(await self._load(), date_from, date_to, stations):
            day = _day(m.get("Смена") or {})
            if not day:
                continue
            sale_dates.add(day)
            for sk, _ in _SECTIONS:
                for ln in (((m.get("Секции") or {}).get(sk)) or {}).get("строки") or []:
                    g = ln.get("Номенклатура")
                    if g:
                        dsku[g][day] += float(ln.get("Количество") or 0)
                    if sk == "продажа_общепит":
                        for ing in ln.get("Ингредиенты") or []:
                            if ing.get("Номенклатура"):
                                ingredient_refs.add(ing.get("Номенклатура"))
        if sale_dates:
            d0 = date.fromisoformat(min(sale_dates))
            span_days = (date.fromisoformat(max(sale_dates)) - d0).days + 1
        else:
            d0, span_days = date_from, (date_to - date_from).days + 1
        n_weeks = max(1, (span_days + 6) // 7)

        def _week(dayiso: str) -> int:
            try:
                return min(n_weeks - 1, max(0, (date.fromisoformat(dayiso) - d0).days // 7))
            except ValueError:
                return 0

        def _xyz(g: str, qty_total: float):
            if qty_total <= 0:
                return "Z", None
            if n_weeks < 2:
                return "X", None  # одно активное окно — считаем стабильным
            buckets = [0.0] * n_weeks
            for dd, qv in dsku.get(g, {}).items():
                buckets[_week(dd)] += qv
            mean = sum(buckets) / n_weeks
            if mean <= 0:
                return "Z", None
            cv = ((sum((v - mean) ** 2 for v in buckets) / n_weeks) ** 0.5) / mean
            return ("X" if cv <= 0.5 else "Y" if cv <= 1.0 else "Z"), round(cv, 2)

        def _action(abc: str, xyz: str, status: str) -> str:
            if status == "dead":
                return "Неликвид — распродать / вывести"
            if status == "out_of_stock":
                return "Нет на остатке — пополнить" + (" срочно" if abc in ("A", "B") else "")
            if status == "overstock":
                return "Затоварка — снизить закупку"
            if abc == "A" and xyz == "X":
                return "Ядро ассортимента — не допускать дефицит"
            if abc == "A":
                return "Важный — держать, страховой запас"
            if abc == "C" and xyz == "Z":
                return "Кандидат на вывод"
            return "Держать"

        matrix: dict[str, dict] = defaultdict(lambda: {"count": 0, "revenue": 0.0})
        rows = []
        for s in skus:
            if category in catmap and s["category"] != catmap[category]:
                continue
            g = s["guid"]; qty = s["qty"]
            st = stk.get(g, {"qty": 0.0, "cost": 0.0, "retail": 0.0})
            sq, sc, sr = st["qty"], st["cost"], st["retail"]
            xcls, cv = _xyz(g, qty)
            cell = f'{s["abc"]}{xcls}'
            avg_daily = qty / span_days if span_days else 0  # по окну данных, не периоду
            dos = round(sq / avg_daily, 1) if avg_daily > 0 and sq > 0 else None
            gmroi = round(s["margin"] / sc, 2) if s["margin"] is not None and sc > 0 else None
            dead = sq > 0 and qty <= 0
            oos = sq <= 0 and qty > 0
            overstock = dos is not None and dos > 90
            status = "dead" if dead else ("out_of_stock" if oos else ("overstock" if overstock else "ok"))
            # продажа ниже себестоимости (надёжная себест.) — регуляторный/маржинальный риск (О-3)
            loss = bool(s["margin_pct"] is not None and s["margin_pct"] < 0 and s.get("cost_reliable"))
            matrix[cell]["count"] += 1; matrix[cell]["revenue"] += s["revenue"]
            rows.append({
                "guid": g, "name": s["name"], "category": s["category"],
                "revenue": s["revenue"], "qty": s["qty"], "avg_price": s["avg_price"],
                "margin": s["margin"], "margin_pct": s["margin_pct"], "marked": s["marked"],
                "cost_reliable": s.get("cost_reliable", False),
                "abc": s["abc"], "xyz": xcls, "cv": cv, "abc_xyz": cell,
                "stock_qty": round(sq, 3), "stock_cost": round(sc, 2), "stock_retail": round(sr, 2),
                "days_of_supply": dos, "gmroi": gmroi, "status": status, "loss": loss,
                "action": ("⚠ Ниже себестоимости — проверить цену" if loss else _action(s["abc"], xcls, status)),
            })

        # неликвиды: есть остаток, но НЕ продавались в периоде (в sku_analytics их нет).
        # Категория неизвестна → только в общем срезе (category='all').
        if category == "all":
            sold = {s["guid"] for s in skus}
            for ref, st in stk.items():
                if st["qty"] > 0 and ref not in sold and ref not in ingredient_refs:
                    nn = nom.get(ref)
                    matrix["CZ"]["count"] += 1
                    rows.append({
                        "guid": ref, "name": (nn.name if nn else ref[:8]), "category": None,
                        "revenue": 0.0, "qty": 0.0, "avg_price": 0.0, "margin": None, "margin_pct": None,
                        "marked": bool(nn and nn.marked), "abc": "C", "xyz": "Z", "cv": None, "abc_xyz": "CZ",
                        "stock_qty": round(st["qty"], 3), "stock_cost": round(st["cost"], 2),
                        "stock_retail": round(st["retail"], 2),
                        "days_of_supply": None, "gmroi": None, "status": "dead",
                        "action": "Неликвид — распродать / вывести",
                    })
        rows.sort(key=lambda x: (-x["revenue"], -x["stock_cost"]))

        costed = [r for r in rows if r["margin"] is not None]
        dead_r = [r for r in rows if r["status"] == "dead"]
        oos_r = [r for r in rows if r["status"] == "out_of_stock"]
        over_r = [r for r in rows if r["status"] == "overstock"]
        tot_margin = sum(r["margin"] for r in costed)
        tot_stock_cost = sum(r["stock_cost"] for r in rows)
        # GMROI: знаменатель — запас costed-позиций (числитель costed), сопоставимо (К-14)
        gmroi_stock = sum(r["stock_cost"] for r in costed) or 0.0
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "category": category,
            "summary": {
                "sku_count": len(rows),
                "stock_cost": round(tot_stock_cost, 2),
                "stock_retail": round(sum(r["stock_retail"] for r in rows), 2),
                "gmroi": round(tot_margin / gmroi_stock, 2) if gmroi_stock > 0 else None,
                "dead_count": len(dead_r), "dead_cost": round(sum(r["stock_cost"] for r in dead_r), 2),
                "oos_count": len(oos_r), "loss_count": sum(1 for r in rows if r.get("loss")),
                "overstock_count": len(over_r), "overstock_cost": round(sum(r["stock_cost"] for r in over_r), 2),
            },
            "abc": data["abc"],
            "matrix": {k: {"count": v["count"], "revenue": round(v["revenue"], 2)} for k, v in matrix.items()},
            "skus": rows,
        }


    # ── Приёмка (реестр поступлений) ──
    async def receipts(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        metas = await self._load_purchases(date_from, date_to, stations)
        cparty = await self._refs("counterparty")
        nom_names = {ref: n.name for ref, n in (await self._names()).items()}
        docs = []
        tot_net = tot_vat = 0.0
        for m in metas:
            d = m.get("Документ") or {}
            lines = d.get("Товары") or []
            amt = sum(float(l.get("Сумма") or 0) for l in lines)
            vat = sum(float(l.get("СуммаНДС") or 0) for l in lines)
            net = sum(self._purch_net(d, l) for l in lines)   # F8: учёт СуммаВключаетНДС
            docs.append({
                "date": str(d.get("Дата") or "")[:10],
                "number": d.get("Номер"),
                # Смена берётся из самой записи: поступления приезжают из ЦБ вместе со
                # сменным отчётом, гадать по дню (как для витринных) не надо.
                "shift_number": (m.get("Смена") or {}).get("НомерСмены") or None,
                "supplier": cparty.get(d.get("Контрагент")) or (d.get("Контрагент") or "—"),
                # Кто завёл документ. В переходный период это первый вопрос к
                # приходу: станция приняла товар у себя или его ввели из центра,
                # разбирая архив 1С. Без подписи оба выглядят одинаково, а
                # отвечают за них разные люди.
                "author": (d.get("Автор") or "").strip() or "—",
                "positions": len(lines),
                "amount": round(amt, 2), "vat": round(vat, 2), "amount_net": round(net, 2),
                # Состав накладной — для расшифровки строки реестра и поставщика. Формат
                # тот же, что у остальных документных экранов (ref/name/qty/amount), чтобы
                # фронт открывал их одной модалкой.
                "lines": [{"ref": l.get("Номенклатура"), "name": nom_names.get(l.get("Номенклатура") or ""),
                           "qty": float(l.get("Количество") or 0),
                           "amount": round(float(l.get("Сумма") or 0), 2),
                           "amount_net": round(self._purch_net(d, l), 2)} for l in lines],
            })
            tot_net += net
            tot_vat += vat
        docs.sort(key=lambda x: x["date"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "docs": docs,
            "summary": {"count": len(docs), "amount_net": round(tot_net, 2), "vat": round(tot_vat, 2)},
        }

    # ── Поставщики ──
    async def _item_groups(self) -> dict[str, str]:
        """Карта «номенклатура 1С → ветка каталога».

        Карточки Ledger и номенклатура ЦБ связаны по UUID полностью, поэтому
        закупки раскладываются по тем же группам, что и ассортимент. Без этого
        про поставщика можно сказать только «сумма и документы» — а вопрос у
        товароведа другой: что именно он у него берёт.
        """
        if getattr(self, "_grp_cache", None) is not None:
            return self._grp_cache
        rows = (await self.session.execute(text("""
            SELECT i.external_uuid::text AS ref, g.path
            FROM edge.item i JOIN edge.item_group g ON g.id = i.group_id
        """))).mappings().all()
        self._grp_cache = {r["ref"]: r["path"] for r in rows}
        return self._grp_cache

    async def _item_marked(self) -> set[str]:
        """Маркируемые позиции — по каталогу Ledger, обогащённому из 1С."""
        if getattr(self, "_marked_cache", None) is not None:
            return self._marked_cache
        rows = (await self.session.execute(text(
            "SELECT external_uuid::text AS ref FROM edge.item WHERE marked"))).mappings().all()
        self._marked_cache = {r["ref"] for r in rows}
        return self._marked_cache

    async def supplier_history(self, station: str | None = None) -> dict[str, dict]:
        """Сводка работы с каждым поставщиком по документам 1С: {имя: {...}}.

        Нужна станции. Она видит только то, что принимала сама, а реальные
        поставки за годы лежат в ЦБ — без них её справочник выглядит пустым,
        хотя товаровед точно помнит, что этот поставщик возит каждую неделю.
        Считаем здесь и отдаём вниз сводкой: три числа и дата на контрагента,
        канал не жалко.
        """
        metas = await self._load_purchases(date(2000, 1, 1), date(2100, 1, 1),
                                           [station] if station else None)
        cparty = await self._refs("counterparty")
        свод: dict[str, dict] = {}
        даты: dict[str, list[str]] = {}
        for m in metas:
            d = m.get("Документ") or {}
            имя = cparty.get(d.get("Контрагент")) or (d.get("Контрагент") or "")
            if not имя:
                continue
            lines = d.get("Товары") or []
            запись = свод.setdefault(имя, {
                "docs_1c": 0, "amount_1c": 0.0, "positions_1c": set(), "last_1c": None,
            })
            запись["docs_1c"] += 1
            запись["amount_1c"] += sum(self._purch_net(d, l) for l in lines)
            for l in lines:
                if l.get("Номенклатура"):
                    запись["positions_1c"].add(l["Номенклатура"])
            дата = str(d.get("Дата") or "")[:10]
            if дата:
                даты.setdefault(имя, []).append(дата)
                if not запись["last_1c"] or дата > запись["last_1c"]:
                    запись["last_1c"] = дата
        out: dict[str, dict] = {}
        for имя, з in свод.items():
            свои = sorted(даты.get(имя, []))
            интервал = None
            if len(свои) > 1:
                интервал = round(
                    (date.fromisoformat(свои[-1]) - date.fromisoformat(свои[0])).days
                    / (len(свои) - 1), 1)
            out[имя] = {
                "docs_1c": з["docs_1c"],
                "amount_1c": round(з["amount_1c"], 2),
                "positions_1c": len(з["positions_1c"]),
                "last_1c": з["last_1c"],
                "first_1c": свои[0] if свои else None,
                "avg_days_1c": интервал,
            }
        return out

    async def supplier_card(self, name: str, date_from: date, date_to: date,
                            stations: list[str] | None = None) -> dict:
        """Карточка одного поставщика: история поставок, что возит, как менялись цены.

        Отношения с поставщиком — половина работы товароведа, а до сих пор про него
        была строка в отчёте: сумма, документы, число SKU. На вопросы «почём в прошлый
        раз», «когда привозил», «что вообще у него берём» отвечать было нечем — данные
        в 1С есть, просто никто их не разворачивал.

        Период ограничивает документы, а НЕ историю цен: сравнение «стало дороже»
        имеет смысл только с прошлой поставкой, даже если она была до начала периода.
        """
        metas = await self._load_purchases(date(2000, 1, 1), date(2100, 1, 1), stations)
        cparty = await self._refs("counterparty")
        nom_names = {ref: n.name for ref, n in (await self._names()).items()}
        returns = await self._load_returns()

        свои = []
        for m in metas:
            d = m.get("Документ") or {}
            имя = cparty.get(d.get("Контрагент")) or (d.get("Контрагент") or "—")
            if имя != name:
                continue
            свои.append((str(d.get("Дата") or "")[:10], d, m))
        свои.sort(key=lambda x: x[0], reverse=True)

        docs, позиции = [], {}
        оборот = 0.0
        for дата, d, m in свои:
            lines = d.get("Товары") or []
            net = sum(self._purch_net(d, l) for l in lines)
            в_периоде = date_from.isoformat() <= дата <= date_to.isoformat()
            if в_периоде:
                docs.append({
                    "date": дата, "number": d.get("Номер"),
                    "incoming": d.get("ВходящийНомер") or None,
                    "station": (m.get("Смена") or {}).get("Станция")
                               or m.get("Станция") or None,
                    "positions": len(lines),
                    "amount": round(sum(float(l.get("Сумма") or 0) for l in lines), 2),
                    "amount_net": round(net, 2),
                    "lines": [{"ref": l.get("Номенклатура"),
                               "name": nom_names.get(l.get("Номенклатура") or ""),
                               "qty": float(l.get("Количество") or 0),
                               "price": round(float(l.get("Цена") or 0), 2),
                               "amount_net": round(self._purch_net(d, l), 2)} for l in lines],
                })
                оборот += net
            # Позиции и цены собираем по ВСЕЙ истории: «в прошлый раз было столько»
            # не должно зависеть от того, какой период выбран на экране.
            for l in lines:
                ref = l.get("Номенклатура")
                if not ref:
                    continue
                qty = float(l.get("Количество") or 0)
                цена = round(float(l.get("Цена") or 0), 2)
                it = позиции.setdefault(ref, {
                    "ref": ref, "name": nom_names.get(ref) or ref, "qty": 0.0,
                    "amount_net": 0.0, "docs": 0, "last_price": None,
                    "prev_price": None, "last_date": None,
                })
                if в_периоде:
                    it["qty"] += qty
                    it["amount_net"] += self._purch_net(d, l)
                    it["docs"] += 1
                if цена > 0:
                    if it["last_price"] is None:
                        it["last_price"], it["last_date"] = цена, дата
                    elif it["prev_price"] is None and цена != it["last_price"]:
                        it["prev_price"] = цена

        items = [i for i in позиции.values() if i["docs"] > 0]
        for i in items:
            i["amount_net"] = round(i["amount_net"], 2)
            if i["last_price"] and i["prev_price"]:
                i["price_delta_pct"] = round(
                    (i["last_price"] - i["prev_price"]) / i["prev_price"] * 100, 1)
            else:
                i["price_delta_pct"] = None
        items.sort(key=lambda x: -x["amount_net"])

        # Возвраты этому поставщику: разговор о качестве начинается с них.
        возвраты = []
        for m in returns:
            d = m.get("Документ") or {}
            если_имя = cparty.get(d.get("Контрагент")) or (d.get("Контрагент") or "—")
            if если_имя != name:
                continue
            возвраты.append({
                "date": str(d.get("Дата") or "")[:10], "number": d.get("Номер"),
                "positions": len(d.get("Товары") or []),
                "amount": round(sum(float(l.get("Сумма") or 0)
                                    for l in (d.get("Товары") or [])), 2),
            })
        возвраты.sort(key=lambda x: x["date"], reverse=True)

        # Разрезы, ради которых карточку и открывают: что за категории он
        # возит, как шли закупки по месяцам, велика ли зависимость от него.
        группы_карта = await self._item_groups()
        маркируемые = await self._item_marked()
        по_группам: dict[str, dict] = {}
        по_месяцам: dict[str, dict] = {}
        маркир_сумма = 0.0
        for дата, d, _ in свои:
            if not (date_from.isoformat() <= дата <= date_to.isoformat()):
                continue
            месяц = дата[:7]
            м = по_месяцам.setdefault(месяц, {"month": месяц, "docs": 0, "amount_net": 0.0})
            м["docs"] += 1
            for l in (d.get("Товары") or []):
                ref = l.get("Номенклатура") or ""
                net = self._purch_net(d, l)
                м["amount_net"] += net
                путь = группы_карта.get(ref) or "— не разобрано"
                г = по_группам.setdefault(путь, {"group": путь, "amount_net": 0.0, "positions": set()})
                г["amount_net"] += net
                г["positions"].add(ref)
                if ref in маркируемые:
                    маркир_сумма += net

        группы = [{"group": г["group"], "amount_net": round(г["amount_net"], 2),
                   "positions": len(г["positions"])} for г in по_группам.values()]
        группы.sort(key=lambda x: -x["amount_net"])
        месяцы = [{"month": м["month"], "docs": м["docs"],
                   "amount_net": round(м["amount_net"], 2)} for м in по_месяцам.values()]
        месяцы.sort(key=lambda x: x["month"])

        # Доля в закупках и монополия на позиции: зависимость от поставщика —
        # не абстракция. Если он один возит сорок позиций, его срыв это дыра на
        # полке, которую нечем закрыть.
        все = await self._load_purchases(date_from, date_to, stations)
        всего_закупки = 0.0
        поставщики_позиции: dict[str, set[str]] = {}
        for m in все:
            d = m.get("Документ") or {}
            имя = cparty.get(d.get("Контрагент")) or (d.get("Контрагент") or "—")
            for l in (d.get("Товары") or []):
                всего_закупки += self._purch_net(d, l)
                ref = l.get("Номенклатура")
                if ref:
                    поставщики_позиции.setdefault(ref, set()).add(имя)
        эксклюзив = sum(1 for i in items
                        if поставщики_позиции.get(i["ref"], set()) == {name})
        подорожало = sum(1 for i in items if (i["price_delta_pct"] or 0) > 0)
        подешевело = sum(1 for i in items if (i["price_delta_pct"] or 0) < 0)

        даты = [дата for дата, _, _ in свои]
        интервал = None
        if len(даты) > 1:
            первая, последняя = date.fromisoformat(даты[-1]), date.fromisoformat(даты[0])
            интервал = round((последняя - первая).days / (len(даты) - 1), 1)
        return {
            "name": name,
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "totals": {
                "docs": len(docs), "amount_net": round(оборот, 2),
                "positions": len(items),
                "docs_all_time": len(свои),
                "first": даты[-1] if даты else None,
                "last": даты[0] if даты else None,
                "avg_days": интервал,
                "returns": len(возвраты),
            },
            "docs": docs, "items": items, "returns": возвраты,
            "by_group": группы, "by_month": месяцы,
            "analytics": {
                "share_pct": round(оборот / всего_закупки * 100, 1) if всего_закупки else None,
                "avg_doc": round(оборот / len(docs), 2) if docs else None,
                "exclusive_positions": эксклюзив,
                "marked_share_pct": round(маркир_сумма / оборот * 100, 1) if оборот else None,
                "price_up": подорожало, "price_down": подешевело,
            },
        }

    async def suppliers(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        metas = await self._load_purchases(date_from, date_to, stations)
        cparty = await self._refs("counterparty")
        agg: dict[str, dict] = defaultdict(lambda: {"net": 0.0, "docs": 0, "skus": set()})
        for m in metas:
            d = m.get("Документ") or {}
            c = d.get("Контрагент") or "—"
            lines = d.get("Товары") or []
            agg[c]["net"] += sum(self._purch_net(d, l) for l in lines)   # F8
            agg[c]["docs"] += 1
            for l in lines:
                agg[c]["skus"].add(l.get("Номенклатура"))
        rows = [{
            "name": cparty.get(c) or c, "amount_net": round(v["net"], 2),
            "docs": v["docs"], "sku_count": len(v["skus"]),
        } for c, v in agg.items()]
        rows.sort(key=lambda x: -x["amount_net"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "suppliers": rows,
            "summary": {"count": len(rows), "amount_net": round(sum(r["amount_net"] for r in rows), 2)},
        }

    # OB-4/K-2: старый catering() (оконная база _avg_cost) → тонкий алиас на
    # catering_menu (единая all-time база _cost_unit_map). Раньше давал третью,
    # расходящуюся базу food-cost; теперь одна база для всех экранов общепита.
    # (метод-маршрут store_report сохранён, чтобы не трогать роутер.)
    async def catering(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        return await self.catering_menu(date_from, date_to, stations)

    # ── Общепит — инжиниринг меню (продажи блюд + состав ТТК + динамика) ──
    async def _catering_menu_legacy(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        """Менеджерская аналитика общепита: по каждому блюду — продажи, фудкост, маржа,
        класс меню (Звезда/Загадка/Рабочая лошадка/Собака), состав ТТК (ингредиенты с
        себестоимостью на порцию) и дневная динамика продаж (для раскрытия строки)."""
        sale_metas = self._select(await self._load(), date_from, date_to, stations)
        avgc = {g: c[0] for g, c in (await self._cost_unit_map(stations)).items()}  # закуп-net all-time
        # Себестоимость от 1С по документу выпуска — то, чем реально закрывается смена.
        rel = await self._release_cost_unit(date_from, date_to, stations)
        nom = await self._names()

        def _dish():
            return {"qty": 0.0, "rev": 0.0, "revnet": 0.0, "cost": 0.0, "cost_known": False,
                    "ings": defaultdict(lambda: {"qty": 0.0, "cost": 0.0, "known": False}),
                    "daily": defaultdict(lambda: {"qty": 0.0, "rev": 0.0})}
        dishes: dict[str, dict] = defaultdict(_dish)
        for m in sale_metas:
            day = _day(m.get("Смена") or {})
            for ln in ((m.get("Секции") or {}).get("продажа_общепит") or {}).get("строки") or []:
                g = ln.get("Номенклатура")
                if not g:
                    continue
                q = float(ln.get("Количество") or 0)
                rev = float(ln.get("Сумма") or 0)
                revnet = rev - float(ln.get("СуммаНДС") or 0)
                d = dishes[g]
                d["qty"] += q; d["rev"] += rev; d["revnet"] += revnet
                dd = d["daily"][day]; dd["qty"] += q; dd["rev"] += rev
                for ing in ln.get("Ингредиенты") or []:
                    ig = ing.get("Номенклатура"); iq = float(ing.get("Количество") or 0)
                    ii = d["ings"][ig]; ii["qty"] += iq
                    if ig in avgc:
                        c = iq * avgc[ig]; ii["cost"] += c; ii["known"] = True
                        d["cost"] += c; d["cost_known"] = True

        # покрытие ТТК: доля ингредиентов с известной себест. Costed только при ≥90%
        # (OB-3/К-5): при 60–89% food-cost занижен (cost по части состава) и класс
        # меню неверен — такие блюда «предварительные», вне сводной costed-маржи.
        for d in dishes.values():
            tot_ing = len(d["ings"])
            d["coverage"] = (sum(1 for ii in d["ings"].values() if ii["known"]) / tot_ing) if tot_ing else 0.0
            d["covered"] = tot_ing > 0 and d["coverage"] >= _TTK_COVERAGE_MIN

        total_rev = sum(x["rev"] for x in dishes.values()) or 1.0
        total_qty = sum(x["qty"] for x in dishes.values()) or 1.0
        n_dishes = len(dishes) or 1
        # классический порог популярности Kasavana–Smith: 70% от равной доли
        pop_threshold = (100.0 / n_dishes) * 0.7
        costed_margin = sum((x["revnet"] - x["cost"]) for x in dishes.values() if x["covered"])
        costed_qty = sum(x["qty"] for x in dishes.values() if x["covered"]) or 1.0
        avg_cm = costed_margin / costed_qty  # средняя вклад-маржа на порцию

        matrix: dict[str, dict] = defaultdict(lambda: {"count": 0, "revenue": 0.0})
        rows = []
        for g, d in dishes.items():
            nnn = nom.get(g)
            qty, rev, revnet = d["qty"], d["rev"], d["revnet"]
            # Порядок источников: выпуск 1С → сборка по ТТК (только при полном покрытии).
            # Сборка занижена по природе (средняя закупка вместо себестоимости списания),
            # поэтому она запасная, а не основная.
            unit = rel.get(g)
            if unit is not None:
                cost, cost_source = unit * qty, "release"
            elif d["covered"]:
                cost, cost_source = d["cost"], "ttk"
            else:
                cost, cost_source = None, None
            margin = (revnet - cost) if cost is not None else None
            food_cost = (100 * cost / revnet) if cost is not None and revnet else None
            margin_pct = (100 * margin / revnet) if margin is not None and revnet else None
            cm_unit = (margin / qty) if margin is not None and qty else None
            pop = 100 * qty / total_qty
            if cost is None:
                cls = "unknown"
            else:
                high_pop = pop >= pop_threshold
                high_cm = (cm_unit or 0) >= avg_cm
                cls = ("star" if high_pop and high_cm else
                       "plowhorse" if high_pop and not high_cm else
                       "puzzle" if not high_pop and high_cm else "dog")
            matrix[cls]["count"] += 1; matrix[cls]["revenue"] += rev
            ings = []
            for ig, ii in d["ings"].items():
                inm = nom.get(ig)
                ings.append({
                    "ref": ig, "name": (inm.name if inm else str(ig)[:8]),
                    "marked": bool(inm and inm.marked),
                    "qty_total": round(ii["qty"], 3),
                    "qty_per_portion": round(ii["qty"] / qty, 4) if qty else None,
                    "cost_total": round(ii["cost"], 2) if ii["known"] else None,
                    "cost_per_portion": round(ii["cost"] / qty, 4) if ii["known"] and qty else None,
                })
            ings.sort(key=lambda x: -(x["cost_total"] or 0))
            daily = [{"date": dt, "qty": round(v["qty"], 2), "revenue": round(v["rev"], 2)}
                     for dt, v in sorted(d["daily"].items())]
            rows.append({
                "guid": g, "name": (nnn.name if nnn else str(g)[:8]),
                "qty": round(qty, 2), "revenue": round(rev, 2), "revenue_net": round(revnet, 2),
                "avg_price": round(rev / qty, 2) if qty else 0.0,
                "cost": round(cost, 2) if cost is not None else None,
                "cost_per_portion": round(cost / qty, 2) if cost is not None and qty else None,
                "margin": round(margin, 2) if margin is not None else None,
                "food_cost_pct": round(food_cost, 1) if food_cost is not None else None,
                "margin_pct": round(margin_pct, 1) if margin_pct is not None else None,
                "cm_unit": round(cm_unit, 2) if cm_unit is not None else None,
                "share": round(100 * rev / total_rev, 1),
                "popularity_pct": round(pop, 1),
                "menu_class": cls,
                "coverage": round(100 * d["coverage"]),
                # Чем посчитана себестоимость: выпуском 1С или сборкой по ТТК. На экране
                # это подпись под цифрой — иначе непонятно, почему у соседних блюд
                # разная точность.
                "cost_source": cost_source,
                # OB-3: 60–89% покрытия — себестоимость частичная, показываем как
                # «предварительную» (в costed-маржу не входит, cost=None выше).
                "preliminary": (not d["covered"]) and d["coverage"] >= 0.6,
                "ing_count": len(ings),
                "ingredients": ings,
                "daily": daily,
            })
        rows.sort(key=lambda x: -x["revenue"])

        tot_cost = sum(r["cost"] for r in rows if r["cost"] is not None)
        tot_revnet_costed = sum(r["revenue_net"] for r in rows if r["cost"] is not None)
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "summary": {
                "dishes_count": len(rows),
                "dishes_costed": sum(1 for r in rows if r["cost"] is not None),
                "revenue": round(sum(r["revenue"] for r in rows), 2),
                "revenue_net": round(sum(r["revenue_net"] for r in rows), 2),
                # Выручка ТЕХ блюд, по которым известна себестоимость: фудкост и прибыль
                # считаются от неё, а не от общей. Пока это не отдавалось наружу, плитки
                # «прибыль» и «выручка» стояли рядом на разных базах и читались как
                # рентабельность в разы ниже фактической.
                "revenue_costed": round(sum(r["revenue"] for r in rows if r["cost"] is not None), 2),
                "portions": round(sum(r["qty"] for r in rows), 2),
                "cost": round(tot_cost, 2),
                "margin": round(tot_revnet_costed - tot_cost, 2),
                "food_cost_pct": round(100 * tot_cost / tot_revnet_costed, 1) if tot_revnet_costed else None,
                "margin_pct": round(100 * (tot_revnet_costed - tot_cost) / tot_revnet_costed, 1) if tot_revnet_costed else None,
            },
            "matrix": {k: {"count": v["count"], "revenue": round(v["revenue"], 2)} for k, v in matrix.items()},
            "dishes": rows,
        }

    async def _catering_return_documents(self, date_from: date, date_to: date,
                                           stations: list[str] | None,
                                           dish_ids: set[str]) -> dict:
        rows = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id,
            DataEntry.layer == "clean",
            DataEntry.source == "edge",
            DataEntry.doc_type_id == "return_sale",
            DataEntry.status != "superseded",
        ))).scalars().all()
        total: dict[str, dict] = defaultdict(lambda: {
            "returns": 0.0, "return_vat": 0.0, "vat_missing": 0})
        by_key: dict[tuple[str, str], dict[str, dict]] = defaultdict(
            lambda: defaultdict(lambda: {"returns": 0.0, "return_vat": 0.0,
                                          "vat_missing": 0}))
        for row in rows:
            meta, document = row.meta or {}, (row.meta or {}).get("Документ") or {}
            station = str((meta.get("Смена") or {}).get("КодАЗС") or
                          (meta.get("Edge") or {}).get("station_id") or "")
            day = str(document.get("Дата") or _day(meta.get("Смена") or {}))[:10]
            if not day or not (date_from.isoformat() <= day <= date_to.isoformat()):
                continue
            if stations and station not in stations:
                continue
            for line in document.get("Товары") or []:
                dish = str(line.get("Номенклатура") or "")
                if dish not in dish_ids:
                    continue
                for target in (total[dish], by_key[(station, _week_of(day))][dish]):
                    target["returns"] += abs(_num(line.get("Сумма")))
                    if line.get("СуммаНДС") is None:
                        target["vat_missing"] += 1
                    else:
                        target["return_vat"] += abs(_num(line.get("СуммаНДС")))
        return {"total": total, "by_key": by_key}

    async def _catering_losses(self, date_from: date, date_to: date,
                               stations: list[str] | None,
                               kitchen_items: set[str]) -> dict:
        rows = (await self.session.execute(select(DataEntry).where(
            DataEntry.company_id == self.company_id,
            DataEntry.layer == "clean",
            DataEntry.source == "edge",
            DataEntry.doc_type_id.in_(("writeoff", "inventory")),
            DataEntry.status != "superseded",
        ))).scalars().all()
        empty = lambda: {"writeoffs": 0.0, "shortages": 0.0, "exact": 0.0,
                         "estimated": 0.0, "missing_docs": 0, "documents": 0}
        total = empty()
        by_key: dict[tuple[str, str], dict] = defaultdict(empty)
        for row in rows:
            meta = row.meta or {}
            document = meta.get("Документ") or {}
            if document.get("СлужебныйДокумент"):
                continue
            station = str((meta.get("Смена") or {}).get("КодАЗС") or
                          (meta.get("Edge") or {}).get("station_id") or "")
            day = str(document.get("Дата") or _day(meta.get("Смена") or {}))[:10]
            if not day or not (date_from.isoformat() <= day <= date_to.isoformat()):
                continue
            if stations and station not in stations:
                continue
            targets = (total, by_key[(station, _week_of(day))])
            evidence = document.get("СебестоимостьИнгредиентов") or {}
            evidence_items = [item for item in evidence.get("items") or []
                              if str(item.get("item_uuid") or "") in kitchen_items]
            if evidence_items:
                for target in targets:
                    target["documents"] += 1
                for item in evidence_items:
                    amount = _num(item.get("amount"))
                    bucket = "shortages" if row.doc_type_id == "inventory" else "writeoffs"
                    status = "exact" if item.get("status") == "known" else "estimated"
                    for target in targets:
                        target[bucket] += amount
                        target[status] += amount
                continue
            touches = any(
                str(line.get("Номенклатура") or "") in kitchen_items or
                line.get("КлассSKU") == "Общепит"
                for line in document.get("Товары") or [])
            if touches:
                for target in targets:
                    target["missing_docs"] += 1
        return {"total": total, "by_key": by_key}

    async def _catering_cheques(self, date_from: date, date_to: date,
                                stations: list[str] | None,
                                dish_ids: set[str]) -> dict:
        conditions = [
            StoreCheque.company_id == self.company_id,
            StoreCheque.at >= datetime.combine(date_from, time.min, tzinfo=timezone.utc),
            StoreCheque.at < datetime.combine(date_to + timedelta(days=1), time.min,
                                               tzinfo=timezone.utc),
        ]
        if stations:
            conditions.append(StoreCheque.station_id.in_([int(station) for station in stations]))
        rows = (await self.session.execute(select(StoreCheque).where(*conditions))).scalars().all()
        empty = lambda: {"cheques": 0, "kitchen_cheques": 0, "fuel_cheques": 0,
                         "fuel_with_kitchen": 0, "kitchen_in_fuel": 0.0}
        total = empty()
        by_key: dict[tuple[str, str], dict] = defaultdict(empty)
        pairs: dict[tuple[str, str], dict] = defaultdict(lambda: {"cheques": 0, "amount": 0.0})
        for cheque in rows:
            if cheque.is_return:
                continue
            key = (str(cheque.station_id), _week_of(cheque.at.date()))
            targets = (total, by_key[key])
            kitchen = [line for line in cheque.lines or []
                       if str(line.get("item_uuid") or "") in dish_ids]
            for target in targets:
                target["cheques"] += 1
                if cheque.had_fuel:
                    target["fuel_cheques"] += 1
            if not kitchen:
                continue
            kitchen_amount = sum(abs(_num(line.get("amount"))) for line in kitchen)
            for target in targets:
                target["kitchen_cheques"] += 1
                if cheque.had_fuel:
                    target["fuel_with_kitchen"] += 1
                    target["kitchen_in_fuel"] += kitchen_amount
            others = [line for line in cheque.lines or []
                      if str(line.get("item_uuid") or "") not in dish_ids]
            for dish in kitchen:
                for other in others:
                    pair = (str(dish.get("name") or "Блюдо"),
                            str(other.get("name") or "Товар"))
                    pairs[pair]["cheques"] += 1
                    pairs[pair]["amount"] += abs(_num(other.get("amount")))
        for target in [total, *by_key.values()]:
            target["attach_rate"] = round(
                target["fuel_with_kitchen"] / target["fuel_cheques"] * 100, 1
            ) if target["fuel_cheques"] else None
            target["avg_kitchen_in_fuel"] = round(
                target["kitchen_in_fuel"] / target["fuel_with_kitchen"], 2
            ) if target["fuel_with_kitchen"] else None
            target["kitchen_in_fuel"] = round(target["kitchen_in_fuel"], 2)
        top_pairs = [{"dish": dish, "with_item": item, "cheques": value["cheques"],
                      "with_item_amount": round(value["amount"], 2)}
                     for (dish, item), value in pairs.items()]
        top_pairs.sort(key=lambda item: (-item["cheques"], -item["with_item_amount"]))
        total["pairs"] = top_pairs[:12]
        total["available"] = bool(rows)
        return {"total": total, "by_key": by_key}

    async def catering_menu(self, date_from: date, date_to: date,
                            stations: list[str] | None = None) -> dict:
        """Один экономический контракт для станции и сети."""
        base = await self._catering_menu_legacy(date_from, date_to, stations)
        sale_metas = self._select(await self._load(), date_from, date_to, stations)
        facts = _catering_sale_facts(sale_metas)
        dish_ids = set(facts)
        recipe_versions = (await self.session.execute(select(StoreRecipeVersion).where(
            StoreRecipeVersion.company_id == self.company_id,
        ))).scalars().all()
        recipe_names = {recipe.dish_uuid: recipe.dish_name for recipe in recipe_versions
                        if recipe.recipe_kind in ("dish", "combo")}
        dish_ids.update(recipe_names)
        return_documents = await self._catering_return_documents(
            date_from, date_to, stations, dish_ids)
        _merge_customer_returns(facts, return_documents["total"])
        kitchen_items = set(dish_ids)
        for recipe in recipe_versions:
            kitchen_items.update(str(line.get("item") or "")
                                 for line in recipe.lines or [] if line.get("item"))
        for fact in facts.values():
            kitchen_items.update(fact["ings"])
        losses = await self._catering_losses(date_from, date_to, stations, kitchen_items)
        cheques = await self._catering_cheques(date_from, date_to, stations, dish_ids)
        base_rows = {row["guid"]: row for row in base["dishes"]}
        fallback = {}
        for guid, row in base_rows.items():
            unit = row["cost"] / row["qty"] if row.get("cost") is not None and row.get("qty") else None
            source = row.get("cost_source")
            fallback[guid] = (unit, "exact" if source == "release" else
                              "estimate" if unit is not None else "missing", source)

        def evaluate(source_facts: dict[str, dict], loss: dict) -> tuple[dict, dict[str, dict]]:
            evaluated = {}
            for guid, fact in source_facts.items():
                if fact["edge_cost"] > 0:
                    cost = fact["edge_cost"]
                    status = "estimate" if fact["edge_estimated"] > 0 else "exact"
                    source = "edge_estimate" if status == "estimate" else "edge_exact"
                else:
                    unit, status, source = fallback.get(guid, (None, "missing", None))
                    cost = unit * fact["qty"] if unit is not None else None
                gross_after_returns = fact["gross"] - fact["returns"]
                vat = fact["vat"] - fact["return_vat"]
                net = gross_after_returns - vat
                evaluated[guid] = {**fact, "cost": cost, "cost_status": status,
                                   "cost_source": source, "vat_net": vat, "net": net,
                                   "contribution": net - cost if cost is not None else None}
            statuses = {item["cost_status"] for item in evaluated.values()}
            sales = sum(item["gross"] for item in evaluated.values())
            returns = sum(item["returns"] for item in evaluated.values())
            vat = sum(item["vat_net"] for item in evaluated.values())
            net = sales - returns - vat
            ingredients = sum(item["cost"] or 0 for item in evaluated.values())
            direct = loss.get("writeoffs", 0) + loss.get("shortages", 0)
            if not evaluated or "missing" in statuses:
                status = "missing"
            elif loss.get("missing_docs", 0) or any(item["vat_missing"] for item in evaluated.values()):
                status = "partial"
            elif "estimate" in statuses or loss.get("estimated", 0) > 0:
                status = "estimate"
            else:
                status = "exact"
            preliminary = net - ingredients - direct
            exact_cost = sum((item["cost"] or 0) for item in evaluated.values()
                             if item["cost_status"] == "exact") + loss.get("exact", 0)
            total_cost = ingredients + direct
            summary = {
                "dishes_count": len(evaluated),
                "dishes_costed": sum(1 for item in evaluated.values() if item["cost"] is not None),
                "revenue": round(sales, 2), "sales_gross": round(sales, 2),
                "customer_returns": round(returns, 2),
                "gross_revenue": round(sales - returns, 2), "vat": round(vat, 2),
                "revenue_net": round(net, 2), "net_revenue": round(net, 2),
                "revenue_costed": round(sum(item["gross"] for item in evaluated.values()
                                               if item["cost"] is not None), 2),
                "portions": round(sum(item["qty"] for item in evaluated.values()), 2),
                "cost": round(ingredients, 2), "ingredient_cost": round(ingredients, 2),
                "ingredient_cost_exact": round(sum((item["cost"] or 0)
                                                    for item in evaluated.values()
                                                    if item["cost_status"] == "exact"), 2),
                "ingredient_cost_estimated": round(sum((item["cost"] or 0)
                                                        for item in evaluated.values()
                                                        if item["cost_status"] == "estimate"), 2),
                "writeoffs": round(loss.get("writeoffs", 0), 2),
                "shortages": round(loss.get("shortages", 0), 2),
                "direct_losses": round(direct, 2),
                "operating_contribution": round(preliminary, 2) if status == "exact" else None,
                "preliminary_contribution": round(preliminary, 2),
                "margin": round(preliminary, 2),
                "food_cost_pct": round(ingredients / net * 100, 1) if net else None,
                "margin_pct": round(preliminary / net * 100, 1) if net else None,
                "cost_status": status,
                "exact_coverage_pct": round(exact_cost / total_cost * 100, 1) if total_cost else 0.0,
                "missing_loss_documents": loss.get("missing_docs", 0),
            }
            return summary, evaluated

        summary, evaluated = evaluate(facts, losses["total"])
        total_qty = sum(item["qty"] for item in evaluated.values()) or 1.0
        exact = [item for item in evaluated.values()
                 if item["cost_status"] == "exact" and item["qty"]]
        avg_cm = (sum(item["contribution"] or 0 for item in exact) /
                  sum(item["qty"] for item in exact)) if exact else 0.0
        pop_threshold = 70 / (len(evaluated) or 1)
        matrix: dict[str, dict] = defaultdict(lambda: {"count": 0, "revenue": 0.0})
        rows = []
        for guid, fact in evaluated.items():
            row = dict(base_rows.get(guid) or {
                "guid": guid, "name": recipe_names.get(guid) or guid[:8],
                "ingredients": [], "daily": [],
                "coverage": 0, "ing_count": 0,
            })
            qty, contribution = fact["qty"], fact["contribution"]
            popularity = qty / total_qty * 100
            cm_unit = contribution / qty if contribution is not None and qty else None
            if fact["cost_status"] != "exact":
                menu_class = "unknown"
            else:
                high_pop, high_cm = popularity >= pop_threshold, (cm_unit or 0) >= avg_cm
                menu_class = ("star" if high_pop and high_cm else
                              "plowhorse" if high_pop else
                              "puzzle" if high_cm else "dog")
            matrix[menu_class]["count"] += 1
            matrix[menu_class]["revenue"] += fact["gross"]
            row.update({
                "qty": round(qty, 2), "revenue": round(fact["gross"], 2),
                "returns": round(fact["returns"], 2), "vat": round(fact["vat_net"], 2),
                "revenue_net": round(fact["net"], 2),
                "avg_price": round(fact["gross"] / qty, 2) if qty else 0.0,
                "cost": round(fact["cost"], 2) if fact["cost"] is not None else None,
                "cost_per_portion": round(fact["cost"] / qty, 2)
                if fact["cost"] is not None and qty else None,
                "cost_source": fact["cost_source"], "cost_status": fact["cost_status"],
                "margin": round(contribution, 2) if contribution is not None else None,
                "food_cost_pct": round(fact["cost"] / fact["net"] * 100, 1)
                if fact["cost"] is not None and fact["net"] else None,
                "margin_pct": round(contribution / fact["net"] * 100, 1)
                if contribution is not None and fact["net"] else None,
                "cm_unit": round(cm_unit, 2) if cm_unit is not None else None,
                "popularity_pct": round(popularity, 1), "menu_class": menu_class,
                "preliminary": fact["cost_status"] != "exact",
            })
            rows.append(row)
        rows.sort(key=lambda row: -row["revenue"])

        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for meta in sale_metas:
            shift = meta.get("Смена") or {}
            station, day = str(shift.get("КодАЗС") or ""), _day(shift)
            if station and day:
                grouped[(station, _week_of(day))].append(meta)
        comparison = []
        for key, metas in sorted(grouped.items()):
            grouped_facts = _catering_sale_facts(metas)
            _merge_customer_returns(grouped_facts, return_documents["by_key"].get(key, {}))
            item_summary, _ = evaluate(grouped_facts, losses["by_key"].get(key, {}))
            comparison.append({
                "station_id": key[0], "week_from": key[1],
                "week_to": (date.fromisoformat(key[1]) + timedelta(days=6)).isoformat(),
                "attach_rate": cheques["by_key"].get(key, {}).get("attach_rate"),
                **item_summary,
            })

        recommendations = []
        def recommend(title: str, evidence: str, action: str):
            if len(recommendations) < 5:
                recommendations.append({"title": title, "evidence": evidence, "action": action})
        if summary["cost_status"] != "exact":
            recommend("Довести экономику до точной",
                      f"статус {summary['cost_status']}, покрытие {summary['exact_coverage_pct']}%",
                      "проверить CostEvidence, цены сырья, НДС и неоценённые потери")
        if summary["shortages"] > 0:
            recommend("Сравнить недостачи по АЗС", f"{summary['shortages']:.2f} ₽",
                      "найти станцию и неделю с наибольшим отклонением")
        if summary["writeoffs"] > 0:
            recommend("Сравнить списания по неделям", f"{summary['writeoffs']:.2f} ₽",
                      "проверить рост и причины на станции")
        if summary["customer_returns"] > 0:
            recommend("Разобрать возвраты гостей", f"{summary['customer_returns']:.2f} ₽",
                      "сравнить блюда, станции и недели")
        puzzles = matrix.get("puzzle", {}).get("count", 0)
        if puzzles:
            recommend("Проверить выгодные позиции с низким спросом", f"позиций: {puzzles}",
                      "сопоставить витрину и наблюдаемые пары в чеках; это не доказанная причина")
        if not recommendations:
            recommend("Сохранить текущий режим", "экономика точная, явных отклонений нет",
                      "сверить динамику на следующей неделе")

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "summary": summary,
            "matrix": {key: {"count": value["count"], "revenue": round(value["revenue"], 2)}
                       for key, value in matrix.items()},
            "dishes": rows, "comparison": comparison,
            "cross_sell": cheques["total"], "recommendations": recommendations,
        }

    # ── Категории (Сопутка/Общепит) ──
    async def categories(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        skus = (await self.sku_analytics(date_from, date_to, stations))["skus"]
        agg: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "revenue_net": 0.0, "margin": 0.0, "margin_known": 0.0, "sku": 0, "qty": 0.0})
        for s in skus:
            c = s["category"] or "—"
            a = agg[c]
            a["revenue"] += s["revenue"]
            a["revenue_net"] += s["revenue_net"]
            a["sku"] += 1
            a["qty"] += s["qty"]
            if s["margin"] is not None:
                a["margin"] += s["margin"]
                a["margin_known"] += s["revenue_net"]
        total = sum(a["revenue"] for a in agg.values()) or 1.0
        rows = [{
            "category": c, "revenue": round(a["revenue"], 2), "revenue_net": round(a["revenue_net"], 2),
            "sku_count": a["sku"], "qty": round(a["qty"], 2),
            "share": round(100 * a["revenue"] / total, 1),
            "margin": round(a["margin"], 2) if a["margin_known"] else None,
            "margin_pct": round(100 * a["margin"] / a["margin_known"], 1) if a["margin_known"] else None,
        } for c, a in agg.items()]
        rows.sort(key=lambda x: -x["revenue"])

        # Второй разрез — по ТОВАРНЫМ ГРУППАМ, а не по двум классам.
        #
        # «Сопутка» и «Общепит» — это вид учёта, и на них экран заканчивался:
        # две строки на весь каталог. Работают же с группами — «Табак /
        # Сигареты», «Автотовары / Автохимия», — и вопрос у товароведа именно
        # там: какая группа кормит, а какая лежит. Путь группы отдаём как есть,
        # дерево из него собирает экран: уровней бывает два, а бывает три, и
        # раскладывать их на сервере значит зашить глубину навсегда.
        пути = {r["external_uuid"]: (r["path"], r["sku_class"]) for r in (await self.session.execute(text("""
            SELECT i.external_uuid::text AS external_uuid,
                   coalesce(g.path, '') AS path,
                   coalesce(i.sku_class, '') AS sku_class
              FROM edge.item i
              LEFT JOIN edge.item_group g ON g.id = i.group_id
             WHERE NOT i.deleted AND (i.company_id IS NULL OR i.company_id = :cid)
        """), {"cid": self.company_id})).mappings().all()}

        по_группам: dict[str, dict] = defaultdict(
            lambda: {"revenue": 0.0, "revenue_net": 0.0, "margin": 0.0,
                     "margin_known": 0.0, "sku": 0, "qty": 0.0, "sku_class": ""})
        for s_ in skus:
            путь, класс = пути.get(s_["guid"], ("", ""))
            ключ = путь or "— без группы —"
            g = по_группам[ключ]
            g["revenue"] += s_["revenue"]
            g["revenue_net"] += s_["revenue_net"]
            g["sku"] += 1
            g["qty"] += s_["qty"]
            g["sku_class"] = g["sku_class"] or класс
            if s_["margin"] is not None:
                g["margin"] += s_["margin"]
                g["margin_known"] += s_["revenue_net"]

        группы = [{
            "path": путь, "sku_class": g["sku_class"],
            "revenue": round(g["revenue"], 2), "revenue_net": round(g["revenue_net"], 2),
            "sku_count": g["sku"], "qty": round(g["qty"], 2),
            "share": round(100 * g["revenue"] / total, 1),
            "margin_pct": round(100 * g["margin"] / g["margin_known"], 1) if g["margin_known"] else None,
        } for путь, g in по_группам.items()]
        группы.sort(key=lambda x: -x["revenue"])

        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "categories": rows,
            "groups": группы,
            "summary": {"count": len(rows), "revenue": round(sum(r["revenue"] for r in rows), 2),
                        "groups": len(группы)},
        }

    # ── Штрихкоды (справочник-снимок, не по периоду) ──
    async def barcodes(self) -> dict:
        """Штрихкоды рабочего справочника: код всегда при своём товаре.

        Раньше экран показывал снимок справочника ЦБ 1С (`cb_barcode`) — 11 025
        строк на всю историю сети. Из них в работе 1 455: остальное архив чужих
        станций и позиций, снятых годы назад. Список читался как «у нас
        одиннадцать тысяч кодов», хотя это не так, и найти в нём рабочий код
        было нельзя.

        Штрихкод сам по себе — просто цифра. Значение он имеет только вместе с
        карточкой, поэтому показываем пары «код → товар» и ничего больше:
        код без живого товара в список не попадает вовсе.
        """
        rows = (await self.session.execute(text("""
            WITH живые AS (
                SELECT b.id, b.code, b.status, b.station_id, b.last_sold, b.item_id
                  FROM edge.barcode b
                  JOIN edge.item i ON i.id = b.item_id
                 WHERE (b.company_id IS NULL OR b.company_id = :cid)
                   AND NOT i.deleted AND b.status = 'active'
            ),
            -- Сколько РАЗНЫХ карточек носит один и тот же код. Оконная функция
            -- здесь не годится: Postgres не умеет DISTINCT внутри OVER, а
            -- считать строки вместо карточек значит объявить дублем код,
            -- дважды записанный одной и той же позиции.
            дубли AS (
                SELECT code, count(DISTINCT item_id) AS n FROM живые GROUP BY code
            )
            SELECT b.code, b.status, b.station_id, b.last_sold,
                   i.name AS owner_name, i.external_uuid AS owner_guid, i.sku,
                   coalesce(i.sku_class, '') AS sku_class,
                   -- Сколько кодов у ЭТОЙ карточки и на скольких карточках
                   -- висит ЭТОТ код. Оба вопроса задаёт товаровед, и оба
                   -- отвечаются здесь же, а не отдельным разбором.
                   count(*) OVER (PARTITION BY b.item_id) AS item_barcodes,
                   d.n AS dup_items,
                   -- Остаток и код кассы — по ЭТОМУ штрихкоду, а не по карточке.
                   --
                   -- У карточки с несколькими кодами остаток лежит на каждом
                   -- своём, и в кассе они разные строки: «сколько числится
                   -- именно под этим кодом» — вопрос, из-за которого товар и не
                   -- пробивается. Поле last_sold в справочнике не заполняется
                   -- ничем (0 из 1455), и колонка «Продавали» стояла пустой у
                   -- всех — вместо неё показываем то, что есть.
                   coalesce((SELECT sum(st.qty) FROM edge.stock st
                              WHERE st.barcode_id = b.id), 0) AS stock_qty,
                   (SELECT nc.ns_code FROM edge.ns_code nc
                     WHERE nc.barcode_id = b.id AND nc.status = 'active'
                     ORDER BY nc.ns_code LIMIT 1) AS ns_code,
                   -- Тип определяем по самому коду: в справочнике он не
                   -- хранится, а человеку нужен — по нему видно, чужой это код
                   -- с упаковки или внутренний номер станции.
                   CASE
                     WHEN b.code ~ '^[0-9]{13}$' THEN 'EAN13'
                     WHEN b.code ~ '^[0-9]{12}$' THEN 'UPC-A'
                     WHEN b.code ~ '^[0-9]{8}$'  THEN 'EAN8'
                     WHEN b.code ~ '^[0-9]{14}$' THEN 'ITF-14'
                     WHEN b.code ~ '^[0-9]+$'    THEN 'внутренний'
                     ELSE 'иной'
                   END AS btype
              FROM живые b
              JOIN edge.item i ON i.id = b.item_id
              JOIN дубли d ON d.code = b.code
             ORDER BY i.name, b.code
        """), {"cid": self.company_id})).mappings().all()

        by_type: dict[str, int] = defaultdict(int)
        станции: dict[str, int] = defaultdict(int)
        без_продаж = 0
        items = []
        for r in rows:
            by_type[r["btype"]] += 1
            if r["station_id"] is not None:
                станции[str(r["station_id"])] += 1
            if not r["last_sold"]:
                без_продаж += 1
            items.append({
                "barcode": r["code"],
                "owner_name": r["owner_name"],
                "owner_guid": str(r["owner_guid"]) if r["owner_guid"] else None,
                "sku": r["sku"],
                "sku_class": r["sku_class"],
                "type": r["btype"],
                "station_id": r["station_id"],
                "last_sold": r["last_sold"].isoformat() if r["last_sold"] else None,
                "stock_qty": float(r["stock_qty"] or 0),
                "ns_code": r["ns_code"],
                "item_barcodes": int(r["item_barcodes"] or 1),
                "dup_items": int(r["dup_items"] or 1),
                # Поле осталось ради прежней разметки: «основным» в нашем
                # справочнике код не помечается — у карточки их может быть
                # несколько, и все равноправны.
                "main": False,
            })

        # Карточки БЕЗ единого кода — отдельный список, а не пропуск.
        #
        # Такой товар не пробить на кассе: касса ищет только по штрихкоду. Пока
        # экран показывал одни коды, эти позиции были невидимы — их нет ни в
        # одной строке, потому что кода у них нет.
        без_кода = (await self.session.execute(text("""
            SELECT i.name, i.sku, coalesce(i.sku_class, '') AS sku_class,
                   i.external_uuid AS guid,
                   coalesce((SELECT sum(st.qty) FROM edge.stock st
                              JOIN edge.barcode b2 ON b2.id = st.barcode_id
                             WHERE b2.item_id = i.id), 0) AS stock_qty
              FROM edge.item i
             WHERE NOT i.deleted AND (i.company_id IS NULL OR i.company_id = :cid)
               AND NOT EXISTS (SELECT 1 FROM edge.barcode b
                                WHERE b.item_id = i.id AND b.status = 'active')
             ORDER BY i.name
        """), {"cid": self.company_id})).mappings().all()

        # Архив старого справочника считаем, но не показываем: цифра объясняет,
        # куда делись «одиннадцать тысяч», и не даёт решить, что список урезали.
        архив = (await self.session.execute(text(
            "SELECT count(*) FROM cb_barcode WHERE company_id = :cid"),
            {"cid": self.company_id})).scalar() or 0

        карточек = len({i["owner_guid"] for i in items})
        return {
            "total": len(items),
            "by_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
            "by_station": dict(sorted(станции.items())),
            "without_sales": без_продаж,
            "without_ns_code": sum(1 for i in items if not i["ns_code"]),
            "archive_total": int(архив),
            "items_with_barcode": карточек,
            "duplicates": sum(1 for i in items if i["dup_items"] > 1),
            "multi_barcode_items": len({i["owner_guid"] for i in items if i["item_barcodes"] > 1}),
            "internal_codes": by_type.get("внутренний", 0),
            "items_without_barcode": [
                {"name": r["name"], "sku": r["sku"], "sku_class": r["sku_class"],
                 "guid": str(r["guid"]) if r["guid"] else None,
                 "stock_qty": float(r["stock_qty"] or 0)}
                for r in без_кода
            ],
            "items": items,
        }

    async def _edge_stock_onhand(self, *, warehouse: str | None, q: str,
                                 marked: str, only_negative: bool,
                                 stations: list[str] | None = None) -> dict | None:
        """Последний полный остаток собственного журнала агента.

        Возвращает None только пока компания не прислала новый edge_ledger-снимок;
        это оставляет безопасный переходный fallback на прежний срез ЦБ.
        """
        rows = (await self.session.execute(select(StoreStockBalance).where(
            StoreStockBalance.company_id == self.company_id,
            StoreStockBalance.source == "edge_ledger",
        ))).scalars().all()
        if not rows:
            return None
        if stations:
            rows = [row for row in rows if str(row.station_id) in stations]

        nom = await self._names()
        wh_agg: dict[str, dict] = defaultdict(
            lambda: {"station_id": 0, "place_code": "", "name": "", "sku": 0,
                     "positive": 0, "retail_value": 0.0})
        for row in rows:
            key = f"{row.station_id}:{row.place}"
            item = wh_agg[key]
            item["station_id"] = row.station_id
            item["place_code"] = row.place
            item["name"] = row.place_name or f"место {row.place}"
            item["sku"] += 1
            qty = float(row.quantity or 0)
            price = float(row.retail_price) if row.retail_price is not None else 0
            if qty > 0:
                item["positive"] += 1
            item["retail_value"] += qty * price
        warehouses = [{"code": key, **value,
                       "retail_value": round(value["retail_value"], 2)}
                      for key, value in wh_agg.items()]
        warehouses.sort(key=lambda item: (-item["sku"], item["code"]))

        # «all» — вся сеть разом: пока станция одна, это то же самое, но при
        # двенадцати АЗС вопрос «где вообще лежит этот товар» задают чаще, чем
        # «что лежит на конкретной полке», и ответ не должен требовать двенадцати
        # переключений. Строка при этом всегда знает свою станцию и место.
        selected = warehouse
        if selected and selected != "all" and selected not in wh_agg:
            matches = [key for key, value in wh_agg.items()
                       if value["place_code"] == selected]
            selected = matches[0] if len(matches) == 1 else None
        selected = selected or "all"
        всё = selected == "all"
        ql = (q or "").lower().strip()

        items = []
        for row in rows:
            if not всё and selected != f"{row.station_id}:{row.place}":
                continue
            card = nom.get(row.item_uuid)
            is_marked = bool(card and card.marked)
            if marked == "marked" and not is_marked:
                continue
            if marked == "plain" and is_marked:
                continue
            name = row.name or (card.name if card else row.item_uuid[:8])
            if ql and ql not in name.lower() and ql not in row.barcode.lower():
                continue
            qty = float(row.quantity or 0)
            if only_negative and qty >= 0:
                continue
            price = float(row.retail_price) if row.retail_price is not None else None
            value = round(qty * price, 2) if price is not None else None
            cost_unit = float(row.cost_unit) if row.cost_unit is not None else None
            coverage = float(row.cost_known_pct or 0)
            cost_doubt = (f"себестоимость известна для {coverage:.0f}% остатка"
                          if cost_unit is not None and coverage < 99.5 else None)
            cost_amount = (round(qty * cost_unit, 2)
                           if cost_unit is not None and coverage >= 99.5 else None)
            margin = (round(value - cost_amount, 2)
                      if value is not None and cost_amount is not None else None)
            margin_pct = (round(100 * margin / value, 1)
                          if margin is not None and value else None)
            items.append({
                "guid": row.item_uuid,
                # Станция и место в самой строке: в сводном разрезе без них
                # непонятно, чей это остаток, а «остаток вообще» бессмыслен —
                # товар лежит на конкретной полке конкретной АЗС.
                "station_id": row.station_id,
                "place_code": row.place,
                "place_name": row.place_name or f"место {row.place}",
                "name": name,
                "article": card.article if card else None,
                "vat": card.vat if card else None,
                "marked": is_marked,
                "weighed": bool(card and card.weighed),
                "barcode": row.barcode,
                "qty": round(qty, 3),
                "negative": qty < 0,
                "retail_price": round(price, 2) if price is not None else None,
                "retail_value": value,
                "cost_unit": round(cost_unit, 4) if cost_unit is not None else None,
                "cost_amount": cost_amount,
                "margin": margin,
                "margin_pct": margin_pct,
                "unit": card.unit if card else None,
                "cost_doubt": cost_doubt,
                "buy_unit": None,
            })
        items.sort(key=lambda item: (item["retail_value"] is None,
                                     -(item["retail_value"] or 0)))
        positive = [item for item in items if item["qty"] > 0]
        negative = [item for item in items if item["qty"] < 0]
        costed = [item for item in positive if item["cost_amount"] is not None]
        doubt = [item for item in positive if item["cost_doubt"]]
        cost_value = sum(item["cost_amount"] or 0 for item in costed)
        retail_costed = sum(item["retail_value"] or 0 for item in costed)
        snapshot_at = max((row.snapshot_at for row in rows), default=None)

        # Свод по станциям: сколько мест, позиций, денег на полке и когда
        # приходил последний снимок. Свежесть здесь не украшение — остаток
        # станции, молчащей вторые сутки, стоит читать иначе.
        по_станциям: dict[int, dict] = defaultdict(
            lambda: {"places": 0, "sku": 0, "positive": 0, "negative": 0,
                     "retail_value": 0.0, "snapshot_at": None})
        for key, value in wh_agg.items():
            узел = по_станциям[value["station_id"]]
            узел["places"] += 1
            узел["sku"] += value["sku"]
            узел["positive"] += value["positive"]
            узел["retail_value"] += value["retail_value"]
        for row in rows:
            узел = по_станциям[row.station_id]
            if float(row.quantity or 0) < 0:
                узел["negative"] += 1
            снято = row.snapshot_at.isoformat() if row.snapshot_at else None
            if снято and (узел["snapshot_at"] is None or снято > узел["snapshot_at"]):
                узел["snapshot_at"] = снято
        stations = [{"station_id": sid, **value,
                     "retail_value": round(value["retail_value"], 2)}
                    for sid, value in sorted(по_станциям.items())]

        return {
            "source": "edge_agent",
            "warehouse": selected,
            "warehouses": warehouses,
            "stations": stations,
            "items": items,
            "snapshot_at": snapshot_at.isoformat() if snapshot_at else None,
            "summary": {
                "sku_count": len(items),
                "positive": len(positive),
                "negative": len(negative),
                "retail_value_positive": round(sum(
                    (item["retail_value"] or 0) for item in positive), 2),
                "retail_value_all": round(sum(
                    (item["retail_value"] or 0) for item in items), 2),
                "cost_value": round(cost_value, 2),
                "costed_count": len(costed),
                "retail_costed": round(retail_costed, 2),
                "doubt_count": len(doubt),
                "no_cost_count": len(positive) - len(costed) - len(doubt),
                "margin_value": round(retail_costed - cost_value, 2),
                "margin_pct": (round(100 * (retail_costed - cost_value) / retail_costed, 1)
                               if retail_costed else None),
                "marked_count": sum(1 for item in items if item["marked"]),
                "units_positive": round(sum(item["qty"] for item in positive), 3),
            },
        }

    # ── Остатки: основной источник — собственный журнал агента ──
    async def stock_onhand(self, *, warehouse: str | None = None, q: str = "",
                           marked: str = "all", only_negative: bool = False,
                           stations: list[str] | None = None) -> dict:
        """Достоверный остаток товара (снимок регистров ЦБ), не оценка stock_est.

        warehouse — код склада (по умолчанию склад с наибольшим числом SKU, обычно 208
        Торговый зал). Возвращает позиции выбранного склада + список складов для селектора.
        """
        edge = await self._edge_stock_onhand(
            warehouse=warehouse, q=q, marked=marked, only_negative=only_negative,
            stations=stations)
        if edge is not None:
            return edge

        rows = (await self.session.execute(select(StockOnHand).where(
            StockOnHand.company_id == self.company_id))).scalars().all()
        if stations:
            rows = [r for r in rows if _warehouse_in_stations(r.warehouse_code, stations)]
        nom = await self._names()
        # Средняя закупка — не вторая база себестоимости, а ПРОВЕРКА партийной: на рознице
        # партийный регистр смешанный (пересорт, старые партии), и у каждой пятой позиции
        # цифра мусорная — то выше розничной цены, то вдвое ниже реальной закупки.
        buy = {g: c[0] for g, c in (await self._cost_unit_map(stations)).items()}

        # склады: сводка (код → имя, SKU, стоимость остатка) для селектора
        wh_agg: dict[str, dict] = defaultdict(
            lambda: {"name": None, "sku": 0, "positive": 0, "retail_value": 0.0})
        for r in rows:
            w = wh_agg[r.warehouse_code]
            w["name"] = r.warehouse_name
            w["sku"] += 1
            if float(r.quantity or 0) > 0:
                w["positive"] += 1
            w["retail_value"] += float(r.quantity or 0) * float(r.retail_price or 0)
        # positive в селекторе: у склада 20800002 из 140 позиций на полке 32, остальное —
        # отрицательные хвосты, и «(140)» рядом с торговым залом обещает лишнего.
        warehouses = [{
            "code": c, "name": v["name"], "sku": v["sku"], "positive": v["positive"],
            "retail_value": round(v["retail_value"], 2),
        } for c, v in wh_agg.items()]
        warehouses.sort(key=lambda x: -x["sku"])

        # склад по умолчанию — с наибольшим числом SKU
        wh = warehouse or (warehouses[0]["code"] if warehouses else None)
        ql = (q or "").lower().strip()

        items = []
        for r in rows:
            if wh and r.warehouse_code != wh:
                continue
            n = nom.get(r.nomenclature_ref)
            is_marked = bool(n and n.marked)
            if marked == "marked" and not is_marked:
                continue
            if marked == "plain" and is_marked:
                continue
            name = n.name if n else r.nomenclature_ref[:8]
            if ql and not (ql in (name or "").lower() or ql in (r.barcode or "")):
                continue
            qty = float(r.quantity or 0)
            if only_negative and qty >= 0:
                continue
            price = float(r.retail_price) if r.retail_price is not None else None
            retail_value = round(qty * price, 2) if price is not None else None
            # себест. остатка и маржа из удельной себест. партий (базовые единицы —
            # совпадают с остатком, корректно для блоков/весовых).
            cu = float(r.cost_unit) if r.cost_unit is not None else None
            cost_amount = round(qty * cu, 2) if cu is not None else None
            margin = (round(retail_value - cost_amount, 2)
                      if retail_value is not None and cost_amount is not None else None)
            margin_pct = (round(100 * margin / retail_value, 1)
                          if margin is not None and retail_value else None)
            bu = buy.get(r.nomenclature_ref)
            cost_doubt = _cost_doubt(cu, price, bu)
            items.append({
                "guid": r.nomenclature_ref,
                "name": name,
                "article": (n.article if n else None),
                "vat": (n.vat if n else None),
                "marked": is_marked,
                "weighed": bool(n and n.weighed),
                "barcode": r.barcode,
                "qty": round(qty, 3),
                "negative": qty < 0,
                "retail_price": round(price, 2) if price is not None else None,
                "retail_value": retail_value,
                "cost_unit": round(cu, 4) if cu is not None else None,
                "cost_amount": cost_amount,
                "margin": margin,
                "margin_pct": margin_pct,
                # Единица регистра: остаток весового товара хранится в базовой единице
                # (молоко — в мл, соусы — в граммах), и без неё «71 510» читается как штуки.
                "unit": (n.unit if n else None),
                "cost_doubt": cost_doubt,
                "buy_unit": round(bu, 2) if bu else None,
            })
        items.sort(key=lambda x: (x["retail_value"] is None, -(x["retail_value"] or 0)))

        pos = [i for i in items if i["qty"] > 0]
        neg = [i for i in items if i["qty"] < 0]
        # Сводная маржа считается по позициям, где себестоимость есть И не вызывает
        # сомнений: иначе в неё попадали 48 позиций с себестоимостью выше цены и 66
        # заниженных вдвое, и «потенц. маржа» жила своей жизнью.
        costed = [i for i in pos if i["cost_amount"] is not None and not i["cost_doubt"]]
        doubt = [i for i in pos if i["cost_amount"] is not None and i["cost_doubt"]]
        cost_value = sum(i["cost_amount"] for i in costed)
        retail_costed = sum((i["retail_value"] or 0) for i in costed)
        return {
            "source": "legacy_cb_snapshot",
            "warehouse": wh,
            "warehouses": warehouses,
            "items": items,
            "snapshot_at": self._snap(rows),   # F3: дата снимка остатков
            "summary": {
                "sku_count": len(items),
                "positive": len(pos),
                "negative": len(neg),
                # стоимость товара на полке (только положительный остаток) — надёжная метрика;
                # retail_value_all включает отрицательные позиции (для сверки).
                "retail_value_positive": round(sum((i["retail_value"] or 0) for i in pos), 2),
                "retail_value_all": round(sum((i["retail_value"] or 0) for i in items), 2),
                # Себест. остатка и потенц. маржа — по ОДНОМУ множеству (costed): без этого
                # плитки стояли на разных базах (635 против 573) и разность одной из другой
                # не давала показанного процента.
                "cost_value": round(cost_value, 2),
                "costed_count": len(costed),
                "retail_costed": round(retail_costed, 2),   # база маржи — видна на экране
                "doubt_count": len(doubt),                  # себестоимость есть, но ей нельзя верить
                "no_cost_count": len(pos) - len(costed) - len(doubt),
                "margin_value": round(retail_costed - cost_value, 2),
                "margin_pct": round(100 * (retail_costed - cost_value) / retail_costed, 1) if retail_costed else None,
                "marked_count": sum(1 for i in items if i["marked"]),
                "units_positive": round(sum(i["qty"] for i in pos), 3),
            },
        }

    # ── Инвентаризация: реестр + отклонения факт↔учёт (недостачи/излишки) ──
    @staticmethod
    def _by_period(docs: list, date_from: date | None, date_to: date | None) -> list:
        """Фильтр документов движения по doc_date в периоде (К-17)."""
        if not (date_from and date_to):
            return docs
        a, b = date_from.isoformat(), date_to.isoformat()
        return [d for d in docs if d.doc_date and a <= d.doc_date <= b]

    async def inventory(self, *, warehouse: str | None = None, only_dev: bool = False,
                        date_from: date | None = None, date_to: date | None = None,
                        stations: list[str] | None = None) -> dict:
        """Реестр инвентаризаций ЦБ + агрегаты недостач/излишков (shrinkage).

        warehouse — код склада (по умолч. все склады магазина). only_dev — только
        документы с отклонениями. date_from/date_to — период (К-17). Строки — drill-down.
        """
        docs = self._by_period((await self.session.execute(select(CbInventoryDoc).where(
            CbInventoryDoc.company_id == self.company_id,
            CbInventoryDoc.deleted.is_(False)))).scalars().all(), date_from, date_to)
        if stations:
            docs = [d for d in docs if _warehouse_in_stations(d.warehouse_code, stations)]

        # Смена документа: движение товара живёт внутри смены, поэтому смена нужна в
        # реестре. У витринных документов есть только дата — в двухсменный день
        # документ относится к обеим сменам, и это показывается, а не прячется.
        shift_index = await self._shift_index(
            date_from or date(2000, 1, 1), date_to or date(2100, 1, 1), stations)
        _shifts = [sh for lst in shift_index.values() for sh in lst]
        shift_stations = stations or list(shift_index)

        # склады для селектора
        wh_agg: dict[str, dict] = defaultdict(lambda: {"name": None, "count": 0})
        for d in docs:
            w = wh_agg[d.warehouse_code]
            w["name"] = d.warehouse_name
            w["count"] += 1
        warehouses = [{"code": c, "name": v["name"], "count": v["count"]}
                      for c, v in sorted(wh_agg.items(), key=lambda x: -x[1]["count"])]

        sel = [d for d in docs if (not warehouse or d.warehouse_code == warehouse)]
        if only_dev:
            sel = [d for d in sel if d.dev_positions]

        out_docs = []
        sku_short: dict[str, dict] = defaultdict(lambda: {"name": None, "qty": 0.0, "amount": 0.0, "docs": 0})
        tot_sh = tot_su = 0.0
        dates = []
        for d in sel:
            tot_sh += float(d.shortage_amount or 0)
            tot_su += float(d.surplus_amount or 0)
            if d.doc_date:
                dates.append(d.doc_date)
            for ln in (d.lines or []):
                if ln.get("dev", 0) < 0:  # недостача — копим по SKU
                    k = ln.get("ref") or ln.get("name")
                    s = sku_short[k]
                    s["name"] = ln.get("name")
                    s["ref"] = ln.get("ref")   # чтобы строка топа вела в карточку товара
                    s["qty"] += float(ln.get("dev") or 0)
                    s["amount"] += float(ln.get("amount_dev") or 0)
                    s["docs"] += 1
            out_docs.append({
                "ref": d.external_ref, "number": d.number, "date": d.doc_date,
                "warehouse_code": d.warehouse_code, "warehouse_name": d.warehouse_name,
                "comment": d.comment, "dev_positions": d.dev_positions,
                **{f"shift_{k}": v for k, v in
                   self._shift_of(
                       _shifts, (d.doc_date or "")[:10],
                       _station_of_warehouse(d.warehouse_code, shift_stations),
                   ).items()},
                "shortage_qty": float(d.shortage_qty or 0), "shortage_amount": float(d.shortage_amount or 0),
                "surplus_qty": float(d.surplus_qty or 0), "surplus_amount": float(d.surplus_amount or 0),
                "net_amount": float(d.net_amount or 0),
                # lines в БД — полная ТЧ; дрилл реестра показывает только отклонения.
                # Если отклонений нет вовсе — отдаём состав как есть, иначе документ
                # «пересчитано 340 позиций, расхождений нет» открывался пустым.
                "lines": [ln for ln in (d.lines or []) if ln.get("dev")] or (d.lines or []),
            })
        out_docs.sort(key=lambda x: (x["date"] or ""), reverse=True)

        top_short = sorted(sku_short.values(), key=lambda x: x["amount"])[:12]
        for t in top_short:
            t["qty"] = round(t["qty"], 3); t["amount"] = round(t["amount"], 2)

        return {
            "warehouse": warehouse,
            "warehouses": warehouses,
            "docs": out_docs,
            "top_shortage": top_short,
            "snapshot_at": self._snap(sel),   # F3: дата снимка данных
            "summary": {
                "docs_count": len(sel),
                "docs_with_dev": sum(1 for d in sel if d.dev_positions),
                "shortage_amount": round(tot_sh, 2),
                "surplus_amount": round(tot_su, 2),
                "net_amount": round(tot_sh + tot_su, 2),
                "period_from": (min(dates) if dates else None),
                "period_to": (max(dates) if dates else None),
            },
        }

    # ── Списания: реестр + причины (недостача/брак/…) + топ списанных SKU ──
    async def writeoffs(self, *, warehouse: str | None = None, reason: str | None = None,
                        date_from: date | None = None, date_to: date | None = None,
                        stations: list[str] | None = None) -> dict:
        """Реестр списаний ЦБ (СписаниеТоваров) + разбивка по причинам и топ SKU."""
        docs = self._by_period((await self.session.execute(select(CbMovementDoc).where(
            CbMovementDoc.company_id == self.company_id,
            CbMovementDoc.deleted.is_(False), CbMovementDoc.posted.is_(True),
            CbMovementDoc.kind == "writeoff"))).scalars().all(), date_from, date_to)
        if stations:
            docs = [d for d in docs if _warehouse_in_stations(d.warehouse_code, stations)]

        # Смена документа: движение товара живёт внутри смены, поэтому смена нужна в
        # реестре. У витринных документов есть только дата — в двухсменный день
        # документ относится к обеим сменам, и это показывается, а не прячется.
        shift_index = await self._shift_index(
            date_from or date(2000, 1, 1), date_to or date(2100, 1, 1), stations)
        _shifts = [sh for lst in shift_index.values() for sh in lst]
        shift_stations = stations or list(shift_index)

        wh_agg: dict[str, dict] = defaultdict(lambda: {"name": None, "count": 0})
        reasons_all: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount": 0.0})
        for d in docs:
            w = wh_agg[d.warehouse_code]; w["name"] = d.warehouse_name; w["count"] += 1
        warehouses = [{"code": c, "name": v["name"], "count": v["count"]}
                      for c, v in sorted(wh_agg.items(), key=lambda x: -x[1]["count"])]

        sel = [d for d in docs if (not warehouse or d.warehouse_code == warehouse)
               and (not reason or d.reason == reason)]

        out_docs = []
        sku: dict[str, dict] = defaultdict(lambda: {"name": None, "qty": 0.0, "amount": 0.0, "docs": 0})
        tot_amt = inv_amt = 0.0
        dates = []
        for d in sel:
            amt = float(d.total_amount or 0)
            tot_amt += amt
            if d.from_inventory:
                inv_amt += amt
            reasons_all[d.reason or "Прочее"]["count"] += 1
            reasons_all[d.reason or "Прочее"]["amount"] += amt
            if d.doc_date:
                dates.append(d.doc_date)
            for ln in (d.lines or []):
                k = ln.get("ref") or ln.get("name")
                sk = sku[k]; sk["name"] = ln.get("name")
                sk["ref"] = ln.get("ref")   # чтобы строка топа вела в карточку товара
                sk["qty"] += float(ln.get("qty") or 0)
                sk["amount"] += float(ln.get("amount") or 0)
                sk["docs"] += 1
            out_docs.append({
                "ref": d.external_ref, "number": d.number, "date": d.doc_date,
                "warehouse_code": d.warehouse_code, "warehouse_name": d.warehouse_name,
                "reason": d.reason, "from_inventory": d.from_inventory, "comment": d.comment,
                **{f"shift_{k}": v for k, v in
                   self._shift_of(
                       _shifts, (d.doc_date or "")[:10],
                       _station_of_warehouse(d.warehouse_code, shift_stations),
                   ).items()},
                "positions": d.positions, "total_qty": float(d.total_qty or 0),
                "total_amount": amt, "lines": d.lines or [],
            })
        out_docs.sort(key=lambda x: (x["date"] or ""), reverse=True)

        by_reason = [{"reason": r, "count": v["count"], "amount": round(v["amount"], 2)}
                     for r, v in sorted(reasons_all.items(), key=lambda x: -x[1]["amount"])]
        top_sku = sorted(sku.values(), key=lambda x: -x["amount"])[:12]
        for t in top_sku:
            t["qty"] = round(t["qty"], 3); t["amount"] = round(t["amount"], 2)

        return {
            "warehouse": warehouse,
            "warehouses": warehouses,
            "docs": out_docs,
            "by_reason": by_reason,
            "top_sku": top_sku,
            "snapshot_at": self._snap(sel),   # F3: дата снимка данных
            "summary": {
                "docs_count": len(sel),
                "total_amount": round(tot_amt, 2),
                "from_inventory_amount": round(inv_amt, 2),
                "other_amount": round(tot_amt - inv_amt, 2),
                "period_from": (min(dates) if dates else None),
                "period_to": (max(dates) if dates else None),
            },
        }

    # ── Перемещения: реестр откуда→куда + направления (внутр/приход/расход) ──
    async def transfers(self, *, direction: str | None = None,
                        date_from: date | None = None, date_to: date | None = None,
                        stations: list[str] | None = None) -> dict:
        """Реестр перемещений ЦБ (ПеремещениеТоваров) относительно складов магазина.

        Сумма = розн. стоимость перемещённого (Количество × Цена; себестоимость у
        внутренних перемещений не заполнена). direction — фильтр по направлению.
        """
        docs = self._by_period((await self.session.execute(select(CbMovementDoc).where(
            CbMovementDoc.company_id == self.company_id,
            CbMovementDoc.deleted.is_(False), CbMovementDoc.posted.is_(True),
            CbMovementDoc.kind == "transfer"))).scalars().all(), date_from, date_to)
        if stations:
            docs = [
                d for d in docs
                if _warehouse_in_stations(d.warehouse_code, stations)
                or _warehouse_in_stations(d.warehouse_to_code, stations)
            ]

        # Смена документа: движение товара живёт внутри смены, поэтому смена нужна в
        # реестре. У витринных документов есть только дата — в двухсменный день
        # документ относится к обеим сменам, и это показывается, а не прячется.
        shift_index = await self._shift_index(
            date_from or date(2000, 1, 1), date_to or date(2100, 1, 1), stations)
        _shifts = [sh for lst in shift_index.values() for sh in lst]
        shift_stations = stations or list(shift_index)

        dirs_all: dict[str, dict] = defaultdict(lambda: {"count": 0, "amount": 0.0})
        for d in docs:
            dirs_all[d.reason or "Прочее"]["count"] += 1
            dirs_all[d.reason or "Прочее"]["amount"] += float(d.total_amount or 0)

        sel = [d for d in docs if (not direction or d.reason == direction)]

        out_docs = []
        sku: dict[str, dict] = defaultdict(lambda: {"name": None, "qty": 0.0, "amount": 0.0, "docs": 0})
        tot_amt = 0.0
        dates = []
        for d in sel:
            amt = float(d.total_amount or 0)
            tot_amt += amt
            if d.doc_date:
                dates.append(d.doc_date)
            for ln in (d.lines or []):
                k = ln.get("ref") or ln.get("name")
                sk = sku[k]; sk["name"] = ln.get("name")
                sk["ref"] = ln.get("ref")   # чтобы строка топа вела в карточку товара
                sk["qty"] += float(ln.get("qty") or 0)
                sk["amount"] += float(ln.get("amount") or 0)
                sk["docs"] += 1
            out_docs.append({
                "ref": d.external_ref, "number": d.number, "date": d.doc_date,
                "from_code": d.warehouse_code, "from_name": d.warehouse_name,
                "to_code": d.warehouse_to_code, "to_name": d.warehouse_to_name,
                **{f"shift_{k}": v for k, v in
                   self._shift_of(
                       _shifts, (d.doc_date or "")[:10],
                       _station_of_warehouse(d.warehouse_code, shift_stations)
                       or _station_of_warehouse(d.warehouse_to_code, shift_stations),
                   ).items()},
                "direction": d.reason, "comment": d.comment,
                "positions": d.positions, "total_qty": float(d.total_qty or 0),
                "total_amount": amt, "lines": d.lines or [],
            })
        out_docs.sort(key=lambda x: (x["date"] or ""), reverse=True)

        by_direction = [{"direction": r, "count": v["count"], "amount": round(v["amount"], 2)}
                        for r, v in sorted(dirs_all.items(), key=lambda x: -x[1]["amount"])]
        top_sku = sorted(sku.values(), key=lambda x: -x["amount"])[:12]
        for t in top_sku:
            t["qty"] = round(t["qty"], 3); t["amount"] = round(t["amount"], 2)

        return {
            "direction": direction,
            "docs": out_docs,
            "by_direction": by_direction,
            "top_sku": top_sku,
            "snapshot_at": self._snap(sel),   # F3: дата снимка данных
            "summary": {
                "docs_count": len(sel),
                "total_amount": round(tot_amt, 2),
                "inbound_amount": round(dirs_all.get("Приход (на 208)", {}).get("amount", 0.0), 2),
                "outbound_amount": round(dirs_all.get("Расход (с 208)", {}).get("amount", 0.0), 2),
                "internal_amount": round(dirs_all.get("Внутреннее (склад↔зал)", {}).get("amount", 0.0), 2),
                "period_from": (min(dates) if dates else None),
                "period_to": (max(dates) if dates else None),
            },
        }

    # ── Переоценка: реестр изменений цен + подорожания/удешевления ──
    async def revaluation(self, *, reason: str | None = None,
                          date_from: date | None = None, date_to: date | None = None,
                          stations: list[str] | None = None) -> dict:
        """Реестр переоценок ЦБ (ПереоценкаТоваровАЗК): старая→новая розн. цена,
        Δ%, влияние на стоимость остатка (Σ Δ×кол). reason — фильтр направления."""
        docs = self._by_period((await self.session.execute(select(CbMovementDoc).where(
            CbMovementDoc.company_id == self.company_id,
            CbMovementDoc.deleted.is_(False), CbMovementDoc.posted.is_(True),
            CbMovementDoc.kind == "revaluation"))).scalars().all(), date_from, date_to)

        docs = [d for d in docs if _warehouse_in_stations(d.warehouse_code, stations)]

        reasons_all: dict[str, dict] = defaultdict(lambda: {"count": 0})
        for d in docs:
            reasons_all[d.reason or "—"]["count"] += 1

        # Порядок обхода фиксируем: у зеркальных пар «уценка → возврат» модуль разницы
        # одинаков, и без сортировки в топ попадала та строка, что первой пришла из
        # скана — состав списка менялся между обновлениями сам по себе.
        sel = sorted([d for d in docs if (not reason or d.reason == reason)],
                     key=lambda d: (d.doc_date or '', d.number or ''))

        out_docs = []
        up_lines = down_lines = 0
        pct_sum = pct_n = 0.0
        impact = 0.0
        dates = []
        # Единица берётся из справочника: у весового товара базовая единица — грамм,
        # и «0,35» без неё читается как цена за килограмм (в имени карточки стоит «1 кг.»).
        units = {ref: (n.unit or '') for ref, n in (await self._names()).items()}
        best_by_sku: dict[str, dict] = {}  # SKU → строка с макс. рублёвой разницей
        for d in sel:
            impact += float(d.total_amount or 0)
            if d.doc_date:
                dates.append(d.doc_date)
            for ln in (d.lines or []):
                delta = float(ln.get("delta") or 0)
                if delta > 0:
                    up_lines += 1
                elif delta < 0:
                    down_lines += 1
                if ln.get("pct") is not None:
                    pct_sum += float(ln["pct"]); pct_n += 1
                k = ln.get("ref") or ln.get("name")
                prev = best_by_sku.get(k)
                if prev is None or abs(delta) > abs(prev["delta"]):
                    best_by_sku[k] = {"name": ln.get("name"), "old": ln.get("old"),
                                      "new": ln.get("new"), "delta": delta, "pct": ln.get("pct"),
                                      "ref": ln.get("ref"), "unit": units.get(ln.get("ref") or "", ""),
                                      # Деньги: разница цены × количество в документе — во
                                      # столько обошлась переоценка на остатке той даты.
                                      "amount": delta * float(ln.get("qty") or 0)}
            out_docs.append({
                "ref": d.external_ref, "number": d.number, "date": d.doc_date,
                "warehouse_code": d.warehouse_code, "warehouse_name": d.warehouse_name,
                "reason": d.reason, "comment": d.comment,
                # Смену здесь не показываем: переоценка меняет цену на складе, а не
                # движение внутри смены — привязка к смене ничего бы не объясняла.
                "positions": d.positions, "up_count": int(d.total_qty or 0),
                "value_impact": float(d.total_amount or 0), "lines": d.lines or [],
            })
        out_docs.sort(key=lambda x: (x["date"] or ""), reverse=True)

        moves = list(best_by_sku.values())
        # Ранжируем по деньгам, а не по проценту: движение в 25 копеек за грамм давало
        # +250% и вытесняло из списка переоценки на тысячи рублей. Процент остаётся
        # подписью к сумме — он отвечает на «насколько», а сумма на «сколько это стоило».
        top_up = sorted([m for m in moves if m["delta"] > 0],
                        key=lambda x: (-abs(x["amount"]), -(x["pct"] or 0), x["name"] or ""))[:10]
        top_down = sorted([m for m in moves if m["delta"] < 0],
                          key=lambda x: (-abs(x["amount"]), x["pct"] or 0, x["name"] or ""))[:10]
        by_reason = [{"reason": r, "count": v["count"]}
                     for r, v in sorted(reasons_all.items(), key=lambda x: -x[1]["count"])]

        return {
            "reason": reason,
            "docs": out_docs,
            "by_reason": by_reason,
            "top_up": top_up,
            "top_down": top_down,
            "snapshot_at": self._snap(sel),   # F3: дата снимка данных
            "summary": {
                "docs_count": len(sel),
                "up_lines": up_lines, "down_lines": down_lines,
                "avg_pct": round(pct_sum / pct_n, 1) if pct_n else None,
                "value_impact": round(impact, 2),
                "period_from": (min(dates) if dates else None),
                "period_to": (max(dates) if dates else None),
            },
        }

    # ── Рецептуры (ТТК): блюда общепита → ингредиенты ──
    async def recipes(self, date_from: date, date_to: date, stations: list[str] | None = None) -> dict:
        metas = self._select(await self._load(), date_from, date_to, stations)
        nom = await self._names()
        dishes: dict[str, dict] = {}
        for m in metas:
            for ln in ((m.get("Секции") or {}).get("продажа_общепит") or {}).get("строки") or []:
                g = ln.get("Номенклатура")
                if not g or g in dishes:
                    continue
                ings = []
                for ing in ln.get("Ингредиенты") or []:
                    ig = ing.get("Номенклатура")
                    n = nom.get(ig)
                    # guid ингредиента — чтобы из состава ТТК открывалась его карточка
                    ings.append({"guid": ig, "name": (n.name if n else str(ig)[:8]),
                                 "qty": round(float(ing.get("Количество") or 0), 3)})
                if ings:
                    dn = nom.get(g)
                    dishes[g] = {"guid": g, "name": (dn.name if dn else str(g)[:8]), "ingredients": ings, "ing_count": len(ings)}
        rows = sorted(dishes.values(), key=lambda x: x["name"])
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "recipes": rows,
            "summary": {"count": len(rows)},
        }

    # ── Номенклатура: полный справочник НСИ + обогащение продажами/ШК (главный товарный экран) ──
    async def nomenclature_catalog(self, date_from: date, date_to: date, *, kind: str = "all",
                                   marked: str = "all", weighed: str = "all", has_sales: str = "all",
                                   q: str = "", stations: list[str] | None = None) -> dict:
        """Справочник сети: карточки, которыми торгуют станции.

        Источник — `edge.item`, наш сетевой каталог, а не выгрузка мастер-НСИ
        центральной базы 1С. Прежде здесь показывался снимок ЦБ ЭЛСИ.АЗК —
        7 547 карточек с топливом, услугами и ставками 10/20 %, — и раздел
        «Каталог» расходился сам с собой: здоровье и матрица считали по нашему
        каталогу, а список показывал чужой. Топливо в «Магазине» не ведут вовсе
        (канон, п. 7a), поэтому ГСМ отсюда исчез вместе со сменой источника.

        «Вид» теперь — класс позиции (Сопутка · Блюдо · Сырьё): именно он решает,
        как считается остаток и что уезжает в кассу.
        """
        sk = {s["guid"]: s for s in (await self.sku_analytics(date_from, date_to, stations))["skus"]}
        станции = [int(x) for x in stations if str(x).isdigit()] if stations else None

        параметры: dict = {"cid": self.company_id}
        фильтр_станций = ""
        if станции:
            параметры["st"] = станции
            фильтр_станций = " AND p.station_id = ANY(:st)"

        rows = (await self.session.execute(text(f"""
            SELECT i.external_uuid::text AS guid, i.name, i.sku AS article,
                   i.vat_rate AS vat, i.marked, i.unit,
                   coalesce(i.sku_class, '— не разобрано') AS kind,
                   g.path AS group_path,
                   EXISTS (SELECT 1 FROM edge.barcode b
                            WHERE b.item_id = i.id AND b.status = 'active') AS has_barcode,
                   (SELECT sum(st.qty) FROM edge.stock st
                      JOIN edge.barcode b2 ON b2.id = st.barcode_id
                     WHERE b2.item_id = i.id) AS stock_qty,
                   (SELECT p.price FROM edge.price p
                     WHERE p.item_id = i.id AND p.valid_to IS NULL{фильтр_станций}
                     ORDER BY p.station_id LIMIT 1) AS retail_price,
                   (SELECT count(DISTINCT p.station_id) FROM edge.price p
                     WHERE p.item_id = i.id AND p.valid_to IS NULL) AS stations_count,
                   -- Не только СКОЛЬКО станций, но и какие именно.
                   --
                   -- Пока в колонке стояло число, оно ничего не говорило: «2» у
                   -- сети из двух АЗС и «1» рядом читаются одинаково, а вопрос
                   -- у товароведа другой — «где эта позиция есть, а где её нет».
                   (SELECT string_agg(DISTINCT p.station_id::text, ', '
                                      ORDER BY p.station_id::text)
                      FROM edge.price p
                     WHERE p.item_id = i.id AND p.valid_to IS NULL) AS stations_list,
                   -- Штрихкоды карточки — чтобы найти позицию сканером.
                   --
                   -- Поиск шёл по имени и артикулу, а человек за прилавком
                   -- держит в руках упаковку: он сканирует код, а не набирает
                   -- «Сигареты Winston XS Compact 100s Blue» по буквам.
                   (SELECT string_agg(b.code, ' ') FROM edge.barcode b
                     WHERE b.item_id = i.id AND b.status = 'active') AS barcodes
              FROM edge.item i
              LEFT JOIN edge.item_group g ON g.id = i.group_id
             WHERE NOT i.deleted AND (i.company_id IS NULL OR i.company_id = :cid)
             ORDER BY i.name
        """), параметры)).mappings().all()

        ql = (q or "").lower().strip()
        items = []
        kinds_seen: set = set()
        for n in rows:
            if ql and not (ql in (n["name"] or "").lower()
                           or ql in (n["article"] or "").lower()
                           or ql in (n["barcodes"] or "")):
                continue
            if marked == "marked" and not n["marked"]:
                continue
            if marked == "plain" and n["marked"]:
                continue
            # Весовой признак живёт в единице измерения: отдельной колонки у
            # карточки сети нет, а грамм и килограмм — это и есть вес.
            весовой = (n["unit"] or "").strip().lower() in ("г", "гр", "кг", "мл", "л")
            if weighed == "weighed" and not весовой:
                continue
            карточка = sk.get(n["guid"])
            if has_sales == "yes" and not карточка:
                continue
            if has_sales == "no" and карточка:
                continue
            kinds_seen.add(n["kind"])
            if kind != "all" and n["kind"] != kind:
                continue
            items.append({
                "guid": n["guid"], "name": n["name"], "article": n["article"],
                "vat": n["vat"], "marked": bool(n["marked"]), "weighed": весовой,
                "kind": n["kind"], "unit": n["unit"],
                "group_path": n["group_path"],
                "has_barcode": bool(n["has_barcode"]),
                "stations_count": int(n["stations_count"] or 0),
                "stations_list": n["stations_list"] or "",
                "revenue": карточка["revenue"] if карточка else 0.0,
                "qty": карточка["qty"] if карточка else 0.0,
                "stock_qty": round(float(n["stock_qty"] or 0), 3),
                "retail_price": float(n["retail_price"]) if n["retail_price"] is not None else None,
            })
        items.sort(key=lambda x: (-x["revenue"], x["name"]))
        return {
            "items": items,
            "kinds": sorted(kinds_seen),
            "summary": {
                "total": len(items),
                "marked": sum(1 for i in items if i["marked"]),
                "with_barcode": sum(1 for i in items if i["has_barcode"]),
                "with_sales": sum(1 for i in items if i["revenue"]),
                "on_stations": sum(1 for i in items if i["stations_count"] > 0),
            },
        }

    async def sales_analysis(self, date_from: date, date_to: date, *, group_by: str = "sku",
                             category: str = "all", marked: str = "all", q: str = "",
                             stations: list[str] | None = None) -> dict:
        sale_metas = self._select(await self._load(), date_from, date_to, stations)
        nom = await self._names()
        kinds = await self._refs("nom_kind")
        ql = (q or "").lower().strip()

        agg: dict[str, dict] = defaultdict(lambda: {"rev": 0.0, "net": 0.0, "vat": 0.0, "qty": 0.0, "skus": set(), "label": ""})
        shifts = len(sale_metas)

        # Что реально применено к выборке этого разреза (шапка UI не должна показывать
        # фильтр активным, если разрез его не поддерживает).
        applied = {"category": category, "marked": marked, "q": q}
        ignored: list[str] = []

        # payment — по секции оплат, не по строкам товаров
        if group_by == "payment":
            # Разрез «форма оплаты» товарного измерения не имеет: строка оплаты не несёт
            # ни номенклатуры, ни категории. Товарные фильтры к нему неприменимы —
            # раньше они молча игнорировались, но возвращались как применённые.
            for name, val, default in (("category", category, "all"), ("marked", marked, "all"), ("q", ql, "")):
                if val != default:
                    ignored.append(name)
            applied = {"category": "all", "marked": "all", "q": ""}

            for m in sale_metas:
                sec = m.get("Секции") or {}
                pay_lines = (sec.get("оплаты") or {}).get("строки") or []
                pay_sum = sum(float(o.get("Сумма") or 0) for o in pay_lines)
                # НДС берём фактический — из товарных строк смены (СуммаНДС), не по
                # фиксированной ставке 22%: у товаров бывает 10%/0%. Разносим НДС смены
                # на формы оплаты пропорционально суммам → итог сходится с товарным разрезом.
                shift_vat = sum(
                    float(ln.get("СуммаНДС") or 0)
                    for sec_key, _ in _SECTIONS
                    for ln in (sec.get(sec_key) or {}).get("строки") or []
                )
                for o in pay_lines:
                    kanon = str(o.get("ФормаОплатыКанон") or o.get("ФормаОплаты") or "—")
                    amt = float(o.get("Сумма") or 0)
                    vat = shift_vat * amt / pay_sum if pay_sum else 0.0
                    a = agg[kanon]
                    a["rev"] += amt
                    a["net"] += amt - vat
                    a["vat"] += vat
                    a["label"] = kanon
        else:
            for m in sale_metas:
                smena = m.get("Смена") or {}
                day = _day(smena)
                station = str(smena.get("КодАЗС") or "—")
                shift_key = str(smena.get("Смена") or f"{day}|{station}")
                sec = m.get("Секции") or {}
                for sec_key, catname in _SECTIONS:
                    if category == "soputka" and sec_key != "продажа_сопутка":
                        continue
                    if category == "obshepit" and sec_key != "продажа_общепит":
                        continue
                    for ln in (sec.get(sec_key) or {}).get("строки") or []:
                        g = ln.get("Номенклатура")
                        n = nom.get(g)
                        is_marked = bool(n and n.marked)
                        if marked == "marked" and not is_marked:
                            continue
                        if marked == "plain" and is_marked:
                            continue
                        if ql and not ((n and ql in (n.name or "").lower()) or (ql in str(g or "").lower())):
                            continue
                        summ = float(ln.get("Сумма") or 0)
                        vat = float(ln.get("СуммаНДС") or 0)
                        qty = float(ln.get("Количество") or 0)

                        if group_by == "category":
                            key, label = catname, catname
                        elif group_by == "kind":
                            kr = n.kind_ref if n else None
                            key = kr or "—"
                            label = kinds.get(kr, "— вид не указан")
                        elif group_by == "marking":
                            key = "marked" if is_marked else "plain"
                            label = "Маркированные (ЧЗ)" if is_marked else "Обычные товары"
                        elif group_by == "vat":
                            key = str(ln.get("СтавкаНДС") or (n.vat if n else None) or "—")
                            label = key
                        elif group_by == "day":
                            key = label = day
                        elif group_by == "shift":
                            key = shift_key
                            label = f"{day} · АЗС {station}"
                        else:  # sku
                            key = g or "—"
                            label = (n.name if n else str(g)[:8])

                        a = agg[key]
                        a["rev"] += summ
                        a["net"] += summ - vat
                        a["vat"] += vat
                        a["qty"] += qty
                        a["skus"].add(g)
                        a["label"] = label

        total = sum(a["rev"] for a in agg.values()) or 1.0
        groups = [{
            "key": k, "label": a["label"] or k,
            "revenue": round(a["rev"], 2), "revenue_net": round(a["net"], 2), "vat": round(a["vat"], 2),
            "qty": round(a["qty"], 3), "sku_count": len(a["skus"]),
            "share": round(100 * a["rev"] / total, 1),
        } for k, a in agg.items()]

        # Остаток и «хватит на» — только в разрезе по товарам, где вопрос имеет
        # смысл. «Сколько дней хватит категории “Сопутка”» ответа не имеет, а
        # цифра в таблице выглядела бы как ответ.
        #
        # Раньше за этим ходили в «Ассортимент»: там те же позиции и тот же
        # остаток, но разговор «что продаётся» и «на сколько хватит» — один, и
        # разрывать его на два экрана значит заставлять человека сверять списки.
        if group_by == "sku":
            дней = max((date_to - date_from).days + 1, 1)
            остатки: dict[str, float] = defaultdict(float)
            for r in (await self.session.execute(select(StockOnHand).where(
                StockOnHand.company_id == self.company_id))).scalars().all():
                if _warehouse_in_stations(r.warehouse_code, stations):
                    остатки[r.nomenclature_ref] += float(r.quantity or 0)
            for г in groups:
                остаток = остатки.get(г["key"], 0.0)
                в_день = г["qty"] / дней
                г["stock_qty"] = round(остаток, 3)
                г["days_of_supply"] = (round(остаток / в_день, 1)
                                       if в_день > 0 and остаток > 0 else None)
        if group_by in ("day", "shift"):
            groups.sort(key=lambda x: x["label"])   # хронологически
        else:
            groups.sort(key=lambda x: -x["revenue"])

        all_skus: set = set()
        for a in agg.values():
            all_skus |= a["skus"]
        return {
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "group_by": group_by,
            # filters — что РЕАЛЬНО применено; filters_ignored — запрошенные, но
            # неприменимые в этом разрезе (UI обязан показать их снятыми/недоступными).
            "filters": applied,
            "filters_ignored": ignored,
            "groups": groups,
            "summary": {
                "revenue": round(sum(a["rev"] for a in agg.values()), 2),
                "revenue_net": round(sum(a["net"] for a in agg.values()), 2),
                "vat": round(sum(a["vat"] for a in agg.values()), 2),
                "qty": round(sum(a["qty"] for a in agg.values()), 3),
                "sku_count": len(all_skus),
                "shifts": shifts,
                "groups_count": len(groups),
            },
        }

    # ── Слой политик: план продаж + план-факт-светофор (О-1, слой управляемости) ──

    @staticmethod
    def _month_range(period_ym: str) -> tuple[date, date]:
        """'YYYY-MM' → (первый день, последний день месяца)."""
        y, m = int(period_ym[:4]), int(period_ym[5:7])
        return date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])

    async def get_plans(self, period_ym: str) -> dict:
        """План продаж на месяц (сырые строки для формы редактирования)."""
        rows = (await self.session.execute(select(StorePlan).where(
            StorePlan.company_id == self.company_id,
            StorePlan.period_ym == period_ym,
        ))).scalars().all()
        return {
            "period": period_ym,
            "plans": [{
                "scope_kind": r.scope_kind, "scope_key": r.scope_key,
                "metric": r.metric, "plan_value": float(r.plan_value),
            } for r in rows],
        }

    async def save_plans(self, period_ym: str, items: list[dict]) -> dict:
        """Upsert плана (ручной ввод руководителя). Значение ≤0 удаляет строку."""
        existing = {
            (r.scope_kind, r.scope_key, r.metric): r
            for r in (await self.session.execute(select(StorePlan).where(
                StorePlan.company_id == self.company_id,
                StorePlan.period_ym == period_ym,
            ))).scalars().all()
        }
        for it in items or []:
            sk = str(it.get("scope_kind") or "total")
            key = str(it.get("scope_key") or "*")
            metric = str(it.get("metric") or "revenue")
            val = float(it.get("plan_value") or 0)
            row = existing.get((sk, key, metric))
            if val <= 0:
                if row is not None:
                    await self.session.delete(row)
                continue
            if row is not None:
                row.plan_value = val
            else:
                self.session.add(StorePlan(
                    company_id=self.company_id, period_ym=period_ym,
                    scope_kind=sk, scope_key=key, metric=metric, plan_value=val,
                ))
        await self.session.commit()
        return await self.get_plans(period_ym)

    async def plan_facts(self, period_ym: str) -> dict:
        """План-факт-светофор за месяц: карты факт/план/%/🟢🟡🔴 + спарклайн.
        Факт считается из продаж на лету; план — ручной StorePlan. ППГ/тренд —
        задел (включится с накоплением истории, сейчас данные ≈ 1 месяц)."""
        mstart, mend = self._month_range(period_ym)
        metas = self._select(await self._load(), mstart, mend, None)
        kpis = self._kpis(metas)
        fin, un = kpis["financial"], kpis["units"]
        by_cat = {c["category"]: c["revenue"] for c in un["by_category"]}
        by_station = self._by_station(metas)
        daily = self._charts(metas, mstart, mend)["daily"]

        pmap = {
            (p["scope_kind"], p["scope_key"], p["metric"]): p["plan_value"]
            for p in (await self.get_plans(period_ym))["plans"]
        }

        def card(scope_kind: str, scope_key: str, label: str, metric: str, fact: float) -> dict:
            plan = pmap.get((scope_kind, scope_key, metric))
            pct = round(100 * fact / plan, 1) if plan else None
            traffic = None
            if plan:
                traffic = "green" if pct >= 100 else ("amber" if pct >= 80 else "red")
            return {
                "scope_kind": scope_kind, "scope_key": scope_key, "label": label,
                "metric": metric, "fact": round(fact, 2),
                "plan": round(plan, 2) if plan else None,
                "pct": pct, "traffic": traffic,
                "delta": round(fact - plan, 2) if plan else None,
            }

        total = card("total", "*", "Выручка всего", "revenue", fin["total_revenue"])
        total["sparkline"] = [{"date": d["date"], "value": d["revenue"]} for d in daily]
        units = card("total", "*", "Позиций продано", "qty", un["total_units"])
        cat_cards = [card("category", name, name, "revenue", rev) for name, rev in by_cat.items()]
        station_cards = [
            card("station", s["station"], f"АЗС {s['station']}", "revenue", s["revenue"])
            for s in by_station
        ]
        all_cards = [total, units, *cat_cards, *station_cards]
        planned = sum(1 for c in all_cards if c["plan"] is not None)
        return {
            "period": {"ym": period_ym, "from": mstart.isoformat(), "to": mend.isoformat()},
            "total": total,
            "units": units,
            "by_category": cat_cards,
            "by_station": station_cards,
            "has_plan": planned > 0,
            "planned_count": planned,
        }

    # ── Слой политик: МРЦ табака — регуляторный контроль «продажа выше МРЦ» (О-3) ──

    async def _barcode_ref_map(self) -> dict[str, str]:
        """Штрихкод (GTIN) → GUID номенклатуры (для матча CSV МРЦ).
        В регистре ЦБ owner_ref не заполнен → мост через owner_name → имя
        номенклатуры (owner_ref, если появится, имеет приоритет)."""
        names = await self._names()
        name_to_ref: dict[str, str] = {}
        for ref, n in names.items():
            if n.name:
                name_to_ref.setdefault(n.name.strip().lower(), ref)
        rows = (await self.session.execute(select(CbBarcode).where(
            CbBarcode.company_id == self.company_id))).scalars().all()
        m: dict[str, str] = {}
        for b in rows:
            if not b.barcode:
                continue
            ref = b.owner_ref or name_to_ref.get((b.owner_name or "").strip().lower())
            if ref:
                m.setdefault(b.barcode.strip(), ref)
        return m

    async def import_mrc(self, rows: list[dict]) -> dict:
        """Импорт справочника МРЦ (ручной CSV). Строка: {barcode?|article?, name?, mrc}.
        Резолв в nomenclature_ref: штрихкод → артикул; нерезолвленные возвращаются."""
        bc_map = await self._barcode_ref_map()
        names = await self._names()
        art_map = {n.article.strip(): n.external_ref for n in names.values() if n.article}
        name_map = {n.name.strip().lower(): n.external_ref for n in names.values() if n.name}
        existing = {
            r.nomenclature_ref: r
            for r in (await self.session.execute(select(TobaccoMrc).where(
                TobaccoMrc.company_id == self.company_id))).scalars().all()
        }
        touched: dict[str, TobaccoMrc] = {}
        imported = 0
        unresolved: list[dict] = []
        for r in rows or []:
            raw = str(r.get("mrc") if r.get("mrc") is not None else "").replace(",", ".").replace(" ", "")
            try:
                mrc = float(raw)
            except (TypeError, ValueError):
                continue
            if mrc <= 0:
                continue
            bc = str(r.get("barcode") or "").strip()
            art = str(r.get("article") or "").strip()
            nm = str(r.get("name") or "").strip()
            ref = matched_bc = None
            if bc and bc in bc_map:
                ref, matched_bc = bc_map[bc], bc
            elif art and art in art_map:
                ref = art_map[art]
            elif nm and nm.strip().lower() in name_map:
                ref = name_map[nm.strip().lower()]
            if not ref:
                unresolved.append({"barcode": bc, "article": art, "name": nm, "mrc": mrc})
                continue
            row = touched.get(ref) or existing.get(ref)
            if row is not None:
                row.mrc = mrc
                if nm:
                    row.name = nm
                if matched_bc:
                    row.barcode = matched_bc
            else:
                n = names.get(ref)
                row = TobaccoMrc(
                    company_id=self.company_id, nomenclature_ref=ref,
                    name=nm or (n.name if n else None), barcode=matched_bc, mrc=mrc,
                )
                self.session.add(row)
                touched[ref] = row
            imported += 1
        await self.session.commit()
        return {"imported": imported, "unresolved_count": len(unresolved), "unresolved": unresolved[:200]}

    async def mrc_control(self) -> dict:
        """Контроль МРЦ: розничная цена vs МРЦ (нарушение = продажа выше МРЦ) +
        табак без заданной МРЦ (пробел справочника)."""
        mrc_rows = (await self.session.execute(select(TobaccoMrc).where(
            TobaccoMrc.company_id == self.company_id))).scalars().all()
        mrc_map = {r.nomenclature_ref: r for r in mrc_rows}
        names = await self._names()

        # розничная цена = ЦенаВРознице (StockOnHand); при нескольких складах — макс.
        soh = (await self.session.execute(select(StockOnHand).where(
            StockOnHand.company_id == self.company_id))).scalars().all()
        price_map: dict[str, float] = {}
        for s in soh:
            if s.retail_price is not None:
                p = float(s.retail_price)
                if p > price_map.get(s.nomenclature_ref, 0):
                    price_map[s.nomenclature_ref] = p

        items = []
        violations = missing_price = 0
        for ref, m in mrc_map.items():
            n = names.get(ref)
            price = price_map.get(ref)
            over = price is not None and price > float(m.mrc) + 0.001
            if over:
                violations += 1
            if price is None:
                missing_price += 1
            items.append({
                "ref": ref, "name": (n.name if n else m.name) or ref[:8],
                "barcode": m.barcode, "mrc": round(float(m.mrc), 2),
                "retail_price": round(price, 2) if price is not None else None,
                "over": over,
                "diff": round(price - float(m.mrc), 2) if price is not None else None,
            })
        # нарушения вперёд, затем по величине превышения
        items.sort(key=lambda x: (not x["over"], -(x["diff"] if x["diff"] is not None else -1e9)))

        # пробел справочника: табак без МРЦ. Вид в ЦБ 208 не различает табак
        # (5 общих видов) → детекция по имени (сигарет/табак/tobacco), marked усиливает.
        kinds = await self._refs("nom_kind")
        missing_mrc = 0
        for ref, n in names.items():
            if ref in mrc_map:
                continue
            hay = f"{n.name or ''} {kinds.get(n.kind_ref) or '' if n.kind_ref else ''}".lower()
            is_tobacco = ("сигар" in hay or "табак" in hay or "tobacco" in hay
                          or ("сигарил" in hay) or ("папирос" in hay))
            if is_tobacco:
                missing_mrc += 1

        return {
            "items": items,
            "summary": {
                "controlled": len(items),
                "violations": violations,
                "missing_price": missing_price,
                "missing_mrc": missing_mrc,
            },
        }

    # ── Смена как составной документ: роллап операций на смену (архитектура МАГа) ──

    async def shifts_composite(self, date_from: date, date_to: date,
                               stations: list[str] | None = None) -> dict:
        """Смена = организующая единица: за каждую смену — продажи (сопутка/
        общепит) + возвраты + роллап приходов/инвентаризаций/списаний того же
        дня. Приходы/инвентаризации в ЦБ не несут GUID смены → связка по
        (станция, дата). Первый шаг к смене-umbrella над всеми операциями."""
        d0, d1 = date_from.isoformat(), date_to.isoformat()
        metas = self._select(await self._load(), date_from, date_to, stations)

        # приходы (ПТУ) по дате
        rec_by_day: dict[tuple[str, str], dict] = defaultdict(
            lambda: {"amount_net": 0.0, "count": 0})
        for m in await self._load_purchases(date_from, date_to, stations):
            d = m.get("Документ") or {}
            station = str((m.get("Смена") or {}).get("КодАЗС") or "—")
            day = str(d.get("Дата") or "")[:10]
            lines = d.get("Товары") or []
            amt = sum(float(l.get("Сумма") or 0) for l in lines)
            vat = sum(float(l.get("СуммаНДС") or 0) for l in lines)
            rec_by_day[(station, day)]["amount_net"] += amt - vat
            rec_by_day[(station, day)]["count"] += 1

        shift_stations = sorted({
            str((m.get("Смена") or {}).get("КодАЗС") or "") for m in metas
        }, key=len, reverse=True)

        def station_of_warehouse(code: str | None) -> str | None:
            return next((st for st in shift_stations
                         if st and _warehouse_in_stations(code, [st])), None)

        # инвентаризации по дате
        inv_by_day: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "net": 0.0})
        for r in (await self.session.execute(select(CbInventoryDoc).where(
                CbInventoryDoc.company_id == self.company_id,
            CbInventoryDoc.deleted.is_(False)))).scalars().all():
            day = (r.doc_date or "")[:10]
            station = station_of_warehouse(r.warehouse_code)
            if station and d0 <= day <= d1:
                inv_by_day[(station, day)]["count"] += 1
                inv_by_day[(station, day)]["net"] += float(r.net_amount or 0)

        # списания / перемещения / переоценки по дате (все движения одним запросом)
        wo_by_day: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "amount": 0.0})
        tr_by_day: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0, "amount": 0.0})
        rv_by_day: dict[tuple[str, str], dict] = defaultdict(lambda: {"count": 0})
        for r in (await self.session.execute(select(CbMovementDoc).where(
                CbMovementDoc.company_id == self.company_id,
                CbMovementDoc.deleted.is_(False), CbMovementDoc.posted.is_(True)))).scalars().all():
            day = (r.doc_date or "")[:10]
            station = station_of_warehouse(r.warehouse_code)
            if r.kind == "transfer" and not station:
                station = station_of_warehouse(r.warehouse_to_code)
            if not station or not (d0 <= day <= d1):
                continue
            key = (station, day)
            if r.kind == "writeoff":
                wo_by_day[key]["count"] += 1
                wo_by_day[key]["amount"] += float(r.total_amount or 0)
            elif r.kind == "transfer":
                tr_by_day[key]["count"] += 1
                tr_by_day[key]["amount"] += float(r.total_amount or 0)
            elif r.kind == "revaluation":
                rv_by_day[key]["count"] += 1

        # Поток людей по смене: чеки с товаром и заправки той же смены.
        #
        # Выручка смены сама по себе не говорит ничего: сорок тысяч — это много
        # или мало, зависит от того, прошло мимо кассы 385 человек или 90. Тот же
        # вопрос задаёт себе администратор станции в своём реестре смен, и центр
        # обязан отвечать на него так же — иначе разговор о работе смены
        # упирается в «а у меня другие цифры».
        чеки_смены: dict[tuple[int, int], int] = {}
        for r in (await self.session.execute(text("""
            SELECT station_id, shift_number, count(*) AS n
              FROM store_cheques
             WHERE company_id = :cid AND is_return = false
             GROUP BY station_id, shift_number
        """), {"cid": self.company_id})).mappings().all():
            чеки_смены[(int(r["station_id"]), int(r["shift_number"]))] = int(r["n"])
        заправки_смены: dict[tuple[int, int], int] = {}
        for r in (await self.session.execute(text("""
            SELECT station_code, shift_number, count(DISTINCT receipt) AS n
              FROM fuel_transactions
             WHERE company_id = :cid AND shift_number IS NOT NULL
             GROUP BY station_code, shift_number
        """), {"cid": self.company_id})).mappings().all():
            заправки_смены[(int(r["station_code"]), int(r["shift_number"]))] = int(r["n"])

        # F6: документы дня (приходы/инвентаризации/списания/перемещения) связаны с
        # днём, не со сменой; на ДВУХСМЕННОМ дне они приписывались КАЖДОЙ смене и
        # задваивались в summary. Привязываем день-документы к ОДНОЙ смене дня
        # (первой по (станция, дата)); остальные смены дня получают нули.
        metas = sorted(metas, key=lambda m: (
            _day(m.get("Смена") or {}), str((m.get("Смена") or {}).get("Открытие") or "")))

        day_assigned: set[tuple[str, str]] = set()
        shifts = []
        for m in metas:
            smena = m.get("Смена") or {}
            day = _day(smena)
            station = str(smena.get("КодАЗС") or "—")
            sec = m.get("Секции") or {}
            sop = sec.get("продажа_сопутка") or {}
            obsh = sec.get("продажа_общепит") or {}
            sop_rev = float(sop.get("сумма") or 0)
            obsh_rev = float(obsh.get("сумма") or 0)
            dkey = (station, day)
            if dkey in day_assigned:
                rec = inv = wo = tr = rv = {}   # день уже отдан первой смене
            else:
                day_assigned.add(dkey)
                rec = rec_by_day.get(dkey, {})
                inv = inv_by_day.get(dkey, {})
                wo = wo_by_day.get(dkey, {})
                tr = tr_by_day.get(dkey, {})
                rv = rv_by_day.get(dkey, {})
            shifts.append({
                "shift_key": str(smena.get("Смена") or f"{day}|{station}"),
                "date": day, "station": station,
                "number": smena.get("НомерСмены") or smena.get("Номер"),
                "open": smena.get("Открытие"), "close": smena.get("Закрытие"),
                # Оператор смены — из пакета станции; у документов ЦБ его нет,
                # поэтому поле пустое, а не выдуманное.
                "operator": smena.get("Оператор") or None,
                "register": smena.get("Касса") or None,
                "internal_no": smena.get("НомерСменыВнутр") or None,
                **_поток_смены(station, smena.get("НомерСменыВнутр"),
                               чеки_смены, заправки_смены),
                "revenue": round(sop_rev + obsh_rev, 2),
                "soputka": round(sop_rev, 2), "obshepit": round(obsh_rev, 2),
                "positions": len(sop.get("строки") or []) + len(obsh.get("строки") or []),
                "returns": round(float((sec.get("возвраты") or {}).get("сумма") or 0), 2),
                "receipts_amount": round(rec.get("amount_net", 0.0), 2),
                "receipts_count": rec.get("count", 0),
                "inventory_count": inv.get("count", 0),
                "inventory_net": round(inv.get("net", 0.0), 2),
                "writeoff_amount": round(wo.get("amount", 0.0), 2),
                "writeoff_count": wo.get("count", 0),
                "transfer_count": tr.get("count", 0),
                "transfer_amount": round(tr.get("amount", 0.0), 2),
                "reval_count": rv.get("count", 0),
            })
        shifts.sort(key=lambda x: x["date"])
        return {
            "period": {"from": d0, "to": d1},
            "shifts": shifts,
            "summary": {
                "count": len(shifts),
                "revenue": round(sum(s["revenue"] for s in shifts), 2),
                "returns": round(sum(s["returns"] for s in shifts), 2),
                "receipts_amount": round(sum(s["receipts_amount"] for s in shifts), 2),
                "inventory_docs": sum(s["inventory_count"] for s in shifts),
                "inventory_net": round(sum(s["inventory_net"] for s in shifts), 2),
                "writeoff_amount": round(sum(s["writeoff_amount"] for s in shifts), 2),
                "transfer_docs": sum(s["transfer_count"] for s in shifts),
                "reval_docs": sum(s["reval_count"] for s in shifts),
            },
        }

    async def shift_detail(self, shift_key: str) -> dict:
        """Смена-детализация (модалка): операции одной смены — строки продаж
        (сопутка/общепит по SKU), касса (оплаты), возвраты + документы приходов/
        инвентаризаций/списаний того же дня (связка по станция+дата)."""
        target = day = station = None
        for m in self._select(await self._load(), date(2000, 1, 1), date(2100, 1, 1), None):
            smena = m.get("Смена") or {}
            d = _day(smena)
            st = str(smena.get("КодАЗС") or "—")
            if str(smena.get("Смена") or f"{d}|{st}") == shift_key:
                target, day, station = m, d, st
                break
        if target is None:
            return {"found": False, "shift_key": shift_key}

        nom = await self._names()
        smena = target.get("Смена") or {}
        sec = target.get("Секции") or {}

        # строки продаж, свёрнутые по SKU
        agg: dict[str, dict] = defaultdict(lambda: {"name": "", "qty": 0.0, "revenue": 0.0, "category": None, "marked": False})
        sop_rev = obsh_rev = 0.0
        for sec_key, catname in _SECTIONS:
            for ln in (sec.get(sec_key) or {}).get("строки") or []:
                g = ln.get("Номенклатура") or "—"
                n = nom.get(g)
                summ = float(ln.get("Сумма") or 0)
                a = agg[g]
                a["name"] = n.name if n else str(g)[:8]
                a["qty"] += float(ln.get("Количество") or 0)
                a["revenue"] += summ
                a["category"] = catname
                a["marked"] = bool(n and n.marked)
                if sec_key == "продажа_сопутка":
                    sop_rev += summ
                else:
                    obsh_rev += summ
        sales = sorted(
            [{"guid": g, "name": a["name"], "category": a["category"], "marked": a["marked"],
              "qty": round(a["qty"], 3), "revenue": round(a["revenue"], 2)} for g, a in agg.items()],
            key=lambda x: -x["revenue"],
        )

        # Вид оплаты называется по-разному у двух источников: ЦБ пишет
        # «ФормаОплаты», агент станции — «ВидОплаты» (так это поле зовётся в
        # контракте БП). Читаем оба, иначе у собственных смен станции вместо
        # «Наличные» и «Карты МПС» стоял прочерк.
        payments = [
            {"form": str(o.get("ФормаОплатыКанон") or o.get("ФормаОплаты")
                         or o.get("ВидОплаты") or "—"),
             "amount": round(float(o.get("Сумма") or 0), 2)}
            for o in ((sec.get("оплаты") or {}).get("строки") or [])
        ]
        payments.sort(key=lambda x: -x["amount"])
        ret = sec.get("возвраты") or {}

        # документы того же дня (полный состав смены + строки для раскрытия)
        d0 = date.fromisoformat(day) if day else None
        receipts: list[dict] = []
        if d0 is not None:
            cparty = await self._refs("counterparty")
            for m in await self._load_purchases(d0, d0, [station]):
                dd = m.get("Документ") or {}
                lns = dd.get("Товары") or []
                amt = sum(float(l.get("Сумма") or 0) for l in lns)
                vat = sum(float(l.get("СуммаНДС") or 0) for l in lns)
                receipts.append({
                    "number": dd.get("Номер"),
                    "supplier": cparty.get(dd.get("Контрагент")) or (dd.get("Контрагент") or "—"),
                    "positions": len(lns), "amount_net": round(amt - vat, 2),
                    "lines": [{
                        "name": (nom[l["Номенклатура"]].name if nom.get(l.get("Номенклатура")) else "—"),
                        "qty": round(float(l.get("Количество") or 0), 3),
                        "price": round(float(l.get("Цена") or 0), 2),
                        "amount": round(float(l.get("Сумма") or 0), 2),
                    } for l in lns],
                })

        dl = (day or "") + "%"
        inv_docs = (await self.session.execute(select(CbInventoryDoc).where(
            CbInventoryDoc.company_id == self.company_id,
            CbInventoryDoc.deleted.is_(False),
            CbInventoryDoc.doc_date.like(dl)))).scalars().all()
        inventory = [{
            "number": r.number, "dev_positions": r.dev_positions, "net": round(float(r.net_amount or 0), 2),
            "lines": [{"name": ln.get("name"), "fact": ln.get("fact"), "uchet": ln.get("uchet"),
                       "dev": ln.get("dev"), "amount": ln.get("amount_dev")}
                      for ln in (r.lines or []) if ln.get("dev")],
        } for r in inv_docs if _warehouse_in_stations(r.warehouse_code, [station])]

        mv = (await self.session.execute(select(CbMovementDoc).where(
            CbMovementDoc.company_id == self.company_id,
            CbMovementDoc.deleted.is_(False), CbMovementDoc.posted.is_(True),
            CbMovementDoc.doc_date.like(dl)))).scalars().all()

        def _mv_lines(r):
            return [{"name": ln.get("name"), "qty": ln.get("qty"), "amount": ln.get("amount"),
                     "price": ln.get("price"), "old": ln.get("old"), "new": ln.get("new"),
                     "pct": ln.get("pct")} for ln in (r.lines or [])]

        mv = [
            r for r in mv
            if _warehouse_in_stations(r.warehouse_code, [station])
            or (r.kind == "transfer" and _warehouse_in_stations(r.warehouse_to_code, [station]))
        ]
        writeoffs = [{"number": r.number, "reason": r.reason, "positions": r.positions,
                      "amount": round(float(r.total_amount or 0), 2), "lines": _mv_lines(r)}
                     for r in mv if r.kind == "writeoff"]
        transfers = [{"number": r.number, "to": r.warehouse_to_name or r.warehouse_to_code,
                      "positions": r.positions, "amount": round(float(r.total_amount or 0), 2),
                      "lines": _mv_lines(r)}
                     for r in mv if r.kind == "transfer"]
        revaluations = [{"number": r.number, "positions": r.positions, "lines": _mv_lines(r)}
                        for r in mv if r.kind == "revaluation"]

        return {
            "found": True,
            "shift": {
                "shift_key": shift_key, "date": day, "station": station,
                "number": smena.get("НомерСмены") or smena.get("Номер"),
                "open": smena.get("Открытие"), "close": smena.get("Закрытие"),
                # Кто стоял за кассой и на какой кассе — реквизиты смены, а не
                # украшение: при разборе расхождения первый вопрос бухгалтера
                # именно этот. Агент их присылает, ЦБ оператора не отдавал вовсе.
                "operator": smena.get("Оператор") or None,
                "register": smena.get("Касса") or None,
                "internal_no": smena.get("НомерСменыВнутр") or None,
                "revenue": round(sop_rev + obsh_rev, 2),
                "soputka": round(sop_rev, 2), "obshepit": round(obsh_rev, 2),
                "positions": len(sales),
                "returns": round(float(ret.get("сумма") or 0), 2),
            },
            "sales": sales,
            "payments": payments,
            "receipts": receipts,
            "inventory": inventory,
            "writeoffs": writeoffs,
            "transfers": transfers,
            "revaluations": revaluations,
        }
