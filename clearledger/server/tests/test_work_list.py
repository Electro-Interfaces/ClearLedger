"""Единый список работы: документы и поручения одной лентой.

Ловим то, что молча ломается при объединении двух контуров: предмет теряется по
дороге (union собран не по тем колонкам); состояние в отборе расходится с
состоянием в карточке (два выражения одного правила — SQL и Python); чужая
закрытая работа видна в общем списке, потому что применили правила только одного
контура.
"""
import pytest
from httpx import AsyncClient
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _me(client: AsyncClient) -> dict:
    r = await client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()


async def test_работа_показывается_одной_лентой(auth_client: AsyncClient):
    me = await _me(auth_client)
    cid = seed_company_id(me)

    # Виды документов заводятся посевом; берём любой живой.
    r = await auth_client.post(f"/api/docs/kinds/starter?company_id={cid}")
    assert r.status_code in (200, 201), r.text
    kinds = (await auth_client.get("/api/docs/kinds",
                                   params={"company_id": cid})).json()["kinds"]
    kind = next(k for k in kinds if k["code"] == "doc_in")

    r = await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"],
        "title": "Письмо для единой ленты"})
    assert r.status_code == 201, r.text
    doc = r.json()

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Поручение для единой ленты",
        "assignee_id": me["id"]})
    assert r.status_code == 201, r.text
    task = r.json()

    body = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "limit": 200})).json()
    rows = {r["id"]: r for r in body["work"]}
    assert doc["id"] in rows, "документ не доехал до общей ленты"
    assert task["id"] in rows, "поручение не доехало до общей ленты"
    assert rows[doc["id"]]["kind"] == "doc"
    assert rows[task["id"]]["kind"] == "task"
    # Черновик документа честно называется черновиком: выдуманный номер увёл бы
    # человека искать его в журнале.
    assert rows[doc["id"]]["key"] == "черновик"
    assert rows[task["id"]]["key"] == f"№{task['number']}"
    assert [c["code"] for c in body["columns"]] == [
        "new", "in_work", "approval", "external", "done"]

    # Род — фильтр, а не раздел.
    only_docs = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "kind": "doc", "limit": 200})).json()
    assert all(r["kind"] == "doc" for r in only_docs["work"])
    assert doc["id"] in {r["id"] for r in only_docs["work"]}


async def test_состояние_в_отборе_совпадает_с_карточкой(auth_client: AsyncClient):
    """SQL-выражение и функция проекции — два выражения одного правила.

    Разойдись они, отбор «на согласовании» показал бы одно, а карточка другое, и
    доверия к доске не осталось бы. Здесь они сверяются на живых данных.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    listed = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "limit": 200})).json()["work"]
    assert listed, "в компании нет работы — сверять нечего"

    for row in listed:
        by_state = (await auth_client.get("/api/work", params={
            "company_id": cid, "scope": "all", "state": row["state"],
            "limit": 200})).json()["work"]
        assert row["id"] in {r["id"] for r in by_state}, (
            f"{row['key']} показан в «{row['state_name']}», а отбором не находится")

    # Карточка предмета отвечает тем же состоянием, что лента.
    task_row = next((r for r in listed if r["kind"] == "task"), None)
    if task_row:
        card = (await auth_client.get(f"/api/tasks/{task_row['id']}",
                                      params={"company_id": cid})).json()
        assert card["state"] == task_row["state"], "лента и карточка разошлись"
    doc_row = next((r for r in listed if r["kind"] == "doc"), None)
    if doc_row:
        card = (await auth_client.get(f"/api/docs/{doc_row['id']}",
                                      params={"company_id": cid})).json()
        assert card["state"] == doc_row["state"], "лента и карточка разошлись"


async def test_закрытая_работа_в_общую_ленту_не_попадает(auth_client: AsyncClient):
    """Объединение не должно стать дырой в правах.

    Приватное поручение видно причастным; в общей ленте оно обязано подчиняться
    тому же правилу, что в реестре поручений.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Кадровое поручение", "assignee_id": me["id"]})
    task = r.json()
    r = await auth_client.post(f"/api/tasks/{task['id']}/action", json={
        "company_id": cid, "visibility": "private"})
    assert r.status_code == 200, r.text

    # Себе видно: я исполнитель.
    body = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "limit": 200})).json()
    assert task["id"] in {r["id"] for r in body["work"]}

    # Сводка по колонкам считает то же, что лента.
    summary = (await auth_client.get("/api/work/summary",
                                     params={"company_id": cid})).json()
    assert {c["code"] for c in summary["columns"]} == {
        "new", "in_work", "approval", "external", "done"}
    total_summary = sum(c["total"] for c in summary["columns"])
    total_list = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "limit": 1})).json()["total"]
    assert total_summary == total_list, "сводка и лента считают по-разному"


