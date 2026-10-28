"""Разбор новостей рынка (app/services/market_news.py).

Проверяем то, что ломается на живых лентах: разный адрес одной новости, хвост
«— Издание» у поисковой ленты, мусорная тема при подходящем слове и подсказка
привязки, которая не должна становиться утверждением.

Прогон:  py -m pytest server/tests/test_market_news.py -q
"""
from __future__ import annotations

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services.market_news import (clean_title, normalize_url, parse_feed, relevant,
                                      site_query, suggest_links, title_key, topic_of)

# Фрагмент настоящего ответа поисковой ленты (28.10.2026): ссылка — редирект с
# меткой `?oc=5`, `guid` стабилен, издание дописано в заголовок.
SEARCH_XML = """<?xml version="1.0"?><rss version="2.0"><channel>
<item><title>Зарядные станции PUNKT E включены в «белые списки» - PUNKT E</title>
<link>https://news.google.com/rss/articles/CBMiABC?oc=5</link>
<guid isPermaLink="false">CBMiABC</guid>
<pubDate>Tue, 27 Oct 2026 07:00:00 GMT</pubDate>
<description>&lt;a href="https://news.google.com/rss/articles/CBMiABC?oc=5"&gt;Зарядные станции&lt;/a&gt;</description>
<source url="https://punkt-e.ru">PUNKT E</source></item>
<item><title>Без ссылки</title></item>
</channel></rss>"""

ATOM_XML = """<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
<entry><title>Росатом открыл станции в Северске</title>
<link href="https://example.ru/news/1"/>
<updated>2026-10-20T10:00:00Z</updated>
<summary>Открыты первые зарядные станции</summary></entry></feed>"""


def test_same_news_two_links_one_key():
    """Метка кампании, якорь и хвостовой слэш не делают новость второй."""
    a = normalize_url("https://www.example.ru/news/1/?utm_source=tg&utm_medium=post#top")
    b = normalize_url("http://example.ru/news/1")
    assert a == b == "https://example.ru/news/1"


def test_search_feed_item_is_parsed_whole():
    """Из элемента поисковой ленты нужны пять полей — и издание отрезано от заголовка."""
    items = parse_feed(SEARCH_XML)
    assert len(items) == 1, "элемент без ссылки — служебная запись, не новость"
    it = items[0]
    assert it["title"] == "Зарядные станции PUNKT E включены в «белые списки»"
    assert it["sourceName"] == "PUNKT E"
    assert it["publishedAt"] == datetime(2026, 10, 27, 7, 0, tzinfo=timezone.utc)
    # Ключ строится по стабильному guid, а не по ссылке с `?oc=5`.
    assert it["key"] == normalize_url("https://news.google.com/rss/articles/CBMiABC?oc=5")
    assert "<a href" not in (it["snippet"] or "")


def test_atom_feed_is_parsed_too():
    """Лента оператора может быть Atom — разбирается тем же кодом."""
    items = parse_feed(ATOM_XML)
    assert len(items) == 1
    assert items[0]["url"] == "https://example.ru/news/1"
    assert items[0]["publishedAt"].year == 2026


def test_broken_xml_is_not_an_exception():
    """Чужая лента отдаёт мусор — обход продолжается, а не падает."""
    assert parse_feed("<html>мы переехали</html>") == []
    assert parse_feed("") == []


def test_topic_tells_deal_from_opening():
    """Сделка важнее открытия: «купил бизнес Sitronics» — не новость о стройке."""
    assert topic_of("Punkt E купил бизнес Sitronics Electro") == "deal"
    assert topic_of("В Астрахани открыли восьмую станцию быстрой зарядки") == "opening"
    assert topic_of("Зарядка электромобилей может подорожать из-за тарифа") == "price"
    assert topic_of("Правительство утвердило требования к машино-местам") == "regulation"
    assert topic_of("Парус электро поставит отечественные инверторы") == "tech"
    assert topic_of("Пилот рассказал о поездке") == "other"


def test_phone_chargers_do_not_pass_as_market_news():
    """Широкая лента приносит «беспроводную зарядку телефона» — это не рынок ЭЗС."""
    assert relevant("Открыта новая зарядная станция для электромобилей", False)
    assert not relevant("Лучшая беспроводная зарядка телефона 2026", False)
    assert not relevant("Городские новости за неделю", False)
    # Товарные подборки: оба заголовка пришли с живой выдачи 28.10.2026 и прошли
    # фильтр по слову «зарядн», пока в стоп-словах не появились подборки.
    assert not relevant("Рейтинг Лучших Зарядных Станций - Для Дома и Улицы", False)
    assert not relevant("Топ-10 лучших зарядных станций для электромобилей в 2026 году", False)
    # Профильный источник проходит целиком: тема у него одна и она наша.
    assert relevant("Годовой отчёт компании", True)


