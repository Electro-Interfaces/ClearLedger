"""Личная запись закрыта и на ручках ИЗМЕНЕНИЯ, а не только на выборках.

Дыра, ради которой написан файл (найдена сторонним аудитом 29.08.2026): ручка
действия над задачей не спрашивала права ПРОСМОТРА вовсе, а «только реплика»
считалась перечислением полей — списком имён, отставшим от модели на шесть
штук. Прислав реплику вместе с `visibility`, посторонний сотрудник открывал
чужую личную запись всей компании и получал в ответе её текст.

Правило простое и проверяется здесь целиком: **личную запись меняет только
автор — ни администратор, ни суперадминистратор**. Ответ посторонннему — 404,
а не 403: подтверждать существование чужой личной записи это уже утечка.
"""
import uuid
from contextlib import contextmanager

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.main import app
from app.models import Task, User, UserCompany
from app.routers import tasks_router
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


@contextmanager
def _как(user: User):
    """Выполнить запрос от имени другого человека.

    Подменяем зависимость, а не логинимся: у заведённого здесь сотрудника нет
    пароля, и заводить ему рабочую учётку ради проверки прав значило бы
    проверять не то. Ручка при этом идёт целиком — со всеми своими проверками.
    """
    app.dependency_overrides[get_current_user] = lambda: user
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_user, None)


async def _company(client) -> str:
    me = (await client.get("/api/auth/me")).json()
    return seed_company_id(me)


async def _чужой(db: AsyncSession, cid: str, *, admin: bool = False) -> User:
    """Сотрудник той же компании, которому личная запись не принадлежит."""
    роль = "admin" if admin else "user"
    u = User(email=f"{роль}-{uuid.uuid4().hex[:8]}@test.local",
             name=f"Посторонний {роль}", role="user", password_hash="!нет")
    db.add(u)
    await db.flush()
    db.add(UserCompany(user_id=u.id, company_id=uuid.UUID(cid), role=роль))
    await db.commit()
    return u


async def _личная(client, cid: str) -> str:
    r = await client.post("/api/tasks", json={
        "company_id": cid, "title": "Личное: пароль от сейфа",
        "description": "текст, которого никто не должен увидеть",
        "visibility": "personal"})
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def test_посторонний_не_меняет_видимость_чужой_записи(auth_client, db):
    """Главный случай дыры, сквозь всю ручку.

    Проверяем не функцию права, а сам запрос: посторонний шлёт реплику вместе с
    `visibility` — ровно то тело, которым запись открывали всей компании.
    """
    cid = await _company(auth_client)
    task_id = await _личная(auth_client, cid)
    чужак = await _чужой(db, cid)

    with _как(чужак):
        r = await auth_client.post(f"/api/tasks/{task_id}/action", json={
            "company_id": cid, "note": "привет", "visibility": "company"})

    # Именно 404: 403 подтвердил бы, что запись существует.
    assert r.status_code == 404, r.text
    # И текста записи в ответе быть не должно ни при каком исходе.
    assert "пароль от сейфа" not in r.text

    t = await db.get(Task, uuid.UUID(task_id))
    await db.refresh(t)
    assert t.visibility == "personal", "видимость личной записи изменилась"


async def test_посторонний_не_дописывает_реплику_в_чужую_запись(auth_client, db):
    """Даже голая реплика: ручка спрашивает право просмотра, а раньше не
    спрашивала вовсе — и возвращала в ответе всю карточку."""
    cid = await _company(auth_client)
    task_id = await _личная(auth_client, cid)
    чужак = await _чужой(db, cid)

    with _как(чужак):
        r = await auth_client.post(f"/api/tasks/{task_id}/action", json={
            "company_id": cid, "note": "это уже сделано"})
    assert r.status_code == 404, r.text
    assert "пароль от сейфа" not in r.text


async def test_администратор_личную_запись_не_трогает(auth_client, db):
    """У администратора исключения нет. Кадровое поручение он видеть обязан,
    личную заметку — нет, и на изменении это правило то же самое."""
    cid = await _company(auth_client)
    task_id = await _личная(auth_client, cid)
    админ = await _чужой(db, cid, admin=True)
    t = await db.get(Task, uuid.UUID(task_id))

    with pytest.raises(HTTPException) as exc:
        await tasks_router._assert_actor(db, uuid.UUID(cid), админ, t)
    assert exc.value.status_code == 404


