"""Справочники измерений и метрик сводных - единственное место, откуда берётся SQL.

Правило безопасности: в запрос подставляется **только** выражение из этих карт.
Ничего пришедшего от клиента в SQL не попадает: клиент передаёт ключи (`station`,
`fuel`), а не колонки. Неизвестный ключ, дубль и превышение лимита уровней это 400,
а не «молча пропустим».

Второе назначение - общий словарь для источников. Их уже два (реализации и
поступления топлива), и у каждого свои измерения с метриками: у продаж литры с
выручкой, у приёмки массы по документу и факту с отклонением. Складывать их в одну
сводную нельзя (итоги разойдутся с KPI), поэтому источники разведены явно.
"""
from __future__ import annotations

from typing import Any

from datetime import datetime, timedelta, timezone

from sqlalchemy import case, cast, func
from sqlalchemy.orm import aliased
from sqlalchemy.types import String

from app.models import FuelReceipt as R
from app.models import FuelTransaction as T
from app.models import MarketOperator, MarketSite as MS
from app.models import StoreCheque as CQ
from app.models import StoreStockBalance as SB

MAX_DIMS = 5

# ─── Источник «реализации» (пооперационные транзакции) ───────────────────────
_TX_DIMS: dict[str, dict[str, Any]] = {
    "station": {"label": "АЗС", "expr": T.station_code},
    "fuel": {"label": "Вид топлива", "expr": T.fuel_name},
    "payment": {"label": "Способ оплаты", "expr": func.coalesce(T.payment_method, T.pay_type_name)},
    "pay_type": {"label": "Вид оплаты (как в источнике)", "expr": T.pay_type_name},
    "status": {"label": "Статус", "expr": T.status},
    "shift": {"label": "Смена", "expr": T.shift_number},
    "pos": {"label": "Касса (POS)", "expr": T.pos},
    "nozzle": {"label": "Пистолет", "expr": T.nozzle},
    "tank": {"label": "Резервуар", "expr": T.tank},
    "card": {"label": "Карта", "expr": T.card},
    "day": {"label": "День", "expr": func.to_char(T.dt, "YYYY-MM-DD")},
    "month": {"label": "Месяц", "expr": func.to_char(T.dt, "YYYY-MM")},
    "weekday": {"label": "День недели", "expr": func.to_char(T.dt, "ID")},
    "hour": {"label": "Час", "expr": func.to_char(T.dt, "HH24")},
}

_TX_METRICS: dict[str, dict[str, Any]] = {
    "ops": {"label": "Операций", "expr": func.count(), "digits": 0},
    "liters": {"label": "Литры", "expr": func.coalesce(func.sum(T.liters), 0), "digits": 3},
    "amount": {"label": "Выручка, ₽", "expr": func.coalesce(func.sum(T.amount), 0), "digits": 2},
}

# ─── Источник «поступления» (приёмка ТТН) ────────────────────────────────────
# Здесь метрики другие и это принципиально: приёмку сверяют по МАССЕ, а не по литрам
# (объём зависит от температуры). Отклонение факта от документа - главный ответ
# экрана, поэтому оно считается суммой, а не выводится из средних.
_RC_DIMS: dict[str, dict[str, Any]] = {
    "supplier": {"label": "Поставщик", "expr": func.coalesce(R.supplier, "")},
    "fuel": {"label": "Вид топлива", "expr": R.fuel_name},
    "station": {"label": "АЗС", "expr": R.station_id},
    "tank": {"label": "Резервуар", "expr": R.tank},
    "shift": {"label": "Смена", "expr": R.shift_number},
    "ttn": {"label": "Номер ТТН", "expr": R.ttn},
    "day": {"label": "День", "expr": func.to_char(R.received_at, "YYYY-MM-DD")},
    "month": {"label": "Месяц", "expr": func.to_char(R.received_at, "YYYY-MM")},
}

