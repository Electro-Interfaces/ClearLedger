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

import asyncio
import os
import re
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from html import unescape
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (MarketActor, MarketNews, MarketNewsMention, MarketNewsSource,
                        MarketOperator, MarketPlayer, Region)

TIMEOUT = httpx.Timeout(25.0)
UA = "ElsyPlusMarket/1.0 (+https://rushydro.dataworker.ru)"
# Браузерный User-Agent — только для страницы издания: часть сайтов отдаёт карточке
# бота усечённую версию без og-разметки, и обложка тогда не находится.
UA_PAGE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/129.0 Safari/537.36")

# Поисковые ленты. Их две, и они не равнозначны.
#
# Bing отдаёт ссылку через свой счётчик `apiclick.aspx`, но это ОБЫЧНЫЙ HTTP-редирект:
# пройдя его, мы получаем адрес издания и можем забрать обложку, лид и видео из
# og-разметки. Поэтому он основной — лента с картинками собирается только так.
#
# Google News даёт вчетверо больше материалов, но прячет адрес издания в зашифрованном
# токене `CBMi…` (проверено 28.10.2026: старый приём с base64 больше не раскрывает его,
# а переход ведёт на consent.google.com). Из него можно взять заголовок, издание и дату,
# но ни обложки, ни прямой ссылки — поэтому он «широкий невод», а не лента.
BING_BASE = "https://www.bing.com/news/search"
GOOGLE_BASE = "https://news.google.com/rss/search"

# Сколько лент тянем одновременно. Шесть — компромисс: тридцать источников
# укладываются в несколько секунд, а прокси стека не получает залпом весь список.
FETCH_PARALLEL = 6

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
                   "лучшие зарядные устройства", "обзор зарядных устройств",
                   # «Зарядная станция» бывает и для геймпада: 28.10.2026 в ленту
                   # приехала док-станция 8BitDo — слово то же, рынок другой.
                   "8bitdo", "геймпад", "консол", "док-станц", "докстанц", "наушник",
                   "ноутбук", "пылесос", "для телефона", "для смартфона")


def proxy() -> str | None:
    """Через что ходить наружу. Пусто — напрямую.

    Со стенда часть источников недоступна напрямую: `news.google.com` отвечает
    таймаутом TLS-рукопожатия (геоблокировка), и обход возвращал бы пустую ленту
    при исправном коде. Стек для таких случаев уже держит прокси —
    `SECURITY_TG_PROXY`, тот же путь, которым уходят уведомления в Telegram, —
    поэтому своей настройки обход не требует, а `MARKET_NEWS_PROXY` оставлен на
    случай, когда новостям нужен отдельный выход.
    """
    for name in ("MARKET_NEWS_PROXY", "HTTPS_PROXY", "https_proxy", "SECURITY_TG_PROXY"):
        v = (os.environ.get(name) or "").strip()
        if v:
            return v
    return None


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


# Оператор OR обнуляет выдачу Bing: по запросу с ним приходит ноль элементов,
# без него — девять-двенадцать (проверено 28.10.2026 на «Парус электро»).
# Источник с таким запросом выглядит живым — отвечает без ошибки и приносит
# пусто, то есть молчит громче, чем сломанный.
OR_IN_QUERY = re.compile(r"\s+OR\s+")


def clean_query(query: str) -> str:
    """Запрос без того, что гасит поисковую ленту."""
    return OR_IN_QUERY.sub(" ", query or "").strip()


def search_url(query: str, kind: str = "search") -> str:
    """Адрес поисковой ленты по запросу: Bing для ленты, Google для широкого невода."""
    query = clean_query(query)
    if kind == "search_wide":
        return f"{GOOGLE_BASE}?{urlencode({'q': query, 'hl': 'ru', 'gl': 'RU', 'ceid': 'RU:ru'})}"
    return f"{BING_BASE}?{urlencode({'q': query, 'format': 'RSS', 'setmkt': 'ru-RU'})}"


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


