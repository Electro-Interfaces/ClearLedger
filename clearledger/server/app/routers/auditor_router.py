"""Аудитор пространства: настройки агента и след его работы.

Сам агент живёт отдельным сервисом стека (`ecosystem-deploy/services/auditor`) — он
выбирает навыки, берёт данные и разговаривает. Здесь только то, что принадлежит
ПРОСТРАНСТВУ, а не образу: чем агенту пользоваться нельзя, что он обязан помнить о
компании, в каком режиме отвечать, и что он уже отвечал.

Почему настройки в базе, а не в окружении сервиса: их правит человек в интерфейсе,
они переживают пересборку образа и попадают в бэкап пространства. В окружении
остаётся только секрет подписки.

Гейт — право на продукт `auditor`. Правка настроек — отдельно, админам: указания
агенту действуют на всех, кто его спрашивает, поэтому менять их может не каждый,
кто им пользуется.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, assert_company_product, get_current_user
from app.database import get_db
from app.models import AuditorRun, AuditorSetting, User, UserCompany

router = APIRouter(prefix="/auditor", tags=["Аудитор пространства"])

MODES = {"careful", "normal", "thorough"}


async def _is_space_admin(user: User, cid: uuid.UUID, db: AsyncSession) -> bool:
    """Админ ПРОСТРАНСТВА — по членству в этой организации, а не по `User.role`:
    глобальное поле у перенесённых с прода людей стоит как попало (та же грабля,
    что в чате: рядовые сотрудники получали управление чатами пространства)."""
    if user.is_superadmin:
        return True
    role = (await db.execute(select(UserCompany.role).where(
        UserCompany.user_id == user.id, UserCompany.company_id == cid))).scalar_one_or_none()
    return role == "admin"


class SettingsIn(BaseModel):
    disabled_skills: list[str] = Field(default_factory=list)
    instructions: str | None = None
    mode: str = "normal"
    model_plan: str | None = None
    model_answer: str | None = None


class SettingsOut(SettingsIn):
    updated_at: datetime | None = None
    # Может ли этот человек менять настройки и входить в мастерскую. Считает СЕРВЕР:
    # сервис аудитора спрашивает его же ручкой и решает, пускать ли в режим с
    # инструментами. Клиенту тут верить нельзя — он сам себе админом не назначается.
    can_manage: bool = False
    # Имя правщика — уходит в автора коммита рабочей папки агента: по истории должно быть
    # видно, кто менял знание, а не «кто-то через интерфейс».
    author_name: str | None = None
    # Кто спрашивает. Нужен агенту, чтобы взять ЛИЧНЫЙ слой знания
    # (`knowledge/people/<user_id>.md`): у разных сотрудников свои предметы, свои
    # привычные формулировки и свои договорённости с агентом. Идентификатор, а не имя:
    # имена меняются и повторяются, а файл знания привязан к учётной записи.
    user_id: str | None = None


class RunIn(BaseModel):
    question: str
    path: str | None = None
    skills: list[str] = Field(default_factory=list)
    answer: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list)
    duration_ms: int | None = None


async def _get_or_default(cid: uuid.UUID, db: AsyncSession) -> AuditorSetting | None:
    return (await db.execute(
        select(AuditorSetting).where(AuditorSetting.company_id == cid)
    )).scalar_one_or_none()


@router.get("/settings", response_model=SettingsOut)
async def get_settings(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsOut:
    """Настройки агента. Читает их и сам сервис аудитора — токеном спросившего."""
    cid = await assert_company_product(company_id, current_user, db, "auditor")
    can_manage = await _is_space_admin(current_user, cid, db)
    row = await _get_or_default(cid, db)
    if row is None:
        # Записи нет — это НЕ ошибка: пространство просто ничего не меняло.
        return SettingsOut(disabled_skills=[], instructions=None, mode="normal",
                           can_manage=can_manage, author_name=current_user.name,
                           user_id=str(current_user.id))
    return SettingsOut(
        disabled_skills=row.disabled_skills or [],
        instructions=row.instructions,
        mode=row.mode,
        model_plan=row.model_plan,
        model_answer=row.model_answer,
        updated_at=row.updated_at,
        can_manage=can_manage,
        author_name=current_user.name,
        user_id=str(current_user.id),
    )


@router.put("/settings", response_model=SettingsOut)
async def put_settings(
    payload: SettingsIn,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> SettingsOut:
    cid = await assert_company_product(company_id, current_user, db, "auditor")
    if not await _is_space_admin(current_user, cid, db):
        raise HTTPException(403, "Настройки аудитора меняет администратор пространства")
    if payload.mode not in MODES:
        raise HTTPException(422, f"Режим должен быть одним из: {', '.join(sorted(MODES))}")

    row = await _get_or_default(cid, db)
    if row is None:
        row = AuditorSetting(company_id=cid)
        db.add(row)
    row.disabled_skills = payload.disabled_skills
    # Пустая строка — это «указаний нет», а не пустое указание в промпте.
    row.instructions = (payload.instructions or "").strip() or None
    row.mode = payload.mode
    row.model_plan = payload.model_plan or None
    row.model_answer = payload.model_answer or None
    row.updated_by = current_user.id
    await db.commit()
    await db.refresh(row)
    return SettingsOut(
        disabled_skills=row.disabled_skills or [], instructions=row.instructions,
        mode=row.mode, model_plan=row.model_plan, model_answer=row.model_answer,
        updated_at=row.updated_at, can_manage=True,   # сюда дошёл только админ
    )


class RateIn(BaseModel):
    verdict: str
    feedback: str | None = None


VERDICTS = {"ok", "wrong", "not_an_issue"}


@router.post("/runs/{run_id}/rate")
async def rate_run(
    run_id: uuid.UUID,
    payload: RateIn,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Оценка ответа — вход петли обучения.

    Переоценка разрешена: человек часто отмечает «неверно» сгоряча, а разобравшись,
    меняет решение. Хранится последняя оценка и кто её поставил.
    """
    cid = await assert_company_product(company_id, current_user, db, "auditor")
    if payload.verdict not in VERDICTS:
        raise HTTPException(422, f"Оценка должна быть одной из: {', '.join(sorted(VERDICTS))}")
    run = (await db.execute(select(AuditorRun).where(
        AuditorRun.id == run_id, AuditorRun.company_id == cid))).scalar_one_or_none()
    if run is None:
        raise HTTPException(404, "Ответ не найден")
    run.verdict = payload.verdict
    run.feedback = (payload.feedback or "").strip() or None
    run.rated_at = datetime.now(UTC)
    run.rated_by = current_user.id
    await db.commit()
    return {"status": "ok"}