_RC_METRICS: dict[str, dict[str, Any]] = {
    "docs": {"label": "Документов", "expr": func.count(), "digits": 0},
    "doc_mass": {"label": "Масса по ТТН, кг", "expr": func.coalesce(func.sum(R.doc_mass_kg), 0), "digits": 2},
    "fact_mass": {"label": "Масса факт, кг", "expr": func.coalesce(func.sum(R.fact_mass_kg), 0), "digits": 2},
    "diff_mass": {"label": "Отклонение массы, кг", "expr": func.coalesce(func.sum(R.diff_mass), 0), "digits": 2},
    "doc_volume": {"label": "Объём по ТТН, л", "expr": func.coalesce(func.sum(R.doc_volume_liters), 0), "digits": 2},
    "fact_volume": {"label": "Объём факт, л", "expr": func.coalesce(func.sum(R.fact_volume_liters), 0), "digits": 2},
    # Сумм по ТТН в источнике нет: `doc_cost` и `fact_cost` приходят нулями на всех
    # 1445 документах (проверено на данных ГИГ). Колонка из нулей только мешает
    # читать разрез, вернём её, когда поставщик начнёт отдавать суммы.
}

# ─── Источник «остатки магазина» (снимки станций) ────────────────────────────
# Товароучёт сопутки живёт теми же вопросами, что и топливо: где лежит, чего
# сколько, почём. Поэтому сводная у него не своя, а та же — с этими картами.
_ST_DIMS: dict[str, dict[str, Any]] = {
    "station": {"label": "АЗС", "expr": SB.station_id},
    "place": {"label": "Место хранения", "expr": func.coalesce(SB.place_name, SB.place)},
    "item": {"label": "Товар", "expr": SB.name},
    "barcode": {"label": "Штрихкод", "expr": SB.barcode},
    "cost_known": {"label": "Себестоимость известна",
                   "expr": case((func.coalesce(SB.cost_unit, 0) > 0, "да"), else_="нет")},
    "day": {"label": "День снимка", "expr": func.to_char(SB.snapshot_at, "YYYY-MM-DD")},
}

_ST_METRICS: dict[str, dict[str, Any]] = {
    "rows": {"label": "Позиций", "expr": func.count(), "digits": 0},
    "qty": {"label": "Количество", "expr": func.coalesce(func.sum(SB.quantity), 0), "digits": 3},
    "retail": {"label": "Сумма в рознице, ₽",
               "expr": func.coalesce(func.sum(SB.quantity * func.coalesce(SB.retail_price, 0)), 0),
               "digits": 2},
    "cost": {"label": "Сумма в себестоимости, ₽",
             "expr": func.coalesce(func.sum(SB.quantity * func.coalesce(SB.cost_unit, 0)), 0),
             "digits": 2},
}

# ─── Источник «чеки магазина» ────────────────────────────────────────────────
# Продажа на уровне покупки: чек — то, что человек унёс с собой за один подход
# к кассе. Средний чек и разбивка по оплате считаются только здесь.
_CQ_DIMS: dict[str, dict[str, Any]] = {
    "station": {"label": "АЗС", "expr": CQ.station_id},
    "shift": {"label": "Смена", "expr": CQ.shift_number},
    "payment": {"label": "Способ оплаты", "expr": func.coalesce(CQ.pay_name, "—")},
    "with_fuel": {"label": "С топливом", "expr": case((CQ.had_fuel, "да"), else_="нет")},
    "kind": {"label": "Вид чека", "expr": case((CQ.is_return, "возврат"), else_="продажа")},
    "day": {"label": "День", "expr": func.to_char(CQ.at, "YYYY-MM-DD")},
    "month": {"label": "Месяц", "expr": func.to_char(CQ.at, "YYYY-MM")},
    "weekday": {"label": "День недели", "expr": func.to_char(CQ.at, "ID")},
    "hour": {"label": "Час", "expr": func.to_char(CQ.at, "HH24")},
}

_CQ_METRICS: dict[str, dict[str, Any]] = {
    "cheques": {"label": "Чеков", "expr": func.count(), "digits": 0},
    "positions": {"label": "Позиций", "expr": func.coalesce(func.sum(CQ.positions), 0), "digits": 0},
    "amount": {"label": "Сумма, ₽", "expr": func.coalesce(func.sum(CQ.total), 0), "digits": 2},
}

