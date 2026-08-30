"""Охват надзора: за кем человек смотрит.

Правило простое, но у него три состояния и дерево, и ошибка в любом из них
означает либо чужую работу на экране, либо свою, которой не видно. Проверяется
на настоящей структуре: управление с двумя отделами внутри.
"""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, Department, User, UserCompany
from app.services import oversight

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _структура(db: AsyncSession):
    """Управление → два отдела; в каждом по человеку, у каждого свой начальник.

        Управление      (нач. Крупный)
          ├ Отдел А     (нач. Средний)   — Рядовой А
          └ Отдел Б                      — Рядовой Б
    """
    cid = (await db.execute(select(Company.id).limit(1))).scalar()
    assert cid is not None, "в базе нет ни одного пространства"
    хвост = uuid.uuid4().hex[:6]

    люди = {}
    for ключ, имя in (("крупный", "Крупный"), ("средний", "Средний"),
                      ("а", "Рядовой А"), ("б", "Рядовой Б"), ("чужой", "Чужой")):
        u = User(email=f"{ключ}-{хвост}@пример.рф", name=f"{имя} {хвост}",
                 password_hash="!нет")
        db.add(u)
        люди[ключ] = u
    await db.flush()

    управление = Department(company_id=cid, name=f"Управление {хвост}",
                            head_user_id=люди["крупный"].id)
    db.add(управление)
    await db.flush()
    отдел_а = Department(company_id=cid, name=f"Отдел А {хвост}",
                         parent_id=управление.id, head_user_id=люди["средний"].id)
    отдел_б = Department(company_id=cid, name=f"Отдел Б {хвост}",
                         parent_id=управление.id)
    db.add_all([отдел_а, отдел_б])
    await db.flush()

    места = {
        "крупный": управление.id, "средний": отдел_а.id,
        "а": отдел_а.id, "б": отдел_б.id, "чужой": None,
    }
    for ключ, u in люди.items():
        db.add(UserCompany(user_id=u.id, company_id=cid, role="user",
                           department_id=места[ключ]))
    await db.flush()
    return cid, люди


async def test_рядовой_не_надзирает_ни_за_кем(db: AsyncSession):
    cid, люди = await _структура(db)
    о = await oversight.охват(db, cid, люди["а"])
    assert not о.есть, "рядовому сотруднику раздел «Компания» не положен"
    assert not await oversight.надзирает(db, cid, люди["а"])


async def test_начальник_отдела_видит_свой_отдел(db: AsyncSession):
    cid, люди = await _структура(db)
    о = await oversight.охват(db, cid, люди["средний"])
    assert о.есть
    assert о.входит(люди["а"].id), "свой подчинённый вне охвата"
    assert о.входит(люди["средний"].id), "себя руководитель тоже надзирает"
    assert not о.входит(люди["б"].id), "соседний отдел в охват не входит"
    assert not о.входит(люди["крупный"].id), "начальник выше — не подчинённый"


async def test_начальник_управления_видит_всю_ветку(db: AsyncSession):
    """Обход вниз целиком: управление отвечает и за отделы внутри."""
    cid, люди = await _структура(db)
    о = await oversight.охват(db, cid, люди["крупный"])
    for ключ in ("а", "б", "средний", "крупный"):
        assert о.входит(люди[ключ].id), f"«{ключ}» выпал из охвата управления"
    assert not о.входит(люди["чужой"].id), "человек вне структуры не надзирается"


async def test_работа_без_исполнителя_забота_надзирающего(db: AsyncSession):
    """Она и висит потому, что её никто не взял, — значит это его вопрос."""
    cid, люди = await _структура(db)
    о = await oversight.охват(db, cid, люди["средний"])
    assert о.входит(None)
    пусто = await oversight.охват(db, cid, люди["а"])
    assert not пусто.входит(None), "рядовому бесхозная работа не адресована"


async def test_администратор_видит_всех(db: AsyncSession):
    cid, люди = await _структура(db)
    членство = await db.get(UserCompany, (люди["чужой"].id, cid))
    членство.role = "admin"
    await db.flush()
    о = await oversight.охват(db, cid, люди["чужой"])
    assert о.вся_компания
    assert о.входит(люди["а"].id)
    assert о.входит(uuid.uuid4()), "«вся компания» означает всех, включая новых"


async def test_надзирающий_вправе_вмешаться_в_своей_ветке(db: AsyncSession):
    """То, ради чего раздел и существует: увидел затык — дотянулся."""
    from app.models import Task, TaskType
    from app.routers.tasks_router import _assert_actor
    from fastapi import HTTPException

    cid, люди = await _структура(db)
    тип = TaskType(company_id=cid, code=f"OV{uuid.uuid4().hex[:5].upper()}",
                   name="Проверка надзора",
                   route=[{"code": "new", "name": "Заведено"}],
                   default_priority="medium")
    db.add(тип)
    await db.flush()
    задача = Task(company_id=cid, type_id=тип.id, title="Работа подчинённого",
                  status="open", stage_code="new", visibility="company",
                  author_id=люди["а"].id, assignee_id=люди["а"].id)
    db.add(задача)
    await db.flush()

    # Начальник отдела — вправе.
    await _assert_actor(db, cid, люди["средний"], задача)
    # Начальник управления — тоже: ветка идёт вниз целиком.
    await _assert_actor(db, cid, люди["крупный"], задача)

    # Сосед по компании — нет: охват не резиновый.
    with pytest.raises(HTTPException) as ошибка:
        await _assert_actor(db, cid, люди["чужой"], задача)
    assert ошибка.value.status_code == 403


