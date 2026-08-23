"""Единый список работы: документы и поручения одной лентой.

Ловим то, что молча ломается при объединении двух контуров: предмет теряется по
дороге (union собран не по тем колонкам); состояние в отборе расходится с
состоянием в карточке (два выражения одного правила — SQL и Python); чужая
закрытая работа видна в общем списке, потому что применили правила только одного
контура.
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _me(client: AsyncClient) -> dict:
    r = await client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()


async def test_работа_показывается_одной_лентой(auth_client: AsyncClient):
    me = await _me(auth_client)
    cid = me["companies"][0]["id"]

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
    cid = me["companies"][0]["id"]

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
    cid = me["companies"][0]["id"]

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
