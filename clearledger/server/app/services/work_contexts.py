from fastapi import HTTPException
from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from app.models import WorkContextResult


_providers = {}


def register(provider):
    if provider.prefix in _providers:
        raise ValueError(f"Повторный поставщик контекста: {provider.prefix}")
    _providers[provider.prefix] = provider


def providers():
    return list(_providers.values())


def provider_for(ref):
    prefix, _, key = ref.partition(":")
    provider = _providers.get(prefix)
    if provider is None or not key:
        raise HTTPException(400, "Приложение не зарегистрировало этот контекст работы")
    return provider, key


async def resolve(db, cid, user, ref):
    provider, key = provider_for(ref)
    return await provider.resolve(db, cid, user, key)


async def publish_result(db, cid, ref, *, work_ref, outcome, result_key):
    if not ref:
        return
    prefix = ref.partition(":")[0]
    provider = _providers.get(prefix)
    if provider is not None and hasattr(provider, "result"):
        kind, entity_id = work_ref.split(":", 1)
        import uuid
        await db.execute(insert(WorkContextResult).values(company_id=cid, context_ref=ref,
            work_kind=kind, entity_id=uuid.UUID(entity_id), outcome=outcome, result_key=result_key)
            .on_conflict_do_nothing(index_elements=["company_id", "context_ref", "result_key"]))


async def deliver_pending(db, limit=20):
    rows = (await db.execute(select(WorkContextResult).where(WorkContextResult.delivered_at.is_(None),
        WorkContextResult.attempts < 10).order_by(WorkContextResult.created_at)
        .limit(limit).with_for_update(skip_locked=True))).scalars().all()
    for row in rows:
        row.attempts += 1
        try:
            async with db.begin_nested():
                provider, key = provider_for(row.context_ref)
                await provider.result(db, row.company_id, key, f"{row.work_kind}:{row.entity_id}", row.outcome, row.result_key)
            row.delivered_at = datetime.now(timezone.utc)
            row.last_error = None
        except Exception as exc:
            row.last_error = f"{type(exc).__name__}: {exc}"[:500]
    return len(rows)
