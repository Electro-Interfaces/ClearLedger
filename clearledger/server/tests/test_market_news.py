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


@pytest.mark.asyncio
async def test_обогащение_раскрывает_издание_и_обложку():
    """Карточка ленты строится из того, что издание само показывает при репосте.

    Bing отдаёт ссылку через счётчик `apiclick.aspx`; без прохода по редиректу в
    карточке остался бы адрес поисковика, без og-разметки — пустая строка вместо
    лида и серое место вместо картинки.
    """
    import httpx
    from app.services.market_news import enrich

    СТРАНИЦА = """<html><head>
      <meta property="og:image" content="https://izdanie.ru/img/cover.jpg">
      <meta property="og:description" content="Станция открыта на трассе М-11">
      <meta property="og:site_name" content="Издание">
    </head><body>…</body></html>"""

    def транспорт(request: httpx.Request) -> httpx.Response:
        if "apiclick" in str(request.url):
            return httpx.Response(302, headers={"location": "https://izdanie.ru/news/1"})
        return httpx.Response(200, text=СТРАНИЦА)

    async with httpx.AsyncClient(transport=httpx.MockTransport(транспорт),
                                 follow_redirects=True) as c:
        it = {"title": "Открыта станция", "url": "http://www.bing.com/news/apiclick.aspx?x=1",
              "key": "k", "snippet": None, "sourceName": None, "publishedAt": None,
              "image": None, "media": "article"}
        out = await enrich(it, c)
    assert out["url"] == "https://izdanie.ru/news/1", "адрес издания, а не поисковика"
    assert out["image"] == "https://izdanie.ru/img/cover.jpg"
    assert out["snippet"] == "Станция открыта на трассе М-11"
    assert out["sourceName"] == "Издание"
    assert out["media"] == "article"


@pytest.mark.asyncio
async def test_видео_распознаётся_и_по_разметке_и_по_адресу():
    """Материал с видео помечается: в ленте у него значок, а не тихая картинка."""
    import httpx
    from app.services.market_news import enrich

    def видео_разметкой(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text='<meta property="og:video" content="https://v/1.mp4">')

    def видео_адресом(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><head></head></html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(видео_разметкой)) as c:
        it = await enrich({"title": "t", "url": "https://izdanie.ru/a", "key": "k",
                           "snippet": None, "sourceName": "И", "publishedAt": None,
                           "image": None, "media": "article"}, c)
        assert it["media"] == "video"
    async with httpx.AsyncClient(transport=httpx.MockTransport(видео_адресом)) as c:
        it = await enrich({"title": "t", "url": "https://www.m24.ru/videos/1", "key": "k",
                           "snippet": None, "sourceName": "И", "publishedAt": None,
                           "image": None, "media": "article"}, c)
        assert it["media"] == "video", "видеохостинг узнаётся по адресу"


