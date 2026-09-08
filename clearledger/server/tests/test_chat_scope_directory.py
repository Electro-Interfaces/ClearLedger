"""Контур роли запирает не только чаты, но и справочник людей.

Проверка контакт-центра 08.09.2026 нашла живым запросом: оператор подрядчика в
общие комнаты заказчика не попадал, зато находил поиском любого его сотрудника
с почтой, должностью и последним входом и открывал карточку. Граница держалась
одним концом.

Тест ловит оба конца: поиск и карточку. Проверяется и обратное направление —
человек без контура по-прежнему видит всех, иначе сотрудник заказчика не найдёт
оператора, которому пишет.
"""
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.models import Company, CompanyRole, User, UserCompany

pytestmark = pytest.mark.asyncio(loop_scope="session")

PASSWORD = "scope-test-123"


async def _person(db: AsyncSession, cid: uuid.UUID, name: str,
                  scope: str | None) -> tuple[User, CompanyRole | None]:
    """Человек компании: с контуром роли или обычный сотрудник."""
    user = User(company_id=cid, email=f"scope-{uuid.uuid4().hex}@example.org",
                name=name, password_hash=hash_password(PASSWORD))
    db.add(user)
    await db.flush()
    role = None
    if scope:
        role = CompanyRole(company_id=cid, name=f"Роль {scope} {uuid.uuid4().hex[:6]}",
                           modules=[scope], chat_scope=scope)
        db.add(role)
        await db.flush()
    db.add(UserCompany(user_id=user.id, company_id=cid, role="company",
                       role_id=role.id if role else None, modules=[scope] if scope else None))
    await db.commit()
    return user, role


async def _headers(client: AsyncClient, email: str) -> dict[str, str]:
    resp = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_контур_не_выдаёт_справочник_чужого_контура(
        client: AsyncClient, db: AsyncSession):
    company = (await db.execute(select(Company).order_by(Company.created_at))).scalars().first()
    assert company is not None
    оператор, _ = await _person(db, company.id, "Оператор линии", "support")
    коллега, _ = await _person(db, company.id, "Второй оператор", "support")
    сотрудник, _ = await _person(db, company.id, "Сотрудник заказчика", None)

    h = await _headers(client, оператор.email)

    found = await client.get("/api/chat/users/search", headers=h)
    assert found.status_code == 200, found.text
    ids = {row["userId"] for row in found.json()}
    assert str(коллега.id) in ids, "свой по контуру должен находиться"
    assert str(сотрудник.id) not in ids, "сотрудник заказчика в справочнике оператора не место"

    card = await client.get(f"/api/chat/users/{сотрудник.id}/profile", headers=h)
    assert card.status_code == 404, "карточка не должна обходить границу поиска"

    свой = await client.get(f"/api/chat/users/{коллега.id}/profile", headers=h)
    assert свой.status_code == 200, свой.text


async def test_человек_без_контура_видит_всех(client: AsyncClient, db: AsyncSession):
    company = (await db.execute(select(Company).order_by(Company.created_at))).scalars().first()
    assert company is not None
    оператор, _ = await _person(db, company.id, "Оператор смены", "support")
    сотрудник, _ = await _person(db, company.id, "Руководитель отдела", None)

    h = await _headers(client, сотрудник.email)
    found = await client.get("/api/chat/users/search", headers=h)
    assert found.status_code == 200, found.text
    assert str(оператор.id) in {row["userId"] for row in found.json()}, \
        "ограничение одностороннее: заказчик вправе написать оператору"
