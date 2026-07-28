"""«Инфо» — знание пространства: дерево, поиск, контекст рабочей области.

Модель и решения — `docs/INFO.md`. Коротко: одно приложение на всё пространство,
три пласта знания (инструкция платформы, отраслевая норма, документ компании) и
привязки к продуктам-разделам, из которых собирается контекстная подсказка.

Правило видимости одно на все запросы: пространство видит своё (`company_id`) плюс
платформенное (`company_id IS NULL`), причём отраслевое — только своего профиля.
Чужого пространства не видно никогда.
"""
from __future__ import annotations

import uuid as _uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, InfoArticle, InfoBinding, InfoCategory, User

# Пласты знания. Порядок — порядок групп в дереве: сначала «как работать»,
# потом «что требует закон», потом «как принято у нас».
KINDS = [
    {"key": "guide", "label": "Работа в системе", "hint": "инструкции по продуктам платформы"},
    {"key": "norm", "label": "Нормы и требования", "hint": "законы, ГОСТы, отраслевые правила"},
    {"key": "lnd", "label": "Документы компании", "hint": "регламенты и приказы пространства"},
    {"key": "faq", "label": "Частые вопросы", "hint": "короткие ответы"},
]
KIND_LABELS = {k["key"]: k["label"] for k in KINDS}


async def _profile(db: AsyncSession, company_id) -> str | None:
    return (await db.execute(
        select(Company.profile_id).where(Company.id == company_id))).scalar()


def _visible(model: Any, company_id, profile: str | None):
    """Условие видимости: своё пространство + платформенное своего профиля."""
    return or_(
        model.company_id == company_id,
        (model.company_id.is_(None)
         & (model.profile_id.is_(None) | (model.profile_id == profile))),
    )


def _article_out(a: InfoArticle, *, body: bool = False) -> dict[str, Any]:
    out = {
        "id": str(a.id), "title": a.title, "summary": a.summary,
        "kind": a.kind, "kindLabel": KIND_LABELS.get(a.kind, a.kind),
        "scope": "company" if a.company_id else "platform",
        "categoryId": str(a.category_id) if a.category_id else None,
        "docNumber": a.doc_number, "effectiveDate": a.effective_date,
        "sourceUrl": a.source_url, "tags": a.tags or [],
        "processRef": a.process_ref,
        "updatedAt": (a.updated_at or a.created_at).isoformat() if (a.updated_at or a.created_at) else None,
    }
    if body:
        out["bodyMd"] = a.body_md
    return out


async def tree(db: AsyncSession, company_id) -> dict[str, Any]:
    """Дерево знания: разделы и статьи, сгруппированные по пластам."""
    profile = await _profile(db, company_id)
    cats = (await db.execute(
        select(InfoCategory).where(_visible(InfoCategory, company_id, profile))
        .order_by(InfoCategory.sort_order, InfoCategory.title))).scalars().all()
    arts = (await db.execute(
        select(InfoArticle).where(
            _visible(InfoArticle, company_id, profile), InfoArticle.status == "published")
        .order_by(InfoArticle.sort_order, InfoArticle.title))).scalars().all()

    by_cat: dict[str, list[dict[str, Any]]] = {}
    for a in arts:
        by_cat.setdefault(str(a.category_id) if a.category_id else "", []).append(_article_out(a))
    groups = []
    for k in KINDS:
        items = [a for a in arts if a.kind == k["key"]]
        if not items:
            continue
        cat_ids = {str(a.category_id) for a in items if a.category_id}
        groups.append({
            **k,
            "count": len(items),
            "categories": [{"id": str(c.id), "title": c.title,
                            "articles": [x for x in by_cat.get(str(c.id), [])
                                         if x["kind"] == k["key"]]}
                           for c in cats if str(c.id) in cat_ids],
            # Статьи без раздела показываем в конце группы, а не прячем.
            "loose": [x for x in by_cat.get("", []) if x["kind"] == k["key"]],
        })
    return {"groups": groups, "profile": profile,
            "total": len([a for a in arts])}


