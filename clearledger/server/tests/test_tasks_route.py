"""Движок «Задач»: маршрут, переадресация, завершение и след.

Ловим то, что молча ломается: задача уходит на стадию, которой нет в маршруте
её типа; переадресация не попадает в след (и работа выглядит перепрыгнувшей к
другому человеку сама); реплика к действию задваивается в ленте.
"""
import pytest
from httpx import AsyncClient
from tests.helpers import seed_company_id

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
    cid = seed_company_id(me)

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
    cid = seed_company_id(await _me(auth_client))
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
    cid = seed_company_id(me)
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


async def test_карточка_собирает_работу_целиком(auth_client: AsyncClient):
    """Чек-лист, подзадачи, связи и метки — то, ради чего трекер и заводят.

    Ловим: прогресс чек-листа не доезжает до строки списка; связь видна только из
    той карточки, где её завели; родитель закрывается молча при живых подзадачах;
    метка не фильтрует.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    async def new(title: str, **extra) -> dict:
        r = await auth_client.post("/api/tasks", json={
            "company_id": cid, "title": title, **extra})
        assert r.status_code == 201, r.text
        return r.json()

    parent = await new("Смонтировать ЭЗС на площадке", assignee_id=me["id"])
    kid = await new("Согласовать подключение к сети")

    # Чек-лист: два пункта, один отмечен — в списке это видно как 1 из 2.
    for text in ("Заказать оборудование", "Вызвать бригаду"):
        r = await auth_client.post(f"/api/tasks/{parent['id']}/checklist",
                                   json={"company_id": cid, "text": text})
        assert r.status_code == 201, r.text
    card = (await auth_client.get(f"/api/tasks/{parent['id']}",
                                  params={"company_id": cid})).json()
    assert [c["text"] for c in card["checklist_items"]] == [
        "Заказать оборудование", "Вызвать бригаду"], "порядок пунктов не по position"
    r = await auth_client.patch(
        f"/api/tasks/{parent['id']}/checklist/{card['checklist_items'][0]['id']}",
        json={"company_id": cid, "done": True})
    assert r.status_code == 200, r.text

    # Подзадача — та же связь вида subtask, где task_id родитель.
    r = await auth_client.post(f"/api/tasks/{parent['id']}/links", json={
        "company_id": cid, "related_task_id": kid["id"], "kind": "subtask"})
    assert r.status_code == 201, r.text
    # Круг из подзадач не заводится: обход дерева стал бы бесконечным.
    r = await auth_client.post(f"/api/tasks/{kid['id']}/links", json={
        "company_id": cid, "related_task_id": parent["id"], "kind": "subtask"})
    assert r.status_code == 400, "подзадача замкнулась в круг"

    # Связь читается с обеих сторон, и с обратной называется иначе.
    kid_card = (await auth_client.get(f"/api/tasks/{kid['id']}",
                                      params={"company_id": cid})).json()
    assert [(l["kind"], l["number"]) for l in kid_card["links"]] == [
        ("parent", parent["number"])], kid_card["links"]

    # Метка: завести, повесить одним действием, отобрать по ней.
    lab = (await auth_client.post("/api/tasks/labels", json={
        "company_id": cid, "name": "стройка", "color": "amber"})).json()
    r = await auth_client.post(f"/api/tasks/{parent['id']}/action", json={
        "company_id": cid, "add_label_id": lab["id"]})
    assert r.status_code == 200, r.text
    assert [x["name"] for x in r.json()["labels"]] == ["стройка"]
    assert r.json()["checklist"] == {"total": 2, "done": 1}, "прогресс не доехал до строки"
    by_label = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all", "label_id": lab["id"]})).json()["tasks"]
    assert [t["id"] for t in by_label] == [parent["id"]]

    # Закрытие родителя при живой подзадаче проходит, но человека предупреждают.
    r = await auth_client.post(f"/api/tasks/{parent['id']}/action", json={
        "company_id": cid, "status": "done"})
    assert r.status_code == 200, r.text
    assert "подзадач" in (r.json().get("warning") or ""), "закрылось молча"


async def test_рабочее_место_отделяет_моё_от_поручённого(auth_client: AsyncClient):
    """«На мне» — что я делаю, «Я поставил» — где мяч у других. Плюс поиск по
    номеру и упоминание, которое подписывает человека на задачу."""
    me = await _me(auth_client)
    cid = seed_company_id(me)

    mine = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Эту делаю я", "assignee_id": me["id"]})).json()
    handed = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Эту я поручил и жду"})).json()

    ids = lambda rows: [t["id"] for t in rows]
    on_me = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "mine"})).json()
    assert mine["id"] in ids(on_me["tasks"])
    assert handed["id"] not in ids(on_me["tasks"]), "чужая работа попала в «на мне»"

    assigned = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "assigned"})).json()
    assert handed["id"] in ids(assigned["tasks"])
    assert mine["id"] not in ids(assigned["tasks"]), "своя работа попала в «я поставил»"

    # Поиск по номеру: человек называет «№123», а не ищет слова из заголовка.
    found = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all", "q": f"№{handed['number']}"})).json()
    assert ids(found["tasks"]) == [handed["id"]], found["total"]

    # Упоминание в реплике подписывает человека на задачу.
    name = (me.get("name") or me["email"]).split()[0]
    r = await auth_client.post(f"/api/tasks/{handed['id']}/action", json={
        "company_id": cid, "note": f"@{name} посмотри, пожалуйста"})
    assert r.status_code == 200, r.text
    card = (await auth_client.get(f"/api/tasks/{handed['id']}",
                                  params={"company_id": cid})).json()
    assert [w["reason"] for w in card["watchers"]] == ["mention"], card["watchers"]

    watching = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "watching"})).json()
    assert handed["id"] in ids(watching["tasks"])


async def test_команда_одной_строкой(auth_client: AsyncClient):
    """Команды как в YouTrack: одна строка делает то, на что уходит пять кликов.

    Ловим: неузнанные слова молча съедаются (человек уверен, что срок поставлен,
    а его нет); свободный хвост теряется вместо реплики.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)
    a = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Команда — первая"})).json()
    b = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Команда — вторая"})).json()

    r = await auth_client.post("/api/tasks/command", json={
        "company_id": cid, "task_ids": [a["id"], b["id"]],
        "command": "на меня срочная срок завтра посмотрю с утра"})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["changed"] == 2, res

    card = (await auth_client.get(f"/api/tasks/{a['id']}",
                                  params={"company_id": cid})).json()
    assert card["assignee_id"] == me["id"]
    assert card["priority"] == "high"
    assert card["due_at"], "срок не поставился"
    # Свободный хвост становится репликой, а не теряется.
    assert any("посмотрю с утра" in (e["note"] or "") for e in card["events"])

    # Неузнанное возвращается списком, а не проглатывается.
    r = await auth_client.post("/api/tasks/command", json={
        "company_id": cid, "task_ids": [a["id"]], "command": "метка несуществующая"})
    assert r.status_code in (200, 400)
    if r.status_code == 200:
        assert r.json()["unknown"], "неизвестная метка проглочена молча"

    # Закрепление реплики — переключатель.
    ev = next(e for e in card["events"] if e["kind"] in ("comment", "assign"))
    r = await auth_client.post(f"/api/tasks/{a['id']}/events/{ev['id']}/pin",
                               params={"company_id": cid})
    assert r.status_code == 200 and r.json()["pinned"] is True
    r = await auth_client.post(f"/api/tasks/{a['id']}/events/{ev['id']}/pin",
                               params={"company_id": cid})
    assert r.json()["pinned"] is False


