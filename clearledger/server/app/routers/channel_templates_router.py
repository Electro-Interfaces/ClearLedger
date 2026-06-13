"""
Роутер справочника шаблонов каналов обработки.

Параллель `source_types_router`: там — каталог типов источников, здесь —
каталог типов каналов (конвейеров). UI строит галерею «Каталог каналов»,
из шаблона создаётся экземпляр Channel (потоки + стадии + расписание).
"""

from fastapi import APIRouter

from app.channel_catalog import list_channel_templates

router = APIRouter(prefix="/channel-templates", tags=["channel-templates"])


@router.get("")
async def get_channel_templates():
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
    return {"items": list_channel_templates()}
