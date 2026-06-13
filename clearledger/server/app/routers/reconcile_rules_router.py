"""
Роутер справочника РАЗРЕЗОВ СВЕРКИ (ReconRule).

Третий справочник (после /source-types и /channel-templates): каталог
переиспользуемых разрезов сверки (6 кубиков). Каналы подключают разрезы
по `id`. UI строит галерею «Каталог сверок».
"""

from fastapi import APIRouter

from app.reconcile_catalog import list_reconcile_rules

router = APIRouter(prefix="/reconcile-rules", tags=["reconcile-rules"])


@router.get("")
async def get_reconcile_rules():
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
    return {"items": list_reconcile_rules()}
