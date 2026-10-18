"""Смена email не меняет идентичность оператора в приложении."""
import uuid

import pytest
from sqlalchemy import select

from app.models import App, Company, User, UserCompany
from app.services import app_registry
from app.services.space_projection import _users_payload

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_projected_user_keeps_core_identity_after_email_change(db):
    await app_registry.seed_apps(db)
    app = (await db.execute(select(App).where(App.code == "support"))).scalar_one()
    own = (await db.execute(select(Company.id).where(Company.slug == "gig"))).scalar_one()
    foreign = (await db.execute(select(Company.id).where(Company.slug == "rushydro"))).scalar_one()
    tag = uuid.uuid4().hex[:8]
    operator = User(email=f"operator-before-{tag}@example.test", name="Тестовый оператор", password_hash="x")
    outsider = User(email=f"operator-other-{tag}@example.test", name="Другой оператор", password_hash="x")
    db.add_all([operator, outsider])
    await db.flush()
    db.add_all([
        UserCompany(user_id=operator.id, company_id=own, role="user", app_roles={"support": "operator"}),
        UserCompany(user_id=outsider.id, company_id=foreign, role="user"),
    ])
    await db.commit()
    before = await _users_payload(db, own, app, "support")
    projected = next(u for u in before if u["ecoUserId"] == str(operator.id))
    assert projected["email"] == operator.email and projected["role"] == "operator"
    assert all(u["ecoUserId"] != str(outsider.id) for u in before)

    operator.email = f"operator-after-{tag}@example.test"
    await db.commit()
    after = await _users_payload(db, own, app, "support")
    same = [u for u in after if u["ecoUserId"] == str(operator.id)]
    assert len(same) == 1 and same[0]["email"] == operator.email
    assert same[0]["role"] == "operator"