async def test_приватная_задача_не_видна_посторонним(auth_client: AsyncClient):
    """Видимость (`visibility` в YouTrack): кадровое поручение читают не все.

    Ловим главное: закрытая задача утекает не «по ссылке», а списком и поиском —
    заголовка достаточно, чтобы понять, о чём речь.
    """
    import uuid as _uuid

    from app.database import async_session_factory
    from app.models import Task, User, UserCompany
    from sqlalchemy import select

    me = await _me(auth_client)
    cid = seed_company_id(me)
    t = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Пересмотр оклада"})).json()
    r = await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "visibility": "private"})
    assert r.status_code == 200 and r.json()["visibility"] == "private"
    # Смена круга — событие: тихое действие с большими последствиями.
    card = (await auth_client.get(f"/api/tasks/{t['id']}",
                                  params={"company_id": cid})).json()
    assert any(e["kind"] == "field" and "видимость" in (e["from"] or "")
               for e in card["events"])

    # Посторонний (не админ, не причастен) её не видит ни списком, ни поиском.
    async with async_session_factory() as db:
        row = (await db.execute(
            select(User).join(UserCompany, UserCompany.user_id == User.id)
            .where(UserCompany.company_id == _uuid.UUID(cid),
                   UserCompany.role != "admin", User.is_superadmin.is_(False),
                   User.mail_only.is_(False)).limit(1))).scalar_one_or_none()
        if row is None:
            # Раньше проверка на этом и заканчивалась: в тестовой базе не было
            # ни одного неадмина, и тело теста не исполнялось никогда. Ветка
            # осталась — но теперь личный тест заводит второго человека, и она
            # срабатывает только при запуске файла в одиночку.
            return
        from app.routers.tasks_router import list_tasks
        # Роутер зовётся напрямую, мимо FastAPI: значения `Query(...)` остаются
        # объектами, поэтому каждый параметр приходится называть явно. Новый
        # параметр в ручке — новая строка здесь.
        args = dict(object_id=None, type_id=None, assignee_id=None, author_id=None,
                    stage=None, priority=None, label_id=None, due_from=None, due_to=None,
                    visibility=None, query=None, project_id=None, sprint_id=None,
                    fix_version_id=None, found_version_id=None, backlog=False,
                    sort="created", limit=100, offset=0, db=db, current_user=row)
        seen = await list_tasks(company_id=cid, scope="all", q=None, **args)
        assert t["id"] not in [x["id"] for x in seen["tasks"]], "приватная утекла списком"
        found = await list_tasks(company_id=cid, scope="all", q="оклад", **args)
        assert t["id"] not in [x["id"] for x in found["tasks"]], "приватная нашлась поиском"


