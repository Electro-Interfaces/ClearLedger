"""Реестр проектов отвечает про весь отбор, а не про загруженную страницу.

Проверка стенда 25.10.2026 показала две вещи, из-за которых по списку нельзя
работать. Первая: сортировка считалась на клиенте, и «самый срочный» наверху был
самым срочным лишь среди загруженных ста строк из 244. Вторая: колонки
«Следующий шаг» и «Срок» брали только ручное поле — отбор «Ждём внешних» давал
53 строки со сплошными прочерками, хотя и текст ожидания, и контрольная дата в
данных есть.

Третий случай — свод «Присоединение»: он считал заявки отклонённых и
замороженных проектов (70 из 79) и выдавал их за работу.
"""
import pytest
from httpx import AsyncClient
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _site(client: AsyncClient, cid: str, address: str, **patch) -> dict:
    r = await client.post("/api/sites", params={"company_id": cid},
                          json={"address": address, "city": "Тверь", "stage": "negotiation"})
    assert r.status_code in (200, 201), r.text
    site = r.json()
    if patch:
        # PATCH отвечает своим представлением — идентификатор берём из создания.
        r = await client.patch(f"/api/sites/{site['id']}", params={"company_id": cid}, json=patch)
        assert r.status_code == 200, r.text
        site = {**r.json(), "id": site["id"], "projectNo": site.get("projectNo")}
    return site


async def test_сортировка_относится_ко_всему_отбору(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    for address, due in [("ул. Ранняя, 1", "2026-09-04"), ("ул. Средняя, 2", "2026-10-10"),
                         ("ул. Поздняя, 3", "2026-12-20")]:
        await _site(auth_client, cid, address, next_action="Позвонить", next_action_due=due)

    # Страница из одной строки: без серверного порядка наверх попала бы случайная.
    r = await auth_client.get("/api/sites", params={
        "company_id": cid, "stage": "active", "sort": "due", "direction": "asc",
        "page": 1, "page_size": 1})
    assert r.status_code == 200, r.text
    первая = r.json()
    assert первая["total"] >= 3
    assert первая["items"][0]["nextActionDue"] == "2026-09-04", "наверху самый ранний срок всей выборки"

    r = await auth_client.get("/api/sites", params={
        "company_id": cid, "stage": "active", "sort": "due", "direction": "desc",
        "page": 1, "page_size": 1})
    assert r.json()["items"][0]["nextActionDue"] == "2026-12-20"

    # Вторая страница продолжает тот же порядок, а не начинает свой.
    r = await auth_client.get("/api/sites", params={
        "company_id": cid, "stage": "active", "sort": "due", "direction": "asc",
        "page": 2, "page_size": 1})
    assert r.json()["items"][0]["nextActionDue"] == "2026-10-10"


async def test_шаг_строки_берётся_из_ожидания_и_поручения(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    ручной = await _site(auth_client, cid, "ул. Ручная, 4",
                         next_action="Съездить на площадку", next_action_due="2026-11-05")
    ожидание = await _site(auth_client, cid, "ул. Ожидания, 5")

    r = await auth_client.put(f"/api/project-workspace/{ожидание['id']}/next",
                              params={"company_id": cid},
                              json={"waiting_for": "Ответ сетевой по ТУ",
                                    "owner_id": me["id"], "follow_up": "2026-10-30"})
    assert r.status_code in (200, 201), r.text

    rows = (await auth_client.get("/api/sites", params={
        "company_id": cid, "stage": "active", "page_size": 200})).json()["items"]
    by_id = {it["id"]: it for it in rows}

    assert by_id[ручной["id"]]["nextStep"] == "Съездить на площадку"
    assert by_id[ручной["id"]]["nextStepDue"] == "2026-11-05"
    assert by_id[ручной["id"]]["nextStepSource"] == "manual"

    ждём = by_id[ожидание["id"]]
    assert ждём["nextStep"] == "Ожидание: Ответ сетевой по ТУ", "в строке видно, чего ждём"
    assert ждём["nextStepDue"] == "2026-10-30", "и до какой даты"
    assert ждём["nextStepSource"] == "wait"
    # Ручное поле проекта ожиданием не подменяется: по нему правят карточку.
    assert ждём["nextAction"] is None


async def test_присоединение_считает_проекты_в_работе(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    живой = await _site(auth_client, cid, "ул. Живая, 6")
    закрытый = await _site(auth_client, cid, "ул. Закрытая, 7")

    for site in (живой, закрытый):
        r = await auth_client.put(f"/api/sites/{site['id']}/tech-connection",
                                  params={"company_id": cid},
                                  json={"status": "applied", "cost": 100000})
        assert r.status_code in (200, 201), r.text

    r = await auth_client.post(f"/api/sites/{закрытый['id']}/stage", params={"company_id": cid},
                               json={"stage": "archive", "reason": "Собственник отказал"})
    assert r.json()["moved"] is True, r.text

    свод = (await auth_client.get("/api/sites/tech-connections",
                                  params={"company_id": cid})).json()
    номера = {i["projectNo"] for i in свод["items"]}
    assert живой["projectNo"] in номера
    assert закрытый["projectNo"] not in номера, "отклонённый проект не выдаётся за работу"
    assert свод["closedTotal"] >= 1, "сколько скрыто — видно в ответе"
    assert свод["costSum"] == 100000

    со_всеми = (await auth_client.get("/api/sites/tech-connections",
                                      params={"company_id": cid, "include_closed": True})).json()
    assert закрытый["projectNo"] in {i["projectNo"] for i in со_всеми["items"]}
    assert со_всеми["costSum"] == 200000