async def article(db: AsyncSession, company_id, article_id) -> dict[str, Any] | None:
    profile = await _profile(db, company_id)
    a = (await db.execute(select(InfoArticle).where(
        InfoArticle.id == article_id,
        _visible(InfoArticle, company_id, profile)))).scalar_one_or_none()
    if a is None:
        return None
    out = _article_out(a, body=True)
    out["bindings"] = [
        {"appCode": b.app_code, "sectionKey": b.section_key, "weight": b.weight}
        for b in (await db.execute(select(InfoBinding).where(
            InfoBinding.article_id == a.id).order_by(InfoBinding.weight.desc()))).scalars()
    ]
    return out


async def search(db: AsyncSession, company_id, query: str, limit: int = 20) -> dict[str, Any]:
    """Поиск по знанию: заголовок весомее тела, сниппет с подсветкой.

    Пустой запрос не отдаёт всю базу: это работа дерева, а не поиска.
    """
    q = (query or "").strip()
    if len(q) < 2:
        return {"items": [], "query": q}
    profile = await _profile(db, company_id)
    sql = text("""
        select a.id, a.title, a.kind, a.doc_number,
               ts_headline('russian', coalesce(a.summary, '') || ' ' || a.body_md,
                           to_tsquery('russian', :tsq),
                           'StartSel=<<, StopSel=>>, MaxWords=24, MinWords=10, MaxFragments=1') as snippet,
               ts_rank(a.search_tsv, to_tsquery('russian', :tsq)) as rank,
               (a.company_id is not null) as own
        from info_articles a
        where a.status = 'published'
          and a.search_tsv @@ to_tsquery('russian', :tsq)
          and (a.company_id = :cid
               or (a.company_id is null and (a.profile_id is null or a.profile_id = :profile)))
        order by rank desc, own desc
        limit :lim
    """)
    # Слова чистим сами: `to_tsquery` не терпит знаков препинания, а `plainto_tsquery`
    # умеет только «все слова сразу» — по запросу из двух слов он молча отдаёт пусто,
    # хотя каждая половина в базе есть. Сначала ищем все слова, потом любое из них.
    words = [w for w in "".join(c if c.isalnum() or c.isspace() else " " for c in q).split() if len(w) > 1]
    if not words:
        return {"items": [], "query": q}
    params = {"cid": company_id, "profile": profile, "lim": limit}
    rows = (await db.execute(sql, {**params, "tsq": " & ".join(f"{w}:*" for w in words)})).mappings().all()
    if not rows and len(words) > 1:
        rows = (await db.execute(sql, {**params, "tsq": " | ".join(f"{w}:*" for w in words)})).mappings().all()
    return {
        "query": q,
        "items": [{"id": str(r["id"]), "title": r["title"], "kind": r["kind"],
                   "kindLabel": KIND_LABELS.get(r["kind"], r["kind"]),
                   "docNumber": r["doc_number"], "snippet": r["snippet"],
                   "scope": "company" if r["own"] else "platform"} for r in rows],
    }


async def context(db: AsyncSession, company_id, *, app_code: str,
                  section_key: str | None = None, limit: int = 8) -> dict[str, Any]:
    """Что показать в правой панели для открытой рабочей области.

    Сначала статьи, привязанные к разделу, потом — к продукту целиком. Если для
    места ничего не заведено, панель не остаётся пустой: отдаём инструкции
    продукта по общему дереву и честно помечаем это как «ничего своего нет».
    """
    profile = await _profile(db, company_id)
    rows = (await db.execute(
        select(InfoArticle, InfoBinding.section_key, InfoBinding.weight)
        .join(InfoBinding, InfoBinding.article_id == InfoArticle.id)
        .where(_visible(InfoArticle, company_id, profile),
               InfoArticle.status == "published",
               InfoBinding.app_code == app_code,
               or_(InfoBinding.section_key.is_(None),
                   InfoBinding.section_key == (section_key or "")))
        .order_by(InfoBinding.section_key.is_(None),   # точное совпадение раздела — выше
                  InfoBinding.weight.desc(), InfoArticle.sort_order)
        .limit(limit))).all()
    items = []
    seen: set[str] = set()
    for a, sec, _w in rows:
        if str(a.id) in seen:
            continue
        seen.add(str(a.id))
        out = _article_out(a)
        out["exact"] = bool(sec)      # привязана именно к этому разделу
        items.append(out)
    return {
        "appCode": app_code, "sectionKey": section_key,
        "items": items,
        "empty": not items,
    }