async def test_учёт_времени_план_и_факт(auth_client: AsyncClient):
    """Оценка и записи о работе — как `estimation` и work items в YouTrack.

    Ловим: длительность понимается только числом (учётом, где надо считать
    минуты в уме, не пользуются); факт не суммируется в строку списка; правка
    оценки не оставляет следа.
    """
    from app.routers.tasks_router import human_duration, parse_duration

    # Люди пишут длительность как придётся — разбирать надо все формы.
    assert parse_duration("2ч 30м") == 150
    assert parse_duration("1,5ч") == 90
    assert parse_duration("90м") == 90
    assert parse_duration("2") == 120, "голое число — это часы"
    assert parse_duration("ерунда") is None
    assert human_duration(150) == "2 ч 30 мин"

    me = await _me(auth_client)
    cid = seed_company_id(me)
    t = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Работа с учётом времени",
        "assignee_id": me["id"]})).json()

    r = await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "estimate": "4ч"})
    assert r.status_code == 200, r.text

    for dur in ("2ч 30м", "45м"):
        r = await auth_client.post(f"/api/tasks/{t['id']}/work", json={
            "company_id": cid, "duration": dur, "description": f"работа {dur}"})
        assert r.status_code == 201, r.text
    r = await auth_client.post(f"/api/tasks/{t['id']}/work", json={
        "company_id": cid, "duration": "ерунда"})
    assert r.status_code == 400, "неразборчивая длительность прошла"

    card = (await auth_client.get(f"/api/tasks/{t['id']}",
                                  params={"company_id": cid})).json()
    assert card["time"]["estimate"] == 240
    assert card["time"]["spent"] == 195, card["time"]
    assert card["time"]["spent_text"] == "3 ч 15 мин"
    assert len(card["work_items"]) == 2
    # Время попадает в след: «делал три часа» отвечает на «почему так долго».
    assert "work" in [e["kind"] for e in card["events"]]
    # Правка оценки — тоже событие.
    assert any(e["kind"] == "field" and "оценка" in (e["from"] or "")
               for e in card["events"]), [e["kind"] for e in card["events"]]

    # Факт виден в строке списка — не открывая карточку.
    row = next(x for x in (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all"})).json()["tasks"] if x["id"] == t["id"])
    assert row["time"]["spent"] == 195 and row["time"]["estimate"] == 240


async def test_закрытая_задача_по_маршруту_не_ходит(auth_client: AsyncClient):
    """Ревизия против YouTrack/Jira: у закрытой задачи переходов нет.

    Иначе выходит «выполнена, но стадия ползёт»: в ленте движение есть, работы
    нет, и любой отчёт по стадиям начинает врать. Вернуть в работу — можно,
    и после этого маршрут снова доступен.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)
    types = (await auth_client.get("/api/tasks/types",
                                   params={"company_id": cid})).json()["types"]
    incident = next(t for t in types if t["code"] == "incident")
    t = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Цикл задачи", "type_id": incident["id"],
        "assignee_id": me["id"]})).json()

    await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "stage_code": "diag"})
    r = await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "status": "done"})
    assert r.status_code == 200, r.text

    r = await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "stage_code": "fix"})
    assert r.status_code == 409, "закрытая задача поехала по маршруту"

    # Переоткрытие снимает отметку закрытия и возвращает движение.
    r = await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "status": "open", "note": "вернули"})
    assert r.status_code == 200 and r.json()["closed_at"] is None
    r = await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "stage_code": "fix"})
    assert r.status_code == 200 and r.json()["stage"] == "Устранение"

    # Просрочка — свойство живой задачи: у закрытой срок уже не сигнал.
    past = "2020-01-01T00:00:00Z"
    await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "due_at": past})
    assert (await auth_client.get(f"/api/tasks/{t['id']}",
                                  params={"company_id": cid})).json()["overdue"] is True
    await auth_client.post(f"/api/tasks/{t['id']}/action", json={
        "company_id": cid, "status": "done"})
    assert (await auth_client.get(f"/api/tasks/{t['id']}",
                                  params={"company_id": cid})).json()["overdue"] is False


async def test_поручение_внешнему_письмом(auth_client: AsyncClient, monkeypatch):
    """Режим B: подрядчик не заходит в пространство, разговариваем почтой.

    Ловим: делегирование не переводит мяч наружу (и задача продолжает висеть
    «на мне»); ответ с чужого адреса принимается; повторная доставка того же
    письма плодит дубли в ленте; ответ не возвращает мяч нам.
    """
    from app.config import settings
    # Канал включаем на время проверки: без ящика ручка честно отвечает 409, и
    # это тоже часть договора — молча глотать поручения она не должна.
    monkeypatch.setattr(settings, "chat_mail_inbox", "space@dataworker.ru", raising=False)
    monkeypatch.setattr(settings, "smtp_host", "localhost", raising=False)

    me = await _me(auth_client)
    cid = seed_company_id(me)
    task = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Заменить шлагбаум на въезде",
        "assignee_id": me["id"]})).json()

    r = await auth_client.post(f"/api/tasks/{task['id']}/delegate", json={
        "company_id": cid, "email": "podryad@example.org", "name": "Пётр Подрядов",
        "note": "Смета согласована, приступайте"})
    assert r.status_code == 201, r.text
    assert r.json()["reply_address"] == f"space+t{task['number']}@dataworker.ru"

    card = (await auth_client.get(f"/api/tasks/{task['id']}",
                                  params={"company_id": cid})).json()
    assert card["waiting_for"] == "external", "мяч не ушёл внешней стороне"
    assert [(p["channel"], p["role"]) for p in card["participants"]] == [("mail", "external")]
    assert card["events"][-1]["kind"] == "delegate"

    # Пока ждём подрядчика, работа не висит «на мне».
    on_me = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "mine"})).json()["tasks"]
    assert task["id"] not in [t["id"] for t in on_me]
    waiting = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "waiting"})).json()["tasks"]
    assert task["id"] in [t["id"] for t in waiting]

    # Ответ письмом приносит поллер Поддержки — он ходит ключом пространства,
    # а не токеном человека: своего поллера у задач нет и не будет.
    import uuid as _uuid

    from app.database import async_session_factory
    from app.models import Company

    async with async_session_factory() as db:
        company = await db.get(Company, _uuid.UUID(cid))
        company.cloud_api_key = "test-space-key"
        await db.commit()
    head = {"X-Cloud-API-Key": "test-space-key"}

    inbound = {"fromAddress": "podryad@example.org", "fromName": "Пётр Подрядов",
               "text": "Шлагбаум привезли, ставим завтра", "messageId": "<m-1@example.org>",
               "emailMessageId": "arch-42"}
    # Чужой адрес не пишет: адрес задачи может утечь пересылкой письма.
    r = await auth_client.post(f"/api/tasks/{task['number']}/inbound-email",
                               json={**inbound, "fromAddress": "kto-to@example.net"},
                               headers=head)
    assert r.status_code == 403, "посторонний написал в задачу"

    r = await auth_client.post(f"/api/tasks/{task['number']}/inbound-email",
                               json=inbound, headers=head)
    assert r.status_code == 201, r.text
    card = (await auth_client.get(f"/api/tasks/{task['id']}",
                                  params={"company_id": cid})).json()
    mail_events = [e for e in card["events"] if e["kind"] == "mail"]
    assert [e["user"] for e in mail_events] == ["Пётр Подрядов"]
    assert card["waiting_for"] == "us", "ответ не вернул мяч нам"

    r = await auth_client.post(f"/api/tasks/{task['number']}/inbound-email",
                               json=inbound, headers=head)
    assert r.json().get("duplicate") is True, "повторная доставка задвоила реплику"


async def test_регламент_шаблоны_расписания_эскалация(auth_client: AsyncClient):
    """Волна 3: заготовка, расписание и «на задачу не откликнулись».

    Ловим: статический путь `/templates` разбирается как идентификатор задачи;
    расписание порождает задачу сразу при заведении (а не в срок); чек-лист
    шаблона не доезжает до задачи; эскалация уходит по задаче, которую уже взяли.
    """
    from datetime import datetime, timedelta, timezone

    from app.services import digest, task_scheduler

    me = await _me(auth_client)
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks/templates", json={
        "company_id": cid, "name": "Закрытие месяца",
        "title": "Закрыть месяц по объекту", "due_days": 5,
        "assignee_id": me["id"],
        "checklist": ["Сверить остатки", "Подписать акт"]})
    assert r.status_code == 201, r.text
    tpl = r.json()
    assert tpl["checklist"] == ["Сверить остатки", "Подписать акт"]

    # Постановка по шаблону — тем же кодом, что и расписание. Адрес у неё
    # теперь в «Треке»: старая `/tasks/templates/{id}/use` ушла вместе с разделом
    # «Задачи» 16.08.2026, а тест продолжал стучаться в неё и падал на 404 —
    # поймано первым же прогоном на стенде 23.08.2026.
    r = await auth_client.post(f"/api/docs/process-templates/{tpl['id']}/start",
                               json={"company_id": cid})
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["kind"] == "task" and made["taskId"], made
    card = (await auth_client.get(f"/api/tasks/{made['taskId']}",
                                  params={"company_id": cid})).json()
    assert card["checklist"] == {"total": 2, "done": 0}, "чек-лист шаблона не доехал"
    assert card["due_at"], "срок по due_days шаблона не проставился"

    r = await auth_client.post("/api/tasks/recurrences", json={
        "company_id": cid, "template_id": tpl["id"],
        "rule": {"mode": "monthly", "day": 1, "at": "09:00", "tz": "Europe/Moscow"}})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["next_run_at"], "дата следующего запуска не посчиталась"

    # Расписание себе заводит любой: за личной дисциплиной к администратору
    # никто не пойдёт. Проверяем, что ручка не требует прав на свой шаблон.
    mine = (await auth_client.post("/api/tasks/templates", json={
        "company_id": cid, "name": "Мой еженедельный отчёт",
        "title": "Свести отчёт за неделю", "assignee_id": me["id"]})).json()
    r = await auth_client.post("/api/tasks/recurrences", json={
        "company_id": cid, "template_id": mine["id"],
        "rule": {"mode": "weekly", "weekday": 0, "at": "09:00", "tz": "Europe/Moscow"}})
    assert r.status_code == 201, r.text

    # Заведение расписания задачу не порождает — ждём срока.
    listed = (await auth_client.get("/api/tasks/recurrences",
                                    params={"company_id": cid})).json()["recurrences"]
    assert "Закрытие месяца" in [x["template"] for x in listed]
    assert "Мой еженедельный отчёт" in [x["template"] for x in listed]

    # Правило считается в местном времени пояса, а не в UTC.
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    nxt = task_scheduler.next_run({"mode": "weekly", "weekday": 0, "at": "09:00",
                                   "tz": "Europe/Moscow"}, now)
    assert nxt > now and nxt.astimezone(
        task_scheduler._tz({"tz": "Europe/Moscow"})).weekday() == 0

    # Эскалация: на задачу не откликнулись за отведённое типом время.
    # Гоняем сам прогон планировщика — в нём и живёт логика, которую иначе
    # проверяет только стенд (так уже поймали `await` не на том выражении).
    import uuid as _uuid

    from app.database import async_session_factory
    from app.models import Task

    r = await auth_client.post("/api/tasks/types", json={
        "company_id": cid, "code": "urgent-react", "name": "С реакцией",
        "route": [{"code": "new", "name": "Постановка"}], "reaction_hours": 1})
    assert r.status_code == 201, r.text
    urgent = r.json()
    assert urgent["reaction_hours"] == 1

    stale = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "На эту никто не откликнулся",
        "type_id": urgent["id"], "assignee_id": me["id"]})).json()
    fresh = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "А эту сразу взяли",
        "type_id": urgent["id"], "assignee_id": me["id"]})).json()
    # По второй откликнулись — эскалация её трогать не должна.
    await auth_client.post(f"/api/tasks/{fresh['id']}/action", json={
        "company_id": cid, "note": "Взял в работу"})

    now = datetime.now(timezone.utc)
    async with async_session_factory() as db:
        row = await db.get(Task, _uuid.UUID(stale["id"]))
        row.created_at = now - timedelta(hours=3)
        row2 = await db.get(Task, _uuid.UUID(fresh["id"]))
        row2.created_at = now - timedelta(hours=3)
        await db.commit()
        bucket = digest.Bucket()
        sent = await task_scheduler.run_escalations(db, now, bucket)
        await db.commit()
    assert sent == 1, f"эскалаций {sent}, а должна быть одна"

    # След ставится ТОЛЬКО вместе с доставкой: после прохода его ещё нет.
    # Иначе ночная эскалация помечалась бы случившейся, утренняя сводка её уже
    # не нашла бы, и в карточке было бы написано «ушло» о том, чего не было.
    card = (await auth_client.get(f"/api/tasks/{stale['id']}",
                                  params={"company_id": cid})).json()
    assert "escalate" not in [e["kind"] for e in card["events"]], \
        "след эскалации записан до доставки"
    # Но повод собран и адресован конкретному человеку.
    поводы = [line.key for lines in bucket.lines.values() for line in lines]
    assert any(k == f"escalate:{stale['id']}" for k in поводы), \
        f"повод эскалации не собран: {поводы}"

    # Доставляем — и след появляется.
    async with async_session_factory() as db:
        for lines in bucket.lines.values():
            for line in lines:
                if line.mark is not None:
                    line.mark()
        await db.commit()

    card2 = (await auth_client.get(f"/api/tasks/{fresh['id']}",
                                   params={"company_id": cid})).json()
    assert "escalate" not in [e["kind"] for e in card2["events"]], "эскалация по взятой задаче"

    # Представление: сохранённый отбор появляется в списке и возвращает свой запрос.
    r = await auth_client.post("/api/tasks/views", json={
        "company_id": cid, "name": "Мои просрочки",
        "query": {"scope": "mine", "sort": "due"}})
    assert r.status_code == 201, r.text
    views = (await auth_client.get("/api/tasks/views",
                                   params={"company_id": cid})).json()["views"]
    mine = next(v for v in views if v["name"] == "Мои просрочки")
    assert mine["query"] == {"scope": "mine", "sort": "due"} and mine["shared"] is False


async def test_зеркало_внешней_системы(auth_client: AsyncClient):
    """Режим C: работа живёт в чужой системе, у нас — связь с ней.

    Ловим: зеркало подменяет наш статус (вторая правда); синхронизация выдумывает
    состояние, когда приложение его не отдаёт; снятие связи оставляет задачу
    вечно «у внешней стороны».
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)
    task = (await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Ремонт по гарантии подрядчика",
        "assignee_id": me["id"]})).json()

    r = await auth_client.post(f"/api/tasks/{task['id']}/external", json={
        "company_id": cid, "connector_key": "support:hubex",
        "connector_label": "HubEx FSM", "external_number": "W-11235",
        "external_url": "https://hubex.example/work/11235",
        "note": "Заявка заведена у подрядчика"})
    assert r.status_code == 201, r.text
    ref = r.json()

    card = (await auth_client.get(f"/api/tasks/{task['id']}",
                                  params={"company_id": cid})).json()
    assert card["waiting_for"] == "external"
    assert [e["external_number"] for e in card["external"]] == ["W-11235"]
    # Наш статус остался нашим: зеркало не подменяет состояние задачи.
    assert card["status"] == "open"

    # Приложение состояние чужой работы не отдаёт — ручка обязана сказать это
    # прямо, а не показать выдуманный статус.
    r = await auth_client.post(
        f"/api/tasks/{task['id']}/external/{ref['id']}/sync",
        params={"company_id": cid})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False and body["reason"], body
    assert body["external_status"] is None, "статус выдуман на пустом ответе"

    # Длительность текущего этапа — то, ради чего чужие этапы вообще вливаются
    # в нашу ленту: «работа стоит или движется».
    from datetime import datetime, timedelta, timezone

    from app.routers.tasks_router import _human_span, _stage_note

    assert _human_span(86400 * 12 + 3600 * 11) == "12 дн 11 ч"
    assert _human_span(30) == "меньше минуты"
    began = (datetime.now(timezone.utc) - timedelta(days=12, hours=11)).isoformat()
    assert "идёт уже 12 дн" in _stage_note({"name": "Диагностика", "date_from": began})
    # У пройденного этапа длительности нет — он уже не отвечает на этот вопрос.
    assert _stage_note({"date_from": began, "date_till": began, "note": "принято"}) == "принято"

    r = await auth_client.delete(f"/api/tasks/{task['id']}/external/{ref['id']}",
                                 params={"company_id": cid})
    assert r.status_code == 200, r.text
    card = (await auth_client.get(f"/api/tasks/{task['id']}",
                                  params={"company_id": cid})).json()
    assert card["waiting_for"] is None, "ждать некого, а мяч всё ещё снаружи"


