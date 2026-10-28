"""Новости рынка: обход источников, разбор и предложение привязок.

Зачем код, а не агент. В «Ангаре» такой же обход делает бот: cron будит агента, тот
вызывает инструмент ленты и сам сочиняет материал. За четыре месяца он принёс 120
материалов — и встал 01.10.2026, когда контейнер бота упал с SIGSEGV; месяц никто не
заметил. Здесь обход живёт в Ядре рядом с остальными заданиями пространства, а
молчание источника видно на экране как факт («последний контакт 20 дней назад»).

Три вида источника и почему именно так (проверено 28.10.2026 с рабочей машины):
  * профильной отраслевой RSS-ленты по зарядной инфраструктуре в рунете нет. У общих
    лент ТАСС и РИА в последней сотне новостей — ноль про зарядки, `peretok.ru/rss`
    (энергетика) — ноль из пяти, а живой `zaryad.com/feed` при подходящем названии
    пишет про вечные двигатели. Поэтому широкий невод — поисковая лента (`search`);
  * сайты операторов, производителей и интеграторов своего RSS не отдают: у
    `punkt-e.ru`, `rosseti.ru`, `minenergo.gov.ru` нет даже тега автодискавери.
    Их заменяет поисковая лента с `site:<домен>` — у «Пункт Е» она отдаёт публикации
    самой компании, включая свежие;
  * `rss` остаётся для источника, который ленту всё-таки отдаёт: он проходит без
    тематического фильтра, потому что тема у него одна и она наша.

Что здесь НЕ делается: разбор произвольной страницы новостей без ленты. В «Ангаре»
это работа агента с `web_fetch`, то есть модели, а не кода; гадать регулярками по
чужой вёрстке — заведомо хрупко. Такой источник помечается ошибкой с понятной
причиной, и вместо него предлагается поисковая лента по его домену.
"""
from __future__ import annotations

import re
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MarketNews, MarketNewsSource, MarketOperator, MarketPlayer, Region

TIMEOUT = httpx.Timeout(25.0)
UA = "ElsyPlusMarket/1.0 (+https://rushydro.dataworker.ru)"
SEARCH_BASE = "https://news.google.com/rss/search"

# Окно обхода по умолчанию. Поисковая лента охотно отдаёт материалы 2022–2024 годов
# по тому же запросу; без окна первая же выгрузка завалит очередь разбора архивом.
SINCE_DAYS = 14

# Хвост «— Издание», который поисковая лента дописывает к каждому заголовку.
TITLE_TAIL = re.compile(r"\s+[-–—]\s+[^-–—]{2,60}$")

# Параметры-метки, от которых адрес одной и той же новости выглядит разным.
JUNK_PARAMS = ("utm_", "yclid", "gclid", "fbclid", "_openstat", "from", "oc")

# Тема новости. Порядок важен: сначала то, что меняет расклад (сделка, цена, стройка),
# потом общий фон. Слово ищется в заголовке — сниппета у поисковой ленты нет.
TOPIC_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("deal", ("купил", "приобрел", "приобрёл", "сделка", "слияние", "продал",
              "инвестиц", "партнерств", "партнёрств", "соглашение о")),
    ("price", ("тариф", "подорожа", "подешеве", "цена зарядки", "стоимость зарядки",
               "повысил", "снизил цен")),
    ("regulation", ("постановлен", "законопроект", "закон", "субсиди", "господдержк",
                    "норматив", "требован", "обязал", "минэнерго", "правительств")),
    ("opening", ("открыл", "открыт", "установил", "запустил", "ввел в эксплуатацию",
                 "ввёл в эксплуатацию", "появил", "расшир", "построи")),
    ("tech", ("мощност", "накопител", "протокол", "ocpp", "ocpi", "платформ",
              "программн", "оборудован", "производств", "импортозамещ",
              # Железо станции называют частями, а не словом «оборудование»:
              # «поставит отечественные инверторы и шкафы» — это новость о технике.
              "инвертор", "аккумулятор", "отечественн", "коннектор")),
)

# Тематический фильтр для широких лент. Профильная лента (`is_profile`) проходит целиком.
DEFAULT_INCLUDE = ("зарядн", "электрозаряд", "эзс", "электромобил", "электрокар",
                   "электротранспорт", "зарядка электро", "электросуд", "электробус")
