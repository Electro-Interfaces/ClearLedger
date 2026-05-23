"""
Роутер каталога зарегистрированных типов источников.

Используется UI для построения раздела «Каталог» — тайлы по категориям
с описаниями и формами настроек.
"""

from fastapi import APIRouter

from app.adapters import list_adapters

router = APIRouter(prefix="/source-types", tags=["source-types"])


@router.get("")
async def get_source_types():
    """Каталог всех зарегистрированных адаптеров источников.

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
    """
    return {"items": list_adapters()}