def _plain(raw: str) -> str:
    """Человеческий текст из ленты: без тегов, лишних пробелов и сущностей.

    Декодируем, пока меняется: часть лент экранирует текст дважды, и один проход
    оставляет в карточке «&#34;электричек&#34;» вместо кавычек (видно на живой
    ленте «Российской газеты» 28.10.2026).
    """
    t = re.sub(r"<[^>]+>", " ", raw or "")
    for _ in range(3):
        d = unescape(t)
        if d == t:
            break
        t = d
    return re.sub(r"\s+", " ", t).strip()


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
        snippet = _plain(snippet)
        # Поисковые ленты кладут в описание тот же заголовок со ссылкой: как лид это
        # пустая строка, занимающая место в карточке.
        if snippet and title_key(snippet).startswith(title_key(clean_title(title, src or None))[:60]):
            snippet = ""
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
            "image": None,
            "media": "article",
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
        stem = re.sub(r"\s+(область|край|республика|округ|автономн\w*)\s*$", "", rl).strip()
        if len(stem) < 5:
            continue
        # Рядом должно стоять слово уровня: справочник пространства держит и мусор
        # («Большой», «Казань», «12»), а без указателя «Большой» ловился в любом
        # тексте и подписывал новость чужим регионом (замечание МАГа 28.10.2026).
        корень = re.escape(stem[:-2] if stem[-2:] in ("ая", "ий", "ой", "ый") else stem)
        if re.search(rf"\b{корень}\w{{0,4}}\s+(?:област|кра[йяею]|республик|округ|ао\b)", t):
            found["region"] = r
            break
    return found


async def get_page(url: str, client: httpx.AsyncClient,
                   proxied: httpx.AsyncClient | None = None,
                   ua: str = UA) -> httpx.Response:
    """Забрать страницу: сначала напрямую, при сетевом отказе — через прокси.

    Порядок именно такой. Прокси стека живёт на VPN-пире, и если сделать его
    единственным путём, то его выключение останавливает обход целиком — включая
    российские источники, которые со стенда открываются напрямую. Наоборот
    безопаснее: прямой путь обслуживает всё, что доступно, а прокси подхватывает
    то, что закрыто геоблокировкой.
    """
    try:
        r = await client.get(url, headers={"User-Agent": ua}, follow_redirects=True)
        r.raise_for_status()
        return r
    except (httpx.TransportError, httpx.HTTPStatusError) as direct_error:
        if proxied is None:
            raise
        try:
            r = await proxied.get(url, headers={"User-Agent": ua}, follow_redirects=True)
            r.raise_for_status()
            return r
        except Exception:
            # В карточку источника важнее причина ПРЯМОГО отказа: она объясняет,
            # почему вообще понадобился обход, — а падение прокси видно по тому,
            # что через него не прошёл ни один источник.
            raise direct_error from None


async def fetch_feed(url: str, client: httpx.AsyncClient,
                     proxied: httpx.AsyncClient | None = None) -> list[dict[str, Any]]:
    """Получить и разобрать ленту. Ошибка источника — факт для карточки, не исключение."""
    r = await get_page(url, client, proxied)
    return parse_feed(r.text)


# Адреса, за которыми стоит поисковик, а не издание: читать там нечего.
SEARCH_HOSTS = re.compile(r"(news\.google\.com|bing\.com/news/apiclick|consent\.google\.com)", re.I)

VIDEO_HOSTS = ("youtube.com", "youtu.be", "rutube.ru", "vk.com/video", "vkvideo.ru",
               "dzen.ru/video", "m24.ru/videos", "smotrim.ru")


def _meta(html: str, prop: str) -> str | None:
    """Значение og-свойства. Порядок атрибутов у сайтов разный, ищем оба."""
    for pattern in (rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)["\']',
                    rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]+(?:property|name)=["\']{prop}["\']'):
        m = re.search(pattern, html, re.I)
        if m and m.group(1).strip():
            return _plain(m.group(1))
    return None


async def enrich(item: dict[str, Any], client: httpx.AsyncClient,
                 proxied: httpx.AsyncClient | None = None) -> dict[str, Any]:
    """Дополнить материал обложкой, лидом и признаком видео со страницы издания.

    Без этого лента нечитаема: заголовок и дата — это список, а не новости. Обложка
    и первые строки берутся из og-разметки самой публикации, то есть из того, что
    издание само показывает при репосте, — не из нашей догадки.

    Попутно раскрывается адрес: Bing отдаёт ссылку через счётчик `apiclick.aspx`,
    и без прохода по редиректу в карточке остался бы адрес поисковика, а не издания.
    Неудача здесь не ошибка источника: материал остаётся в ленте без обложки.
    """
    try:
        r = await get_page(item["url"], client, proxied, ua=UA_PAGE)
    except Exception:  # noqa: BLE001 — обложка необязательна, материал важнее
        return item
    final = str(r.url)
    if final and "bing.com" not in final and "news.google.com" not in final:
        item["url"] = final
        item["key"] = normalize_url(final)
    html = r.text
    item["image"] = _meta(html, "og:image") or _meta(html, "twitter:image") or item.get("image")
    лид = _meta(html, "og:description") or _meta(html, "description")
    if лид and title_key(лид) != title_key(item["title"]):
        item["snippet"] = лид[:1000]
    if _meta(html, "og:video") or _meta(html, "og:video:url") \
            or any(h in final.lower() for h in VIDEO_HOSTS):
        item["media"] = "video"
    if not item.get("sourceName"):
        item["sourceName"] = (_meta(html, "og:site_name")
                              or urlparse(final).hostname or "").removeprefix("www.") or None
    return item


