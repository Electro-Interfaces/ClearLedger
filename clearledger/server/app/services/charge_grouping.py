"""Группировки реестра сессий ЭЗС — один срез данных в разных разрезах.

Реестр отдаёт 117 тыс. строк за год: глазами в них ничего не найти, а
браузеру такую выборку группировать нечем. Поэтому агрегация живёт здесь:
БД сворачивает выборку до десятков строк, наружу уходят только итоги.

Разрезы (`GROUPS`) отвечают на разные вопросы:

  • сеть      — станция, регион, коннектор: где заряжаются;
  • клиент    — тип, организация, карта/телефон: кто заряжается;
  • процесс   — канал запуска, исход, оплата: как прошло;
  • время     — день, неделя, месяц, день недели, час: когда;
  • визит     — склейка попыток одного клиента на станции (charge_visits.py):
                группа = один визит, а не одно касание разъёма.

Фильтры реестра (регион, коннектор, исход, оплата, тип, поиск) применяются
до группировки — иначе итоги группы не сойдутся с тем, что видно в списке.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession, Region, ServiceLocation
from app.services.analytics_cache import cached_report

S = ChargeSession
L = ServiceLocation
# Регион ЭЗС — из справочника (единый источник истины), а не из денорм-колонки
# charge_sessions.region: резолв сессия→объект→регион (location_id → region_id →
# regions.name). Переучёт станций отражается сразу, число совпадает во всех дашбордах.
_REGION = func.coalesce(Region.name, "—")


@dataclass(frozen=True)
class GroupDef:
    """Разрез: чем группируем и как подписываем строку."""
    key: str
    label: str
    family: str          # сеть | клиент | процесс | время | визит
    #: SQL-выражение группировки; label_expr — что показать в первой колонке.
    def expr(self):       # noqa: ANN201 — SQLAlchemy-выражение
        raise NotImplementedError


def _month(col):
    return func.to_char(func.date_trunc("month", col), "YYYY-MM")


def _week(col):
    # ISO-неделя: «2026-W03». Понедельник — начало, как в отчётности.
    return func.to_char(func.date_trunc("week", col), "IYYY-\"W\"IW")


def _band(col, bounds: list[tuple[float, str]]):
    """Непрерывную величину — в полосы. Ключ группы: «1»…«N», подпись — из
    `_labels()`.

    Ключ числовой намеренно: полосы сортируются по границе, а не по выручке и
    не по алфавиту — иначе «100+ кВт» встаёт перед «23–49 кВт». Пустое значение
    (NULL) уходит в NULL-ключ и показывается группой «не заполнено», а не
    молча выпадает из выборки.
    """
    whens = [(col < b, str(i + 1)) for i, (b, _) in enumerate(bounds)]
    return case(*whens, else_=str(len(bounds) + 1))


def _labels(bounds: list[tuple[float, str]], last: str) -> dict[str, str]:
    """Ключ полосы → подпись (последняя полоса — всё, что выше верхней границы)."""
    out = {str(i + 1): lbl for i, (_, lbl) in enumerate(bounds)}
    out[str(len(bounds) + 1)] = last
    return out


# Полосы паспортной мощности станции: 40 уникальных значений разрезом не
# читаются, а границы 22/50/100/150 — это классы AC → быстрый DC → мощный DC.
_POWER_BANDS = [(23, "≤ 22 кВт"), (50, "23–49 кВт"), (100, "50–99 кВт"),
                (150, "100–149 кВт")]
_POWER_LAST = "150+ кВт"

# Энергия за сессию. Нулевая полоса отдельно: это пробы подключения, а не
# «маленькая зарядка» — смешивать их с 1–5 кВт значит прятать отказы.
_ENERGY_BANDS = [(0.001, "0 кВтч (проба)"), (5, "0–5 кВтч"), (10, "5–10 кВтч"),
                 (20, "10–20 кВтч"), (40, "20–40 кВтч")]
_ENERGY_LAST = "40+ кВтч"

_DURATION_BANDS = [(5, "< 5 мин"), (15, "5–15 мин"), (30, "15–30 мин"),
                   (60, "30–60 мин"), (120, "60–120 мин")]
_DURATION_LAST = "120+ мин"

# Фактическая мощность = кВтч / (мин / 60). Деление защищено NULLIF: сессии
# нулевой длительности дают деление на ноль, а не бесконечную мощность.
_ACTUAL_KW = S.energy_kwh / func.nullif(S.duration_min / 60.0, 0)

# Доля фактической мощности от паспортной. Ради этого разреза всё и делалось:
# станция, заявленная как 150 кВт и выдающая 40, ничем не отличается от честной
# 50-киловаттной — обе «работают».
#
# ⚠ `power_kwt` — мощность ВСЕЙ станции, а сессия идёт через ОДИН порт:
# у «Площадь Ленина 15» это 150 кВт на 3 коннектора, то есть 50 на порт.
# Сравнение сессии с полным паспортом дало бы «10% от паспорта» там, где порт
# физически не может больше — и разрез превратился бы в генератор ложных
# тревог. Поэтому делим на число коннекторов, а станции, где оно неизвестно
# (21% парка), уводим в отдельную группу «паспорт не сопоставим»: лучше
# честно меньшая выборка, чем правдоподобная неправда.
_PORT_POWER = L.power_kwt / func.nullif(L.connectors_count, 0)
_POWER_RATIO = _ACTUAL_KW / func.nullif(_PORT_POWER, 0) * 100
_RATIO_BANDS = [(30, "< 30% от паспорта"), (60, "30–60%"), (85, "60–85%")]
_RATIO_LAST = "85%+ (норма)"

# Сессия без отпуска или без длительности мощность не характеризует: деление
# даёт ноль, и проба подключения молча падала бы в «< 30% от паспорта», раздувая
# полосу до 68% выборки. Такие строки — отдельной группой, а не выброшены:
# сумма групп обязана сходиться с итогом реестра.
_NO_POWER_DATA = or_(S.energy_kwh <= 0, S.duration_min <= 0)

# Бренды в справочнике записаны вразнобой: «PSS» и «ПСС», «REWATT»/«Rewatt»/
# «Реватт», «StarCharge» и «StarСharge» (русская «С» — гомоглиф). Сам по себе
# разрез «сравнение надёжности вендоров» на таких данных бессмыслен: один
# вендор размазан по трём строкам, и ни одна не отражает его парк.
# Канонизируем ОТОБРАЖЕНИЕ, справочник не трогаем — чистка НСИ отдельная
# задача, а разрез нужен уже сейчас. Ключ группы = канон, поэтому раскрытие
# строки соберёт сессии всех написаний.
_BRAND_CANON = {
    "FORA": "Fora", "ФОРА": "Fora",
    "PSS": "ПСС",
    "REWATT": "Rewatt", "РЕВАТТ": "Rewatt",
    "KOSTAD": "Kostad",
    "EPROM": "E-PROM",
    "ПАРУС": "Парус",
    "STARCHARGE": "StarCharge", "STARСHARGE": "StarCharge",  # 2-й — с гомоглифом
    "TOUCH": "Touch", "ABB": "ABB", "ENEL": "Enel", "NSP": "NSP",
    "SCHNEIDER": "Schneider", "SETEC": "Setec", "WALLBOX": "Wallbox",
    "НАРТИС": "Нартис", "ONDER": "ONDER", "GRPZ": "GRPZ",
}
_BRAND_EXPR = case(
    *[(func.upper(func.btrim(L.brand)) == k, v) for k, v in _BRAND_CANON.items()],
    else_=func.btrim(L.brand),
)

# Задержка оплаты = paid_at − finished_at, в минутах.
_PAY_DELAY_MIN = func.extract("epoch", S.paid_at - S.finished_at) / 60.0
_DELAY_BANDS = [(5, "сразу (< 5 мин)"), (60, "< 1 часа"), (1440, "< 1 суток")]
_DELAY_LAST = "> 1 суток"

# «Не оплачено» — три РАЗНЫЕ вещи, и складывать их в одну строку нельзя
# (CLAUDE.md, п. 15): у ЮЛ paid_at пуст штатно (постоплата по счёту), проба без
# энергии вообще не подлежит оплате, и только розница с отпуском — это долг.
# Ключи 7–9 идут после оплаченных полос 1–4, поэтому сортировка по ключу
# ставит их в конец списка.
_PAY_DELAY_EXPR = case(
    (S.paid_at.is_not(None), _band(_PAY_DELAY_MIN, _DELAY_BANDS)),
    (S.energy_kwh <= 0, "7"),
    (S.client_name.is_not(None), "8"),
    else_="9",
)
_DELAY_LABELS = {
    **_labels(_DELAY_BANDS, _DELAY_LAST),
    "7": "не оплачено: проба без энергии",
    "8": "не оплачено: постоплата ЮЛ (счёт)",
    "9": "не оплачено: долг розницы",
}


#: Определения разрезов. label_expr = None → подпись равна значению группы.
GROUPS: dict[str, dict[str, Any]] = {
    # ── сеть ───────────────────────────────────────────────────────────
    "station": {"label": "Станция", "family": "сеть",
                "expr": S.station_code,
                "label_expr": func.coalesce(S.station_name, S.station_code)},
    "region": {"label": "Регион", "family": "сеть", "expr": _REGION},
    "connector": {"label": "Коннектор", "family": "сеть", "expr": S.connector_type},
    # ── клиент ─────────────────────────────────────────────────────────
    "user_type": {"label": "Тип клиента (ФЛ/ЮЛ)", "family": "клиент", "expr": S.user_type},
    "client": {"label": "Клиент (ЮЛ)", "family": "клиент", "expr": S.client_name},
    # user_id у розницы — номер телефона, у корпората — идентификатор карты.
    "user": {"label": "Карта / телефон", "family": "клиент", "expr": S.user_id},
    # ── процесс ────────────────────────────────────────────────────────
    "channel": {"label": "Канал запуска", "family": "процесс", "expr": S.charge_type},
    "result": {"label": "Исход", "family": "процесс", "expr": S.result},
    "paid": {"label": "Оплата", "family": "процесс",
             "expr": case((S.paid_at.is_not(None), "Оплачено"), else_="Без оплаты")},
    # ── время ──────────────────────────────────────────────────────────
    "day": {"label": "День", "family": "время",
            "expr": func.to_char(S.started_at, "YYYY-MM-DD")},
    "week": {"label": "Неделя", "family": "время", "expr": _week(S.started_at)},
    "month": {"label": "Месяц", "family": "время", "expr": _month(S.started_at)},
    "weekday": {"label": "День недели", "family": "время",
                "expr": func.to_char(S.started_at, "ID"),
                "label_expr": func.to_char(S.started_at, "ID")},
    "hour": {"label": "Час суток", "family": "время",
             "expr": func.to_char(S.started_at, "HH24")},
    # ── визит ──────────────────────────────────────────────────────────
    # Группа = один визит клиента (склейка смежных попыток), а не строка CPO.
    # Ключ визита — хеш, поэтому подписываем станцией: разбирают такие строки
    # по «где и когда», а не по идентификатору.
    "visit": {"label": "Визит (один заезд клиента)", "family": "визит", "expr": S.visit_key,
              "label_expr": func.coalesce(S.station_name, S.station_code)},
    # ── оборудование (join к справочнику станций) ──────────────────────
    # ⚠ Join ТОЛЬКО по location_id: сравнение service_locations.code с
    # station_code даёт 90 совпадений из 557 — у CPO код обрастает суффиксами
    # блоков («584-1») и ведущими пробелами (CLAUDE.md, п. 12).
    "brand": {"label": "Бренд оборудования", "family": "оборудование",
              "expr": _BRAND_EXPR, "join": True},
    "owner": {"label": "Владелец станции", "family": "оборудование",
              "expr": L.owner, "join": True},
    "power_band": {"label": "Мощность станции (паспорт)", "family": "оборудование",
                   "expr": _band(L.power_kwt, _POWER_BANDS), "join": True,
                   "labels": _labels(_POWER_BANDS, _POWER_LAST), "ordinal": True},
    "speed_class": {"label": "Класс скорости", "family": "оборудование",
                    "expr": L.speed_class, "join": True},
    "location_class": {"label": "Тип площадки", "family": "оборудование",
                       "expr": L.location_class, "join": True},
    "ocpp": {"label": "Протокол OCPP", "family": "оборудование",
             "expr": L.ocpp_protocol, "join": True},
    "city": {"label": "Город", "family": "оборудование", "expr": L.city, "join": True},
    # Порт = станция + разъём. Сейчас видно, что сбоит станция, но не видно,
    # что сбоит конкретный разъём — а меняют и обслуживают именно разъём.
    "port": {"label": "Порт (станция + разъём)", "family": "оборудование",
             "expr": func.concat(func.coalesce(S.station_code, "—"), "|",
                                 func.coalesce(S.connector_no, "—")),
             "label_expr": func.concat(
                 func.coalesce(S.station_name, S.station_code), " · порт ",
                 func.coalesce(S.connector_no, "—"))},
    # ── распределения (binning непрерывных величин) ────────────────────
    # Отвечают на вопрос «как устроена масса», а не «сколько всего».
    "energy_band": {"label": "Энергия за сессию", "family": "распределения",
                    "expr": _band(S.energy_kwh, _ENERGY_BANDS),
                    "labels": _labels(_ENERGY_BANDS, _ENERGY_LAST), "ordinal": True},
    "duration_band": {"label": "Длительность сессии", "family": "распределения",
                      "expr": _band(S.duration_min, _DURATION_BANDS),
                      "labels": _labels(_DURATION_BANDS, _DURATION_LAST), "ordinal": True},
    "actual_power": {"label": "Фактическая мощность", "family": "распределения",
                     "expr": case((_NO_POWER_DATA, "9"),
                                  else_=_band(_ACTUAL_KW, _POWER_BANDS)),
                     "labels": {**_labels(_POWER_BANDS, _POWER_LAST),
                                "9": "нет отпуска (проба)"}, "ordinal": True},
    # Главный разрез семейства: станция заявлена как 150 кВт, а выдаёт 40 —
    # по отдельности обе цифры выглядят нормально, вместе показывают проблему.
    "power_ratio": {"label": "Факт против паспорта порта", "family": "распределения",
                    "expr": case((_NO_POWER_DATA, "9"),
                                 (or_(L.power_kwt.is_(None),
                                      L.connectors_count.is_(None),
                                      L.connectors_count == 0), "8"),
                                 else_=_band(_POWER_RATIO, _RATIO_BANDS)),
                    "join": True,
                    "labels": {**_labels(_RATIO_BANDS, _RATIO_LAST),
                               "8": "паспорт не сопоставим (нет числа портов)",
                               "9": "нет отпуска (проба)"}, "ordinal": True},
    "pay_delay": {"label": "Задержка оплаты", "family": "распределения",
                  "expr": _PAY_DELAY_EXPR, "labels": _DELAY_LABELS, "ordinal": True},
}

WEEKDAY_RU = {"1": "Понедельник", "2": "Вторник", "3": "Среда", "4": "Четверг",
              "5": "Пятница", "6": "Суббота", "7": "Воскресенье"}

#: Коды CPO → человеческие подписи (в реестре показаны так же).
CHANNEL_RU = {"USER": "Приложение", "RFID": "Карта RFID", "AUTO": "Автостарт"}

#: Разрезы, у которых осмысленная сортировка по умолчанию — не выручка.
#: Визиты разбирают с самых тяжёлых: 6 попыток подряд — это жалоба, а не строка.
#: Полосы (`ordinal`) читаются по возрастанию границы: распределение смотрят
#: как шкалу, и «100+ кВт» перед «23–49» ломает картину.
DEFAULT_SORT = {"visit": ("sessions", "desc"), "day": ("label", "asc"),
                "week": ("label", "asc"), "month": ("label", "asc"),
                "weekday": ("label", "asc"), "hour": ("label", "asc")}
DEFAULT_SORT.update({k: ("label", "asc") for k, v in GROUPS.items() if v.get("ordinal")})


def _needs_join(group_by: str) -> bool:
    """Разрезу нужен справочник станций (join по location_id)."""
    return bool(GROUPS.get(group_by, {}).get("join"))


def _needs_region_join(group_by: str, region: str | None = None) -> bool:
    """Регион участвует в группировке или фильтре → нужен join к справочнику регионов."""
    return group_by == "region" or bool(region)


def _with_join(stmt: Select, group_by: str, region: str | None = None) -> Select:
    """Подключить справочник станций (и регионов). LEFT JOIN намеренно: сессия
    станции-сироты не должна исчезать из выборки — иначе итог разреза «по бренду»
    окажется меньше итога реестра, и это прочтётся как потеря данных."""
    need_reg = _needs_region_join(group_by, region)
    if _needs_join(group_by) or need_reg:
        stmt = stmt.join(L, S.location_id == L.id, isouter=True)
    if need_reg:
        stmt = stmt.join(Region, Region.id == L.region_id, isouter=True)
    return stmt


def _apply_filters(stmt: Select, *, user_type: str | None, region: str | None,
                   connector: str | None, result: str | None, paid: str | None,
                   search: str | None) -> Select:
    """Те же фильтры, что в списке реестра: иначе итоги не сойдутся со списком."""
    if user_type:
        stmt = stmt.where(S.user_type == user_type)
    if region:
        # Регион — из справочника (совпадает с группировкой). Требует region-join
        # у вызывающего запроса (см. _with_join(..., region=region)).
        stmt = stmt.where(_REGION == region)
    if connector:
        stmt = stmt.where(S.connector_type == connector)
    if result:
        stmt = stmt.where(S.result == result)
    if paid == "paid":
        stmt = stmt.where(S.paid_at.is_not(None))
    elif paid == "unpaid":
        stmt = stmt.where(S.paid_at.is_(None))
    if search:
        like = f"%{search.lower()}%"
        stmt = stmt.where(or_(
            func.lower(func.coalesce(S.session_ext_id, "")).like(like),
            func.lower(func.coalesce(S.station_name, "")).like(like),
            func.lower(func.coalesce(S.station_code, "")).like(like),
            func.lower(func.coalesce(S.client_name, "")).like(like),
        ))
    return stmt


class ChargeGroupingService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @cached_report("cs:grouped")
    async def grouped(
        self, company_id, date_from: date, date_to: date, group_by: str,
        *, station_codes: list[str] | None = None,
        user_type: str | None = None, region: str | None = None,
        connector: str | None = None, result: str | None = None,
        paid: str | None = None, search: str | None = None,
        sort: str | None = None, sort_dir: str | None = None, limit: int = 500,
    ) -> dict[str, Any]:
        """Свернуть выборку реестра в выбранный разрез с итогами по каждой группе."""
        g = GROUPS.get(group_by)
        if g is None:
            raise ValueError(f"Неизвестный разрез: {group_by}")

        d_sort, d_dir = DEFAULT_SORT.get(group_by, ("revenue", "desc"))
        sort = sort or d_sort
        sort_dir = sort_dir or d_dir

        lo = datetime.combine(date_from, datetime.min.time())
        hi = datetime.combine(date_to, datetime.max.time())
        expr = g["expr"]
        label_expr = g.get("label_expr", expr)

        success = case((S.result == "Complete", 1), else_=0)
        # «Зарядилась» = отпущена энергия. Флаг CPO отвечает на другой вопрос:
        # часть Complete отдала 0 кВтч, часть CompleteError — отдала (charge_visits).
        charged = case((S.energy_kwh > 0, 1), else_=0)

        cols = [
            expr.label("key"),
            func.min(label_expr).label("label"),
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy_kwh"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
            func.coalesce(func.avg(S.duration_min), 0).label("avg_duration"),
            func.coalesce(func.sum(success), 0).label("success"),
            func.coalesce(func.sum(charged), 0).label("charged"),
            func.count(func.distinct(S.station_code)).label("stations"),
            func.count(func.distinct(S.user_id)).label("users"),
            func.min(S.started_at).label("first_at"),
            func.max(S.started_at).label("last_at"),
        ]
        stmt = _with_join(select(*cols), group_by, region=region).where(
            S.company_id == company_id, S.started_at.is_not(None),
            S.started_at >= lo, S.started_at <= hi,
        )
        if station_codes:
            stmt = stmt.where(S.station_code.in_(station_codes))
        # Разрез по визитам без ключа бессмыслен: строки без visit_key — это
        # сессии без клиента, каждая сама себе визит, склеивать их не с чем.
        if group_by == "visit":
            stmt = stmt.where(S.visit_key.is_not(None))
        stmt = _apply_filters(stmt, user_type=user_type, region=region,
                              connector=connector, result=result, paid=paid,
                              search=search).group_by(expr)

        SORTS = {
            "revenue": func.coalesce(func.sum(S.amount), 0),
            "energy_kwh": func.coalesce(func.sum(S.energy_kwh), 0),
            "sessions": func.count(),
            "label": func.min(label_expr),
            "first_at": func.min(S.started_at),
            "last_at": func.max(S.started_at),
        }
        # Время читается по порядку, а не по величине: у разрезов времени
        # «по подписи» = хронология (ключи YYYY-MM, HH — лексикографически
        # совпадают с ней), иначе часы идут «03, 17, 09» вместо суток подряд.
        # Время и полосы читаются по порядку ключа, а не по величине показателя:
        # ключи YYYY-MM/HH и «1»…«N» лексикографически совпадают с нужным
        # порядком, тогда как сортировка по подписи дала бы «03, 17, 09».
        by_key = sort == "label" and (g["family"] == "время" or g.get("ordinal"))
        order = expr if by_key else SORTS.get(sort, SORTS["revenue"])
        primary = order.desc() if sort_dir == "desc" else order.asc()
        # tie-break по ключу группы (уникален в разрезе): при равной метрике состав
        # усечённого LIMIT'ом «хвоста» иначе плавает между запросами.
        stmt = stmt.order_by(primary, expr)

        rows = (await self.db.execute(stmt.limit(limit))).all()

        groups: list[dict[str, Any]] = []
        for r in rows:
            sessions = int(r.sessions or 0)
            energy = float(r.energy_kwh or 0)
            revenue = float(r.revenue or 0)
            key = "" if r.key is None else str(r.key)
            label = "" if r.label is None else str(r.label)
            if group_by == "weekday":
                label = WEEKDAY_RU.get(key, key)
            elif group_by == "hour":
                label = f"{key}:00"
            elif group_by == "channel":
                label = CHANNEL_RU.get(key, key)
            elif group_by == "client" and not label:
                label = "— (розница)"
            elif group_by == "visit" and r.first_at:
                # «Гоголя 1 · 14.03 09:21» — визит опознают по месту и времени.
                label = f"{label or '—'} · {r.first_at.strftime('%d.%m %H:%M')}"
            elif g.get("labels"):
                # Полоса: ключ «3» сам по себе ничего не значит.
                label = g["labels"].get(key, label)
            groups.append({
                "key": key,
                "label": label or "— не заполнено",
                "sessions": sessions,
                "energy_kwh": round(energy, 1),
                "revenue": round(revenue, 2),
                "avg_tariff": round(revenue / energy, 2) if energy else 0.0,
                "avg_check": round(revenue / sessions, 2) if sessions else 0.0,
                "avg_duration": round(float(r.avg_duration or 0), 1),
                "success_pct": round(int(r.success or 0) / sessions * 100, 1) if sessions else 0.0,
                "charged_pct": round(int(r.charged or 0) / sessions * 100, 1) if sessions else 0.0,
                "stations": int(r.stations or 0),
                "users": int(r.users or 0),
                "first_at": r.first_at.isoformat() if r.first_at else None,
                "last_at": r.last_at.isoformat() if r.last_at else None,
            })

        # Итог считаем отдельным запросом по всей выборке, а не суммой строк:
        # при limit сумма показанных групп не равна итогу, и цифра бы врала.
        tot_stmt = _with_join(select(
            func.count().label("sessions"),
            func.coalesce(func.sum(S.energy_kwh), 0).label("energy_kwh"),
            func.coalesce(func.sum(S.amount), 0).label("revenue"),
            func.coalesce(func.sum(success), 0).label("success"),
            func.count(func.distinct(expr)).label("groups"),
        ), group_by, region=region).where(
            S.company_id == company_id, S.started_at.is_not(None),
            S.started_at >= lo, S.started_at <= hi,
        )
        if station_codes:
            tot_stmt = tot_stmt.where(S.station_code.in_(station_codes))
        if group_by == "visit":
            tot_stmt = tot_stmt.where(S.visit_key.is_not(None))
        tot = (await self.db.execute(_apply_filters(
            tot_stmt, user_type=user_type, region=region, connector=connector,
            result=result, paid=paid, search=search))).one()

        t_sessions = int(tot.sessions or 0)
        t_energy = float(tot.energy_kwh or 0)
        t_revenue = float(tot.revenue or 0)
        return {
            "group_by": group_by,
            "label": g["label"],
            "period": {"from": date_from.isoformat(), "to": date_to.isoformat()},
            "groups": groups,
            "shown": len(groups),
            "truncated": int(tot.groups or 0) > len(groups),
            "totals": {
                "groups": int(tot.groups or 0),
                "sessions": t_sessions,
                "energy_kwh": round(t_energy, 1),
                "revenue": round(t_revenue, 2),
                "avg_tariff": round(t_revenue / t_energy, 2) if t_energy else 0.0,
                "avg_check": round(t_revenue / t_sessions, 2) if t_sessions else 0.0,
                "success_pct": round(int(tot.success or 0) / t_sessions * 100, 1) if t_sessions else 0.0,
            },
        }


    async def group_detail(
        self, company_id, date_from: date, date_to: date, group_by: str, key: str,
        *, station_codes: list[str] | None = None,
        user_type: str | None = None, region: str | None = None,
        connector: str | None = None, result: str | None = None,
        paid: str | None = None, search: str | None = None, limit: int = 100,
    ) -> dict[str, Any]:
        """Сессии внутри одной группы — чтобы строку итога можно было разобрать.

        Без этого группировка отвечает «где просело», но не «что именно там
        произошло»: визит со 189 попытками на 0 ₽ разбирается только построчно.
        """
        g = GROUPS.get(group_by)
        if g is None:
            raise ValueError(f"Неизвестный разрез: {group_by}")

        lo = datetime.combine(date_from, datetime.min.time())
        hi = datetime.combine(date_to, datetime.max.time())
        stmt = _with_join(select(
            S.session_ext_id, S.started_at, S.station_code, S.station_name, S.region,
            S.connector_type, S.user_type, S.client_name, S.user_id, S.charge_type,
            S.energy_kwh, S.duration_min, S.tariff, S.amount, S.result, S.paid_at,
            S.visit_seq, S.visit_size,
        ), group_by, region=region).where(
            S.company_id == company_id, S.started_at.is_not(None),
            S.started_at >= lo, S.started_at <= hi,
        )
        if station_codes:
            stmt = stmt.where(S.station_code.in_(station_codes))
        # Пустой ключ = группа «не заполнено»: сравнение с '' её не найдёт.
        expr = g["expr"]
        stmt = stmt.where(expr.is_(None) if key == "" else expr == key)
        stmt = _apply_filters(stmt, user_type=user_type, region=region,
                              connector=connector, result=result, paid=paid,
                              search=search).order_by(S.started_at, S.session_ext_id)

        rows = (await self.db.execute(stmt.limit(limit))).all()
        return {"group_by": group_by, "key": key, "rows": [{
            "session_ext_id": r.session_ext_id,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "station_code": r.station_code, "station_name": r.station_name,
            "region": r.region, "connector_type": r.connector_type,
            "user_type": r.user_type, "client_name": r.client_name,
            "user_id": r.user_id, "charge_type": r.charge_type,
            "energy_kwh": float(r.energy_kwh or 0), "duration_min": r.duration_min,
            "tariff": float(r.tariff or 0), "revenue": float(r.amount or 0),
            "result": r.result, "paid_at": r.paid_at.isoformat() if r.paid_at else None,
            "visit_seq": r.visit_seq, "visit_size": r.visit_size,
        } for r in rows]}


def group_catalog() -> list[dict[str, str]]:
    """Список разрезов для селектора в UI (порядок = порядок в меню)."""
    return [{"key": k, "label": v["label"], "family": v["family"]} for k, v in GROUPS.items()]