@router.get("/runs")
async def list_runs(
    company_id: str,
    limit: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """След разговоров: что спрашивали, куда смотрел, что нашёл."""
    cid = await assert_company_product(company_id, current_user, db, "auditor")
    rows = (await db.execute(
        select(AuditorRun, User.name)
        .outerjoin(User, User.id == AuditorRun.user_id)
        .where(AuditorRun.company_id == cid)
        .order_by(AuditorRun.created_at.desc())
        .limit(limit)
    )).all()
    return {"runs": [{
        "id": str(r.AuditorRun.id),
        "question": r.AuditorRun.question,
        "path": r.AuditorRun.path,
        "skills": r.AuditorRun.skills or [],
        "answer": r.AuditorRun.answer,
        "findings": r.AuditorRun.findings or [],
        "duration_ms": r.AuditorRun.duration_ms,
        "created_at": r.AuditorRun.created_at.isoformat() if r.AuditorRun.created_at else None,
        "user": r[1],
        "verdict": r.AuditorRun.verdict,
        "feedback": r.AuditorRun.feedback,
    } for r in rows]}


@router.post("/runs")
async def add_run(
    payload: RunIn,
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict[str, str]:
    """Запись следа. Зовёт сервис аудитора ТЕМ ЖЕ токеном, что и данные — значит
    автор записи это спросивший человек, а не безличный агент."""
    cid = await assert_company_member(company_id, current_user, db)
    run = AuditorRun(
        company_id=cid, user_id=current_user.id,
        question=payload.question[:4000], path=payload.path,
        skills=payload.skills, answer=(payload.answer or "")[:20000],
        findings=payload.findings, duration_ms=payload.duration_ms,
    )
    db.add(run)
    await db.commit()
    return {"id": str(run.id)}
