"""Transaction-owned document Case catalog barrier.

Readers choose S before locking any DocCard; catalog/default writers choose X
before reading predicates or changing Kind/Case rows, including NULL defaults.
The caller supplies a normal AsyncSession and owns its root and completion.
Repeated acquisition is allowed; callers needing X must choose it initially:
an S-to-X upgrade after row locks is outside this protocol. Multi-company roots
must supply their complete company set up front, not extend it after row locks.
No authorization, row validation or transaction completion belongs here.
"""
from collections.abc import Iterable
from typing import Literal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession


async def acquire_case_catalog(
    db: AsyncSession, cids: Iterable[UUID], mode: Literal["S", "X"],
) -> None:
    """Acquire sorted, deduplicated legacy physical keys until root completion.

    UUID collisions intentionally share the old namespace/key. Locks are PostgreSQL
    transaction locks; returning from this function does not release them. The
    helper neither starts an explicit root nor flushes pending application rows.
    """
    if mode not in ("S", "X"):
        raise ValueError("Case catalog mode must be S or X")
    keys = sorted({cid.int % (2 ** 31) for cid in cids})
    lock = (func.pg_advisory_xact_lock_shared if mode == "S"
            else func.pg_advisory_xact_lock)
    for key in keys:
        await db.execute(select(lock(435_223, key)))