async def test_версия_проекта_собирает_состав(auth_client: AsyncClient):
    """Этап 10: «исправлено в версии» — ответ заявителю, и он не должен врать.

    Ловим то, что молча ломается: версия чужого проекта проставляется задаче
    (заявителю уедет номер релиза, в котором его правки нет); выпуск версии
    остаётся без даты (номер есть, а когда вышла — неизвестно); состав версии
    не отделяет сделанное от висящего, и релиз выпускают недоделанным.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks/projects", json={
        "company_id": cid, "code": "VER", "name": "Проверка версий"})
    assert r.status_code == 201, r.text
    prj = r.json()
    r = await auth_client.post("/api/tasks/projects", json={
        "company_id": cid, "code": "VEROTH", "name": "Соседний продукт"})
    assert r.status_code == 201, r.text
    other = r.json()

    r = await auth_client.post("/api/tasks/versions", json={
        "company_id": cid, "project_id": prj["id"], "name": "1.4.2"})
    assert r.status_code == 201, r.text
    version = r.json()
    assert version["state"] == "open" and version["released_on"] is None

    # Одноимённая версия у соседа — законна: «1.4» у двух продуктов разные вещи.
    r = await auth_client.post("/api/tasks/versions", json={
        "company_id": cid, "project_id": other["id"], "name": "1.4.2"})
    assert r.status_code == 201, r.text
    alien = r.json()
    # А в том же проекте — нет: два разных релиза с одним номером не бывает.
    r = await auth_client.post("/api/tasks/versions", json={
        "company_id": cid, "project_id": prj["id"], "name": "1.4.2"})
    assert r.status_code == 409, r.text

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Правка, которая войдёт в релиз",
        "project_id": prj["id"]})
    assert r.status_code == 201, r.text
    task = r.json()

    # Версия соседнего проекта не проставляется: иначе заявителю уедет номер
    # релиза, в котором его исправления нет.
    r = await auth_client.post(f"/api/tasks/{task['id']}/action", json={
        "company_id": cid, "fix_version_id": alien["id"]})
    assert r.status_code == 400, r.text

    r = await auth_client.post(f"/api/tasks/{task['id']}/action", json={
        "company_id": cid, "fix_version_id": version["id"]})
    assert r.status_code == 200, r.text
    card = (await auth_client.get(f"/api/tasks/{task['id']}",
                                  params={"company_id": cid})).json()
    assert card["fix_version"] == "1.4.2"
    # Смена версии — след, а не тихая правка: она уезжает заявителю.
    assert any(e["kind"] == "field" and (e["from"] or "").startswith("исправлено в версии")
               and e["to"] == "1.4.2" for e in card["events"]), card["events"]

    # Пока задача жива, она в остатке: состав отвечает «можно ли выпускать».
    body = (await auth_client.get(f"/api/tasks/versions/{version['id']}/summary",
                                  params={"company_id": cid})).json()
    assert [t["id"] for t in body["left"]] == [task["id"]]
    assert body["done"] == []

    r = await auth_client.post(f"/api/tasks/{task['id']}/action", json={
        "company_id": cid, "status": "done"})
    assert r.status_code == 200, r.text
    body = (await auth_client.get(f"/api/tasks/versions/{version['id']}/summary",
                                  params={"company_id": cid})).json()
    assert [t["id"] for t in body["done"]] == [task["id"]]
    assert body["left"] == []

    # Выпуск без даты — дырка в ответе заявителю. Дата ставится сама.
    r = await auth_client.patch(f"/api/tasks/versions/{version['id']}", json={
        "company_id": cid, "state": "released"})
    assert r.status_code == 200, r.text
    assert r.json()["released_on"], "версия выпущена, а когда — неизвестно"

    # Отбор по версии — то, из чего собирается список изменений.
    listed = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all", "fix_version_id": version["id"]})).json()
    assert [t["id"] for t in listed["tasks"]] == [task["id"]]

    # Команда одной строкой: «версия 1.4.2» подбирает задачу в релиз проекта.
    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Вторая правка того же релиза",
        "project_id": prj["id"]})
    second = r.json()
    r = await auth_client.post("/api/tasks/command", json={
        "company_id": cid, "task_ids": [second["id"]], "command": "версия 1.4.2"})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == 1, r.text
    card = (await auth_client.get(f"/api/tasks/{second['id']}",
                                  params={"company_id": cid})).json()
    assert card["fix_version"] == "1.4.2"


async def test_спринт_планирует_и_подводит_итог(auth_client: AsyncClient):
    """Этап 11: бэклог, отрезок работы и его итог.

    Ловим то, что молча ломается: в проекте заводится второй «текущий» спринт
    (плана больше нет, есть два списка желаний); закрытие спринта оставляет
    незакрытые задачи внутри и итог показывает «взято = сделано»; в закрытый
    спринт докладывают работу задним числом.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks/projects", json={
        "company_id": cid, "code": "SPR", "name": "Проверка спринтов"})
    assert r.status_code == 201, r.text
    prj = r.json()
    r = await auth_client.post("/api/tasks/projects", json={
        "company_id": cid, "code": "SPROTH", "name": "Соседний продукт"})
    other = r.json()

    r = await auth_client.post("/api/tasks/sprints", json={
        "company_id": cid, "project_id": prj["id"], "name": "Спринт 1",
        "starts_on": "2026-08-24", "ends_on": "2026-09-06"})
    assert r.status_code == 201, r.text
    sprint = r.json()
    assert sprint["state"] == "planned" and sprint["taken"] == 0

    # Отрезок, который кончается раньше, чем начинается, — опечатка, а не план.
    r = await auth_client.post("/api/tasks/sprints", json={
        "company_id": cid, "project_id": prj["id"], "name": "Кривой",
        "starts_on": "2026-09-06", "ends_on": "2026-08-24"})
    assert r.status_code == 400, r.text

    # Две задачи проекта: обе рождаются в бэклоге — спринт им никто не назначал.
    ids = []
    for title in ("Первая работа отрезка", "Вторая работа отрезка"):
        r = await auth_client.post("/api/tasks", json={
            "company_id": cid, "title": title, "project_id": prj["id"]})
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    backlog = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "open", "project_id": prj["id"],
        "backlog": "true"})).json()
    assert set(ids) <= {t["id"] for t in backlog["tasks"]}

    # Спринт соседнего проекта не подходит: отрезок планирует свою работу.
    r = await auth_client.post("/api/tasks/sprints", json={
        "company_id": cid, "project_id": other["id"], "name": "Чужой отрезок"})
    alien = r.json()
    r = await auth_client.post(f"/api/tasks/{ids[0]}/action", json={
        "company_id": cid, "sprint_id": alien["id"]})
    assert r.status_code == 400, r.text

    for task_id in ids:
        r = await auth_client.post(f"/api/tasks/{task_id}/action", json={
            "company_id": cid, "sprint_id": sprint["id"]})
        assert r.status_code == 200, r.text

    # Взяли в работу: активный спринт в проекте ровно один.
    r = await auth_client.patch(f"/api/tasks/sprints/{sprint['id']}", json={
        "company_id": cid, "state": "active"})
    assert r.status_code == 200, r.text
    assert r.json()["taken"] == 2
    r = await auth_client.post("/api/tasks/sprints", json={
        "company_id": cid, "project_id": prj["id"], "name": "Спринт 2"})
    second = r.json()
    r = await auth_client.patch(f"/api/tasks/sprints/{second['id']}", json={
        "company_id": cid, "state": "active"})
    assert r.status_code == 409, "в проекте пошли два спринта разом"

    r = await auth_client.post(f"/api/tasks/{ids[0]}/action", json={
        "company_id": cid, "status": "done"})
    assert r.status_code == 200, r.text

    # Закрытие: сделанное остаётся в отрезке, незакрытое уходит в бэклог, а его
    # число остаётся в спринте — иначе не видно, что отрезок переоценили.
    r = await auth_client.patch(f"/api/tasks/sprints/{sprint['id']}", json={
        "company_id": cid, "state": "closed"})
    assert r.status_code == 200, r.text
    closed = r.json()
    assert (closed["done"], closed["left"], closed["carried_over"]) == (1, 0, 1), closed
    assert closed["taken"] == 2, "итог потерял то, что взяли, но не сделали"

    card = (await auth_client.get(f"/api/tasks/{ids[1]}",
                                  params={"company_id": cid})).json()
    assert card["sprint_id"] is None, "незакрытая задача осталась в закрытом спринте"
    assert any(e["kind"] == "field" and e["to"] == "бэклог" for e in card["events"]), card["events"]

    # Задним числом в закрытый отрезок не докладывают: его итог уже подведён.
    r = await auth_client.post(f"/api/tasks/{ids[1]}/action", json={
        "company_id": cid, "sprint_id": sprint["id"]})
    assert r.status_code == 400, r.text

    # Планирование пачкой — командой, в обе стороны.
    # Несуществующий отрезок не проглатывается молча: человек уверен, что
    # спланировал работу, а она осталась в бэклоге.
    r = await auth_client.post("/api/tasks/command", json={
        "company_id": cid, "task_ids": [ids[1]], "command": "спринт Небывалый"})
    assert r.status_code == 400, r.text
    r = await auth_client.post("/api/tasks/command", json={
        "company_id": cid, "task_ids": [ids[1]], "command": "спринт Спринт 2"})
    assert r.status_code == 200, r.text
    card = (await auth_client.get(f"/api/tasks/{ids[1]}",
                                  params={"company_id": cid})).json()
    assert card["sprint"] == "Спринт 2", card["sprint"]

    r = await auth_client.post("/api/tasks/command", json={
        "company_id": cid, "task_ids": [ids[1]], "command": "спринт бэклог"})
    assert r.status_code == 200, r.text
    card = (await auth_client.get(f"/api/tasks/{ids[1]}",
                                  params={"company_id": cid})).json()
    assert card["sprint_id"] is None


