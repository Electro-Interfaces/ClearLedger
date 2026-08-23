"""Корректировки документов перед выгрузкой в 1С — работа бухгалтера.

Ручки живут в бухгалтерском контуре, а не в «Магазине»: там витрина факта,
одинаковая со станцией, и правки в ней быть не должно. Ответственность за то,
что уйдёт в проводку, несёт бухгалтерия — она и правит.

Канон: `docs/Корректировки_ОРП_перед_выгрузкой.md`.
"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_module, get_current_user
from app.database import get_db
from app.models import User
from app.deps import scope_company_id
from app.services.accounting_adjustment import (
    AdjustmentError,
    завести_корректировку,
    история_корректировок,
    наложить,
    отменить_корректировку,
    список_корректировок,
    хеш_документа,
)

router = APIRouter(prefix="/accounting/adjustments", tags=["Бухгалтерия · корректировки"])


class ПравкаIn(BaseModel):
    """Одна правка документа: что меняем и почему."""

    shift_key: str = Field(..., description="Смена: GUID или «дата|станция»")
    doc_kind: str = Field(..., description="Вид документа пакета, напр. retail_sale_sidegoods")
    document_id: str = Field("", description="Идентификатор документа внутри пакета")
    base_content_hash: str = Field(..., description="Хеш версии факта, на которой сделана правка")
    patch: dict = Field(..., description="{Строки: [...], Шапка: {...}}")
    reason: str = Field(..., description="Почему правим. Обязательно")


async def _доступ(user: User, db: AsyncSession) -> uuid.UUID:
    """Право на бухгалтерию: корректировка — её решение, не товароведа."""
    company_id = await scope_company_id(user, db)
    await assert_company_module(str(company_id), user, db, "ledger")
    return company_id


@router.get("")
async def список(
    shift_key: str = Query(..., description="Смена"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Действующие правки смены и полная история, включая отменённые."""
    company_id = await _доступ(user, db)
    правки = await список_корректировок(db, company_id, shift_key)
    история = await история_корректировок(db, company_id, shift_key)
    return {
        "действующие": [
            {
                "id": str(п.id), "doc_kind": п.doc_kind, "document_id": п.document_id,
                "patch": п.patch, "reason": п.reason, "author": п.author,
                "created_at": п.created_at.isoformat() if п.created_at else None,
                "base_content_hash": п.base_content_hash,
            } for п in правки
        ],
        "история": [
            {
                **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in row.items()
                   if k not in {"created_at", "cancelled_at"}},
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "cancelled_at": row["cancelled_at"].isoformat() if row.get("cancelled_at") else None,
            } for row in история
        ],
    }


@router.get("/preview")
async def предпросмотр(
    shift_key: str = Query(..., description="Смена"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Документы смены в двух состояниях: от станции и к выгрузке.

    Оригинал берём тем же эмиттером, что собирает пакет, — иначе экран показывал
    бы одно, а в бухгалтерию уезжало другое. Хеш каждого документа отдаём сразу:
    правка обязана ссылаться на версию факта, и считать его в браузере нельзя.
    """
    from app.services.bp_export import BpPackageEmitter

    company_id = await _доступ(user, db)
    emitter = BpPackageEmitter(db, company_id)
    try:
        оригинал = await emitter.build_shift_package(shift_key)
    except ValueError as e:
        raise HTTPException(404 if "не найдена" in str(e) else 409, str(e))
    except Exception as e:
        raise HTTPException(400, f"Сборка документов смены: {e}")

    правки = await список_корректировок(db, company_id, shift_key)
    итог = наложить(оригинал, правки)
    правленые = {
        (str(д.get("Тип") or ""), str(д.get("document_id") or д.get("Номер") or "")): д
        for д in (итог.packet.get("Документы") or [])
    }

    документы = []
    for док in (оригинал.get("Документы") or []):
        ключ = (str(док.get("Тип") or ""), str(док.get("document_id") or док.get("Номер") or ""))
        стало = правленые.get(ключ, док)
        документы.append({
            "doc_kind": ключ[0],
            "document_id": ключ[1],
            "Номер": док.get("Номер"),
            "Дата": док.get("Дата"),
            "content_hash": хеш_документа(док),
            "От станции": док,
            "К выгрузке": стало,
            "Правился": bool(стало.get("Корректировка")),
        })
    return {
        "shift_key": shift_key,
        "Документы": документы,
        "Правок": len(итог.применено),
        "Устарели": [
            {"id": str(п.id), "reason": п.reason, "author": п.author}
            for п in итог.устарели
        ],
    }


@router.post("")
async def завести(
    правка: ПравкаIn = Body(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Записать правку. Оригинал не трогаем — она ложится поверх."""
    company_id = await _доступ(user, db)
    try:
        ident = await завести_корректировку(
            db, company_id,
            shift_key=правка.shift_key, doc_kind=правка.doc_kind,
            document_id=правка.document_id, base_content_hash=правка.base_content_hash,
            patch=правка.patch, reason=правка.reason,
            author=(user.email or str(user.id)),
        )
    except AdjustmentError as e:
        raise HTTPException(409, str(e))
    await db.commit()
    return {"id": str(ident), "ok": True}


@router.delete("/{adjustment_id}")
async def отменить(
    adjustment_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Отменить правку. Запись остаётся в истории — она не редактируется."""
    company_id = await _доступ(user, db)
    try:
        await отменить_корректировку(
            db, company_id, adjustment_id, author=(user.email or str(user.id)))
    except AdjustmentError as e:
        raise HTTPException(404, str(e))
    await db.commit()
    return {"ok": True}
