"""
Роутер каталога зарегистрированных типов источников.

Используется UI для построения раздела «Каталог» — тайлы по категориям
с описаниями и формами настроек.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import list_adapters
from app.auth import get_current_user
from app.database import get_db
from app.deps import scope_company_id
from app.models import Company, User
from app.profile_scope import source_types_for

router = APIRouter(prefix="/source-types", tags=["source-types"])


async def _profile(user: User, db: AsyncSession) -> str | None:
    """Профиль активной компании — по нему отбираем справочник поставки."""
    company = await db.get(Company, await scope_company_id(user, db))
    return getattr(company, "profile_id", None) if company else None


@router.get("")
async def get_source_types(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Каталог типов источников, уместных компании.

    Возвращает список:
    [
      {
        "source_type": "sts",
        "label": "STS API (АЗС)",
        "category": "Топливный учёт АЗС",
        "description": "...",
        "icon": "Fuel",
        "setup_schema": [{key, label, type, required, ...}, ...],
        "available_doc_types": [{id, name, description, category}, ...]
      },
      ...
    ]

    Состав зависит от профиля компании (`app.profile_scope`): аудиторской фирме
    незачем видеть кассовый сервер АЗС, а сети ЭЗС — «Честный знак». Раньше каталог
    отдавался целиком всем, и кнопка «Подключить» у чужого типа работала.
    """
    allowed = source_types_for(await _profile(user, db))
    return {"items": [a for a in list_adapters() if a["source_type"] in allowed]}
