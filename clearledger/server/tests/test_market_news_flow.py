"""Конвейер новостей рынка: обход источника, дедупликация, разбор и лента.

Лента наружу здесь не ходит: `fetch_feed` подменяется, потому что проверяется НАШ
конвейер, а не доступность чужого сервиса. Доступность проверяется отдельно, живым
обращением к источнику.

Держим ровно то, что ломается на живых источниках:
  * один и тот же материал во втором обходе не становится второй новостью;
  * материал старше окна не попадает в очередь (поисковая лента охотно отдаёт
    архив двухлетней давности по тому же запросу);
  * привязка источника сильнее словаря: лента оператора — его новости;
  * отказ источника записывается в его карточку, а обход продолжается;
  * «шум» убирает материал из ленты, но не из базы — его можно вернуть.

Прогон:  py -m pytest server/tests/test_market_news_flow.py -q
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.models import Company, MarketOperator
from app.services import market_news


def материал(num: int, when: datetime, title: str | None = None) -> dict:
    return {
        "title": title or f"В Чите открыли зарядную станцию номер {num}",
        "raw_title": title or f"В Чите открыли зарядную станцию номер {num}",
        "url": f"https://example.ru/news/{num}?utm_source=tg",
        "key": market_news.normalize_url(f"https://example.ru/news/{num}"),
        "guid": f"guid-{num}",
        "sourceName": "Пример",
        "publishedAt": when,
        "snippet": "Станция для электромобилей запущена в эксплуатацию",
    }


@pytest.mark.asyncio(loop_scope="session")
async def test_обход_дедупликация_разбор_и_лента(auth_client, db, monkeypatch):
    cid = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    оператор = MarketOperator(company_id=cid, name="QA Новости Оператор",
                              relation="competitor", site_url="https://qa-news-operator.ru")
    db.add(оператор)
    await db.commit()
    общий = {"company_id": str(cid)}

    # Источник оператора: его публикации принадлежат ему независимо от словаря.
    создан = await auth_client.post("/api/market/news/sources", params=общий, json={
        "title": "QA Новости Оператор — пресс-релизы",
        "kind": "search", "url": "site:qa-news-operator.ru",
        "operator_id": str(оператор.id),
    })
    assert создан.status_code == 201, создан.text
    source_id = создан.json()["id"]

    # Тот же источник второй раз — отказ с понятной причиной, а не второй обход.
    assert (await auth_client.post("/api/market/news/sources", params=общий, json={
        "title": "он же", "kind": "search", "url": "site:qa-news-operator.ru",
    })).status_code == 409

    свежий = datetime.now(timezone.utc) - timedelta(days=2)
    старый = datetime.now(timezone.utc) - timedelta(days=400)

    async def лента(url, client, proxied=None):  # noqa: ARG001 — подпись как у настоящей
        return [материал(1, свежий), материал(2, свежий), материал(3, старый)]

    monkeypatch.setattr(market_news, "fetch_feed", лента)

    первый = await auth_client.post("/api/market/news/fetch",
                                    params={**общий, "since_days": 14})
    assert первый.status_code == 200, первый.text
    assert первый.json()["added"] == 2, "материал старше окна в очередь не попадает"

    # Повторный обход того же источника не плодит повторов.
    второй = await auth_client.post("/api/market/news/fetch",
                                    params={**общий, "since_days": 14})
    assert второй.json()["added"] == 0

    очередь = await auth_client.get("/api/market/news",
                                    params={**общий, "status": "new"})
    assert очередь.status_code == 200, очередь.text
    строки = [n for n in очередь.json()["news"] if n["sourceId"] == source_id]
    assert len(строки) == 2
    n1 = строки[0]
    assert n1["operatorName"] == "QA Новости Оператор", "привязка источника сильнее словаря"
    assert n1["topic"] == "opening"
    assert n1["channel"] == "search"
    assert n1["url"].startswith("https://example.ru/news/")
    assert n1["publishedAt"], "дата публикации источника сохранена, а не подменена датой обхода"

    # Разбор: одну отобрать, другую отбросить.
    assert (await auth_client.patch(f"/api/market/news/{n1['id']}", params=общий,
                                    json={"status": "kept"})).status_code == 200
    шум = строки[1]
    assert (await auth_client.patch(f"/api/market/news/{шум['id']}", params=общий,
                                    json={"status": "noise"})).status_code == 200

    лента_ответ = (await auth_client.get("/api/market/news",
                                         params={**общий, "status": "feed"})).json()
    ид = {n["id"] for n in лента_ответ["news"]}
    assert n1["id"] in ид and шум["id"] not in ид, "шум не показывается в ленте"
    assert лента_ответ["counts"]["noise"] >= 1

    # Шум остаётся в базе и возвращается в разбор: ошибочное «мимо» обратимо.
    assert (await auth_client.patch(f"/api/market/news/{шум['id']}", params=общий,
                                    json={"status": "new"})).status_code == 200
    снова = (await auth_client.get("/api/market/news", params={**общий, "status": "new"})).json()
    assert шум["id"] in {n["id"] for n in снова["news"]}

    # Отбор по оператору: лента оператора в его карточке.
    по_оператору = (await auth_client.get("/api/market/news", params={
        **общий, "operator_id": str(оператор.id)})).json()
    assert по_оператору["total"] >= 2


@pytest.mark.asyncio(loop_scope="session")
async def test_отказ_источника_попадает_в_его_карточку(auth_client, db, monkeypatch):
    """Лента не ответила — это факт карточки, а не упавший обход."""
    cid = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    общий = {"company_id": str(cid)}
    создан = await auth_client.post("/api/market/news/sources", params=общий, json={
        "title": "QA мёртвая лента", "kind": "rss",
        "url": "https://qa-dead-feed.example.ru/rss",
    })
    assert создан.status_code == 201, создан.text
    sid = создан.json()["id"]

    async def падение(url, client, proxied=None):  # noqa: ARG001
        raise RuntimeError("504 Gateway Timeout")

    monkeypatch.setattr(market_news, "fetch_feed", падение)
    ответ = await auth_client.post("/api/market/news/fetch",
                                   params={**общий, "source_id": sid})
    assert ответ.status_code == 200, ответ.text
    свой = [s for s in ответ.json()["sources"] if s["id"] == sid]
    assert свой and "504" in свой[0]["error"]

    карточки = (await auth_client.get("/api/market/news/sources", params=общий)).json()
    карточка = next(s for s in карточки["sources"] if s["id"] == sid)
    assert "504" in (карточка["lastError"] or "")
    assert карточка["lastRunAt"], "попытка отмечена"
    assert карточка["lastOkAt"] is None, "неудачный обход не считается ответом источника"


@pytest.mark.asyncio(loop_scope="session")
async def test_внутренний_адрес_источником_не_принимается(auth_client, db):
    """Адрес ленты вводит человек, а ходит по нему бэкенд изнутри стека."""
    cid = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    ответ = await auth_client.post("/api/market/news/sources",
                                   params={"company_id": str(cid)},
                                   json={"title": "сосед по стеку", "kind": "rss",
                                         "url": "http://postgres:5432/rss"})
    assert ответ.status_code == 400, ответ.text


@pytest.mark.asyncio(loop_scope="session")
async def test_руками_добавленная_новость_сразу_в_ленте(auth_client, db):
    """Человек её уже прочитал — своя же очередь разбора ей не нужна."""
    cid = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    общий = {"company_id": str(cid)}
    ответ = await auth_client.post("/api/market/news", params=общий, json={
        "title": "Partner E купил сеть QA Charge",
        "url": "https://example.ru/qa-deal?utm_medium=tg",
    })
    assert ответ.status_code == 201, ответ.text
    # Повтор той же ссылки с другой меткой кампании — не вторая новость.
    assert (await auth_client.post("/api/market/news", params=общий, json={
        "title": "он же", "url": "https://example.ru/qa-deal"})).status_code == 409

    лента = (await auth_client.get("/api/market/news", params={**общий, "status": "kept"})).json()
    своя = next(n for n in лента["news"] if n["id"] == ответ.json()["id"])
    assert своя["channel"] == "manual" and своя["status"] == "kept"
    assert своя["topic"] == "deal", "тема определена по заголовку, когда её не задали"
    assert своя["author"], "у ручной записи виден автор"


@pytest.mark.asyncio(loop_scope="session")
async def test_базовый_набор_берёт_компании_из_реестра(auth_client, db):
    """Набор не выдуман в коде: сайты сетей берутся из реестра операторов.

    Общие запросы по событиям рынка — наши, а компании те, что уже ведутся в
    продукте. Повторный вызов не плодит повторов: источник уникален по адресу.
    """
    cid = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    db.add(MarketOperator(company_id=cid, name="QA Набор Сеть", relation="competitor",
                          site_url="https://qa-preset-net.example.ru/about", points_total=500))
    await db.commit()
    общий = {"company_id": str(cid)}

    первый = await auth_client.post("/api/market/news/sources/preset", params=общий)
    assert первый.status_code == 200, первый.text
    assert первый.json()["added"] >= 6, "общие запросы плюс компании реестра"

    второй = await auth_client.post("/api/market/news/sources/preset", params=общий)
    assert второй.json()["added"] == 0, "повторный вызов добавляет только отсутствующее"

    список = (await auth_client.get("/api/market/news/sources", params=общий)).json()["sources"]
    по_домену = [s for s in список if s["url"] == "site:qa-preset-net.example.ru"]
    assert по_домену, "сайт сети из реестра стал источником"
    assert по_домену[0]["operatorName"] == "QA Набор Сеть"
    assert any(s["url"] == "зарядная станция электромобиля открыли" for s in список), \
        "общий невод по событиям рынка тоже поставлен"


@pytest.mark.asyncio(loop_scope="session")
async def test_обход_берёт_порцию_и_говорит_об_остатке(auth_client, db, monkeypatch):
    """Кнопка «Обновить» не должна упираться в таймаут кромки.

    28.10.2026 обход всех источников шёл последовательно одним запросом, и на
    трёх десятках лент человек получал «Bad Gateway» вместо новостей. Теперь за
    вызов берётся порция, а ответ говорит, сколько осталось.
    """
    cid = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    общий = {"company_id": str(cid)}
    for i in range(5):
        r = await auth_client.post("/api/market/news/sources", params=общий, json={
            "title": f"QA порция {i}", "kind": "search", "url": f"порция запрос {i}"})
        assert r.status_code == 201, r.text

    async def пусто(url, client, proxied=None):  # noqa: ARG001
        return []

    monkeypatch.setattr(market_news, "fetch_feed", пусто)
    ответ = await auth_client.post("/api/market/news/fetch",
                                    params={**общий, "limit_sources": 2})
    assert ответ.status_code == 200, ответ.text
    d = ответ.json()
    assert len(d["sources"]) == 2, "за вызов обходим только порцию"
    assert d["pending"] >= 3, "остаток назван, чтобы человек нажал ещё раз"

    # Следующий вызов берёт ДРУГИХ: первыми идут те, кого дольше не обходили.
    первые = {s["id"] for s in d["sources"]}
    второй = (await auth_client.post("/api/market/news/fetch",
                                     params={**общий, "limit_sources": 2})).json()
    assert не_пересекаются(первые, {s["id"] for s in второй["sources"]})


def не_пересекаются(a: set[str], b: set[str]) -> bool:
    return not (a & b)


@pytest.mark.asyncio(loop_scope="session")
async def test_колонка_доезжает_на_таблицу_созданную_раньше(db):
    """`create_all` не добавляет колонки в готовую таблицу — это делает миграция.

    28.10.2026 источники завелись утренней выкаткой, а рубрика у них появилась
    вечерней: на стенде таблица уже существовала, колонки `default_topic` в ней
    не было, и обход падал с `UndefinedColumnError` при живом коде и зелёных
    тестах. Тест повторяет именно эту последовательность: старая таблица →
    миграция → колонка на месте.
    """
    from sqlalchemy import text
    from app.database import MARKET_NEWS_MIGRATION_DDL

    await db.execute(text("DROP TABLE IF EXISTS qa_news_sources_old"))
    await db.execute(text(
        "CREATE TABLE qa_news_sources_old (id uuid PRIMARY KEY, kind VARCHAR(10))"))
    # Миграция написана по именам рабочих таблиц; на копии проверяем её форму:
    # ADD COLUMN IF NOT EXISTS и расширение типа обязаны быть идемпотентны.
    for stmt in MARKET_NEWS_MIGRATION_DDL:
        проба = (stmt.replace("market_news_sources", "qa_news_sources_old")
                     .replace("market_news ", "qa_news_sources_old "))
        await db.execute(text(проба))
        await db.execute(text(проба))  # повтор: миграция гоняется при каждом старте
    колонки = {r[0] for r in (await db.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = 'qa_news_sources_old'"))).all()}
    длина = (await db.execute(text(
        "SELECT character_maximum_length FROM information_schema.columns "
        "WHERE table_name = 'qa_news_sources_old' AND column_name = 'kind'"))).scalar()
    await db.execute(text("DROP TABLE qa_news_sources_old"))
    await db.commit()

    assert "default_topic" in колонки, "рубрика источника не доезжает на старую таблицу"
    assert длина == 12, "вид источника `search_wide` не влезает в прежний VARCHAR(10)"


def test_миграция_новостей_перечислена_в_старте():
    """Набор DDL бесполезен, пока его никто не выполняет при старте приложения."""
    from pathlib import Path
    текст = Path("app/database.py").read_text(encoding="utf-8")
    assert "for stmt in MARKET_NEWS_MIGRATION_DDL:" in текст