async def test_суперадминистратор_тоже_не_трогает(auth_client, db):
    cid = await _company(auth_client)
    task_id = await _личная(auth_client, cid)
    сa = await _чужой(db, cid)
    сa.is_superadmin = True
    await db.commit()
    t = await db.get(Task, uuid.UUID(task_id))

    with pytest.raises(HTTPException) as exc:
        await tasks_router._assert_actor(db, uuid.UUID(cid), сa, t)
    assert exc.value.status_code == 404


async def test_автор_свою_запись_меняет(auth_client, db):
    """Обратная сторона: правило не должно запереть саму хозяйку записи."""
    cid = await _company(auth_client)
    task_id = await _личная(auth_client, cid)
    r = await auth_client.post(f"/api/tasks/{task_id}/action", json={
        "company_id": cid, "visibility": "company", "note": "отдаю в работу"})
    assert r.status_code == 200, r.text
    assert r.json()["visibility"] == "company"


async def test_посторонний_не_видит_запись_через_ручку_действия(auth_client, db):
    """Даже одна реплика не проходит: ручка спрашивает право просмотра."""
    cid = await _company(auth_client)
    task_id = await _личная(auth_client, cid)
    чужак = await _чужой(db, cid)
    t = await db.get(Task, uuid.UUID(task_id))
    assert await tasks_router._can_view_task(
        db, uuid.UUID(cid), чужак, t) is False


@pytest.mark.parametrize("поле,значение", [
    ("visibility", "company"),
    ("project_id", None),
    ("sprint_id", ""),
    ("estimate", "4ч"),
    ("fix_version_id", ""),
    ("found_version_id", ""),
])
async def test_ни_одно_поле_не_проходит_как_реплика(поле, значение):
    """«Только реплика» считается структурно, а не перечислением имён.

    Прежний список отстал от модели на шесть полей, и каждое из них проезжало
    мимо проверки права, если прислать его вместе с репликой. Новое поле в
    `TaskAction` теперь закрыто по умолчанию, а не до тех пор, пока о нём
    вспомнят, — это и проверяется.
    """
    payload = tasks_router.TaskAction(
        company_id=str(uuid.uuid4()), note="реплика", **{поле: значение})
    выставлено = payload.model_fields_set - {"company_id", "note"}
    assert выставлено, f"поле {поле} не считается действием над задачей"


async def test_голая_реплика_остаётся_репликой():
    """Правило не должно затянуться: коллега, заметивший «это уже сделано»,
    по-прежнему пишет в задачу, которую видит, не будучи её участником."""
    payload = tasks_router.TaskAction(
        company_id=str(uuid.uuid4()), note="это уже сделано")
    assert not (payload.model_fields_set - {"company_id", "note"})


async def test_запись_без_срока_срока_не_получает(auth_client, db):
    """«Без срока — заметка». Тип поручения умеет подставлять срок по умолчанию,
    и для работы компании это верно; личной записи он молча превращал мысль в
    обязательство, о котором потом напоминал."""
    cid = await _company(auth_client)
    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Мысль без срока", "visibility": "personal"})
    assert r.status_code in (200, 201), r.text
    assert r.json()["due_at"] is None, "личной записи подставили срок"


async def test_датированная_запись_видна_в_моих_сроках(auth_client, db):
    """«Со сроком — дело»: как только у записи появился срок, она обязана быть
    там, где человек смотрит свои обязательства. Разрез `my_due` кормит
    календарь, и общий отсев «не личное» отменял его смысл целиком."""
    cid = await _company(auth_client)
    r = await auth_client.post("/api/tasks", json={
        "company_id": cid, "title": "Запись, ставшая делом",
        "visibility": "personal", "due_at": "2030-01-15T12:00:00Z"})
    assert r.status_code in (200, 201), r.text
    tid = r.json()["id"]

    q = await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "my_due", "limit": 200})
    assert q.status_code == 200, q.text
    номера = [t["id"] for t in q.json()["tasks"]]
    assert tid in номера, "датированная запись не попала в «мои сроки»"

    # И обратная сторона: в общих разрезах её по-прежнему нет.
    o = await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "open", "limit": 200})
    assert tid not in [t["id"] for t in o.json()["tasks"]],         "личная запись попала в общий разрез"