async def upsert_article(db: AsyncSession, company_id, payload: dict[str, Any],
                         user: User | None) -> dict[str, Any]:
    """Завести или поправить статью пространства.

    Платформенные статьи (`company_id IS NULL`) отсюда не правятся: их ведёт
    поставщик, и пространство не должно менять общую нормативку у всех разом.
    """
    aid = payload.get("id")
    a = None
    if aid:
        a = (await db.execute(select(InfoArticle).where(
            InfoArticle.id == _uuid.UUID(str(aid)),
            InfoArticle.company_id == company_id))).scalar_one_or_none()
        if a is None:
            return {"ok": False, "message": "Статья не найдена или принадлежит платформе"}
    if a is None:
        a = InfoArticle(company_id=company_id)
        db.add(a)
    title = str(payload.get("title") or "").strip()
    if not title:
        return {"ok": False, "message": "Нужен заголовок"}
    a.title = title[:300]
    a.summary = (payload.get("summary") or None)
    a.body_md = payload.get("body_md") or ""
    a.kind = payload.get("kind") if payload.get("kind") in KIND_LABELS else "lnd"
    a.status = "draft" if payload.get("status") == "draft" else "published"
    a.doc_number = payload.get("doc_number") or None
    a.effective_date = payload.get("effective_date") or None
    a.source_url = payload.get("source_url") or None
    a.tags = payload.get("tags") or None
    a.category_id = _uuid.UUID(str(payload["category_id"])) if payload.get("category_id") else None
    a.updated_by = user.id if user is not None else None
    a.updated_at = datetime.now(timezone.utc)
    if a.created_by is None and user is not None:
        a.created_by = user.id
    await db.flush()

    # Привязки задаются целиком: список — это и есть настройка «где показывать».
    if "bindings" in payload:
        await db.execute(text("delete from info_bindings where article_id = :aid"),
                         {"aid": str(a.id)})
        for b in payload.get("bindings") or []:
            code = str(b.get("app_code") or "").strip()
            if not code:
                continue
            db.add(InfoBinding(article_id=a.id, app_code=code,
                               section_key=(b.get("section_key") or None),
                               weight=int(b.get("weight") or 0)))
    return {"ok": True, "id": str(a.id)}


async def delete_article(db: AsyncSession, company_id, article_id) -> bool:
    a = (await db.execute(select(InfoArticle).where(
        InfoArticle.id == article_id,
        InfoArticle.company_id == company_id))).scalar_one_or_none()
    if a is None:
        return False
    await db.delete(a)
    return True


async def upsert_category(db: AsyncSession, company_id, payload: dict[str, Any]) -> dict[str, Any]:
    cid = payload.get("id")
    c = None
    if cid:
        c = (await db.execute(select(InfoCategory).where(
            InfoCategory.id == _uuid.UUID(str(cid)),
            InfoCategory.company_id == company_id))).scalar_one_or_none()
    if c is None:
        c = InfoCategory(company_id=company_id)
        db.add(c)
    title = str(payload.get("title") or "").strip()
    if not title:
        return {"ok": False, "message": "Нужно название раздела"}
    c.title = title[:200]
    c.sort_order = int(payload.get("sort_order") or 0)
    await db.flush()
    return {"ok": True, "id": str(c.id)}


async def stats(db: AsyncSession, company_id) -> dict[str, Any]:
    """Сколько знания в пространстве и чего не хватает — для плитки и админки."""
    profile = await _profile(db, company_id)
    rows = (await db.execute(
        select(InfoArticle.kind, InfoArticle.company_id.is_(None).label("platform"),
               func.count().label("n"))
        .where(_visible(InfoArticle, company_id, profile), InfoArticle.status == "published")
        .group_by(InfoArticle.kind, InfoArticle.company_id.is_(None)))).all()
    by_kind: dict[str, dict[str, int]] = {}
    for kind, is_platform, n in rows:
        d = by_kind.setdefault(kind, {"platform": 0, "company": 0})
        d["platform" if is_platform else "company"] += int(n)
    bound = (await db.execute(
        select(func.count(func.distinct(InfoBinding.app_code))))).scalar() or 0
    return {
        "byKind": [{"kind": k["key"], "label": k["label"],
                    "platform": by_kind.get(k["key"], {}).get("platform", 0),
                    "company": by_kind.get(k["key"], {}).get("company", 0)} for k in KINDS],
        "apps": int(bound),
        "profile": profile,
    }