DEFAULT_EXCLUDE = ("зарядное устройство для телефон", "powerbank", "пауэрбанк",
                   "зарядка смартфон", "зарядка айфон", "беспроводная зарядка телефон",
                   # Товарные подборки и инструкции. На живой выдаче 28.10.2026 слово
                   # «зарядн» пропустило «Рейтинг лучших зарядных станций — для дома и
                   # улицы» и «Топ-10 лучших зарядных станций»: это магазинный обзор
                   # бытовых устройств, а не событие рынка.
                   "рейтинг лучших", "топ-10", "топ 10", "как выбрать", "своими руками",
                   "лучшие зарядные устройства", "обзор зарядных устройств")


def normalize_url(url: str) -> str:
    """Ключ совпадения новости: адрес без метки кампании, якоря и хвостового слэша.

    Одну новость перепечатывают пять сайтов и приводят по пяти разным ссылкам с
    `utm_source`. Без приведения лента за неделю зарастает повторами, и «семь
    упоминаний оператора» оказываются одним пресс-релизом.
    """
    try:
        p = urlparse((url or "").strip())
    except ValueError:
        return (url or "").strip().lower()[:600]
    if not p.netloc:
        return (url or "").strip().lower()[:600]
    query = urlencode([(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
                       if not k.lower().startswith(JUNK_PARAMS)])
    path = p.path.rstrip("/") or "/"
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return urlunparse(("https", host, path, "", query, ""))[:600]


def clean_title(title: str, source_name: str | None = None) -> str:
    """Заголовок без дописанного издания: «… - PUNKT E» → «…»."""
    t = re.sub(r"\s+", " ", (title or "").strip())
    if source_name and t.lower().endswith(f"- {source_name.lower()}"):
        return t[: -(len(source_name) + 2)].strip()
    return TITLE_TAIL.sub("", t) if len(t) > 40 else t


def title_key(title: str) -> str:
    """Ключ заголовка для склейки перепечаток: без регистра, пунктуации и ё."""
    t = unicodedata.normalize("NFKC", (title or "")).lower().replace("ё", "е")
    return re.sub(r"[^a-zа-я0-9 ]+", " ", t).strip()[:200]


def search_url(query: str) -> str:
    """Поисковая лента по запросу — широкий невод отрасли."""
    return f"{SEARCH_BASE}?{urlencode({'q': query, 'hl': 'ru', 'gl': 'RU', 'ceid': 'RU:ru'})}"


def site_query(site_url: str | None, name: str | None = None) -> str | None:
    """Запрос «публикации этого домена» — замена отсутствующей ленты оператора.

    У операторов, производителей и ведомств своего RSS нет, но их пресс-релизы
    индексируются. `site:punkt-e.ru` отдаёт материалы самой компании, а имя в
    кавычках добирает то, что про неё написали другие.
    """
    host = (urlparse(site_url or "").hostname or "").lower().removeprefix("www.")
    if host:
        return f"site:{host}"
    return f'"{name.strip()}" зарядная станция' if name and name.strip() else None


def _text(el: ET.Element | None) -> str:
    return re.sub(r"\s+", " ", "".join(el.itertext()).strip()) if el is not None else ""


def _when(raw: str) -> datetime | None:
    """Дата публикации источника. Неизвестную не подменяем датой скачивания."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw).astimezone(timezone.utc)
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def parse_feed(xml_text: str) -> list[dict[str, Any]]:
    """RSS 2.0 и Atom одной функцией: нужны пять полей, библиотеки для них не нужно.

    Элемент без ссылки или без заголовка пропускается молча: это не новость, а
    служебная запись ленты.
    """
    try:
        root = ET.fromstring(xml_text.lstrip("﻿ \n\r\t"))
    except ET.ParseError:
        return []
    atom = "{http://www.w3.org/2005/Atom}"
    nodes = root.findall(".//item") or root.findall(f".//{atom}entry")
    out: list[dict[str, Any]] = []
    for n in nodes:
        link = _text(n.find("link")) or _text(n.find("guid"))
        if not link:
            href = n.find(f"{atom}link")
            link = (href.get("href") or "") if href is not None else ""
        title = _text(n.find("title")) or _text(n.find(f"{atom}title"))
        if not link or not title:
            continue
        src = _text(n.find("source")) or _text(n.find(f"{atom}source"))
        guid = _text(n.find("guid"))
        published = (_when(_text(n.find("pubDate")))
                     or _when(_text(n.find(f"{atom}updated")))
                     or _when(_text(n.find(f"{atom}published"))))
        snippet = _text(n.find("description")) or _text(n.find(f"{atom}summary"))
        if snippet.startswith("<a href") or snippet.lstrip().startswith("<"):
            snippet = re.sub(r"<[^>]+>", " ", snippet)
        snippet = re.sub(r"\s+", " ", snippet).strip()
        out.append({
            "title": clean_title(title, src or None),
            "raw_title": title,
            "url": link,
            # У поисковой ленты ссылка — редирект с меткой `?oc=5`, а `guid` стабилен:
            # по нему одна и та же статья из двух разных запросов совпадёт.
            "key": normalize_url(guid if guid.startswith("http") else link) if link else "",
            "guid": guid or None,
            "sourceName": src or None,
            "publishedAt": published,
            "snippet": snippet[:1000] or None,
        })
    return out


def topic_of(text: str) -> str:
    """О чём новость. Не классификатор смысла, а подсказка для отбора в ленте."""
    t = (text or "").lower().replace("ё", "е")
    for topic, words in TOPIC_WORDS:
        if any(w.replace("ё", "е") in t for w in words):
            return topic
    return "other"


def relevant(text: str, is_profile: bool,
             include: Iterable[str] = DEFAULT_INCLUDE,
             exclude: Iterable[str] = DEFAULT_EXCLUDE) -> bool:
    """Наша ли это тема. Профильный источник проходит целиком, широкий — по словарю."""
    t = (text or "").lower().replace("ё", "е")
    if any(w in t for w in exclude):
        return False
    return True if is_profile else any(w in t for w in include)


def _name_variants(name: str) -> set[str]:
    """Имя компании, как его могли написать: без кавычек, ОООшек и регистра."""
    base = re.sub(r"[«»\"'`]", "", (name or "")).strip().lower().replace("ё", "е")
    base = re.sub(r"^(ооо|оао|пао|зао|ао|ип)\s+", "", base).strip()
    out = {base}
    if len(base) > 4:
        out.add(base.replace("-", " "))
        out.add(base.replace(" ", ""))
    return {v for v in out if len(v) >= 4}


def suggest_links(text: str, operators: list[MarketOperator],
                  players: list[MarketPlayer], regions: list[str]) -> dict[str, Any]:
    """Предложить, к чему относится новость: оператор, игрок, регион.

    Предлагает, а не решает (как разбор владельцев, docs/MARKET.md §3). Совпадение
    слова в заголовке — повод показать человеку подсказку, а не факт о компании:
    «Лента» в тексте одинаково хорошо значит сеть магазинов и ленту новостей.
    """
    t = (text or "").lower().replace("ё", "е")
    found: dict[str, Any] = {}
    for op in operators:
        for v in _name_variants(op.name) | _name_variants(op.short_name or ""):
            if v and v in t:
                found["operatorId"] = str(op.id)
                found["operatorName"] = op.name
                found["matched"] = v
                break
        if "operatorId" in found:
            break
    if "operatorId" not in found:
        for pl in players:
            for v in _name_variants(pl.brand or "") | _name_variants(pl.app or ""):
                if v and v in t:
                    found["playerId"] = str(pl.id)
                    found["playerName"] = pl.brand or pl.app
                    found["matched"] = v
                    break
            if "playerId" in found:
                break
    for r in regions:
        rl = (r or "").lower().replace("ё", "е")
        # «Московская область» → ищем «московск»: в новостях пишут «в Московской области».
        stem = re.sub(r"\s+(область|край|республика|округ|автономн\w*)\s*$", "", rl).strip()
        if len(stem) >= 5 and stem[:-2] in t:
            found["region"] = r
            break
    return found


async def fetch_feed(url: str, client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Получить и разобрать ленту. Ошибка источника — факт для карточки, не исключение."""
    r = await client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
    r.raise_for_status()
    return parse_feed(r.text)


async def discover_feed(page_url: str, client: httpx.AsyncClient) -> str | None:
    """Есть ли у страницы своя лента (`<link rel=alternate type=application/rss+xml>`).

    У операторов её не нашлось ни у одного проверенного (28.10.2026), но проверить
    дешевле, чем объяснять человеку, почему мы ищем его пресс-релизы в поиске.
    """
    r = await client.get(page_url, headers={"User-Agent": UA}, follow_redirects=True)
    r.raise_for_status()
    m = re.search(r'<link[^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', r.text, re.I)
    if not m:
        return None
    href = re.search(r'href=["\']([^"\']+)["\']', m.group(0))
    if not href:
        return None
    link = href.group(1)
    if link.startswith("//"):
        return "https:" + link
    if link.startswith("/"):
        p = urlparse(page_url)
        return f"{p.scheme}://{p.netloc}{link}"
    return link if link.startswith("http") else None


async def collect(db: AsyncSession, cid: uuid.UUID, sources: list[MarketNewsSource],
                  since_days: int = SINCE_DAYS, per_source: int = 40) -> dict[str, Any]:
    """Обойти источники и сложить новое в очередь разбора.

    Идемпотентно: ключ новости — приведённый адрес, повторный обход обновляет
    найденное, а не плодит второе. Перепечатка с тем же заголовком в пределах окна
    тоже считается той же новостью: иначе один пресс-релиз даёт пять «упоминаний».
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, since_days))
    operators = list((await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all())
    players = list((await db.execute(select(MarketPlayer).where(
        MarketPlayer.company_id == cid))).scalars().all())
    regions = [r for (r,) in (await db.execute(select(Region.name).where(
        Region.company_id == cid))).all() if r]

    known_keys = {k for (k,) in (await db.execute(select(MarketNews.url_key).where(
        MarketNews.company_id == cid))).all()}
    recent_titles = {title_key(t) for (t,) in (await db.execute(select(MarketNews.title).where(
        MarketNews.company_id == cid,
        MarketNews.retrieved_at >= datetime.now(timezone.utc) - timedelta(days=45)))).all()}

    added = 0
    per_source_stat: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        for src in sources:
            src.last_run_at = now
            feed_url = src.url if src.kind != "search" else search_url(src.url)
            stat: dict[str, Any] = {"id": str(src.id), "title": src.title, "added": 0}
            try:
                if src.kind == "page":
                    found = await discover_feed(src.url, client)
                    if not found:
                        raise RuntimeError(
                            "страница не отдаёт ленту — используйте поисковый источник "
                            f"по домену: {site_query(src.url, src.title)}")
                    feed_url = found
                items = await fetch_feed(feed_url, client)
            except Exception as e:  # noqa: BLE001 — причина нужна в карточке источника
                src.last_error = f"{type(e).__name__}: {e}"[:300]
                stat["error"] = src.last_error
                per_source_stat.append(stat)
                continue
            src.last_error = None
            src.last_ok_at = now
            src.found_total = (src.found_total or 0) + len(items)
            fresh = 0
            for it in items[: max(1, per_source) * 3]:
                when = it["publishedAt"]
                if when is not None and when < cutoff:
                    continue
                key = it["key"] or normalize_url(it["url"])
                if not key or key in known_keys:
                    continue
                tkey = title_key(it["title"])
                if tkey and tkey in recent_titles:
                    continue
                text = f"{it['title']} {it.get('snippet') or ''}"
                if not relevant(text, src.is_profile):
                    continue
                hints = suggest_links(text, operators, players, regions)
                db.add(MarketNews(
                    company_id=cid, source_id=src.id,
                    title=it["title"][:500], url=it["url"][:900], url_key=key,
                    snippet=it.get("snippet"), source_name=it.get("sourceName"),
                    published_at=when, retrieved_at=now,
                    channel="search" if src.kind == "search" else src.kind,
                    topic=topic_of(text),
                    # Привязка источника сильнее словаря: лента оператора — его новости.
                    operator_id=src.operator_id or (
                        uuid.UUID(hints["operatorId"]) if hints.get("operatorId") else None),
                    player_id=src.player_id or (
                        uuid.UUID(hints["playerId"]) if hints.get("playerId") else None),
                    region=hints.get("region"),
                    suggested=hints or None, linked_by="auto",
                    raw={"guid": it.get("guid"), "rawTitle": it.get("raw_title"),
                         "feed": feed_url},
                ))
                known_keys.add(key)
                if tkey:
                    recent_titles.add(tkey)
                added += 1
                fresh += 1
                if fresh >= per_source:
                    break
            stat["added"] = fresh
            stat["seen"] = len(items)
            per_source_stat.append(stat)
    await db.commit()
    return {"added": added, "sources": per_source_stat, "sinceDays": since_days}
