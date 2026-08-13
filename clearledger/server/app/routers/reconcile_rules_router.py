"""
Роутер справочника РАЗРЕЗОВ СВЕРКИ (ReconRule).

Третий справочник (после /source-types и /channel-templates): каталог
переиспользуемых разрезов сверки (6 кубиков). Каналы подключают разрезы
по `id`. UI строит галерею «Каталог сверок».
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.reconcile_catalog import list_reconcile_rules
from app.auth import get_current_user
from app.database import get_db
from app.deps import scope_company_id
from app.models import Company, User
from app.profile_scope import allows_direction

router = APIRouter(prefix="/reconcile-rules", tags=["reconcile-rules"])


async def _profile(user: User, db: AsyncSession) -> str | None:
    """Профиль активной компании — по нему отбираем справочник поставки."""
    company = await db.get(Company, await scope_company_id(user, db))
    return getattr(company, "profile_id", None) if company else None


@router.get("")
async def get_reconcile_rules(
    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    """Каталог разрезов сверки.

    [
      {
        "id": "corp_fuel", "label": "...", "module": "fuel",
        "status": "imperative", "impl": "...",
        "streams": [{role, source_type, doc_type, label}, ...],
        "filter": {...}, "key": [...],
        "match": {time_tolerance, pick, bonus_fields:[...]},
        "compare": [{field, tolerance_abs, unit}, ...],
        "severity": {thresholds, critical_fields, period_promote},
        "statuses_codomain": [...]
      },
      ...
    ]
    """
    # Все тринадцать разрезов относятся к топливу, сопутке, общепиту или ЭЗС —
    # общих нет вовсе. Компании без объектов показывать нечего, и заголовок
    # «Разрезы учёта · 13» с «Талонами» и «Честным знаком» ей только мешал.
    prof = await _profile(user, db)
    return {"items": [r for r in list_reconcile_rules()
                      if allows_direction(prof, r.get("module"))]}
