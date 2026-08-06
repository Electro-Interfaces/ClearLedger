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


async def test_карточка_собирает_работу_целиком(auth_client: AsyncClient):
    """Чек-лист, подзадачи, связи и метки — то, ради чего трекер и заводят.

    Ловим: прогресс чек-листа не доезжает до строки списка; связь видна только из
    той карточки, где её завели; родитель закрывается молча при живых подзадачах;
    метка не фильтрует.
    """
    me = await _me(auth_client)
    cid = me["companies"][0]["id"]

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
    cid = me["companies"][0]["id"]

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
    cid = me["companies"][0]["id"]
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

    from app.services import task_scheduler

    me = await _me(auth_client)
    cid = me["companies"][0]["id"]

    r = await auth_client.post("/api/tasks/templates", json={
        "company_id": cid, "name": "Закрытие месяца",
        "title": "Закрыть месяц по объекту", "due_days": 5,
        "assignee_id": me["id"],
        "checklist": ["Сверить остатки", "Подписать акт"]})
    assert r.status_code == 201, r.text
    tpl = r.json()
    assert tpl["checklist"] == ["Сверить остатки", "Подписать акт"]

    # Постановка по шаблону — тем же кодом, что и расписание.
    r = await auth_client.post(f"/api/tasks/templates/{tpl['id']}/use",
                               params={"company_id": cid})
    assert r.status_code == 201, r.text
    made = r.json()
    assert made["checklist"] == {"total": 2, "done": 0}, "чек-лист шаблона не доехал"
    assert made["due_at"], "срок по due_days шаблона не проставился"

    r = await auth_client.post("/api/tasks/recurrences", json={
        "company_id": cid, "template_id": tpl["id"],
        "rule": {"mode": "monthly", "day": 1, "at": "09:00", "tz": "Europe/Moscow"}})
    assert r.status_code == 201, r.text
    rec = r.json()
    assert rec["next_run_at"], "дата следующего запуска не посчиталась"

    # Заведение расписания задачу не порождает — ждём срока.
    listed = (await auth_client.get("/api/tasks/recurrences",
                                    params={"company_id": cid})).json()["recurrences"]
    assert [x["template"] for x in listed] == ["Закрытие месяца"]

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
        sent = await task_scheduler.run_escalations(db, now)
        await db.commit()
    assert sent == 1, f"эскалаций {sent}, а должна быть одна"

    card = (await auth_client.get(f"/api/tasks/{stale['id']}",
                                  params={"company_id": cid})).json()
    assert "escalate" in [e["kind"] for e in card["events"]], "след эскалации не записан"
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
    cid = me["companies"][0]["id"]
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
