"""Личная запись видна только автору — и никому больше.

Единственная логика этого раздела, поломка которой не выглядит поломкой:
экран не падает, ошибки в логе нет, просто чужая записная книжка появляется в
реестре компании. Поэтому проверяется отдельно и со стороны каждого списка,
который её мог бы показать.

Ловим ровно то, из-за чего условие видимости и переписывалось: оно было
написано через отрицание (`visibility != "private"`), и для любого нового
значения такое выражение истинно — то есть добавление уровня «личное» само по
себе раскрывало бы все личные записи.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Task, User, UserCompany

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _second_person(db: AsyncSession, cid: uuid.UUID) -> User:
    """Второй человек той же компании — не автор записи."""
    other = (await db.execute(
        select(User).join(UserCompany, UserCompany.user_id == User.id)
        .where(UserCompany.company_id == cid, User.email != "admin@clearledger.ru")
        .limit(1))).scalars().first()
    if other is None:
        other = User(email=f"other-{uuid.uuid4().hex[:8]}@test.local",
                     name="Второй сотрудник", role="user",
                     password_hash="!test", company_id=cid)
        db.add(other)
        await db.flush()
        db.add(UserCompany(user_id=other.id, company_id=cid, role="user"))
        await db.commit()
    return other


async def test_личная_запись_не_видна_чужим(auth_client: AsyncClient, db: AsyncSession):
    from tests.helpers import seed_company_id

    me = (await auth_client.get("/api/auth/me")).json()
    cid = uuid.UUID(seed_company_id(me))
    author = (await db.execute(
        select(User).where(User.email == "admin@clearledger.ru"))).scalars().one()
    other = await _second_person(db, cid)

    note = Task(company_id=cid, title=f"Личная запись {uuid.uuid4().hex[:6]}",
                author_id=author.id, visibility="personal", status="open")
    db.add(note)
    await db.commit()

    from app.routers.tasks_router import _can_view_task, _visible_to

    # Автор своё видит.
    assert await _can_view_task(db, cid, author, note) is True
    seen = (await db.execute(select(Task.id).where(
        Task.company_id == cid, _visible_to(author, False), Task.id == note.id))).all()
    assert seen, "автор не видит собственную запись"

    # Второй сотрудник — нет.
    assert await _can_view_task(db, cid, other, note) is False
    hidden = (await db.execute(select(Task.id).where(
        Task.company_id == cid, _visible_to(other, False), Task.id == note.id))).all()
    assert not hidden, "личная запись видна постороннему"

    # Администратор пространства — тоже нет: иначе слово «личное» неправда.
    # Приватное (кадровое, денежное) он по-прежнему видит — это разные вещи.
    assert await _can_view_task(db, cid, other, note) is False
    admin_sees = (await db.execute(select(Task.id).where(
        Task.company_id == cid, _visible_to(other, True), Task.id == note.id))).all()
    assert not admin_sees, "администратор читает чужую личную запись"

    private = Task(company_id=cid, title="Кадровое поручение",
                   author_id=author.id, visibility="private", status="open")
    db.add(private)
    await db.commit()
    admin_private = (await db.execute(select(Task.id).where(
        Task.company_id == cid, _visible_to(other, True), Task.id == private.id))).all()
    assert admin_private, "администратор перестал видеть приватное — сломали не то"

    await db.execute(Task.__table__.delete().where(Task.id.in_([note.id, private.id])))
    await db.commit()


async def test_личное_не_попадает_в_работу_компании(auth_client: AsyncClient, db: AsyncSession):
    """Право видеть своё есть, но в ленте компании и в счётчиках личного нет:
    иначе записная книжка одного человека раздувает показатели всем."""
    from tests.helpers import seed_company_id

    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)
    author = (await db.execute(
        select(User).where(User.email == "admin@clearledger.ru"))).scalars().one()

    note = Task(company_id=uuid.UUID(cid), title=f"Заметка {uuid.uuid4().hex[:6]}",
                author_id=author.id, visibility="personal", status="open")
    db.add(note)
    await db.commit()

    # Список задач без параметра отвечает про работу компании.
    common = await auth_client.get("/api/tasks", params={"company_id": cid, "scope": "all"})
    assert common.status_code == 200, common.text
    assert str(note.id) not in [t["id"] for t in common.json()["tasks"]], \
        "личная запись попала в общий список задач"

    # С явным запросом — своя лента.
    personal = await auth_client.get("/api/tasks", params={
        "company_id": cid, "scope": "all", "visibility": "personal"})
    assert personal.status_code == 200, personal.text
    assert str(note.id) in [t["id"] for t in personal.json()["tasks"]], \
        "личная лента не показывает собственную запись"

    # Лента работы компании.
    work = await auth_client.get("/api/work", params={"company_id": cid, "scope": "all"})
    assert work.status_code == 200, work.text
    assert str(note.id) not in [w["id"] for w in work.json()["work"]], \
        "личная запись попала в ленту работы компании"

    await db.execute(Task.__table__.delete().where(Task.id == note.id))
    await db.commit()
