"""Импорт точек рынка из Open Charge Map — открытого реестра ЭЗС (docs/MARKET.md).

Почему именно он: у нас записано, что источники ранжируются, и официальный API с
лицензией стоит выше парсинга чужих карт (принцип 6). OCM отдаёт оператора, мощность,
коннекторы, число портов и нередко тариф — то есть ровно те поля, из которых считается
позиция объекта. Сайты операторов (Пункт Е, Яндекс) публичного списка не отдают, а
подбирать их внутренние ручки мы себе запретили сами.

Ключ бесплатный (регистрация на openchargemap.org) и живёт в переменной окружения
`OCM_API_KEY` стека — не в коде и не в базе: это ключ поставки, а не компании.

Импорт идемпотентен: повторный прогон обновляет `last_seen_at` и не плодит дублей —
ключ совпадения тот же, что у ручного ввода (координата с округлением + вид).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketObservation, MarketOperator, MarketSite

OCM_URL = "https://api.openchargemap.io/v3/poi/"
TIMEOUT = httpx.Timeout(45.0)
# Ранг источника: официальный API ниже партнёрского обмена, но выше парсинга и импорта
# из выгрузок — так конфликт фактов разрешается в пользу более близкого к первоисточнику.
SOURCE_RANK = 90

# Один и тот же оператор в OCM пишется по-разному; без приведения «PUNKT E» и «Punkt E»
# станут двумя конкурентами, и доля рынка посчитается по выдуманному числу сетей.
ALIASES = {
    "punkt e": "PUNKT E", "punkte": "PUNKT E", "пункт е": "PUNKT E",
    "yandex": "Яндекс", "яндекс": "Яндекс",
    "rosseti": "Россети", "россети": "Россети",
    "sitronics": "Sitronics Electro", "ситроникс": "Sitronics Electro",
    "mosenergo": "Мосэнергосбыт", "мосэнерго": "Мосэнергосбыт",
    "ev-time": "EV-Time", "evtime": "EV-Time",
    "rushydro": "РусГидро", "русгидро": "РусГидро",
}
# Наши станции в чужой реестр не переносим: они уже есть в реестре пространства, и копия
# сделала бы объект конкурентом самому себе.
OURS = ("русгидро", "rushydro")


def api_key() -> str | None:
    return os.getenv("OCM_API_KEY") or None


def _canon_operator(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    for alias, name in ALIASES.items():
        if alias in key:
            return name
    return raw.strip()[:80]


def _dedup_key(kind: str, lat: float | None, lon: float | None, name: str) -> str:
    if lat is not None and lon is not None:
        return f"{kind}:{round(float(lat), 3)}:{round(float(lon), 3)}"
    return f"{kind}:{name.strip().lower()[:80]}"


def _price_from(usage_cost: str | None) -> float | None:
    """Тариф из свободной строки OCM («25 RUB/kWh», «22 руб/кВтч», «Free»).

    Разбираем только рублёвую цену за кВтч: всё остальное («за сессию», «по подписке»)
    сравнивать с нашей ценой нельзя, а показать как сравнимое — значит соврать
    (принцип 3 docs/MARKET.md). Непонятную строку кладём в заметку наблюдения.
    """
    if not usage_cost:
        return None
    text = usage_cost.lower().replace(",", ".")
    if "kwh" not in text and "квтч" not in text and "квт·ч" not in text:
        return None
    number, seen_dot = "", False
    for ch in text:
        if ch.isdigit():
            number += ch
        elif ch == "." and number and not seen_dot:
            number += ch
            seen_dot = True
        elif number:
            break
    try:
        value = float(number)
    except ValueError:
        return None
    # Отсекаем мусор: реальный тариф в рублях за кВтч лежит между 1 и 200.
    return value if 1 <= value <= 200 else None


async def fetch_pois(bbox: tuple[float, float, float, float], max_results: int = 500) -> list[dict[str, Any]]:
    """Точки OCM в прямоугольнике (юг, запад, север, восток)."""
    key = api_key()
    if not key:
        raise RuntimeError("Не задан OCM_API_KEY — ключ Open Charge Map не настроен в стеке")
    south, west, north, east = bbox
    params = {
        "output": "json", "countrycode": "RU", "compact": "true", "verbose": "false",
        "maxresults": str(max_results),
        "boundingbox": f"({south},{west}),({north},{east})",
        "key": key,
    }
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        resp = await client.get(OCM_URL, params=params,
                                headers={"User-Agent": "ElsyPlus-Market/1.0"})
    if resp.status_code >= 400:
        raise RuntimeError(f"Open Charge Map ответил HTTP {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    return data if isinstance(data, list) else []


async def import_area(
    db: AsyncSession, company_id: uuid.UUID, bbox: tuple[float, float, float, float],
    user_id: uuid.UUID | None = None, user_name: str | None = None,
) -> dict[str, Any]:
    """Загрузить прямоугольник в рынок компании. Возвращает счётчики для отчёта."""
    pois = await fetch_pois(bbox)
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    known_ops = {(o.name or "").strip().lower(): o.id for o in (await db.execute(
        select(MarketOperator).where(MarketOperator.company_id == company_id))).scalars().all()}

    created = updated = priced = skipped_ours = 0
    for poi in pois:
        info = poi.get("AddressInfo") or {}
        lat, lon = info.get("Latitude"), info.get("Longitude")
        if lat is None or lon is None:
            continue
        operator = _canon_operator((poi.get("OperatorInfo") or {}).get("Title"))
        if operator and any(o in operator.lower() for o in OURS):
            skipped_ours += 1
            continue

        title = (info.get("Title") or "").strip() or (f"ЭЗС {operator}" if operator else "ЭЗС")
        town = (info.get("Town") or "").strip() or None
        connections = poi.get("Connections") or []
        power = max((c.get("PowerKW") or 0) for c in connections) if connections else None
        types = sorted({(c.get("ConnectionType") or {}).get("Title") for c in connections
                        if (c.get("ConnectionType") or {}).get("Title")})
        ports = poi.get("NumberOfPoints") or (len(connections) or None)

        op_id = None
        if operator:
            key = operator.lower()
            if key not in known_ops:
                op = MarketOperator(company_id=company_id, name=operator, relation="competitor")
                db.add(op)
                await db.flush()
                known_ops[key] = op.id
            op_id = known_ops[key]

        dkey = _dedup_key("ezs", lat, lon, title)
        site = (await db.execute(select(MarketSite).where(
            MarketSite.company_id == company_id,
            MarketSite.dedup_key == dkey))).scalar_one_or_none()
        if site is None:
            site = MarketSite(
                company_id=company_id, dedup_key=dkey, kind="ezs",
                name=f"{title} · {town}"[:290] if town else title[:290],
                operator_id=op_id, address=(info.get("AddressLine1") or None), city=town,
                latitude=lat, longitude=lon, ports=ports,
                max_power_kw=power or None, connectors=", ".join(types)[:200] or None,
                source="api", source_ref=f"ocm:{poi.get('ID')}", source_rank=SOURCE_RANK,
                first_seen_at=now, last_seen_at=now,
            )
            db.add(site)
            await db.flush()
            created += 1
        else:
            # Ручную правку не трогаем (принцип 2): импорт лишь подтверждает, что точка
            # жива, и дополняет пустые поля.
            site.last_seen_at = now
            if op_id and not site.operator_id:
                site.operator_id = op_id
            if site.ports is None and ports:
                site.ports = ports
            if site.max_power_kw is None and power:
                site.max_power_kw = power
            updated += 1

        price = _price_from(poi.get("UsageCost"))
        if price:
            db.add(MarketObservation(
                company_id=company_id, site_id=site.id, kind="price",
                observed_on=today, price_value=price, price_unit="kwh",
                price_per_kwh=price,
                basis=f"OCM: {str(poi.get('UsageCost'))[:100]}",
                power_kw=power or None,
                connector_type=", ".join(types)[:40] or None,
                channel="import", source_ref=f"ocm:{poi.get('ID')}",
                author_id=user_id, author_name=user_name,
            ))
            priced += 1

    await db.commit()
    return {"found": len(pois), "created": created, "updated": updated,
            "prices": priced, "skippedOurs": skipped_ours}