async def test_личную_запись_не_трогает_и_надзирающий(db: AsyncSession):
    """«Личное» обязано быть правдой и для начальника."""
    from app.models import Task, TaskType
    from app.routers.tasks_router import _assert_actor
    from fastapi import HTTPException

    cid, люди = await _структура(db)
    тип = TaskType(company_id=cid, code=f"OP{uuid.uuid4().hex[:5].upper()}",
                   name="Личное", route=[{"code": "new", "name": "Заведено"}],
                   default_priority="medium")
    db.add(тип)
    await db.flush()
    запись = Task(company_id=cid, type_id=тип.id, title="Своя записка",
                  status="open", stage_code="new", visibility="personal",
                  author_id=люди["а"].id, assignee_id=люди["а"].id)
    db.add(запись)
    await db.flush()

    for кто in ("средний", "крупный"):
        with pytest.raises(HTTPException) as ошибка:
            await _assert_actor(db, cid, люди[кто], запись)
        assert ошибка.value.status_code == 404, (
            f"«{кто}» получил ответ о существовании чужой личной записи")


async def test_лента_компании_сужена_охватом(auth_client, db: AsyncSession):
    """Начальник отдела видит своих людей, а не всё пространство."""
    from app.models import Task, TaskType
    from app.auth import get_current_user
    from app.main import app

    cid, люди = await _структура(db)
    тип = TaskType(company_id=cid, code=f"SC{uuid.uuid4().hex[:5].upper()}",
                   name="Охват", route=[{"code": "new", "name": "Заведено"}],
                   default_priority="medium")
    db.add(тип)
    await db.flush()
    метка = uuid.uuid4().hex[:8]
    for ключ in ("а", "б"):
        db.add(Task(company_id=cid, type_id=тип.id,
                    title=f"[{метка}] работа {ключ}", status="open",
                    stage_code="new", visibility="company",
                    author_id=люди[ключ].id, assignee_id=люди[ключ].id))
    await db.commit()

    async def лента(кто):
        app.dependency_overrides[get_current_user] = lambda: кто
        try:
            r = await auth_client.get("/api/work", params={
                "company_id": str(cid), "scope": "open", "limit": 200})
        finally:
            app.dependency_overrides.pop(get_current_user, None)
        return r

    # Начальник отдела А видит своего и не видит соседнего.
    r = await лента(люди["средний"])
    assert r.status_code == 200, r.text
    названия = {w["title"] for w in r.json()["work"]}
    assert f"[{метка}] работа а" in названия, "свой подчинённый не показан"
    assert f"[{метка}] работа б" not in названия, (
        "соседний отдел виден — лента не сужена охватом")

    # Начальник управления видит обоих: ветка идёт вниз целиком.
    r = await лента(люди["крупный"])
    названия = {w["title"] for w in r.json()["work"]}
    assert {f"[{метка}] работа а", f"[{метка}] работа б"} <= названия

    # Рядовому разрез не открывается вовсе — и отказ объясняет, почему.
    r = await лента(люди["а"])
    assert r.status_code == 403, "рядовой получил ленту компании"
    assert "«Моё»" in r.json().get("detail", ""), (
        "отказ не сказал, где искать свою работу"
    )


async def test_подтолкнуть_может_надзирающий_и_постановщик(auth_client, db: AsyncSession):
    """Толчок ничего не меняет в работе, но приходит человеку лично — и потому
    доступен не каждому, кто эту работу видит."""
    from app.models import Task, TaskEvent, TaskType
    from app.auth import get_current_user
    from app.main import app
    from sqlalchemy import func

    cid, люди = await _структура(db)
    тип = TaskType(company_id=cid, code=f"NU{uuid.uuid4().hex[:5].upper()}",
                   name="Толчок", route=[{"code": "new", "name": "Заведено"}],
                   default_priority="medium")
    db.add(тип)
    await db.flush()
    задача = Task(company_id=cid, type_id=тип.id, title="Работа Рядового А",
                  status="open", stage_code="new", visibility="company",
                  author_id=люди["крупный"].id, assignee_id=люди["а"].id)
    db.add(задача)
    await db.commit()
    ссылка = f"task:{задача.id}"

    async def толкнуть(кто):
        app.dependency_overrides[get_current_user] = lambda: кто
        try:
            return await auth_client.post("/api/work/nudge", json={
                "company_id": str(cid), "ref": ссылка})
        finally:
            app.dependency_overrides.pop(get_current_user, None)

    r = await толкнуть(люди["средний"])
    assert r.status_code == 200, f"начальник отдела не смог напомнить: {r.text}"
    assert r.json()["sent"] == 1

    # Постановщик — вправе всегда, даже вне охвата.
    assert (await толкнуть(люди["крупный"])).status_code == 200

    # Сосед по компании — нет.
    r = await толкнуть(люди["чужой"])
    assert r.status_code == 403, "чужой человек напомнил о не своей работе"

    # Себе не толкают: адресат совпал с нажимающим — уходить некому.
    r = await толкнуть(люди["а"])
    assert r.status_code == 403, "исполнитель напомнил сам себе"

    # След остался — ради него всё и делается.
    толчков = (await db.execute(select(func.count()).select_from(TaskEvent).where(
        TaskEvent.task_id == задача.id, TaskEvent.kind == "nudge"))).scalar()
    assert толчков == 2, f"в следе {толчков} толчков вместо двух"


