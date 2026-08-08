"""Управляемая политика «Магазина» и эффективные бизнес-полномочия."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import get_current_user
from app.business_access import (
    ROLE_STATION_ADMINISTRATOR,
    STORE_POLICY_KEY,
    has_network_merchandiser,
    new_store_policy,
    store_policy,
)
from app.database import get_db
from app.deps import scope_company_id
from app.models import Company, User, UserCompany
from app.routers.users_router import require_company_admin
from app.services.station_roster import refresh_company_rosters

router = APIRouter(prefix="/store/access-policy", tags=["Магазин — доступ"])


class StorePolicyUpdate(BaseModel):
    commercial_owner: str = "station"


async def _payload(db: AsyncSession, company: Company, user: User) -> dict:
    membership = await db.get(UserCompany, (user.id, company.id))
    grants = list(getattr(membership, "business_grants", None) or []) if membership else []
    policy = store_policy(company.customization)
    station_ids = sorted({
        str(g.get("scope_id")) for g in grants
        if g.get("role") == ROLE_STATION_ADMINISTRATOR
        and g.get("scope_type") == "station"
    })
    return {
        **policy,
        "business_grants": grants,
        "capabilities": {
            "station_administrator": station_ids,
            "network_merchandiser": has_network_merchandiser(grants, company.slug),
            # v1: центр наблюдает и предлагает, коммерческие решения исполняет АЗС.
            "central_commercial_write": False,
        },
    }


@router.get("")
async def get_store_access_policy(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cid = await scope_company_id(user, db)
    company = await db.get(Company, cid)
    if company is None:
        raise HTTPException(404, "Организация не найдена")
    return await _payload(db, company, user)


@router.put("")
async def update_store_access_policy(
    body: StorePolicyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    cid = await scope_company_id(user, db)
    await require_company_admin(str(cid), user, db)
    if body.commercial_owner != "station":
        raise HTTPException(
            409,
            "Сетевое управление товарами ещё не включено: сначала нужны правила "
            "по категориям/карточкам и безопасное разрешение конфликтов",
        )
    company = await db.get(Company, cid)
    if company is None:
        raise HTTPException(404, "Организация не найдена")
    policy = new_store_policy()
    company.customization = {**(company.customization or {}), STORE_POLICY_KEY: policy}
    await log_audit(
        db, actor=user, company_id=cid, action="store.access_policy",
        target=company.slug, details=policy,
    )
    await refresh_company_rosters(db, cid)
    await db.commit()
    return await _payload(db, company, user)
