"""Движок «Задач»: маршрут, переадресация, завершение и след.

Ловим то, что молча ломается: задача уходит на стадию, которой нет в маршруте
её типа; переадресация не попадает в след (и работа выглядит перепрыгнувшей к
другому человеку сама); реплика к действию задваивается в ленте.
"""
import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _me(client: AsyncClient) -> dict:
    """Компанию берём СВОЮ, а не первую из каталога: переадресация проверяет
    членство, а сид-суперадмин состоит ровно в одной компании."""
    r = await client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    me = r.json()
    assert me["companies"], "сид-суперадмин не состоит ни в одной компании"
    return me


async def test_задача_идёт_по_маршруту_типа(auth_client: AsyncClient):
    me = await _me(auth_client)
    cid = me["companies"][0]["id"]

    # Заготовки типов — идемпотентно: повторный вызов не плодит дублей.
    r = await auth_client.post(f"/api/tasks/types/starter?company_id={cid}")
    assert r.status_code == 201, r.text
    r = await auth_client.post(f"/api/tasks/types/starter?company_id={cid}")
    assert r.json()["added"] == 0, "заготовки завелись повторно"

    types = (await auth_client.get("/api/tasks/types", params={"company_id": cid})).json()["types"]
    incident = next(t for t in types if t["code"] == "incident")
    assert [s["code"] for s in incident["route"]] == ["reg", "diag", "fix", "check"]

    # Постановка: маршрут и срочность приходят от типа, стадия — первая в маршруте.
    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Проверка движка задач", "type_id": incident["id"],
    })
    assert r.status_code == 201, r.text
    task = r.json()
    assert task["stage_code"] == "reg"
    assert task["priority"] == "high", "срочность типа не применилась"
    assert task["due_at"], "срок по due_days типа не проставился"
    tid = task["id"]

    # Движение по маршруту.
    r = await auth_client.post(f"/api/tasks/{tid}/action", json={
        "company_id": cid, "stage_code": "diag", "note": "Смотрю логи",
    })
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "Диагностика"

    # Стадия чужого маршрута не принимается: иначе задача встаёт в состояние,
    # которого нет ни в одном списке, и исчезает из работы.
    r = await auth_client.post(f"/api/tasks/{tid}/action", json={
        "company_id": cid, "stage_code": "approve",
    })
    assert r.status_code == 400, "стадия вне маршрута прошла"

    # Переадресация: событие обязано попасть в след, иначе работа выглядит
    # перепрыгнувшей к другому человеку сама собой.
    r = await auth_client.post(f"/api/tasks/{tid}/action", json={
        "company_id": cid, "assignee_id": me["id"],
    })
    assert r.status_code == 200, r.text
    assert r.json()["assignee_id"] == me["id"]

    # Завершение.
    r = await auth_client.post(f"/api/tasks/{tid}/action", json={
        "company_id": cid, "status": "done", "note": "Устранено",
    })
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "done"
    assert r.json()["closed_at"]

    card = (await auth_client.get(f"/api/tasks/{tid}", params={"company_id": cid})).json()
    kinds = [e["kind"] for e in card["events"]]
    assert kinds == ["created", "stage", "assign", "status"], kinds
    # Реплика при действии прицеплена к событию, а не продублирована комментарием.
    assert [e["note"] for e in card["events"] if e["kind"] == "status"] == ["Устранено"]
    assert "comment" not in kinds

    # Закрытая задача уходит из активных и находится в завершённых.
    active = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "open"})).json()["tasks"]
    assert tid not in [t["id"] for t in active]
    closed = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "closed"})).json()["tasks"]
    assert tid in [t["id"] for t in closed]


async def test_реплика_на_текущей_стадии_не_теряется(auth_client: AsyncClient):
    """Клик по стадии, на которой задача уже стоит, событием не становится —
    но написанное человеком должно остаться в следе, а не исчезнуть."""
    cid = (await _me(auth_client))["companies"][0]["id"]
    tid = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Задача без типа идёт маршрутом поручения",
    })).json()["id"]

    r = await auth_client.post(f"/api/tasks/{tid}/action", json={
        "company_id": cid, "stage_code": "new", "note": "Жду доступ",
    })
    assert r.status_code == 200, r.text

    card = (await auth_client.get(f"/api/tasks/{tid}", params={"company_id": cid})).json()
    assert [s["code"] for s in card["route"]] == ["new", "in_progress", "review"]
    assert [(e["kind"], e["note"]) for e in card["events"]][-1] == ("comment", "Жду доступ")


async def test_обзор_видит_просрочку_и_разрезы(auth_client: AsyncClient):
    """Обзор приложения: сколько горит, кто чем занят и как оттуда попасть в список.

    Ловим три тихие поломки: «summary» разбирается как идентификатор задачи (маршрут
    объявлен после `/{task_id}`); просроченной считается закрытая задача с давним
    сроком; разрез по людям отдаёт одно имя без id — и провалиться из обзора в список
    некуда, хотя кнопка нажимается."""
    me = await _me(auth_client)
    cid = me["companies"][0]["id"]
    past = "2020-01-01T00:00:00Z"

    async def new(title: str, **extra) -> str:
        r = await auth_client.post("/api/tasks", json={
            "company_id": cid, "title": title, **extra})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    horit = await new("Срок прошёл, работа стоит", assignee_id=me["id"], due_at=past)
    nichey = await new("Поставлена, но ни у кого не в руках")
    zakryt = await new("Просроченная, но уже закрытая", assignee_id=me["id"], due_at=past)
    await auth_client.post(f"/api/tasks/{zakryt}/action", json={
        "company_id": cid, "status": "done"})

    overdue = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "overdue"})).json()["tasks"]
    ids = [t["id"] for t in overdue]
    assert horit in ids
    assert zakryt not in ids, "закрытая задача осталась в просроченных"
    assert all(t["overdue"] for t in overdue)

    mine = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all", "assignee_id": me["id"]})).json()["tasks"]
    assert horit in [t["id"] for t in mine]
    assert nichey not in [t["id"] for t in mine], "фильтр по исполнителю не сработал"

    s = (await auth_client.get("/api/tasks/summary", params={
        "company_id": cid, "days": 30})).json()
    assert s["totals"]["overdue"] >= 1
    assert s["totals"]["unassigned"] >= 1
    assert s["totals"]["done"] >= 1 and s["totals"]["avg_days"] is not None

    row = next(r for r in s["by_assignee"] if r["id"] == me["id"])
    assert row["overdue"] >= 1 and row["done"] >= 1
    # Строка «без исполнителя» есть, но проваливаться из неё некуда — id пустой.
    assert any(r["id"] is None and r["open"] >= 1 for r in s["by_assignee"])

    lenta = [(e["kind"], e["task_id"]) for e in s["activity"]]
    assert ("created", nichey) in lenta and ("status", zakryt) in lenta