def test_suggestion_is_a_hint_with_a_reason():
    """Подсказка привязки называет, по какому слову совпало, и не выдумывает регион."""
    ops = [SimpleNamespace(id="11111111-1111-1111-1111-111111111111",
                           name='ООО «Пункт Е»', short_name="PUNKT E")]
    players = [SimpleNamespace(id="22222222-2222-2222-2222-222222222222",
                               brand="Ситроникс", app="Sitronics Electro")]
    hint = suggest_links("PUNKT E включены в белые списки в Московской области",
                         ops, players, ["Московская область", "Забайкальский край"])
    assert hint["operatorId"] == "11111111-1111-1111-1111-111111111111"
    assert hint["matched"]
    assert hint["region"] == "Московская область"
    # Ничего не совпало — пустая подсказка, а не случайная компания.
    assert suggest_links("Обзор рынка электромобилей", ops, players, []) == {}


def test_player_matched_only_when_operator_did_not():
    """Оператор сильнее игрока: сеть важнее приложения, когда названы оба."""
    ops = [SimpleNamespace(id="1", name="Ситроникс Электро", short_name=None)]
    players = [SimpleNamespace(id="2", brand="Ситроникс", app="Sitronics")]
    hint = suggest_links("Ситроникс Электро объявил о сделке", ops, players, [])
    assert hint.get("operatorId") == "1" and "playerId" not in hint


def test_site_query_replaces_missing_operator_feed():
    """У оператора нет RSS — вместо парсинга его вёрстки берём его же домен в поиске."""
    assert site_query("https://www.punkt-e.ru/news/") == "site:punkt-e.ru"
    assert site_query(None, "Пункт Е") == '"Пункт Е" зарядная станция'
    assert site_query(None, None) is None


def test_reprints_share_one_title_key():
    """Один пресс-релиз у двух изданий — один ключ заголовка, а не два упоминания."""
    a = clean_title("Росатом открыл станции в Северске - ТАСС", "ТАСС")
    b = clean_title("Росатом открыл станции в Северске - Интерфакс", "Интерфакс")
    assert title_key(a) == title_key(b)


def test_выход_наружу_берётся_из_окружения_стека(monkeypatch):
    """Прокси не настраивается отдельно: стек уже держит его для Telegram.

    Со стенда `news.google.com` закрыт геоблокировкой, и без этого выхода обход
    возвращал бы пустую ленту при исправном коде.
    """
    from app.services import market_news as mn
    for name in ("MARKET_NEWS_PROXY", "HTTPS_PROXY", "https_proxy", "SECURITY_TG_PROXY"):
        monkeypatch.delenv(name, raising=False)
    assert mn.proxy() is None, "нет настройки — ходим напрямую"

    monkeypatch.setenv("SECURITY_TG_PROXY", "http://10.10.70.50:3128")
    assert mn.proxy() == "http://10.10.70.50:3128"
    # Своя настройка новостей сильнее общей: ей может понадобиться другой выход.
    monkeypatch.setenv("MARKET_NEWS_PROXY", "http://own:3128")
    assert mn.proxy() == "http://own:3128"


@pytest.mark.asyncio
async def test_прокси_подхватывает_только_упавшее_напрямую():
    """Прямой путь основной: падение прокси не должно гасить обход целиком."""
    import httpx
    from app.services.market_news import get_page

    def прямой(request: httpx.Request) -> httpx.Response:
        if "closed" in str(request.url):
            raise httpx.ConnectTimeout("геоблок", request=request)
        return httpx.Response(200, text="напрямую")

    def через_прокси(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="через прокси")

    async with httpx.AsyncClient(transport=httpx.MockTransport(прямой)) as direct, \
            httpx.AsyncClient(transport=httpx.MockTransport(через_прокси)) as proxied:
        открытый = await get_page("https://open.example.ru/rss", direct, proxied)
        assert открытый.text == "напрямую", "доступное напрямую через прокси не гоняем"
        закрытый = await get_page("https://closed.example.ru/rss", direct, proxied)
        assert закрытый.text == "через прокси"

        # Прокси нет вовсе — причина отказа доходит до карточки источника.
        with pytest.raises(httpx.ConnectTimeout):
            await get_page("https://closed.example.ru/rss", direct, None)
