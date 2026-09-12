"""Приём реестра ЭЗС страны: выгрузка публичной карты → рынок пространства.

Источник — повторяемая выгрузка публичного реестра зарядных станций (CSV, 52 поля
на точку). Она не разовая: каждый прогон даёт СРЕЗ на дату, и сравнение срезов —
половина ценности продукта («что изменилось за месяц», «кто открылся рядом»,
«где упала связь»). Поэтому приём пишет и карточку (`MarketSite` — последнее
известное), и ряд (`MarketSiteSnapshot` — состояние на дату среза).

Устройство разбора и решения — `ecosystem-deploy/docs/MARKET-ROADMAP.md` §5.
Три вещи, которые в этом источнике устроены не так, как кажется:

1. **`operator` у пользовательских точек несёт имя самой площадки** (`2Chargers`),
   а не оператора сети. Завести его конкурентом значит получить «сеть» на тысячи
   точек, которой не существует, и испортить долю рынка всем остальным. Такие
   имена в `PLATFORM_NAMES`: оператор не заводится, класс точки берётся из
   `icon_type`.
2. **`manufacturers` — числовые коды чужого справочника** (`1`, `30`, `13`), а не
   названия. Пока словаря нет, код живёт в `raw`, а `vendor` остаётся пустым:
   показать «производитель 30» хуже, чем показать «нет данных».
3. **`is_alive` не означает «жива»**: у большинства точек со статусом «Работает»
   он равен нулю. Живость определяется по `last_session_at` (§3.7 плана), а
   `is_alive`/`under_repair` хранятся как техническое состояние на дату среза.
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

from app.models import (ChannelSyncLog, MarketObservation, MarketOperator,
                        MarketSite, MarketSiteSnapshot)
from app.services.mapping import canon_city, canon_region
from app.services.market_ocm import _canon_operator

logger = logging.getLogger("clearledger.market")

# Ранг источника: открытый реестр ниже официального API (90) и партнёрского обмена
# (100), но выше ручного импорта таблицей (40) и парсинга (20).
SOURCE_RANK = 70
SOURCE_CODE = "registry_ru"

# Имена площадок-агрегаторов, которые выгрузка подставляет вместо оператора.
PLATFORM_NAMES = {"2chargers", "plugshare", "chargemap"}

# Наши сети: точка остаётся в рынке (без неё не увидеть себя глазами клиента), но
# оператор помечается `own` — конкурентом самим себе мы не считаемся.
OURS = ("русгидро", "rushydro")

# Класс точки: сеть оператора или домашняя розетка частника.
CLASS_BY_ICON = {
    "home_station": "home",
    "public_station": "network",
    "public_station_fast": "network",
    "public_station_paid": "network",
    "public_station_paid_fast": "network",
}

# Статус точки в источнике → наш статус жизненного цикла. «Не работает» и «На ремонте»
# — это техническое состояние, а не закрытие: станция стоит и завтра включится.
STATUS_MAP = {
    "работает": "active",
    "доступно": "active",
    "не работает": "active",
    "на ремонте": "active",
    "скоро открытие": "planned",
    "закрыта": "closed",
    "закрыто": "closed",
}

# Код валюты источника. Рубль — единственная валюта, которую можно сравнивать с нашей
# ценой; тариф 0.54 в Беларуси при смешении превратит медиану рынка в выдумку.
CURRENCY_BY_ID = {"1": "RUB", "2": "BYN", "3": "KZT"}

# Сколько срезов подряд точка может отсутствовать, прежде чем считается закрытой.
# Одна пропажа бывает сбоем обхода, три подряд — закрытием.
CLOSE_AFTER_MISSES = 3

# Часовые пояса России. Единственный надёжный признак страны в этой выгрузке:
# `country` пуст у всех строк, а по координатам Финляндия и Прибалтика лежат внутри
# того же прямоугольника широт и долгот, что и Россия. Треть первой выгрузки (508
# точек из 1 506) стоит за границей — приняв их, мы получили бы «рынок России», где
# каждая третья станция чужая, и плотность, доля и медиана цены врали бы везде.
RU_TIMEZONES = {
    "Europe/Kaliningrad", "Europe/Moscow", "Europe/Simferopol", "Europe/Kirov",
    "Europe/Volgograd", "Europe/Astrakhan", "Europe/Saratov", "Europe/Ulyanovsk",
    "Europe/Samara", "Asia/Yekaterinburg", "Asia/Omsk", "Asia/Novosibirsk",
    "Asia/Barnaul", "Asia/Tomsk", "Asia/Novokuznetsk", "Asia/Krasnoyarsk",
    "Asia/Irkutsk", "Asia/Chita", "Asia/Yakutsk", "Asia/Khandyga",
    "Asia/Vladivostok", "Asia/Ust-Nera", "Asia/Magadan", "Asia/Sakhalin",
    "Asia/Srednekolymsk", "Asia/Kamchatka", "Asia/Anadyr",
}


def in_russia(row: dict) -> bool:
    """Российская ли точка. Пустой пояс — не повод выбрасывать: судим только по
    явному признаку, иначе потеряем то, что источник просто не заполнил."""
    tz = (row.get("time_zone") or "").strip()
    return not tz or tz in RU_TIMEZONES


# Верх разумного тарифа за киловатт-час в рублях. Выше — почти наверняка цена за
# сессию, записанная в поле киловатт-часа: в выгрузке есть точка с `per_kwt:600`.
# Такой факт не выбрасываем (он в источнике есть), но в сравнение не пускаем:
# одна строка на 600 ₽ сдвигает медиану района сильнее, чем десять настоящих.
PRICE_SANE_MAX = 200.0


def _s(v, maxlen: int | None = None) -> str | None:
    if v is None:
        return None
    out = str(v).strip()
    if not out:
        return None
    return out[:maxlen] if maxlen else out


def _num(v) -> float | None:
    if v is None:
        return None
    try:
        text = str(v).replace(",", ".").strip()
        return float(text) if text else None
    except (ValueError, TypeError):
        return None


def _int(v) -> int | None:
    value = _num(v)
    return int(value) if value is not None else None


def _bool(v) -> bool | None:
    text = _s(v)
    if text is None:
        return None
    return text not in ("0", "false", "False", "нет")


def _dt(v) -> datetime | None:
    """ISO-время источника («2026-09-12T14:36:11.355+03:00») → datetime с зоной."""
    text = _s(v)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_connectors(raw: str | None) -> list[dict[str, Any]]:
    """«CHAdeMO:50|CCS Combo 2:60» → [{"type": "CHAdeMO", "power_kw": 50.0}, …].

    Мощность у коннектора своя: точка с одним CCS 150 кВт и точка с четырьмя Type 2
    по 22 кВт — разные конкуренты, хотя суммарная мощность сопоставима.
    """
    out: list[dict[str, Any]] = []
    for chunk in (raw or "").split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        name, _, power = chunk.rpartition(":")
        if not name:
            name, power = chunk, ""
        kw = _num(power)
        out.append({"type": name.strip()[:60], "power_kw": kw})
    return out


def parse_tariffs(raw: str | None) -> list[dict[str, Any]]:
    """«per_kwt:20@08:00-23:00|per_kwt:17@23:00-08:00» → список тарифов с окнами.

    Единица измерения обязательна и сохраняется как есть: `per_kwt` сравнимо с нашей
    ценой за киловатт-час, `per_minute` и `per_session` — нет (принцип 3 MARKET.md),
    и молча приводить их к рублю за кВт·ч нельзя.
    """
    out: list[dict[str, Any]] = []
    for chunk in (raw or "").split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        head, _, window = chunk.partition("@")
        unit, _, value = head.partition(":")
        price = _num(value)
        if price is None:
            continue
        out.append({
            "unit": {"per_kwt": "kwh", "per_kwh": "kwh", "per_minute": "minute",
                     "per_session": "session"}.get(unit.strip(), unit.strip()[:16]),
            "price": price,
            "window": window.strip()[:32] or None,
        })
    return out


def comparable_price(unit: str, price: float, *, paid: bool, currency: str | None) -> float | None:
    """Цена, которую МОЖНО сравнивать с нашей ₽/кВт·ч, либо None.

    Три причины, по которым цена из реестра в сравнение не идёт:
      • не за киловатт-час (за минуту, за сессию, подписка) — принцип 3 MARKET.md;
      • не в рублях (в выгрузке есть Беларусь и Казахстан);
      • ноль на ПЛАТНОЙ станции — это «цена не указана», а не «бесплатно»;
      • выше разумного потолка — почти наверняка цена за сессию в поле киловатт-часа.

    Ноль на бесплатной станции — настоящий факт и возвращается как ноль: у нашей сети
    сегодня бесплатны все точки, и сравнение с рынком строится именно на этом.
    """
    if unit != "kwh" or currency != "RUB":
        return None
    if price == 0 and paid:
        return None
    if price > PRICE_SANE_MAX:
        return None
    return price


def site_class(icon_type: str | None, operator: str | None) -> str:
    """Сеть или домашняя розетка. Половина публичного реестра — розетки частников:
    в сравнении операторов они мусор, в карте покрытия — вариант для водителя."""
    known = CLASS_BY_ICON.get((_s(icon_type) or "").lower())
    if known:
        return known
    return "network" if operator else "unknown"


# Приставки субъекта в адресе источника: «Московская обл, 33-й км …», «Респ Крым, …».
_REGION_MARKS = ("обл", "область", "край", "респ", "республика", "ао", "округ")


def split_address(address: str | None) -> tuple[str | None, str | None]:
    """Адрес источника → (регион, город). Отдельных полей в выгрузке нет.

    Адрес приходит одной строкой двух видов: «Московская обл, 33-й км автодороги М8»
    и «Александров, ул Речная дом 14». В первом случае первая часть — субъект, во
    втором — сразу населённый пункт. Без этого разбора разрез «где стоит» показывает
    «город не указан» у всех точек, то есть не показывает ничего.

    Чужие коды (`federal_district_id`, `city_id`) сознательно не используем: они из
    справочника источника, и привязываться к нему значит зависеть от чужой нумерации.
    """
    text = " ".join(str(address or "").split())
    if not text:
        return None, None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    # Адрес иногда начинается со страны — тогда это ни регион, ни город.
    if parts and parts[0].lower() in ("россия", "russia", "рф"):
        parts = parts[1:]
    if not parts:
        return None, None
    head = parts[0]
    low = head.lower().replace(".", " ")
    is_region = any(f" {mark}" in f" {low} " or low.endswith(f" {mark}")
                    for mark in _REGION_MARKS)
    if is_region:
        region = canon_region(head)
        city = canon_city(parts[1]) if len(parts) > 1 else None
        # Вторая часть бывает не городом, а куском адреса («33-й км автодороги»):
        # такое в город не пишем — лучше пусто, чем ложный населённый пункт.
        if city and any(ch.isdigit() for ch in city):
            city = None
        return region, city
    return None, canon_city(head)


def parse_registry_csv(content: bytes) -> list[dict[str, str]]:
    """Выгрузка реестра (CSV `;`, UTF-8 с BOM) → список строк как есть.

    BOM обязателен к снятию: иначе первая колонка называется `\\ufeffid`, ключ точки
    не находится и весь файл заезжает как новые записи при каждом прогоне.
    """
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    return [row for row in reader if any((v or "").strip() for v in row.values())]


async def _bump(db: AsyncSession, log_id, done: int, total: int, created: int, updated: int) -> None:
    """Прогресс в журнал прогона (UI поллит его процентами) + commit."""
    if log_id is None:
        await db.commit()
        return
    log = await db.get(ChannelSyncLog, log_id)
    if log is not None:
        log.loaded = created + updated
        log.events = [{"level": "info", "event": "run",
                       "message": f"точки рынка: {done:,}/{total:,}".replace(",", " "),
                       "sites_done": done, "sites_total": total,
                       "loaded": created + updated}]
    await db.commit()


def _dedup_key(kind: str, lat: float | None, lon: float | None, name: str) -> str:
    """Тот же ключ, что у ручного ввода и импорта OCM: одна станция из двух
    источников не должна стать двумя точками на карте."""
    if lat is not None and lon is not None:
        return f"{kind}:{round(float(lat), 3)}:{round(float(lon), 3)}"
    return f"{kind}:{name.strip().lower()[:80]}"


async def ingest_registry(
    db: AsyncSession,
    company_id: _uuid.UUID,
    rows: list[dict[str, str]],
    *,
    snapshot_date: str | None = None,
    log_id=None,
    source: str = SOURCE_CODE,
) -> dict[str, Any]:
    """Срез реестра → точки рынка, срезы состояния и наблюдения цены.

    Идемпотентно: ключ точки — `uuid` источника, запасной — округлённая координата.
    Повторный прогон того же файла обновляет карточки, переписывает срез той же даты
    и не плодит ни точек, ни наблюдений.
    """
    today = snapshot_date or datetime.now(timezone.utc).date().isoformat()
    now = datetime.now(timezone.utc)
    total = len(rows)

    # Операторы компании: имя в канонической форме → id. Канонизация общая с импортом
    # OCM, иначе «PUNKT E» и «Punkt E» станут двумя сетями и долю рынка посчитают по
    # выдуманному числу операторов.
    operators: dict[str, MarketOperator] = {}
    for op in (await db.execute(select(MarketOperator).where(
            MarketOperator.company_id == company_id))).scalars().all():
        operators[(op.name or "").strip().lower()] = op

    sites = (await db.execute(select(MarketSite).where(
        MarketSite.company_id == company_id))).scalars().all()
    by_ext = {s.external_id: s for s in sites if s.external_id}
    # Запасной ключ (округлённая координата) склеивает точку только с ЧУЖИМ источником:
    # OSM и реестр про одну станцию — одна точка. Внутри одного источника он опасен —
    # два зарядных поста в одном торговом центре стоят в 50 метрах и по координате
    # неразличимы, а по `uuid` это разные станции, и терять вторую нельзя.
    by_key = {s.dedup_key: s for s in sites
              if s.dedup_key and (s.source != source or not s.external_id)}

    # Срезы и наблюдения этой даты — чтобы повтор прогона правил строку, а не добавлял.
    snaps = {(s.site_id, s.snapshot_date): s for s in (await db.execute(
        select(MarketSiteSnapshot).where(
            MarketSiteSnapshot.company_id == company_id,
            MarketSiteSnapshot.snapshot_date == today))).scalars().all()}
    seen_obs = {(o.site_id, o.source_ref) for o in (await db.execute(
        select(MarketObservation).where(
            MarketObservation.company_id == company_id,
            MarketObservation.observed_on == today,
            MarketObservation.channel == "import"))).scalars().all()}

    created = updated = priced = skipped = foreign = 0
    seen_ext: set[str] = set()

    for done, row in enumerate(rows, start=1):
        lat, lon = _num(row.get("lat")), _num(row.get("lon"))
        ext = _s(row.get("uuid"), 80) or _s(row.get("id"), 80)
        if lat is None or lon is None or not ext:
            skipped += 1
            continue
        if not in_russia(row):
            foreign += 1
            continue
        seen_ext.add(ext)

        raw_operator = _s(row.get("operator"), 120)
        platform = (raw_operator or "").strip().lower() in PLATFORM_NAMES
        operator_name = None if platform else _canon_operator(raw_operator)
        klass = site_class(row.get("icon_type"), operator_name)

        operator = None
        if operator_name:
            key = operator_name.lower()
            operator = operators.get(key)
            if operator is None:
                operator = MarketOperator(
                    company_id=company_id, name=operator_name,
                    relation="own" if any(o in key for o in OURS) else "competitor")
                db.add(operator)
                await db.flush()
                operators[key] = operator

        name = _s(row.get("name"), 290) or (f"ЭЗС {operator_name}" if operator_name else "ЭЗС")
        region, city = split_address(row.get("address"))
        connectors = parse_connectors(row.get("connectors"))
        powers = [c["power_kw"] for c in connectors if c.get("power_kw")]
        max_power = _num(row.get("max_power")) or (max(powers) if powers else None)
        currency = CURRENCY_BY_ID.get(_s(row.get("currency_id")) or "", None)
        tariffs = parse_tariffs(row.get("tariffs"))
        paid = bool(_bool(row.get("paid")))
        per_kwh = next((p for p in (comparable_price(t["unit"], t["price"], paid=paid,
                                                     currency=currency)
                                    for t in tariffs) if p is not None), None)
        last_session = _dt(row.get("last_session_at"))
        status = STATUS_MAP.get((_s(row.get("status")) or "").lower(), "active")
        key = _dedup_key("ezs", lat, lon, name)

        site = by_ext.get(ext) or by_key.get(key)
        if site is None:
            # Когда точка появилась, знает источник (`created_at` его записи), а не мы.
            # Поставить сюда дату нашей загрузки — значит получить «как рос конкурент»
            # в виде одного столбика в месяце первой выгрузки.
            site = MarketSite(
                company_id=company_id, kind="ezs", name=name, dedup_key=key,
                external_id=ext, source=source, source_rank=SOURCE_RANK,
                source_ref=f"{source}:{ext}",
                first_seen_at=_dt(row.get("created_at")) or now,
            )
            db.add(site)
            created += 1
        else:
            updated += 1
        site.external_id = ext
        site.last_seen_at = now
        site.closed_confirmations = 0

        # Ручная правка человека сильнее машинной (принцип 2 MARKET.md): у проверенной
        # точки обновляем только то, что меняется от среза к срезу, паспорт не трогаем.
        verified = site.verified_at is not None
        if not verified:
            site.name = name
            site.address = _s(row.get("address"), 400)
            site.region = region
            site.city = city
            site.latitude, site.longitude = lat, lon
            site.operator_id = operator.id if operator else None
            site.site_class = klass
            site.status = status
            site.ports = _int(row.get("connector_count")) or _int(row.get("stations_count"))
            site.max_power_kw = max_power
            site.connectors = ", ".join(
                c["type"] for c in connectors if c.get("type"))[:200] or None
            site.connectors_json = connectors or None
            site.current_type = _s(row.get("socket_type"), 8)
            site.phone = _s(row.get("phone"), 64)
            site.url = _s(row.get("url"), 300)
            site.working_hours = _s(row.get("working_hours"), 120)
            site.currency = currency
            site.notes = _s(row.get("description"))
        # Состояние приезжает из источника всегда: это факт наблюдения, а не паспорт,
        # и «проверено человеком» его не отменяет.
        site.last_session_at = last_session
        site.is_alive = _bool(row.get("is_alive"))
        site.connection_quality_24h = _num(row.get("connection_quality_24h"))
        site.success_charge_pct = _num(row.get("success_charge_pct"))
        site.rating = _num(row.get("rating"))
        site.reviews_count = _int(row.get("reviews_count"))
        site.updated_at = now
        site.raw = dict(row)
        await db.flush()

        by_ext[ext] = site
        # В запасной ключ только что заведённую точку НЕ кладём: следующая строка того
        # же файла с тем же округлением — соседний пост, а не повтор.
        by_key.pop(key, None)

        snap = snaps.get((site.id, today))
        if snap is None:
            snap = MarketSiteSnapshot(company_id=company_id, site_id=site.id,
                                      snapshot_date=today, source=source)
            db.add(snap)
            snaps[(site.id, today)] = snap
        snap.is_alive = _bool(row.get("is_alive"))
        snap.under_repair = _bool(row.get("under_repair"))
        snap.connection_quality_24h = _num(row.get("connection_quality_24h"))
        snap.success_charge_pct = _num(row.get("success_charge_pct"))
        snap.connectors_charging = _int(row.get("connectors_charging"))
        snap.connectors_broken = _int(row.get("connectors_broken"))
        snap.last_session_at = last_session
        snap.rating = _num(row.get("rating"))
        snap.reviews_count = _int(row.get("reviews_count"))
        snap.stars_1_pct = _num(row.get("stars_1_pct"))
        snap.stars_5_pct = _num(row.get("stars_5_pct"))
        snap.ports = site.ports
        snap.max_power_kw = max_power
        snap.price_per_kwh = per_kwh if currency == "RUB" else None
        snap.currency = currency

        # Наблюдение цены заводим только на сравнимую величину: рубли за киловатт-час.
        # Тариф за минуту и за сессию виден в карточке как есть, но в сравнение с нашей
        # ₽/кВт·ч не идёт — иначе «дороже рынка на 12 %» окажется арифметикой над
        # разными единицами.
        for tariff in tariffs:
            if tariff["unit"] != "kwh" or currency != "RUB":
                continue
            price = tariff["price"]
            sane_price = comparable_price(tariff["unit"], price, paid=paid, currency=currency)
            if price == 0 and paid:
                continue
            sane = sane_price is not None
            ref = f"{source}:{ext}:{tariff.get('window') or 'all'}"
            if (site.id, ref) in seen_obs:
                continue
            seen_obs.add((site.id, ref))
            window = f"окно {tariff['window']}" if tariff.get("window") else "круглосуточно"
            db.add(MarketObservation(
                company_id=company_id, site_id=site.id, kind="price",
                observed_on=today, price_value=price, price_unit="kwh",
                price_per_kwh=sane_price,
                basis=(f"реестр, {window}" if sane else
                       f"реестр, {window} — вне разумного диапазона, в сравнение не идёт"),
                power_kw=max_power, channel="import", source_ref=ref,
                confidence="single" if sane else "conflict",
                author_name="Реестр ЭЗС РФ",
            ))
            priced += 1

        if done % 500 == 0:
            await _bump(db, log_id, done, total, created, updated)

    # Точка, которой в срезе не оказалось. Не удаляем и не закрываем сразу: обход
    # публичной карты бывает неполным, и «исчезла один раз» значит только это.
    closed = missing = 0
    for site in list(by_ext.values()):
        if site.source != source or (site.external_id in seen_ext):
            continue
        site.closed_confirmations = (site.closed_confirmations or 0) + 1
        missing += 1
        if site.closed_confirmations >= CLOSE_AFTER_MISSES and site.status != "closed":
            site.status = "closed"
            site.closed_on = today
            closed += 1

    await _bump(db, log_id, total, total, created, updated)
    logger.info("реестр рынка: %s строк, создано %s, обновлено %s, цен %s, пропущено %s",
                total, created, updated, priced, skipped)
    return {"status": "success", "snapshotDate": today, "rows": total,
            "created": created, "updated": updated, "prices": priced,
            "skipped": skipped, "foreign": foreign, "missing": missing, "closed": closed,
            "message": (f"срез {today}: точек {created + updated} "
                        f"(новых {created}), цен {priced}, "
                        f"вне России {foreign}, "
                        f"без координат или ключа {skipped}, "
                        f"не найдено в срезе {missing}")}
