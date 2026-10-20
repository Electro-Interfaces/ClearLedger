"""Чтение только поставляемых публичных инструкций КЦ из общего «Инфо».

У отдельного КЦ нет сессии сотрудника пространства. Узкий read-only пакет
не выдаёт ЛНД, другие статьи, данные компаний или служебные поля модели.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InfoArticle
from app.services.info_seed_cc import ARTICLES


async def instructions(db: AsyncSession) -> dict:
    definitions = {a["title"]: a for a in ARTICLES}
    rows = (await db.execute(select(InfoArticle).where(
        InfoArticle.company_id.is_(None), InfoArticle.profile_id.is_(None),
        InfoArticle.status == "published", InfoArticle.kind == "guide",
        InfoArticle.title.in_(definitions),
    ).order_by(InfoArticle.updated_at.desc(), InfoArticle.id))).scalars().all()
    by_title = {}
    for row in rows:
        by_title.setdefault(row.title, row)
    items = []
    for title, definition in definitions.items():
        row = by_title.get(title)
        if row is not None:
            items.append({"key": definition["cc_key"], "title": row.title,
                          "summary": row.summary or "", "bodyMd": row.body_md,
                          "category": definition["category"],
                          "sections": definition["cc_sections"],
                          "audience": definition["cc_audience"]})
    return {"source": "info", "items": items}