@pytest.mark.asyncio
async def test_недоступная_страница_не_теряет_материал():
    """Обложка необязательна: материал попадает в ленту и без неё."""
    import httpx
    from app.services.market_news import enrich

    def падает(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("нет связи", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(падает)) as c:
        it = await enrich({"title": "Заголовок", "url": "https://izdanie.ru/a", "key": "k",
                           "snippet": "лид из ленты", "sourceName": "И", "publishedAt": None,
                           "image": None, "media": "article"}, c)
    assert it["title"] == "Заголовок" and it["snippet"] == "лид из ленты"
    assert it["image"] is None


def test_поисковая_лента_с_обложками_и_широкий_невод_это_разные_адреса():
    """Bing даёт прямые ссылки и обложки, Google — объём без адреса издания."""
    from app.services.market_news import search_url
    assert "bing.com/news/search" in search_url("зарядные станции")
    assert "format=RSS" in search_url("зарядные станции")
    assert "news.google.com" in search_url("зарядные станции", "search_wide")


def test_адрес_поисковика_не_считается_публикацией():
    """Ссылка, оставшаяся на поисковике, ведёт на редирект, а не на материал.

    На живых данных 28.10.2026 такие записи дали ноль обложек из тридцати шести,
    прямые ссылки — тринадцать из четырнадцати.
    """
    from app.services.market_news import SEARCH_HOSTS
    assert SEARCH_HOSTS.search("https://news.google.com/rss/articles/CBMiABC?oc=5")
    assert SEARCH_HOSTS.search("http://www.bing.com/news/apiclick.aspx?ref=FexRss")
    assert SEARCH_HOSTS.search("https://consent.google.com/ml?continue=x")
    assert not SEARCH_HOSTS.search("https://www.tadviser.ru/index.php/Продукты")


def test_зарядка_геймпада_не_новость_рынка():
    """«Зарядная станция» бывает и для консоли — слово то же, рынок другой.

    28.10.2026 в живую ленту приехала док-станция 8BitDo: словарь пропустил её
    по слову «зарядн».
    """
    from app.services.market_news import relevant
    assert not relevant("Зарядная станция Ultimate Charging Dock от 8BitDo для геймпадов", False)
    assert not relevant("Лучшая зарядная станция для телефона и наушников", False)
    assert relevant("В Северске открыли две электрозарядные станции", False)
    assert relevant("Зарядные станции PUNKT E включены в белые списки электромобилей", False)


def test_двойное_экранирование_раскрывается_до_текста():
    """В карточке должны быть кавычки, а не «&#34;».

    Лента «Российской газеты» 28.10.2026 экранирует описание дважды, и один
    проход декодирования оставлял сущности прямо в тексте новости.
    """
    from app.services.market_news import parse_feed
    xml = ("""<rss><channel><item><title>Заряд</title>"""
           """<link>https://rg.ru/a</link>"""
           """<description>Владельцы &amp;#34;электричек&amp;#34; могут &amp;amp; дальше</description>"""
           """</item></channel></rss>""")
    it = parse_feed(xml)[0]
    assert '"электричек"' in it["snippet"]
    assert "&#34;" not in it["snippet"] and "&amp;" not in it["snippet"]


def test_регион_подставляется_только_со_словом_уровня():
    """Справочник пространства держит и мусор — «Большой», «Казань», «12».

    Без слова-указателя «Большой» ловился в любом тексте и подписывал новость
    чужим регионом (замечание МАГа 28.10.2026).
    """
    from app.services.market_news import suggest_links
    регионы = ["Большой", "Казань", "12", "Амурская", "Московская"]
    текст = "Белорусы могут заряжать электрички в РФ через большой сервис приложений"
    assert "region" not in suggest_links(текст, [], [], регионы)
    assert suggest_links("В Амурской области открыли станцию", [], [], регионы)["region"] == "Амурская"
    assert suggest_links("Станция в Московской области", [], [], регионы)["region"] == "Московская"


def test_состав_участников_а_не_одна_привязка():
    """Рынок читается связями: в материале бывает и завод, и сеть, и ведомство.

    Роль берётся из реестра, а не из текста: оператор остаётся оператором, даже
    если в новости он назван «компанией».
    """
    from types import SimpleNamespace as N
    from app.services.market_news import actors_in_text
    ops = [N(id="1", name="Ситроникс Электро", short_name="Sitronics", is_platform=False),
           N(id="2", name="ItCharge", short_name=None, is_platform=True)]
    pls = [N(id="3", brand="Яндекс Заправки", app="Яндекс Заправки", developer="Яндекс",
             player_class="зарядная сеть / агрегатор"),
           N(id="4", brand="Атом", app="Атом", developer="Кама", player_class="автопроизводитель")]
    acs = [N(id="5", kind="vendor", name="Парус электро", aliases=["парус-электро"])]

    состав = actors_in_text(
        "«Парус электро» поставит инверторы сети Ситроникс Электро, сообщили в Минэнерго",
        ops, pls, acs)
    роли = {m["role"]: m["name"] for m in состав}
    assert роли["vendor"] == "Парус электро"
    assert роли["operator"] == "Ситроникс Электро"
    assert роли["state"] == "Минэнерго России"
    assert all(m["matched"] for m in состав), "по какому написанию узнали — обязательно"

    # Платформа отличается от сети: разговор с ней идёт про протоколы, а не про тариф.
    только_платформа = actors_in_text("Станции работают на системе ItCharge", ops, pls, acs)
    assert только_платформа[0]["role"] == "platform"

    # Класс приложения задаёт роль игрока.
    авто = actors_in_text("Электромобиль Атом получил новую зарядку", ops, pls, acs)
    assert авто[0]["role"] == "automaker"


def test_имя_узнаётся_целым_словом():
    """Подстрока ловит «Волт» внутри «вольтаж» и подписывает новость чужой сетью."""
    from types import SimpleNamespace as N
    from app.services.market_news import actors_in_text
    ops = [N(id="1", name="Волт", short_name=None, is_platform=False)]
    assert actors_in_text("Измеряется вольтаж аккумулятора", ops, [], []) == []
    assert actors_in_text("Сеть «Волт» открыла станцию", ops, [], [])[0]["name"] == "Волт"


def test_псевдоним_справочника_работает_как_имя():
    """«Парус-электро» и «Парус электро» — одна компания, иначе связь распадётся."""
    from types import SimpleNamespace as N
    from app.services.market_news import actors_in_text
    acs = [N(id="5", kind="vendor", name="Парус электро",
             aliases=["парус-электро", "parus electro"])]
    for написание in ("Парус-электро выпустил", "Компания Parus Electro представила"):
        найдено = actors_in_text(написание, [], [], acs)
        assert найдено and найдено[0]["name"] == "Парус электро"


def test_одна_компания_в_двух_реестрах_не_двое():
    """«РусГидро» (сеть) и «ЭЗС РусГидро» (приложение) — один участник.

    Иначе разрез показывает связь компании с самой собой — это и случилось на
    живых данных 28.10.2026.
    """
    from types import SimpleNamespace as N
    from app.services.market_news import actors_in_text
    ops = [N(id="10", name="РусГидро", short_name=None, is_platform=False)]
    pls = [N(id="11", brand="ЭЗС РусГидро", app="ЭЗС РусГидро", developer=None,
             operator_id="10", player_class="зарядная сеть / агрегатор")]
    состав = actors_in_text("РусГидро открыла станции, приложение ЭЗС РусГидро обновилось",
                            ops, pls, [])
    assert [m["role"] for m in состав] == ["operator"], "приложение той же сети — не второй участник"

    # Независимый агрегатор остаётся отдельным участником.
    чужой = [N(id="12", brand="Яндекс Заправки", app="Яндекс Заправки", developer="Яндекс",
               operator_id=None, player_class="зарядная сеть / агрегатор")]
    пара = actors_in_text("РусГидро и Яндекс Заправки договорились", ops, чужой, [])
    assert {m["role"] for m in пара} == {"operator", "aggregator"}
