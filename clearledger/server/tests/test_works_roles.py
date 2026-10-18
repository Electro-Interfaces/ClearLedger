"""Производственный профиль не наследует права топливной розницы."""

import uuid

import pytest
from sqlalchemy import select

from app.access_catalog import app_allowed, module_allowed, system_roles_for
from app.models import Company, CompanyRole
from app.seed import _seed_system_roles


@pytest.mark.parametrize("name", ["Руководитель", "Специалист", "Наблюдатель"])
def test_works_roles_do_not_grant_retail_or_accounting(name):
    roles = {role["name"]: role["modules"] for role in system_roles_for("works")}
    modules = roles[name]
    for code in ("ledger", "sales", "shop", "ops", "finance", "data", "books", "revenue"):
        assert not app_allowed(modules, code), (name, code)
        assert not module_allowed(modules, code, "overview"), (name, code)
    if name == "Наблюдатель":
        assert app_allowed(modules, "pulse")
        assert not app_allowed(modules, "docs")
    else:
        assert app_allowed(modules, "docs")
        assert app_allowed(modules, "chat")


@pytest.mark.asyncio(loop_scope="session")
async def test_works_seed_replaces_unused_fuel_roles_and_preserves_custom(db):
    company = Company(name="Производственная команда", slug=f"works-{uuid.uuid4().hex}",
                      profile_id="works")
    db.add(company)
    await db.flush()
    custom = CompanyRole(company_id=company.id, name="Своя роль", modules=["docs"],
                         is_system=False)
    stale = CompanyRole(company_id=company.id, name="Товаровед", modules=["shop"],
                        is_system=True)
    observer = CompanyRole(company_id=company.id, name="Наблюдатель", modules=["sales"],
                           is_system=True)
    db.add_all([custom, stale, observer])
    await db.flush()

    await _seed_system_roles(db)
    await db.flush()
    first = (await db.scalars(select(CompanyRole).where(
        CompanyRole.company_id == company.id))).all()
    assert "Товаровед" not in {role.name for role in first}
    assert next(role for role in first if role.name == "Специалист").modules == [
        "docs", "chat", "conf"]
    assert next(role for role in first if role.name == "Полный доступ").modules is None
    assert next(role for role in first if role.name == "Наблюдатель").id == observer.id
    assert observer.modules == ["pulse"]
    assert custom.modules == ["docs"] and not custom.is_system

    await _seed_system_roles(db)
    await db.flush()
    second = (await db.scalars(select(CompanyRole).where(
        CompanyRole.company_id == company.id))).all()
    assert {role.id for role in second} == {role.id for role in first}
    await db.rollback()