async def discover_feed(page_url: str, client: httpx.AsyncClient,
                        proxied: httpx.AsyncClient | None = None) -> str | None:
    """Есть ли у страницы своя лента (`<link rel=alternate type=application/rss+xml>`).

    У операторов её не нашлось ни у одного проверенного (28.10.2026), но проверить
    дешевле, чем объяснять человеку, почему мы ищем его пресс-релизы в поиске.
    """
    r = await get_page(page_url, client, proxied)
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
                  since_days: int = SINCE_DAYS, per_source: int = 40,
                  include: Iterable[str] | None = None,
                  exclude: Iterable[str] | None = None) -> dict[str, Any]:
    """Обойти источники и сложить новое в очередь разбора.

    Идемпотентно: ключ новости — приведённый адрес, повторный обход обновляет
    найденное, а не плодит второе. Перепечатка с тем же заголовком в пределах окна
    тоже считается той же новостью: иначе один пресс-релиз даёт пять «упоминаний».

    Ленты забираются ПАРАЛЛЕЛЬНО, и это не оптимизация, а условие работоспособности:
    последовательный обход тридцати источников по несколько секунд каждый не
    укладывается в таймаут кромки, и человек вместо ленты получает «Bad Gateway»
    (28.10.2026). Запись в базу идёт после — одной сессией, последовательно.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, since_days))
    operators = list((await db.execute(select(MarketOperator).where(
        MarketOperator.company_id == cid))).scalars().all())
    players = list((await db.execute(select(MarketPlayer).where(
        MarketPlayer.company_id == cid))).scalars().all())
    actors = list((await db.execute(select(MarketActor).where(
        MarketActor.company_id == cid))).scalars().all())
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
    p = proxy()
    async with httpx.AsyncClient(timeout=TIMEOUT) as client, \
            httpx.AsyncClient(timeout=TIMEOUT, proxy=p) as proxied_client:
        proxied = proxied_client if p else None
        gate = asyncio.Semaphore(FETCH_PARALLEL)

        async def забрать(src: MarketNewsSource) -> tuple[MarketNewsSource, str, Any]:
            """Лента источника или его ошибка. Исключение здесь — результат, не сбой."""
            feed_url = (search_url(src.url, src.kind)
                        if src.kind in ("search", "search_wide") else src.url)
            async with gate:
                try:
                    if src.kind == "page":
                        found = await discover_feed(src.url, client, proxied)
                        if not found:
                            raise RuntimeError(
                                "страница не отдаёт ленту — используйте поисковый источник "
                                f"по домену: {site_query(src.url, src.title)}")
                        feed_url = found
                    return src, feed_url, await fetch_feed(feed_url, client, proxied)
                except Exception as e:  # noqa: BLE001 — причина нужна в карточке источника
                    return src, feed_url, e

        собрано = await asyncio.gather(*(забрать(s) for s in sources))

        for src, feed_url, items in собрано:
            src.last_run_at = now
            stat: dict[str, Any] = {"id": str(src.id), "title": src.title, "added": 0}
            if isinstance(items, BaseException):
                src.last_error = f"{type(items).__name__}: {items}"[:300]
                stat["error"] = src.last_error
                per_source_stat.append(stat)
                continue
            src.last_error = None
            src.last_ok_at = now
            src.found_total = (src.found_total or 0) + len(items)
            # Сначала отбираем кандидатов и только потом идём на страницы изданий:
            # обогащать отброшенное — платить временем за то, что не покажем.
            кандидаты: list[dict[str, Any]] = []
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
                if not relevant(f"{it['title']} {it.get('snippet') or ''}", src.is_profile,
                                include or DEFAULT_INCLUDE, exclude or DEFAULT_EXCLUDE):
                    continue
                known_keys.add(key)
                if tkey:
                    recent_titles.add(tkey)
                кандидаты.append(it)
                if len(кандидаты) >= per_source:
                    break

            # Обложка, лид и признак видео — только у поисковых лент: у собственной
            # ленты издания медиа уже в элементе, а страница `page` ведёт на тот же сайт.
            if src.kind == "search" and кандидаты:
                async def обогатить(it: dict[str, Any]) -> dict[str, Any]:
                    async with gate:
                        return await enrich(it, client, proxied)
                кандидаты = list(await asyncio.gather(*(обогатить(i) for i in кандидаты)))
                # Материал, у которого адрес так и остался на поисковике, в ленту не
                # берём: его ссылка ведёт на редирект или страницу согласия, а не на
                # публикацию. На живых данных 28.10.2026 такие записи дали ноль
                # обложек из тридцати шести, тогда как прямые ссылки — тринадцать
                # обложек из четырнадцати.
                кандидаты = [i for i in кандидаты
                             if not SEARCH_HOSTS.search(i.get("url") or "")]

            fresh = 0
            for it in кандидаты:
                when = it["publishedAt"]
                key = it["key"] or normalize_url(it["url"])
                text = f"{it['title']} {it.get('snippet') or ''}"
                hints = suggest_links(text, operators, players, regions)
                новость = MarketNews(
                    company_id=cid, source_id=src.id,
                    title=it["title"][:500], url=it["url"][:900], url_key=key,
                    snippet=it.get("snippet"),
                    # Имя издания — из ленты, из og:site_name или, на худой конец,
                    # из домена: прочерк в карточке не говорит читателю ничего.
                    source_name=(it.get("sourceName")
                                 or (urlparse(it["url"]).hostname or "").removeprefix("www.")
                                 or None),
                    image_url=(it.get("image") or None),
                    published_at=when, retrieved_at=now,
                    channel="search" if src.kind.startswith("search") else src.kind,
                    # Рубрика источника сильнее словаря: ленту заводят ради темы.
                    topic=src.default_topic or topic_of(text),
                    # Привязка источника сильнее словаря: лента оператора — его новости.
                    operator_id=src.operator_id or (
                        uuid.UUID(hints["operatorId"]) if hints.get("operatorId") else None),
                    player_id=src.player_id or (
                        uuid.UUID(hints["playerId"]) if hints.get("playerId") else None),
                    region=hints.get("region"),
                    suggested=hints or None, linked_by="auto",
                    raw={"guid": it.get("guid"), "rawTitle": it.get("raw_title"),
                         "feed": feed_url, "media": it.get("media") or "article"},
                )
                db.add(новость)
                # Идентификатор нужен сразу: упоминания пишутся той же сессией.
                await db.flush()
                # Состав участников материала — по нему строятся связи «кто с кем».
                for м in actors_in_text(text, operators, players, actors):
                    db.add(MarketNewsMention(
                        company_id=cid, news_id=новость.id, role=м["role"],
                        name=м["name"][:200], matched=(м["matched"] or "")[:200],
                        operator_id=uuid.UUID(м["operator_id"]) if м.get("operator_id") else None,
                        player_id=uuid.UUID(м["player_id"]) if м.get("player_id") else None,
                        actor_id=uuid.UUID(м["actor_id"]) if м.get("actor_id") else None,
                        linked_by="auto"))
                added += 1
                fresh += 1
            stat["added"] = fresh
            stat["seen"] = len(items)
            per_source_stat.append(stat)
    await db.commit()
    return {"added": added, "sources": per_source_stat, "sinceDays": since_days}


# ─────────────────── Участники рынка в тексте новости ───────────────────
#
# Маркетингу нужна не одна привязка «чья новость», а состав участников: рынок
# читается связями — завод и сеть в одном материале, сеть и ведомство, агрегатор
# и банк. Поэтому из текста достаются ВСЕ узнанные имена с их ролями.

# Ведомства и регуляторы: список конечный и меняется редко, поэтому он в коде —
# в отличие от производителей, которых ведёт человек в справочнике участников.
STATE_ACTORS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Минэнерго России", ("минэнерго",)),
    ("Минпромторг России", ("минпромторг",)),
    ("Минтранс России", ("минтранс",)),
    ("Минэкономразвития России", ("минэкономразвития",)),
    ("Правительство России", ("правительство рф", "правительство россии",
                              "кабмин", "постановление правительства")),
    ("ФАС России", ("фас россии", "антимонопольн")),
    ("Росстандарт", ("росстандарт",)),
    ("Ростехнадзор", ("ростехнадзор",)),
    ("Госдума", ("госдума", "государственная дума")),
    ("Правительство Москвы", ("правительство москвы", "дептранс", "мэр москвы")),
    ("Правительство Московской области", ("минэнерго подмосковья",
                                          "правительство подмосковья")),
)

# Слова, по которым в тексте узнаётся роль неизвестного пока участника. Нужны не
# для привязки, а для подсказки «заведите его в справочник»: производителей у нас
# в реестре нет вовсе, и первыми их именами делятся именно новости.
ROLE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("vendor", ("производител", "завод", "выпустил", "изготовител", "поставит оборудование",
                "отечественн", "импортозамещ", "локализац")),
    ("service", ("сервисн", "обслуживан", "монтаж", "подрядчик", "эксплуатирующ")),
    ("state", ("министерств", "ведомств", "правительств", "регулятор", "надзор")),
    ("utility", ("энергосбыт", "сетевая компания", "электросет", "энергосистем")),
)

# Класс игрока из реестра приложений → роль в раскладе рынка.
PLAYER_ROLE = {
    "зарядная сеть / агрегатор": "aggregator",
    "поиск АЗС": "aggregator",
    "сеть АЗС (своё приложение)": "aggregator",
    "топливный процессинг": "platform",
    "мойки и мультисервис": "other",
    "автопроизводитель": "automaker",
    "банк / финтех": "bank",
}


def _found(text: str, variants: Iterable[str]) -> str | None:
    """Нашлось ли имя целым словом. Подстрока ловит «Волт» внутри «вольтаж»."""
    for v in variants:
        if len(v) < 4:
            continue
        if re.search(rf"(?<![а-яa-z0-9]){re.escape(v)}(?![а-яa-z0-9])", text):
            return v
    return None


def actors_in_text(text: str, operators: list[Any], players: list[Any],
                   actors: list[Any]) -> list[dict[str, Any]]:
    """Все узнанные участники рынка с ролями — состав новости, а не одна привязка.

    Роль берётся из реестра, а не из текста: оператор остаётся оператором, даже
    если в материале он назван «компанией». Текст решает только одно — кто в нём
    присутствует.
    """
    t = (text or "").lower().replace("ё", "е")
    out: list[dict[str, Any]] = []
    видели: set[str] = set()

    def добавить(role: str, name: str, matched: str, **ids: Any) -> None:
        ключ = f"{role}:{name.lower()}"
        if ключ in видели:
            return
        видели.add(ключ)
        out.append({"role": role, "name": name, "matched": matched, **ids})

    for op in operators:
        v = _found(t, _name_variants(op.name) | _name_variants(op.short_name or ""))
        if v:
            добавить("platform" if getattr(op, "is_platform", False) else "operator",
                     op.name, v, operator_id=str(op.id))
    # Оператор, уже найденный по сети, не повторяется приложением: «РусГидро» и
    # «ЭЗС РусГидро» — одна компания в двух реестрах, и пара из них дала бы связь
    # с самой собой (замечание на живых данных 28.10.2026).
    свои_операторы = {m.get("operator_id") for m in out if m.get("operator_id")}
    for pl in players:
        if getattr(pl, "operator_id", None) and str(pl.operator_id) in свои_операторы:
            continue
        имя = pl.brand or pl.app
        v = _found(t, _name_variants(имя or "") | _name_variants(pl.developer or ""))
        if v:
            добавить(PLAYER_ROLE.get(pl.player_class or "", "aggregator"),
                     имя or pl.app, v, player_id=str(pl.id))
    # Участник справочника не дублирует реестр: компанию, уже найденную как сеть
    # или приложение, второй записью не заводим. Иначе «Мособлэнерго» приходит и
    # сетью, и энергетикой, а связь с ним удваивается (видно на живых данных
    # 28.10.2026). Справочник ведёт тех, кого в реестрах нет.
    из_реестров = {m["name"].lower().replace("ё", "е") for m in out}
    for ac in actors:
        имя = ac.name.lower().replace("ё", "е")
        if any(имя in r or r in имя for r in из_реестров):
            continue
        псевдонимы = set(ac.aliases or [])
        v = _found(t, _name_variants(ac.name) | {a.lower() for a in псевдонимы})
        if v:
            добавить(ac.kind, ac.name, v, actor_id=str(ac.id))
    for имя, варианты in STATE_ACTORS:
        v = _found(t, варианты)
        if v:
            добавить("state", имя, v)
    return out


def role_hint(text: str) -> str | None:
    """Какая роль звучит в тексте — подсказка для незаведённого участника."""
    t = (text or "").lower().replace("ё", "е")
    for role, words in ROLE_HINTS:
        if any(w in t for w in words):
            return role
    return None