async def test_запрос_строкой_даёт_то_же_что_форма(auth_client: AsyncClient):
    """Этап 12: «проект: QRY #нерешённые исполнитель: я» вместо восьми полей формы.

    Ловим то, что молча ломается: строка отбирает не то же, что форма (тогда
    сохранённый отбор однажды покажет чужую работу); опечатка в имени глотается
    и список молча сужается; значение с пробелом рвётся по пробелу.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)
    my_id = me["id"]

    r = await auth_client.post("/api/tasks/projects", json={
        "company_id": cid, "code": "QRY", "name": "Проверка запросов"})
    assert r.status_code == 201, r.text
    prj = r.json()
    r = await auth_client.post("/api/tasks/sprints", json={
        "company_id": cid, "project_id": prj["id"], "name": "Отрезок с пробелом"})
    assert r.status_code == 201, r.text
    sprint = r.json()

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Разбор запроса строкой", "project_id": prj["id"],
        "assignee_id": my_id, "priority": "high"})
    assert r.status_code == 201, r.text
    mine = r.json()
    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Чужая работа того же проекта",
        "project_id": prj["id"], "priority": "low"})
    other = r.json()

    # Строка и форма отбирают одно и то же — иначе сохранённый отбор однажды
    # покажет не ту работу, и доверия к представлениям больше не будет.
    by_form = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "open", "project_id": prj["id"],
        "assignee_id": my_id, "priority": "high"})).json()
    by_text = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all",
        "query": "проект: QRY #нерешённые исполнитель: я приоритет: срочная"})).json()
    assert [t["id"] for t in by_text["tasks"]] == [t["id"] for t in by_form["tasks"]]
    assert mine["id"] in [t["id"] for t in by_text["tasks"]]
    assert other["id"] not in [t["id"] for t in by_text["tasks"]]
    assert by_text["query"]["unknown"] == [], by_text["query"]

    # Опечатка не глотается: человек должен видеть, что отбор не сработал.
    body = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all",
        "query": "проект: НЕТТАКОГО #выдумка кому: Несуществующий"})).json()
    assert len(body["query"]["unknown"]) == 3, body["query"]

    # Значение с пробелом — в кавычках, иначе рвётся по пробелу.
    r = await auth_client.post(f"/api/tasks/{mine['id']}/action", json={
        "company_id": cid, "sprint_id": sprint["id"]})
    assert r.status_code == 200, r.text
    body = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all",
        "query": 'спринт: "Отрезок с пробелом"'})).json()
    assert [t["id"] for t in body["tasks"]] == [mine["id"]], body["query"]

    # Свободный хвост — обычный поиск по тексту, как в поле «Поиск».
    body = (await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all",
        "query": "проект: QRY разбор запроса"})).json()
    assert body["query"]["text"] == "разбор запроса"
    assert [t["id"] for t in body["tasks"]] == [mine["id"]]

    # Отбор сохраняется представлением и возвращается целиком: до этапа 12
    # половина ключей терялась по дороге.
    r = await auth_client.post("/api/tasks/views", json={
        "company_id": cid, "name": "Мои срочные в QRY",
        "query": {"view": "registry", "query": "проект: QRY #мои приоритет: срочная"}})
    assert r.status_code == 201, r.text
    views = (await auth_client.get("/api/tasks/views",
                                   params={"company_id": cid})).json()["views"]
    saved = next(v for v in views if v["name"] == "Мои срочные в QRY")
    assert saved["query"]["query"] == "проект: QRY #мои приоритет: срочная"


async def test_ссылки_на_код_привязываются_к_задаче(auth_client: AsyncClient):
    """Что сделано в коде по задаче: ветка, коммит, запрос на слияние.

    Ловим: адрес не разбирается и в карточке висит простыня вместо подписи;
    один и тот же коммит привязывается дважды; чужая ссылка удаляется из чужой
    задачи.
    """
    me = await _me(auth_client)
    cid = seed_company_id(me)

    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Работа со ссылкой на код"})
    assert r.status_code == 201, r.text
    task = r.json()

    commit = "https://github.com/Electro-Interfaces/ClearLedger/commit/a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
    r = await auth_client.post(f"/api/tasks/{task['id']}/code", json={
        "company_id": cid, "url": commit})
    assert r.status_code == 201, r.text
    added = r.json()
    # Коммит зовут коротким хешем: полный в строке карточки только мешает.
    assert added["kind"] == "commit" and added["title"] == "a1b2c3d"
    assert added["repo"] == "github · Electro-Interfaces/ClearLedger"

    # Запрос на слияние и ветка узнаются по тому же адресу.
    r = await auth_client.post(f"/api/tasks/{task['id']}/code", json={
        "company_id": cid,
        "url": "https://github.com/Electro-Interfaces/ClearLedger/pull/128"})
    assert r.status_code == 201 and r.json()["kind"] == "pr", r.text
    assert r.json()["title"] == "#128"
    r = await auth_client.post(f"/api/tasks/{task['id']}/code", json={
        "company_id": cid,
        "url": "https://github.com/Electro-Interfaces/ClearLedger/tree/fix/export-bp"})
    assert r.status_code == 201 and r.json()["kind"] == "branch", r.text

    # Неузнанный хостинг не отвергается: он остаётся ссылкой.
    r = await auth_client.post(f"/api/tasks/{task['id']}/code", json={
        "company_id": cid, "url": "https://git.example.ru/some/thing"})
    assert r.status_code == 201 and r.json()["kind"] == "other", r.text

    # Адрес без схемы — опечатка, а не ссылка.
    r = await auth_client.post(f"/api/tasks/{task['id']}/code", json={
        "company_id": cid, "url": "github.com/x/y/commit/abc"})
    assert r.status_code == 400, r.text

    # Тот же коммит второй раз — опечатка, а не второе изменение.
    r = await auth_client.post(f"/api/tasks/{task['id']}/code", json={
        "company_id": cid, "url": commit})
    assert r.status_code == 409, r.text

    listed = (await auth_client.get(f"/api/tasks/{task['id']}/code",
                                    params={"company_id": cid})).json()["code"]
    assert len(listed) == 4
    assert {row["kind"] for row in listed} == {"commit", "pr", "branch", "other"}

    r = await auth_client.delete(
        f"/api/tasks/{task['id']}/code/{added['id']}", params={"company_id": cid})
    assert r.status_code == 200, r.text
    listed = (await auth_client.get(f"/api/tasks/{task['id']}/code",
                                    params={"company_id": cid})).json()["code"]
    assert len(listed) == 3
