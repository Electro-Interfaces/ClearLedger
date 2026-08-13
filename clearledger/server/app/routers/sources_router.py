"""
Роутер экземпляров ИСТОЧНИКОВ (`Source`).

Из записи справочника типов (`/source-types`) создаётся экземпляр Source,
привязанный к компании: не-секретные поля → `Source.connection_config`,
секретные (setup_schema.secret=True) → `SourceCredentials` (Fernet).
Секреты НИКОГДА не возвращаются наружу — только список заданных ключей.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import get_adapter
from app.auth import assert_company_member, get_current_user
from app.routers.users_router import require_company_admin
from app.database import get_db
from app.deps import CompanyDep, get_owned
from app.models import Source, SourceCredentials, User
from app.services.onec.crypto import decrypt_password, encrypt_password

router = APIRouter(prefix="/sources", tags=["sources"])


# ---------------------------------------------------------------------------
# Контракты
# ---------------------------------------------------------------------------
class SourceCreate(BaseModel):
    company_id: str
    source_type: str
    name: str
    description: str | None = None
    config: dict[str, Any] = {}   # все поля формы (секретные + нет) вперемешку


class SourceUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None


class SourceResponse(BaseModel):
    id: str
    company_id: str
    source_type: str
    name: str
    description: str | None
    status: str
    connection_config: dict[str, Any]
    configured_secrets: list[str]   # какие секреты заданы (без значений)
    last_test_at: str | None
    error_message: str | None


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _secret_keys(source_type: str) -> set[str]:
    """Ключи setup_schema, помеченные secret — едут в SourceCredentials."""
    cls = get_adapter(source_type)
    return {f.key for f in cls.setup_schema if f.secret}


def _require_adapter(source_type: str):
    try:
        return get_adapter(source_type)
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Тип источника '{source_type}' не найден в справочнике (/source-types)",
        )


def _split_config(source_type: str, config: dict) -> tuple[dict, dict]:
    """(connection_config без секретов, secrets для шифрования).

    Поля, которых нет в схеме типа, отбрасываем. Иначе клиент, приславший пароль под
    своим именем (`password` вместо `api_password`), клал бы его в открытый
    `connection_config` — и получал обратно в ответе GET.
    """
    cls = get_adapter(source_type)
    known = {f.key for f in cls.setup_schema}
    sk = _secret_keys(source_type)
    public = {k: v for k, v in config.items() if k in known and k not in sk}
    secrets = {k: v for k, v in config.items() if k in sk and v not in (None, "")}
    return public, secrets


async def _creds(db: AsyncSession, source_id: uuid.UUID) -> SourceCredentials | None:
    res = await db.execute(
        select(SourceCredentials).where(SourceCredentials.source_id == source_id)
    )
    return res.scalar_one_or_none()


def _resp(src: Source, secret_keys: list[str]) -> SourceResponse:
    return SourceResponse(
        id=str(src.id),
        company_id=str(src.company_id),
        source_type=src.source_type,
        name=src.name,
        description=src.description,
        status=src.status,
        connection_config=src.connection_config or {},
        configured_secrets=sorted(secret_keys),
        last_test_at=src.last_test_at.isoformat() if src.last_test_at else None,
        error_message=src.error_message,
    )


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------
@router.post("", response_model=SourceResponse)
async def create_source(
    payload: SourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Создать источник из записи справочника и привязать к компании."""
    _require_adapter(payload.source_type)
    # Источник — это доступы во внешнюю систему компании (адреса, логины, ключи).
    # Заводить и править их может администратор организации, а не любой участник:
    # раньше рядовой член компании и внешний подрядчик создавали и удаляли источники.
    cid = await require_company_admin(payload.company_id, current_user, db)

    public, secrets = _split_config(payload.source_type, payload.config)
    src = Source(
        company_id=cid,
        source_type=payload.source_type,
        name=payload.name,
        description=payload.description,
        status="draft",
        connection_config=public,
    )
    db.add(src)
    await db.flush()  # получить src.id

    if secrets:
        db.add(SourceCredentials(
            source_id=src.id,
            encrypted_values={k: encrypt_password(str(v)) for k, v in secrets.items()},
        ))
    await db.flush()
    return _resp(src, list(secrets.keys()))


@router.get("", response_model=list[SourceResponse])
async def list_sources(
    cid: CompanyDep,
    db: AsyncSession = Depends(get_db),
):
    """Источники компании."""
    res = await db.execute(
        select(Source).where(Source.company_id == cid).order_by(Source.created_at)
    )
    out = []
    for src in res.scalars().all():
        cr = await _creds(db, src.id)
        out.append(_resp(src, list((cr.encrypted_values or {}).keys()) if cr else []))
    return out


@router.get("/{source_id}", response_model=SourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    src = await get_owned(Source, source_id, current_user, db)
    cr = await _creds(db, src.id)
    return _resp(src, list((cr.encrypted_values or {}).keys()) if cr else [])


@router.patch("/{source_id}", response_model=SourceResponse)
async def update_source(
    source_id: uuid.UUID,
    payload: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    src = await get_owned(Source, source_id, current_user, db)
    await require_company_admin(str(src.company_id), current_user, db)
    if payload.name is not None:
        src.name = payload.name
    if payload.description is not None:
        src.description = payload.description
    if payload.config is not None:
        public, secrets = _split_config(src.source_type, payload.config)
        # merge публичные поля
        src.connection_config = {**(src.connection_config or {}), **public}
        if secrets:
            cr = await _creds(db, src.id)
            enc = {k: encrypt_password(str(v)) for k, v in secrets.items()}
            if cr:
                cr.encrypted_values = {**(cr.encrypted_values or {}), **enc}
            else:
                db.add(SourceCredentials(source_id=src.id, encrypted_values=enc))
    await db.flush()
    cr = await _creds(db, src.id)
    return _resp(src, list((cr.encrypted_values or {}).keys()) if cr else [])


@router.delete("/{source_id}")
async def delete_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    src = await get_owned(Source, source_id, current_user, db)
    await require_company_admin(str(src.company_id), current_user, db)
    await db.delete(src)  # SourceCredentials каскадом (FK ondelete=CASCADE)
    return {"deleted": str(source_id)}


@router.post("/{source_id}/test")
async def test_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Проверить подключение источника (через адаптер)."""
    src = await get_owned(Source, source_id, current_user, db)
    await require_company_admin(str(src.company_id), current_user, db)
    adapter = _require_adapter(src.source_type)()

    # connection = публичные поля + расшифрованные секреты
    connection: dict[str, Any] = dict(src.connection_config or {})
    cr = await _creds(db, src.id)
    if cr:
        for k, token in (cr.encrypted_values or {}).items():
            connection[k] = decrypt_password(token)

    result = await adapter.test_connection(connection)
    planned = getattr(adapter, "status", "available") == "planned"
    # Запланированный источник: тест не ошибка — статус не понижаем (остаётся draft).
    if not planned:
        src.status = "connected" if result.ok else "error"
        src.error_message = None if result.ok else result.message
    src.last_test_at = datetime.now(timezone.utc)
    await db.flush()
    return {"ok": result.ok, "message": result.message, "details": result.details,
            "planned": planned}