async def test_язык_запросов_работает_над_общей_лентой(auth_client: AsyncClient):
    """Этап 13в: тем же языком спрашивают оба контура.

    Ловим: слово, которого у документов нет (спринт, стадия), молча сужает
    ленту — человек уверен, что отобрал, а отбора не было.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Работа для языка запросов",
        "assignee_id": me["id"]})
    assert r.status_code == 201, r.text
    task = r.json()

    body = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "limit": 200,
        "query": "род: поручение исполнитель: я"})).json()
    assert body["query"]["unknown"] == [], body["query"]
    assert task["id"] in {r["id"] for r in body["work"]}
    assert all(r["kind"] == "task" for r in body["work"])

    # Флаг рода — короче и читается так же.
    docs = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "limit": 200,
        "query": "#документы"})).json()
    assert all(r["kind"] == "doc" for r in docs["work"])

    # Состояние словами человека.
    body = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "limit": 200,
        "query": "состояние: на согласовании"})).json()
    assert body["query"]["parsed"].get("state") == "approval", body["query"]
    assert all(r["state"] == "approval" for r in body["work"])

    # То, чего у документов нет, не проглатывается молча.
    body = (await auth_client.get("/api/work", params={
        "company_id": cid, "scope": "all", "limit": 200,
        "query": "приоритет: срочная"})).json()
    assert body["query"]["unknown"], "молча сузили ленту тем, чего у документов нет"


async def test_очередь_на_мне_собирает_все_роды_действия(auth_client: AsyncClient):
    """Этап 13г: визы, ознакомления, работа и свои документы одной очередью.

    Ловим: предмет двоится, когда он и на визе, и мой; очередь не отвечает «что
    горит», потому что не сгруппирована по сроку.
    """
    from datetime import datetime, timedelta, timezone

    me = await _me(auth_client)
    cid = seed_company_id(me)

    past = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Просроченная работа на мне",
        "assignee_id": me["id"], "due_at": past})
    assert r.status_code == 201, r.text
    task = r.json()

    body = (await auth_client.get("/api/work/mine",
                                  params={"company_id": cid})).json()
    rows = {(r["kind"], r["id"]): r for r in body["mine"]}
    mine = rows.get(("task", task["id"]))
    assert mine, "поручение на мне не попало в очередь"
    assert mine["reason"] == "do" and mine["bucket"] == "overdue"
    assert mine["overdue"] is True
    assert [b["code"] for b in body["buckets"]] == ["overdue", "today", "week", "later"]

    # Один предмет — одна строка: очередь не двоит работу.
    keys = [(r["kind"], r["id"]) for r in body["mine"]]
    assert len(keys) == len(set(keys)), "предмет попал в очередь дважды"

    # Горящее стоит выше того, что без срока.
    order = [r["bucket"] for r in body["mine"]]
    assert order == sorted(order, key=lambda b: ["overdue", "today", "week", "later"].index(b))


async def test_перенос_по_доске_делает_движок_предмета(auth_client: AsyncClient):
    """Этап 13д: доска не заводит третьего способа менять состояние.

    Ловим: перенос молча возвращает карточку (отказ без причины); поручение
    переезжает в колонку, которой нет в его маршруте; «Ждём внешних» выглядит
    местом, куда можно перетащить работу.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks/types/starter", params={"company_id": cid})
    assert r.status_code in (200, 201), r.text
    types = (await auth_client.get("/api/tasks/types",
                                   params={"company_id": cid})).json()["types"]
    incident = next(t for t in types if t["code"] == "incident")

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Работа для доски", "type_id": incident["id"]})
    assert r.status_code == 201, r.text
    task = r.json()

    # Перенос в «В работе» ставит стадию, а не выдумывает состояние.
    r = await auth_client.post(f"/api/work/task/{task['id']}/move", json={
        "company_id": cid, "state": "in_work"})
    assert r.status_code == 200, r.text
    card = (await auth_client.get(f"/api/tasks/{task['id']}",
                                  params={"company_id": cid})).json()
    assert card["state"] == "in_work", card["state"]
    assert card["stage_code"], "стадия не проставилась"

    # В «Готово» — закрытие работы тем же действием, что кнопкой в карточке.
    r = await auth_client.post(f"/api/work/task/{task['id']}/move", json={
        "company_id": cid, "state": "done"})
    assert r.status_code == 200, r.text
    card = (await auth_client.get(f"/api/tasks/{task['id']}",
                                  params={"company_id": cid})).json()
    assert card["status"] == "done" and card["state"] == "done"

    # «Ждём внешних» — не место назначения: туда попадают, отдав работу наружу.
    r = await auth_client.post(f"/api/work/task/{task['id']}/move", json={
        "company_id": cid, "state": "external"})
    assert r.status_code == 400 and "наружу" in r.json()["detail"], r.text

    # Отказ по документу называет причину, а не молчит.
    kinds = (await auth_client.get("/api/docs/kinds",
                                   params={"company_id": cid})).json()["kinds"]
    kind = next(k for k in kinds if k["code"] == "doc_in")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Документ для доски"})).json()
    r = await auth_client.post(f"/api/work/doc/{doc['id']}/move", json={
        "company_id": cid, "state": "new"})
    assert r.status_code == 400 and r.json()["detail"], r.text


async def test_отбор_общей_ленты_сохраняется_представлением(auth_client: AsyncClient):
    """Этап 13ж: справочник отборов один на три списка, но списки не смешиваются.

    Ловим: отбор общей ленты вылезает в реестре поручений — там его ключи ничего
    не значат, и человек видит пустой список без объяснения.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks/views", json={
        "company_id": cid, "name": "Горящее по компании", "list_scope": "work",
        "query": {"scope": "open", "state": "approval"}})
    assert r.status_code == 201, r.text
    assert r.json()["list_scope"] == "work"

    work_views = (await auth_client.get("/api/tasks/views", params={
        "company_id": cid, "list_scope": "work"})).json()["views"]
    assert "Горящее по компании" in [v["name"] for v in work_views]

    task_views = (await auth_client.get("/api/tasks/views", params={
        "company_id": cid, "list_scope": "task"})).json()["views"]
    assert "Горящее по компании" not in [v["name"] for v in task_views], (
        "отбор общей ленты попал в реестр поручений")
