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
    журнал_за_период,
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
    from app.services.bp_export import BpPackageEmitter

    company_id = await _доступ(user, db)
    # Оригинал берём сами: значения «было» и влияние на сумму должны быть
    # настоящими, а не тем, что прислал браузер. Заодно это вторая проверка
    # версии факта — если хеш не сойдётся, правку не примем вовсе.
    try:
        пакет = await BpPackageEmitter(db, company_id).build_shift_package(правка.shift_key)
    except Exception as e:
        raise HTTPException(409, f"Документы смены не собрались: {e}")
    документ = None
    for д in (пакет.get("Документы") or []):
        ключ = str(д.get("document_id") or д.get("Номер") or "")
        if str(д.get("Тип") or "") == правка.doc_kind and ключ == правка.document_id:
            документ = д
            break
    if документ is None:
        raise HTTPException(409, "Документ в смене не найден — возможно, её пересобрали")
    if хеш_документа(документ) != правка.base_content_hash:
        raise HTTPException(
            409,
            "Документ изменился с тех пор, как открыли экран. Обновите страницу: "
            "правка должна опираться на актуальную версию факта",
        )
    смена = пакет.get("Смена") or {}
    станция = str(смена.get("КодАЗС") or "").strip()
    try:
        ident = await завести_корректировку(
            db, company_id,
            shift_key=правка.shift_key, doc_kind=правка.doc_kind,
            document_id=правка.document_id, base_content_hash=правка.base_content_hash,
            patch=правка.patch, reason=правка.reason,
            author=(user.email or str(user.id)),
            оригинал=документ,
            station_id=int(станция) if станция.isdigit() else None,
            business_date=str(смена.get("Открытие") or "")[:10] or None,
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


@router.get("/journal")
async def журнал(
    date_from: str = Query(..., description="с даты, YYYY-MM-DD"),
    date_to: str = Query(..., description="по дату включительно"),
    station_id: int | None = Query(None, description="сузить до одной АЗС"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Все правки за период: что меняли, кто, почему и на какую сумму.

    Отменённые входят намеренно: журнал отвечает на вопрос «что делали», а не
    «что осталось». Отменённая правка объясняет, почему цифра сначала
    изменилась, а потом вернулась.
    """
    company_id = await _доступ(user, db)
    записи = await журнал_за_период(
        db, company_id, date_from=date_from, date_to=date_to, station_id=station_id)

    строки = []
    сумма_влияния = 0.0
    действующих = 0
    for r in записи:
        дельта = float(r["amount_delta"] or 0)
        if r["status"] == "applied":
            сумма_влияния += дельта
            действующих += 1
        строки.append({
            "id": str(r["id"]),
            "shift_key": r["shift_key"],
            "station_id": r["station_id"],
            "business_date": r["business_date"].isoformat() if r["business_date"] else None,
            "doc_kind": r["doc_kind"],
            "document_id": r["document_id"],
            "patch": r["patch"],
            "prev_values": r["prev_values"],
            "amount_delta": дельта,
            "reason": r["reason"],
            "author": r["author"],
            "status": r["status"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "cancelled_at": r["cancelled_at"].isoformat() if r["cancelled_at"] else None,
            "cancelled_by": r["cancelled_by"],
        })
    return {
        "Записи": строки,
        "Всего": len(строки),
        "Действующих": действующих,
        "ВлияниеНаСумму": round(сумма_влияния, 2),
        "Авторы": sorted({r["author"] for r in записи if r["author"]}),
    }
