"""
Роутер справочника шаблонов каналов обработки.

Параллель `source_types_router`: там — каталог типов источников, здесь —
каталог типов каналов (конвейеров). UI строит галерею «Каталог каналов»,
из шаблона создаётся экземпляр Channel (потоки + стадии + расписание).
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.channel_catalog import list_channel_templates
from app.auth import get_current_user
from app.database import get_db
from app.deps import scope_company_id
from app.models import Company, User
from app.profile_scope import allows_direction

router = APIRouter(prefix="/channel-templates", tags=["channel-templates"])


async def _profile(user: User, db: AsyncSession) -> str | None:
    """Профиль активной компании — по нему отбираем справочник поставки."""
    company = await db.get(Company, await scope_company_id(user, db))
    return getattr(company, "profile_id", None) if company else None


@router.get("")
async def get_channel_templates(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Каталог шаблонов каналов.

    [
      {
        "id": "fuel_shift",
        "label": "...", "category": "Нефтепродукты", "icon": "Fuel",
        "direction": "fuel", "status": "partial",
        "streams": [{source_type, doc_type, role, label}, ...],
        "stages":  [{stage_type, name}, ...],
        "reconcile_axes": [{name, anchor, against, key, tolerance}, ...],
        "schedule": {...}
      },
      ...
    ]
    """
    # Отбор по профилю компании: мастер «Создать коннектор» строится из этого же
    # ответа, и до отбора он предлагал аудиторской фирме «Топливо: сменный отчёт»
    # и «Зарядные сессии ЭЗС» — шесть карточек, из которых подходила одна.
    prof = await _profile(user, db)
    return {"items": [t for t in list_channel_templates()
                      if allows_direction(prof, t.get("direction"))]}
