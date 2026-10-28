"""Снимок сети оператора с его собственной карты.

Зачем отдельно от реестров. Публичные выгрузки (OCM, 2Chargers) знают адрес и
оператора, но не знают того, что оператор показывает у себя: какие станции
сейчас не работают, какие помечены новыми и когда введена последняя. На карте
«Пункт Е» 28.10.2026 это 1524 локации и 1673 станции, из них **292 станции
неактивны** — почти пятая часть сети, которой в публичных реестрах не видно.
Наш собственный реестр при этом знал 1418 точек этого оператора: расхождение в
106 точек стало измеримым только после сверки с его картой.

Как устроено у оператора. Страница региона отдаёт массив `dots` ЦЕЛИКОМ — всю
сеть, а не выбранный регион; фильтрация происходит в браузере. Значит один
запрос даёт полный слепок, и обходить 59 региональных страниц не нужно.

Что считается снимком. Точка сети кладётся в общий реестр `market_sites` (тем
же ключом совпадения, что у остальных импортов — координата с округлением), а
её состояние на дату — в `market_site_snapshots`. Ряд снимков и есть ответ на
вопрос «что изменилось за месяц»: чужой реестр истории не отдаёт, и если
хранить только «сейчас», вчерашнее состояние стирается безвозвратно.

Формат чужой страницы нам не принадлежит и может смениться без предупреждения.
Поэтому разбор строгий: нет массива или нет координат — импорт отказывается с
понятной причиной, а не записывает пустоту поверх известного.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketOperator, MarketSite, MarketSiteSnapshot
from app.services.market_news import TIMEOUT, UA_PAGE, get_page, proxy

# Ранг источника: карта самого оператора ближе к первоисточнику, чем публичная
# выгрузка, но ниже партнёрского обмена — оператор показывает то, что хочет.
SOURCE_RANK = 85

DOTS = re.compile(r"let\s+dots\s*=\s*(\[.*?\])\s*;", re.S)

# Коды регионов в данных оператора — автомобильные; держим их отдельно от
# справочника пространства, чтобы не навязывать чужую нумерацию нашим данным.
REGION_BY_CODE = {
    "01": "Адыгея", "02": "Башкортостан", "03": "Бурятия", "04": "Алтай",
    "05": "Дагестан", "07": "Кабардино-Балкария", "09": "Карачаево-Черкесия",
    "10": "Карелия", "11": "Коми", "12": "Марий Эл", "13": "Мордовия",
    "14": "Якутия", "16": "Татарстан", "17": "Тыва", "18": "Удмуртия",
    "19": "Хакасия", "21": "Чувашия", "22": "Алтайский край",
    "23": "Краснодарский край", "24": "Красноярский край", "25": "Приморский край",
    "26": "Ставропольский край", "27": "Хабаровский край", "28": "Амурская область",
    "29": "Архангельская область", "30": "Астраханская область",
    "31": "Белгородская область", "32": "Брянская область", "33": "Владимирская область",
    "34": "Волгоградская область", "35": "Вологодская область", "36": "Воронежская область",
    "37": "Ивановская область", "38": "Иркутская область", "39": "Калининградская область",
    "40": "Калужская область", "41": "Камчатский край", "42": "Кемеровская область",
    "43": "Кировская область", "44": "Костромская область", "45": "Курганская область",
    "46": "Курская область", "47": "Ленинградская область", "48": "Липецкая область",
    "49": "Магаданская область", "50": "Московская область", "51": "Мурманская область",
    "52": "Нижегородская область", "53": "Новгородская область", "54": "Новосибирская область",
    "55": "Омская область", "56": "Оренбургская область", "57": "Орловская область",
    "58": "Пензенская область", "59": "Пермский край", "60": "Псковская область",
    "61": "Ростовская область", "62": "Рязанская область", "63": "Самарская область",
    "64": "Саратовская область", "65": "Сахалинская область", "66": "Свердловская область",
    "68": "Тамбовская область", "69": "Тверская область", "70": "Томская область",
    "71": "Тульская область", "72": "Тюменская область", "73": "Ульяновская область",
    "74": "Челябинская область", "75": "Забайкальский край", "76": "Ярославская область",
    "77": "Москва", "78": "Санкт-Петербург", "86": "ХМАО", "89": "ЯНАО",
    "91": "Крым", "92": "Севастополь",
}


def parse_dots(html: str) -> list[dict[str, Any]]:
    """Достать массив точек со страницы карты оператора.

    Пустой результат — это отказ, а не «сеть пуста»: страница могла смениться.
    Решение, что делать с отказом, принимает вызывающий.
    """
    m = DOTS.search(html or "")
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except json.JSONDecodeError:
        return []
    return [d for d in data if isinstance(d, dict) and d.get("coords")]


def dedup_key(lat: float, lon: float) -> str:
    """Тот же ключ совпадения, что у остальных импортов рынка: ~50 метров."""
    return f"ezs:{round(float(lat), 3)}:{round(float(lon), 3)}"


def summarize(dots: list[dict[str, Any]]) -> dict[str, Any]:
    """Сводка слепка: то, чего публичные реестры не показывают."""
    станций = sum(int(d.get("stations") or 0) for d in dots)
    неактивных = sum(1 for d in dots for s in (d.get("marker") or {}).get("stations", [])
                     if s.get("inactive"))
    новых = sum(1 for d in dots if (d.get("marker") or {}).get("isNew"))
    даты = sorted(d["marker"]["latestCommissioningDate"][:10] for d in dots
                  if (d.get("marker") or {}).get("latestCommissioningDate"))
    по_току: dict[str, int] = {}
    for d in dots:
        for t in d.get("type") or []:
            по_току[t] = по_току.get(t, 0) + 1
    по_регионам: dict[str, int] = {}
    for d in dots:
        имя = REGION_BY_CODE.get(str(d.get("region")), str(d.get("region") or "—"))
        по_регионам[имя] = по_регионам.get(имя, 0) + 1
    return {
        "locations": len(dots), "stations": станций,
        "inactive": неактивных, "new": новых,
        "byCurrent": по_току,
        "byRegion": dict(sorted(по_регионам.items(), key=lambda x: -x[1])[:12]),
        "lastCommissioned": даты[-1] if даты else None,
        "regions": len(по_регионам),
    }


async def import_network(db: AsyncSession, company_id: uuid.UUID, url: str,
                         operator_id: uuid.UUID | None = None,
                         operator_name: str | None = None) -> dict[str, Any]:
    """Забрать карту сети оператора и обновить точки рынка со снимком на дату.

    Идемпотентно: ключ совпадения — координата с округлением, повторный импорт
    того же дня обновляет снимок, а не плодит второй.
    """
    p = proxy()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client, \
            httpx.AsyncClient(timeout=TIMEOUT, proxy=p) as proxied_client:
        r = await get_page(url, client, proxied_client if p else None, ua=UA_PAGE)
    dots = parse_dots(r.text)
    if not dots:
        raise RuntimeError(
            "на странице нет массива точек — формат карты оператора изменился; "
            "проверьте адрес и разбор, прежде чем доверять пустому результату")

    now = datetime.now(timezone.utc)
    today = now.date().isoformat()

    if operator_id is None and operator_name:
        op = (await db.execute(select(MarketOperator).where(
            MarketOperator.company_id == company_id,
            MarketOperator.name == operator_name))).scalar_one_or_none()
        if op is None:
            op = MarketOperator(company_id=company_id, name=operator_name,
                                relation="competitor", site_url=url)
            db.add(op)
            await db.flush()
        operator_id = op.id

    known = {s.dedup_key: s for s in (await db.execute(select(MarketSite).where(
        MarketSite.company_id == company_id))).scalars().all() if s.dedup_key}
    снимки = {(s.site_id, s.snapshot_date): s for s in (await db.execute(
        select(MarketSiteSnapshot).where(
            MarketSiteSnapshot.company_id == company_id,
            MarketSiteSnapshot.snapshot_date == today))).scalars().all()}

    создано = обновлено = снимков = 0
    for d in dots:
        coords = d.get("coords") or []
        if len(coords) != 2:
            continue
        lat, lon = float(coords[0]), float(coords[1])
        key = dedup_key(lat, lon)
        регион = REGION_BY_CODE.get(str(d.get("region")))
        маркер = d.get("marker") or {}
        станции = маркер.get("stations") or []
        живых = [s for s in станции if not s.get("inactive")]
        ток = "/".join(d.get("type") or []) or None
        коннекторы = ", ".join(d.get("plug") or []) or None

        site = known.get(key)
        if site is None:
            site = MarketSite(
                company_id=company_id, dedup_key=key, kind="ezs",
                name=f"{operator_name or 'ЭЗС'} · {регион or 'без региона'}"[:290],
                operator_id=operator_id, region=регион,
                latitude=lat, longitude=lon,
                ports=int(d.get("stations") or 0) or None,
                connectors=коннекторы, current_type=(ток or None),
                site_class="network",
                source="network", source_ref=f"network:{d.get('id')}",
                source_rank=SOURCE_RANK, first_seen_at=now, last_seen_at=now,
            )
            db.add(site)
            await db.flush()
            known[key] = site
            создано += 1
        else:
            site.last_seen_at = now
            if operator_id and not site.operator_id:
                site.operator_id = operator_id
            if регион and not site.region:
                site.region = регион
            if коннекторы and not site.connectors:
                site.connectors = коннекторы
            обновлено += 1
        # Живость — то, ради чего карта оператора и нужна: публичный реестр
        # показывает станцию, оператор показывает, работает ли она сегодня.
        site.is_alive = bool(живых)

        ключ_снимка = (site.id, today)
        снимок = снимки.get(ключ_снимка)
        if снимок is None:
            снимок = MarketSiteSnapshot(
                company_id=company_id, site_id=site.id, snapshot_date=today,
                source="network", source_ref=url[:200])
            db.add(снимок)
            снимки[ключ_снимка] = снимок
            снимков += 1
        снимок.is_alive = bool(живых)
        снимок.connectors_broken = len(станции) - len(живых)
        снимок.ports = int(d.get("stations") or 0) or None

    await db.commit()
    return {"url": url, "date": today, **summarize(dots),
            "created": создано, "updated": обновлено, "snapshots": снимков}
