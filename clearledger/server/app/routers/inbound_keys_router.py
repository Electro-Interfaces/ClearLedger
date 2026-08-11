"""
Именные входящие ключи пространства (docs/CONNECT.md, В2).

Ключ = потребитель: «Дедуп-нода АЗС 208», «Аудитор Поддержки». В базе — только
SHA256-хеш; сам ключ отдаётся ОДИН раз при выдаче (как ссылка приглашения).
Отзыв — мгновенный и точечный: остальные потребители продолжают работать.
Легаси-ключ компании (companies.cloud_api_key) живёт параллельно, пока внешние
узлы не переведены; его видно в витрине подключений.
"""
import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import get_current_user
from app.database import get_db
from app.models import EdgeAgent, SpaceInboundKey, User
from app.routers.users_router import require_company_admin

router = APIRouter(prefix="/inbound-keys", tags=["Входящие ключи"])


class InboundKeyCreate(BaseModel):
    company_id: str
    consumer: str = Field(min_length=2, max_length=200)
    station_id: int | None = Field(default=None, gt=0)


@router.get("")
async def list_keys(
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cid = await require_company_admin(company_id, current_user, db)
    rows = (await db.execute(
        select(SpaceInboundKey).where(SpaceInboundKey.company_id == cid)
        .order_by(SpaceInboundKey.created_at.desc())
    )).scalars().all()
    return {"keys": [{
        "id": str(k.id), "consumer": k.consumer, "prefix": k.key_prefix,
        "station_id": k.station_id,
        "created_at": k.created_at.isoformat() if k.created_at else None,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
    } for k in rows]}


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_key(
    payload: InboundKeyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Выдать ключ потребителю. Сам ключ — только в этом ответе, дальше лишь хеш."""
    cid = await require_company_admin(payload.company_id, current_user, db)
    if payload.station_id is not None:
        agent = (await db.execute(select(EdgeAgent.id).where(
            EdgeAgent.company_id == cid,
            EdgeAgent.station_id == payload.station_id,
        ))).scalar_one_or_none()
        if agent is None:
            raise HTTPException(409, "Сначала зарегистрируйте EdgeAgent этой станции")
        occupied = (await db.execute(select(SpaceInboundKey.id).where(
            SpaceInboundKey.company_id == cid,
            SpaceInboundKey.station_id == payload.station_id,
            SpaceInboundKey.revoked_at.is_(None),
        ))).scalar_one_or_none()
        if occupied is not None:
            raise HTTPException(409, "У станции уже есть активный именной ключ")
    raw = secrets.token_urlsafe(32)
    key = SpaceInboundKey(
        id=uuid.uuid4(), company_id=cid, consumer=payload.consumer.strip(),
        key_hash=hashlib.sha256(raw.encode()).hexdigest(), key_prefix=raw[:8],
        station_id=payload.station_id,
    )
    db.add(key)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="inbound_key.create", target=key.consumer)
    await db.flush()
    return {"id": str(key.id), "consumer": key.consumer, "key": raw,
            "prefix": key.key_prefix, "station_id": key.station_id}


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_key(
    key_id: str,
    company_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Отозвать ключ: строка остаётся в списке с отметкой — история выдач видна."""
    cid = await require_company_admin(company_id, current_user, db)
    try:
        kid = uuid.UUID(key_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невалидный ID")
    key = await db.get(SpaceInboundKey, kid)
    if key is None or key.company_id != cid:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Ключ не найден")
    key.revoked_at = datetime.now(timezone.utc)
    await log_audit(db, actor=current_user, company_id=cid,
                    action="inbound_key.revoke", target=key.consumer)
