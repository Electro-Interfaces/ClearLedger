"""Совместное владение коммерческими данными: правят и центр, и станция.

Раньше режим был жёстко «station»: центральный редактор рецептур был написан,
но всегда отдавал 409, а проверка роли «Товаровед сети» стояла ПОСЛЕ отказа и
потому не помогала никому, включая суперадмина.
"""
import uuid

import pytest
from fastapi import HTTPException

from app.business_access import (
    OWNER_SHARED,
    OWNER_STATION,
    STORE_POLICY_KEY,
    new_store_policy,
    store_policy,
)
from app.routers.store_router import _require_central_commercial_control


class _Company:
    def __init__(self, owner):
        self.id = uuid.uuid4()
        self.slug = "gig"
        self.customization = (
            {STORE_POLICY_KEY: {"commercial_owner": owner}} if owner else {}
        )


class _Membership:
    def __init__(self, grants):
        self.business_grants = grants


class _Session:
    def __init__(self, company, membership):
        self.company = company
        self.membership = membership

    async def get(self, model, key):
        return self.company if model.__name__ == "Company" else self.membership


ТОВАРОВЕД = [{"role": "network_merchandiser", "scope_type": "network",
              "scope_id": "gig"}]


@pytest.fixture(autouse=True)
def _область(monkeypatch):
    async def scope(user, db):
        return db.company.id
    monkeypatch.setattr("app.routers.store_router.scope_company_id", scope)


class _User:
    id = uuid.uuid4()


async def _проверить(owner, grants):
    компания = _Company(owner)
    сессия = _Session(компания, _Membership(grants))
    return await _require_central_commercial_control(_User(), сессия)


def test_umolchanie_stanciya():
    """Молча включать запись центра нельзя — станция ближе к товару."""
    assert store_policy(None)["commercial_owner"] == OWNER_STATION
    assert store_policy({})["commercial_owner"] == OWNER_STATION


def test_opechatka_ne_otkryvaet_zapis():
    """Fail-closed: неизвестный режим читается как «станция»."""
    политика = store_policy({STORE_POLICY_KEY: {"commercial_owner": "central"}})
    assert политика["commercial_owner"] == OWNER_STATION
    assert new_store_policy("что-то")["commercial_owner"] == OWNER_STATION


@pytest.mark.asyncio
async def test_stanciya_zapreshchaet_zapis_centra():
    with pytest.raises(HTTPException) as ошибка:
        await _проверить(OWNER_STATION, ТОВАРОВЕД)
    assert ошибка.value.status_code == 409


@pytest.mark.asyncio
async def test_shared_razreshaet_tovarovedu_seti():
    assert await _проверить(OWNER_SHARED, ТОВАРОВЕД) is not None


@pytest.mark.asyncio
async def test_shared_bez_roli_ne_puskaet():
    """Совместный режим открывает дверь, но не отменяет роль."""
    with pytest.raises(HTTPException) as ошибка:
        await _проверить(OWNER_SHARED, [])
    assert ошибка.value.status_code == 403


@pytest.mark.asyncio
async def test_administrator_azs_ne_stanovitsya_tovarovedom_seti():
    grants = [{"role": "station_administrator", "scope_type": "station",
               "scope_id": "208"}]
    with pytest.raises(HTTPException) as ошибка:
        await _проверить(OWNER_SHARED, grants)
    assert ошибка.value.status_code == 403