# ─── Источник «точки рынка» (внешний реестр ЭЗС) ─────────────────────────────
# Девять тысяч чужих станций: разрез по одному признаку за раз отвечает на «сколько
# их», но не на «чьи они, где стоят и чем оснащены» одновременно (замечание
# РусГидро 14.09.2026). Владелец и эксплуатант — разные компании, поэтому в
# измерениях они тоже разные: имя владельца приходит через свой алиас, имя
# эксплуатанта — через свой.
MARKET_OWNER = aliased(MarketOperator, name="pivot_owner")
MARKET_OPERATOR = aliased(MarketOperator, name="pivot_operator")

# Живой = заряжали за 90 дней. Тот же срок, что на экранах рынка: два разных
# определения «живой» в одном продукте — верный способ не сойтись с витриной.
_MK_ALIVE_DAYS = 90


def _mk_alive_since():
    return datetime.now(timezone.utc) - timedelta(days=_MK_ALIVE_DAYS)


_MK_DIMS: dict[str, dict[str, Any]] = {
    "owner": {"label": "Владелец ЭЗС", "expr": func.coalesce(MARKET_OWNER.name, "— не определён —")},
    "operator": {"label": "Эксплуатант", "expr": func.coalesce(MARKET_OPERATOR.name, "— не указан —")},
    "platform": {"label": "Платформа", "expr": func.coalesce(MARKET_OPERATOR.platform_owner, "— неизвестна —")},
    "region": {"label": "Регион", "expr": func.coalesce(MS.region, "— не указан —")},
    "city": {"label": "Город", "expr": func.coalesce(MS.city, "— не указан —")},
    "site_class": {"label": "Класс точки", "expr": case(
        (MS.site_class == "network", "сеть"),
        (MS.site_class == "independent", "независимая"),
        (MS.site_class == "home", "домашняя розетка"),
        else_="не определён")},
    "kind": {"label": "Вид точки", "expr": MS.kind},
    "current": {"label": "Тип тока", "expr": func.coalesce(MS.current_type, "— не указан —")},
    "power": {"label": "Класс мощности", "expr": case(
        (MS.max_power_kw.is_(None), "не указана"),
        (MS.max_power_kw < 22, "до 22 кВт"),
        (MS.max_power_kw < 50, "22–50 кВт"),
        (MS.max_power_kw < 150, "50–150 кВт"),
        else_="150 кВт и выше")},
    "vendor": {"label": "Производитель", "expr": func.coalesce(MS.vendor, "— не указан —")},
    "alive": {"label": "Заряжали за 90 дней", "expr": case(
        (MS.last_session_at.is_(None), "нет данных"),
        (MS.last_session_at >= _mk_alive_since(), "да"),
        else_="нет")},
    "status": {"label": "Состояние", "expr": MS.status},
    "ours": {"label": "Наша сеть", "expr": case(
        (MS.location_id.is_not(None), "мы"), else_="рынок")},
    "source": {"label": "Источник", "expr": MS.source},
    "owner_checked": {"label": "Владелец подтверждён", "expr": case(
        (MS.owner_checked, "да"), else_="нет")},
    "year": {"label": "Год появления в данных",
             "expr": func.to_char(MS.first_seen_at, "YYYY")},
}

# Цены здесь нет намеренно: она живёт наблюдениями со своей датой и достоверностью,
# а не полем точки. Сводить её суммой было бы бессмыслицей — цена не складывается.
_MK_METRICS: dict[str, dict[str, Any]] = {
    "sites": {"label": "Точек", "expr": func.count(), "digits": 0},
    "ports": {"label": "Портов", "expr": func.coalesce(func.sum(MS.ports), 0), "digits": 0},
    "connectors": {"label": "Разъёмов",
                   "expr": func.coalesce(func.sum(MS.connectors_total), 0), "digits": 0},
    "alive": {"label": "Живых (90 дней)", "expr": func.coalesce(func.sum(
        case((MS.last_session_at >= _mk_alive_since(), 1), else_=0)), 0), "digits": 0},
    "power_kw": {"label": "Мощность всего, кВт",
                 "expr": func.coalesce(func.sum(MS.max_power_kw), 0), "digits": 1},
}

SOURCES: dict[str, dict[str, Any]] = {
    "transactions": {"dims": _TX_DIMS, "metrics": _TX_METRICS, "default_metric": "amount"},
    "receipts": {"dims": _RC_DIMS, "metrics": _RC_METRICS, "default_metric": "doc_mass"},
    "store_stock": {"dims": _ST_DIMS, "metrics": _ST_METRICS, "default_metric": "retail"},
    "store_cheques": {"dims": _CQ_DIMS, "metrics": _CQ_METRICS, "default_metric": "amount"},
    "market_sites": {"dims": _MK_DIMS, "metrics": _MK_METRICS, "default_metric": "sites"},
}


