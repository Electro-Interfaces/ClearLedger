"""Профили операторов рынка: охват, платформа, роуминг, приложение, реквизиты.

Три файла об одном и том же — компаниях, — и связываются они по имени оператора:
  • `ev-operator-profiles.csv` — охват сети, чья платформа, роуминг, сайт, приложение;
  • `ev-apps.csv` — приложение: разработчик, оценка, отзывы, установки;
  • `ev-operators-legal.csv` — юрлицо, ИНН, ОГРН, адрес, руководитель.

Два слоя здесь есть только потому, что их собрали вручную, и в открытых источниках
их нет:

**Чья платформа.** Сеть на чужой системе — клиент своего поставщика, и разговор с
ней идёт иначе, чем с владельцем платформы. Своя платформа у десяти операторов из
семидесяти двух; остальные сидят на четырёх ИТ-системах.

**Роуминг.** Можно ли зарядиться на станции через приложение другого оператора.
Это факт о технологии, а не о качестве сети, и формулируется нейтрально: сеть либо
открыта роумингом, либо работает только в своём приложении.

Достоверность реквизитов обязательна к показу: ссылаться можно только на
«подтверждено». «Похоже» и «не найдено» остаются в карточке пометкой, потому что
бренд и юрлицо часто не совпадают, и ошибиться здесь дороже, чем промолчать.
"""
from __future__ import annotations

import csv
import io
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketOperator
from app.services.market_ocm import _canon_operator

logger = logging.getLogger("clearledger.market")

# Имена площадок-агрегаторов: под ними ходят пользовательские точки, а не сеть.
PLATFORM_NAMES = {"2chargers", "plugshare", "chargemap"}

# Достоверность реквизитов, при которой на них можно ссылаться.
CONFIDENCE_OK = "подтверждено"


def _s(v, maxlen: int | None = None) -> str | None:
    if v is None:
        return None
    out = str(v).strip()
    if not out:
        return None
    return out[:maxlen] if maxlen else out


def _num(v) -> float | None:
    text = _s(v)
    if text is None:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


def _int(v) -> int | None:
    value = _num(v)
    return int(value) if value is not None else None


def _flag(v) -> bool | None:
    text = _s(v)
    if text is None:
        return None
    return text not in ("0", "false", "нет")


def parse_csv(content: bytes) -> list[dict[str, str]]:
    """CSV `;` в UTF-8 с BOM — тот же формат, что у выгрузки станций."""
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig", errors="replace")),
                            delimiter=";")
    return [row for row in reader if any((v or "").strip() for v in row.values())]


