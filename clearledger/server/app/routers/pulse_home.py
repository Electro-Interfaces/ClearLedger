from datetime import datetime
from typing import Literal
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import ForeignKey, Integer, String, func, select
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.auth import assert_company_product, get_current_user
from app.database import Base, get_db
from app.models import User, UserCompany

router = APIRouter()


class PulseHomePreference(Base):
    __tablename__ = "pulse_home_preferences"

    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("companies.id", ondelete="CASCADE"), primary_key=True)
    owner: Mapped[str] = mapped_column(String(36), primary_key=True)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class HomeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sections: list[Literal["work", "chats", "meetings", "metrics", "apps"]] = Field(
        default_factory=lambda: ["work", "chats", "meetings", "metrics", "apps"], max_length=5)
    favorite_apps: list[str] = Field(default_factory=list, max_length=12)
    metric_keys: list[str] | None = Field(default=None, max_length=12)

    @model_validator(mode="after")
    def validate_lists(self):
        for items in (self.sections, self.favorite_apps, self.metric_keys or []):
            if len(items) != len(set(items)):
                raise ValueError("Пункты не должны повторяться")
            if any(not item or len(item) > 80 for item in items):
                raise ValueError("Некорректный код пункта")
        return self


class HomeChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["personal", "space"] = "personal"
    revision: int = Field(ge=0)
    config: HomeConfig | None


async def may_set_default(db, cid, user):
    if user.is_superadmin:
        return True
    member = await db.get(UserCompany, (user.id, cid))
    return bool(member and member.role == "admin")


async def read_home(db, cid, user):
    rows = (await db.scalars(select(PulseHomePreference).where(
        PulseHomePreference.company_id == cid,
        PulseHomePreference.owner.in_(["space", str(user.id)]),
    ))).all()
    by_owner = {row.owner: row for row in rows}
    personal = by_owner.get(str(user.id))
    shared = by_owner.get("space")
    default = shared.config if shared and shared.config is not None else HomeConfig().model_dump()
    own = personal.config if personal else None
    return {
        "effective": own if own is not None else default,
        "personal": own,
        "default": default,
        "personal_revision": personal.revision if personal else 0,
        "space_revision": shared.revision if shared else 0,
        "can_set_default": await may_set_default(db, cid, user),
    }


@router.get("/home-settings")
async def get_home_settings(company_id: str, user: User = Depends(get_current_user),
                            db: AsyncSession = Depends(get_db)):
    cid = await assert_company_product(company_id, user, db, "pulse")
    return await read_home(db, cid, user)


@router.put("/home-settings")
async def save_home_settings(company_id: str, body: HomeChange,
                             user: User = Depends(get_current_user),
                             db: AsyncSession = Depends(get_db)):
    cid = await assert_company_product(company_id, user, db, "pulse")
    if body.scope == "space" and not await may_set_default(db, cid, user):
        raise HTTPException(403, "Общий экран настраивает администратор пространства")
    owner = "space" if body.scope == "space" else str(user.id)
    await db.execute(insert(PulseHomePreference).values(
        company_id=cid, owner=owner, config=None, revision=0,
    ).on_conflict_do_nothing())
    row = await db.scalar(select(PulseHomePreference).where(
        PulseHomePreference.company_id == cid, PulseHomePreference.owner == owner,
    ).with_for_update())
    if row.revision != body.revision:
        raise HTTPException(409, "Настройки изменились на другом устройстве. Обновите экран и повторите выбор")
    row.config = body.config.model_dump() if body.config is not None else None
    row.revision += 1
    await db.commit()
    return await read_home(db, cid, user)