def _src(source: str) -> dict[str, Any]:
    if source not in SOURCES:
        raise ValueError(f"Неизвестный источник сводной: {source}")
    return SOURCES[source]


def dims_catalog(source: str = "transactions") -> list[dict[str, str]]:
    """Справочник измерений для UI: ключ и подпись, в порядке карты."""
    return [{"key": k, "label": v["label"]} for k, v in _src(source)["dims"].items()]


def metrics_catalog(source: str = "transactions") -> list[dict[str, Any]]:
    """Метрики источника: что можно показать и по чему сортировать."""
    return [{"key": k, "label": v["label"], "digits": v["digits"]}
            for k, v in _src(source)["metrics"].items()]


def parse_dims(raw: str | None, source: str = "transactions") -> list[str]:
    """CSV ключей → проверенный список. Мусор, дубли и перебор уровней это ошибка.

    Возвращает ключи, а не SQL: подстановкой занимается `dim_expr`, и только он.
    """
    dims = _src(source)["dims"]
    keys = [k.strip() for k in (raw or "").split(",") if k.strip()]
    if not keys:
        raise ValueError("Не указано ни одного измерения")
    if len(keys) > MAX_DIMS:
        raise ValueError(f"Слишком много уровней: {len(keys)}, максимум {MAX_DIMS}")
    seen: set[str] = set()
    for k in keys:
        if k not in dims:
            raise ValueError(f"Неизвестное измерение: {k}")
        if k in seen:
            raise ValueError(f"Измерение повторяется: {k}")
        seen.add(k)
    return keys


def dim_expr(key: str, source: str = "transactions"):
    """SQL-выражение измерения. Ключ обязан быть проверен `parse_dims`."""
    return _src(source)["dims"][key]["expr"]


def dim_label(key: str, source: str = "transactions") -> str:
    return _src(source)["dims"][key]["label"]


def dim_select(key: str, source: str = "transactions"):
    """Выражение для SELECT: всё приводим к тексту, чтобы ключи строк были однородны."""
    return cast(dim_expr(key, source), String)


def metric_selects(source: str = "transactions") -> list[tuple[str, Any, int]]:
    """(ключ, выражение, знаков после запятой) для всех метрик источника."""
    return [(k, v["expr"], v["digits"]) for k, v in _src(source)["metrics"].items()]


if __name__ == "__main__":  # самопроверка валидации
    assert parse_dims("station,fuel") == ["station", "fuel"]
    assert parse_dims(" station , fuel ") == ["station", "fuel"]
    for bad in ("", "dims=1=1--", "station,station", "dt::date", "station;drop",
                "station,fuel,payment,day,hour,month"):
        try:
            parse_dims(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"должно было упасть: {bad!r}")
    # Измерения источников не пересекаются вслепую: ключ одного не подходит другому.
    assert parse_dims("supplier,fuel", "receipts") == ["supplier", "fuel"]
    for bad_src in ("payment", "card", "nozzle"):
        try:
            parse_dims(bad_src, "receipts")
        except ValueError:
            pass
        else:
            raise AssertionError(f"ключ реализаций прошёл в поступления: {bad_src}")
    try:
        parse_dims("station", "нет-такого")
    except ValueError:
        pass
    else:
        raise AssertionError("неизвестный источник прошёл")
    assert dim_label("station") == "АЗС"
    assert len(metrics_catalog("receipts")) == 6
    # Рынок: владелец и эксплуатант — РАЗНЫЕ измерения, иначе сводная снова сольёт
    # сеть с её платформой.
    assert parse_dims("owner,operator,region", "market_sites") == ["owner", "operator", "region"]
    assert dim_label("owner", "market_sites") == "Владелец ЭЗС"
    for чужой in ("station", "fuel", "payment"):
        try:
            parse_dims(чужой, "market_sites")
        except ValueError:
            pass
        else:
            raise AssertionError(f"ключ другого источника прошёл в рынок: {чужой}")
    print("pivot_dims: проверки прошли")