async def ingest_operator_profiles(
    db: AsyncSession,
    company_id: _uuid.UUID,
    profiles: list[dict[str, str]] | None = None,
    apps: list[dict[str, str]] | None = None,
    legal: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Свести три файла в карточки операторов компании.

    Оператор ищется по канонизированному имени — той же функцией, что и при приёме
    станций, иначе «PUNKT E» из профиля не встретится с «Punkt E» из реестра точек.
    Не найденный оператор заводится: профиль знает о сетях, которых в нашей выгрузке
    точек может не быть.
    """
    known = {(o.name or "").strip().lower(): o for o in (await db.execute(
        select(MarketOperator).where(
            MarketOperator.company_id == company_id))).scalars().all()}
    now = datetime.now(timezone.utc)
    touched: set[str] = set()
    created = 0

    def find(raw_name: str | None) -> MarketOperator | None:
        name = _canon_operator(raw_name)
        if not name or name.strip().lower() in PLATFORM_NAMES:
            return None
        key = name.strip().lower()
        op = known.get(key)
        if op is None:
            op = MarketOperator(company_id=company_id, name=name, relation="competitor")
            db.add(op)
            known[key] = op
        touched.add(key)
        return op

    # Оператор, уже заполненный в этом прогоне более крупной строкой: следующая
    # строка того же оператора может только ДОПОЛНИТЬ пустые поля.
    filled: set[str] = set()

    def put(op: MarketOperator, field: str, value, *, key: str | None = None) -> None:
        """Пустое не затирает заполненное, а мелкая строка — крупную.

        Разные строки источника схлопываются в одного оператора после приведения
        имени: «Россети» (371 точка, платформа Sitronics) и «MOJeSK-EV(ROSSETI)»
        (7 точек, 3 города) — одна компания. Прежде вторая переписывала первую, и
        сеть из 371 точки оказывалась без платформы и с тремя городами
        (проверка 13.09.2026).
        """
        if value is None or value == "":
            return
        if key and key in filled and getattr(op, field, None) is not None:
            return
        setattr(op, field, value)

    # Крупная запись применяется первой: если после неё придёт мелкая, она сможет
    # только дополнить пустые поля, но не переписать содержательные.
    for row in sorted(profiles or [], key=lambda r: -(_int(r.get("points")) or 0)):
        op = find(row.get("operator"))
        if op is None:
            continue
        key = (op.name or "").strip().lower()
        first = key not in filled
        put(op, "base_city", _s(row.get("base"), 160), key=key)
        put(op, "cities", _int(row.get("cities")), key=key)
        put(op, "districts", _int(row.get("districts")), key=key)
        put(op, "alive_pct", _num(row.get("alive_pct")), key=key)
        put(op, "paid_pct", _num(row.get("paid_pct")), key=key)
        put(op, "avg_power_kw", _num(row.get("avg_power")), key=key)
        put(op, "platform_code", _s(row.get("platform_code"), 40), key=key)
        put(op, "platform_owner", _canon_operator(row.get("platform_owner")), key=key)
        # Флаги: «нет роуминга» — такой же факт, как «есть», поэтому False пишется.
        # Но только если поле в строке присутствует: отсутствие графы фактом не является.
        if first and _s(row.get("own_platform")) is not None:
            op.own_platform = _flag(row.get("own_platform"))
        if first and _s(row.get("ocpi_roaming")) is not None:
            op.ocpi_roaming = _flag(row.get("ocpi_roaming"))
        put(op, "ocpi_pct", _num(row.get("ocpi_pct")), key=key)
        if first:
            filled.add(key)
        op.site_url = _s(row.get("site"), 300) or op.site_url
        put(op, "app_name", _s(row.get("app_name"), 160), key=key)
        put(op, "app_package", _s(row.get("app_package"), 160), key=key)
        phones = _s(row.get("phones"))
        if phones:
            op.contacts = {**(op.contacts or {}), "phones": phones}
        op.updated_at = now

    for row in sorted(apps or [], key=lambda r: -(_int(r.get("points")) or 0)):
        op = find(row.get("operator"))
        if op is None:
            continue
        op.app_package = _s(row.get("package"), 160) or op.app_package
        put(op, "app_developer", _s(row.get("developer"), 200))
        put(op, "app_rating", _num(row.get("rating")))
        put(op, "app_reviews", _int(row.get("reviews")))
        put(op, "app_installs", _s(row.get("installs"), 40))
        contacts = dict(op.contacts or {})
        for key in ("email", "social"):
            value = _s(row.get(key))
            if value:
                contacts[key] = value
        op.contacts = contacts or None
        op.updated_at = now

    for row in sorted(legal or [], key=lambda r: -(_int(r.get("points")) or 0)):
        op = find(row.get("operator"))
        if op is None:
            continue
        confidence = _s(row.get("confidence"), 40)
        put(op, "legal_confidence", confidence)
        # Реквизиты пишем всегда, но пригодность к ссылке определяет достоверность:
        # бренд и юрлицо часто не совпадают, и «похоже» — это не «установлено».
        put(op, "legal_name", _s(row.get("legal_name"), 300))
        op.inn = _s(row.get("inn"), 20) or op.inn
        put(op, "ogrn", _s(row.get("ogrn"), 20))
        put(op, "legal_address", _s(row.get("legal_address")))
        put(op, "director", _s(row.get("director"), 200))
        op.app_developer = _s(row.get("app_developer"), 200) or op.app_developer
        op.updated_at = now

    await db.commit()
    # Заведённые в этом прогоне: у них ещё нет времени создания из базы.
    created = sum(1 for key in touched if known[key].created_at is None)
    logger.info("профили операторов: затронуто %s, заведено %s", len(touched), created)
    return {
        "status": "success",
        "operators": len(touched),
        "profiles": len(profiles or []),
        "apps": len(apps or []),
        "legal": len(legal or []),
        "message": (f"профилей {len(profiles or [])}, приложений {len(apps or [])}, "
                    f"реквизитов {len(legal or [])}; затронуто операторов {len(touched)}"),
    }


async def ingest_region_stats(
    db: AsyncSession, company_id: _uuid.UUID, rows: list[dict[str, str]],
    source: str = "АВТОСТАТ + наш обход", as_of: str | None = None,
) -> dict[str, Any]:
    """Парк электромобилей и зарядки по регионам.

    Таблица построена по электромобилям, БЕЗ гибридов: региональной разбивки по
    гибридам в открытом доступе нет, а их вдвое больше — подмешав, мы завысили бы
    спрос вдвое. Дата и источник хранятся рядом: парк обновляется вручную
    несколько раз в год, зарядки — нашим обходом, и возраст у чисел разный.
    """
    from app.models import MarketRegionStat

    known = {r.region: r for r in (await db.execute(select(MarketRegionStat).where(
        MarketRegionStat.company_id == company_id))).scalars().all()}
    now = datetime.now(timezone.utc)
    touched = 0
    for row in rows:
        region = _s(row.get("region"), 160)
        if not region:
            continue
        stat = known.get(region)
        if stat is None:
            stat = MarketRegionStat(company_id=company_id, region=region)
            db.add(stat)
            known[region] = stat
        stat.ev_cars = _int(row.get("ev_cars"))
        stat.ev_share_pct = _num(row.get("ev_share_pct"))
        stat.stations = _int(row.get("stations"))
        stat.stations_dc = _int(row.get("stations_dc"))
        stat.stations_alive = _int(row.get("stations_alive"))
        stat.cars_per_station = _num(row.get("cars_per_station"))
        stat.cars_per_dc = _num(row.get("cars_per_dc"))
        stat.cars_per_alive = _num(row.get("cars_per_alive"))
        stat.source = source
        stat.as_of = as_of
        stat.updated_at = now
        touched += 1
    await db.commit()
    return {"status": "success", "regions": touched,
            "message": f"регионов с парком машин: {touched}"}


async def ingest_players(
    db: AsyncSession, company_id: _uuid.UUID,
    players: list[dict[str, str]] | None = None,
    oem: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Игроки рынка из магазина приложений и автопроизводители.

    Ищут их через магазин потому, что на карте зарядок видно только владельцев
    инфраструктуры: агрегатор, работающий на чужих станциях, там не существует, хотя
    за того же водителя борется наравне.

    Класс приходит проставленным автоматически — по названию и пакету, — и остаётся
    непроверенным, пока человек не подтвердит. Десять записей заведомо осели в
    «прочее»; называть конкретное имя в отчёте до проверки нельзя.
    """
    from app.models import MarketPlayer

    known = {(p.app, p.package or ""): p for p in (await db.execute(
        select(MarketPlayer).where(MarketPlayer.company_id == company_id))).scalars().all()}
    operators = {(o.name or "").strip().lower(): o for o in (await db.execute(
        select(MarketOperator).where(
            MarketOperator.company_id == company_id))).scalars().all()}
    now = datetime.now(timezone.utc)
    touched = 0

    def upsert(app: str, package: str | None) -> Any:
        key = (app, package or "")
        row = known.get(key)
        if row is None:
            row = MarketPlayer(company_id=company_id, app=app, package=package)
            db.add(row)
            known[key] = row
        return row

    for raw in players or []:
        app = _s(raw.get("app"), 200)
        if not app:
            continue
        row = upsert(app, _s(raw.get("package"), 200))
        row.player_class = _s(raw.get("class"), 80)
        row.own_stations = _int(raw.get("own_stations"))
        row.asset_light = _flag(raw.get("asset_light"))
        matched = _s(raw.get("matched_operator"), 200)
        row.matched_operator = matched
        if matched:
            op = operators.get((_canon_operator(matched) or matched).strip().lower())
            if op is not None:
                row.operator_id = op.id
        row.source = "RuStore"
        row.updated_at = now
        touched += 1

    for raw in oem or []:
        app = _s(raw.get("app"), 200) or _s(raw.get("brand"), 200)
        if not app:
            continue
        row = upsert(app, _s(raw.get("package"), 200))
        row.player_class = "автопроизводитель"
        row.brand = _s(raw.get("brand"), 160)
        row.developer = _s(raw.get("developer"), 200)
        row.developer_inn = _s(raw.get("developer_inn"), 60)
        row.email = _s(raw.get("email"), 200)
        row.rating = _num(raw.get("rating"))
        row.reviews = _int(raw.get("reviews"))
        row.own_stations = _int(raw.get("own_stations"))
        row.asset_light = (row.own_stations or 0) == 0
        row.model_note = _s(raw.get("model"))
        row.note = _s(raw.get("note"))
        row.source = "RuStore"
        row.updated_at = now
        touched += 1

    await db.commit()
    return {"status": "success", "players": touched,
            "message": (f"игроков {len(players or [])}, автопроизводителей "
                        f"{len(oem or [])}; записано {touched}")}