async def test_толкать_некого_говорится_словами(auth_client, db: AsyncSession):
    """Работа без исполнителя ждёт в «Разборе», а не напоминания."""
    from app.models import Task, TaskType
    from app.auth import get_current_user
    from app.main import app

    cid, люди = await _структура(db)
    тип = TaskType(company_id=cid, code=f"NB{uuid.uuid4().hex[:5].upper()}",
                   name="Бесхозное", route=[{"code": "new", "name": "Заведено"}],
                   default_priority="medium")
    db.add(тип)
    await db.flush()
    задача = Task(company_id=cid, type_id=тип.id, title="Никем не взято",
                  status="open", stage_code="new", visibility="company",
                  author_id=люди["крупный"].id, assignee_id=None)
    db.add(задача)
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: люди["крупный"]
    try:
        r = await auth_client.post("/api/work/nudge", json={
            "company_id": str(cid), "ref": f"task:{задача.id}"})
    finally:
        app.dependency_overrides.pop(get_current_user, None)
    assert r.status_code == 409
    assert "Разбор" in r.json()["detail"], "отказ не сказал, где эта работа ждёт"


async def test_работа_без_типа_говорит_правду_и_чинится(auth_client, db: AsyncSession):
    """Прогон уткнулся в отказ доски, и виновато было не то, что называлось.

    Сообщение звало править маршрут («у типа „поручение“ нет стадии»), хотя
    «поручение» — запасное слово для случая, когда типа нет вообще. И исправить
    было нечем: тип задавался только при постановке.
    """
    from app.models import Task, TaskType
    from app.auth import get_current_user
    from app.main import app

    cid, люди = await _структура(db)
    админ = await db.get(UserCompany, (люди["чужой"].id, cid))
    админ.role = "admin"
    тип = TaskType(company_id=cid, code=f"TP{uuid.uuid4().hex[:5].upper()}",
                   name="Обычное поручение",
                   route=[{"code": "s1", "name": "Постановка"},
                          {"code": "s2", "name": "В работе"},
                          {"code": "s3", "name": "Проверка"}],
                   default_priority="medium")
    db.add(тип)
    await db.flush()
    сирота = Task(company_id=cid, type_id=None, title="Заведено на бегу",
                  status="open", visibility="company",
                  author_id=люди["чужой"].id, assignee_id=люди["чужой"].id)
    db.add(сирота)
    await db.commit()

    app.dependency_overrides[get_current_user] = lambda: люди["чужой"]
    try:
        r = await auth_client.post(f"/api/work/task/{сирота.id}/move",
                                   json={"company_id": str(cid), "state": "in_work"})
        assert r.status_code == 400
        деталь = r.json()["detail"]
        assert "не задан тип" in деталь, f"отказ винит не то: {деталь}"
        assert "маршрут" not in деталь.split("Задайте")[0] or "нет и маршрута" in деталь

        # И это чинится прямо здесь.
        r = await auth_client.post(f"/api/tasks/{сирота.id}/action",
                                   json={"company_id": str(cid), "type_id": str(тип.id)})
        assert r.status_code == 200, f"тип не назначился: {r.text}"

        r = await auth_client.post(f"/api/work/task/{сирота.id}/move",
                                   json={"company_id": str(cid), "state": "in_work"})
        assert r.status_code == 200, f"с типом работа всё равно не поехала: {r.text}"

        # У закрытой тип не меняют: это переписывание её истории. Проверяем
        # ДРУГИМ типом — повторное назначение того же ничего не меняет и
        # отказывать в нём было бы придиркой.
        другой = TaskType(company_id=cid, code=f"T2{uuid.uuid4().hex[:5].upper()}",
                          name="Другое поручение",
                          route=[{"code": "a", "name": "Начало"},
                                 {"code": "b", "name": "Конец"}],
                          default_priority="medium")
        db.add(другой)
        await db.commit()
        await auth_client.post(f"/api/tasks/{сирота.id}/action",
                               json={"company_id": str(cid), "status": "done"})
        r = await auth_client.post(f"/api/tasks/{сирота.id}/action",
                                   json={"company_id": str(cid), "type_id": str(другой.id)})
        assert r.status_code == 409, "у закрытой работы сменили тип"
    finally:
        app.dependency_overrides.pop(get_current_user, None)
