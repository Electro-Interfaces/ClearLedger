"""Служебные участники — не сотрудники.

«Процесс» и «Секретарь» заводятся сами и живут в составе пространства, потому
что у события должен быть автор. Но людьми они не являются: 30.08.2026 на стенде
«Процесс» стоял исполнителем двух поручений и получал за них сводку — маршрут
завёл работу, никого не назвали, и `launch_task` отдал её тому, кто завёл.

Проверка держит две границы: служебного не предложат выбрать и работа без
названного исполнителя уйдёт в «Разбор», а не на робота.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, TaskType, User
from app.services import errands, process_templates
from app.services.service_accounts import is_service_account
from tests.helpers import seed_company_id

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_служебных_не_предлагают_в_исполнители(
        auth_client: AsyncClient, db: AsyncSession):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = seed_company_id(me)

    # Учётка заводится лениво — трогаем её, чтобы она точно была в составе.
    await errands.service_actor(db, uuid.UUID(cid))
    await db.commit()

    люди = (await auth_client.get("/api/tasks/people",
                                  params={"company_id": cid})).json()["people"]
    имена = {p["name"] for p in люди}
    assert "Процесс" not in имена, (
        "служебный участник предлагается в исполнители — работу можно поручить роботу")

    состав = await auth_client.get("/api/users", params={"company_id": cid})
    if состав.status_code == 200:
        assert not any(is_service_account(type("U", (), u)())
                       for u in состав.json() if u.get("email")), (
            "служебный участник числится в составе пространства")


async def test_работа_без_исполнителя_уходит_в_разбор(db: AsyncSession):
    """Маршрут завёл работу, никого не назвали — исполнителя быть не должно."""
    компания = (await db.execute(select(Company.id).limit(1))).scalar()
    assert компания is not None, "в базе нет ни одного пространства"

    актёр = await errands.service_actor(db, компания)
    assert is_service_account(актёр), "«Процесс» перестал считаться служебным"

    # Свой тип работы: чужой мог бы нести исполнителя по умолчанию, и проверка
    # доказывала бы не то правило.
    тип = TaskType(company_id=компания, code=f"CHK{uuid.uuid4().hex[:5].upper()}",
                   name="Проверка правила", route=[{"code": "new", "name": "Заведено"}],
                   default_priority="medium")
    db.add(тип)
    await db.flush()

    шаблон = type("Шаблон", (), {
        "id": uuid.uuid4(), "company_id": компания, "type_id": тип.id,
        "title": f"Работа без исполнителя {uuid.uuid4().hex[:6]}",
        "description": None, "priority": "medium", "assignee_id": None,
        "object_id": None, "due_days": None, "checklist": None,
        "name": "проверка", "kind": "task", "doc_kind_id": None,
    })()

    задача, _ = await process_templates.launch_task(
        db, компания, шаблон, актёр, title=None, responsible_id=None,
        object_id=None, source_ref=None, source_note="проверка правила")
    await db.commit()

    assert задача.assignee_id is None, (
        "работа без названного исполнителя досталась служебному участнику "
        "вместо «Разбора»")


async def test_домен_опознаётся():
    """Опознание по домену — единственный признак; сломается оно молча."""
    assert is_service_account(User(email="process@space.local", name="Процесс"))
    assert is_service_account(User(email="secretary@space.local", name="Секретарь"))
    assert not is_service_account(User(email="mag@dataworker.ru", name="МАГ"))
    assert not is_service_account(None)
