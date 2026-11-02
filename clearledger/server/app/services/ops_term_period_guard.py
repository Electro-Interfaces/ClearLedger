"""Read-only closed-month checks and the company transaction barrier.

The caller owns transaction completion. Savepoints are deliberately unsupported:
rolling one back can release a PostgreSQL lock while retaining Python state.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import and_, exists, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OpsContractTerm, OpsPeriodCharge, OpsPeriodClose


async def lock_term_period_company(db: AsyncSession, company_id, *, exclusive=False):
    """Company barrier, before contract-window and period/row locks; never upgrade."""
    with db.no_autoflush:
        session = db.sync_session
        if session.in_nested_transaction():
            raise ValueError("Операция условий и закрытия не поддерживает вложенную транзакцию")
        # Establish the root transaction without flushing caller-owned changes.
        await db.connection()
        transaction = session.get_transaction()
        state = session.info.get("ops_term_period_barrier")
        if state is None or state[0] is not transaction:
            state = (transaction, {})
            session.info["ops_term_period_barrier"] = state
        modes = state[1]
        company = str(company_id)
        previous = modes.get(company)
        if previous == "exclusive" or (previous == "shared" and not exclusive):
            return
        if previous is not None:
            # Also fail closed after an interrupted lock acquisition until the
            # caller completes this transaction. Never attempt an SQL upgrade.
            raise ValueError("Закрытие и изменение условий требуют отдельных транзакций")
        mode = "exclusive" if exclusive else "shared"
        modes[company] = "pending"
        function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        await db.execute(text(
            f"SELECT {function}(hashtextextended(:key, 0))"),
            {"key": f"ops-term-period-company:{company}"})
        modes[company] = mode


async def locked_term_snapshot(db: AsyncSession, company_id, term_id):
    """Fresh columns under the contract lock, without touching the identity map."""
    with db.no_autoflush:
        row = (await db.execute(select(*OpsContractTerm.__table__.c).where(
            OpsContractTerm.company_id == company_id,
            OpsContractTerm.id == term_id,
        ).with_for_update())).mappings().one_or_none()
        if row is None:
            raise ValueError("Условие не найдено")
        return SimpleNamespace(**row)


async def check_term_periods(db: AsyncSession, company_id, ranges, *, deleting_term_id=None):
    """Reject inclusive month intersections, including a deleted term's closed FKs.

    Query existing close rows rather than enumerate a bounded calendar. Callers
    supply the actual old/new intervals or the new-version changed tail only.
    """
    # Local import avoids a cycle: close/reopen import the barrier above.
    from app.services.ops_closing import CLOSED_STATUSES

    intersections = []
    for valid_from, valid_to in ranges:
        try:
            start = date.fromisoformat(valid_from).isoformat()
            end = date.fromisoformat(valid_to).isoformat() if valid_to else None
        except (ValueError, TypeError):
            raise ValueError("Срок условия должен быть датой ГГГГ-ММ-ДД") from None
        if end and end < start:
            raise ValueError("Окончание условия не может быть раньше начала")
        overlap = OpsPeriodClose.period >= start[:7] + "-01"
        if end:
            overlap = and_(overlap, OpsPeriodClose.period <= end[:7] + "-01")
        intersections.append(overlap)
    if deleting_term_id is not None:
        # Reopening changes the month status, not the charge's historical
        # closing marker. SET NULL must not unlink that preserved history.
        with db.no_autoflush:
            historical = await db.scalar(select(OpsPeriodCharge.id).where(
                OpsPeriodCharge.company_id == company_id,
                OpsPeriodCharge.term_id == deleting_term_id,
                OpsPeriodCharge.closed_in_period.is_not(None),
            ).limit(1))
        if historical is not None:
            raise ValueError("Условие связано с историей закрытого периода")
        intersections.append(exists(select(OpsPeriodCharge.id).where(
            OpsPeriodCharge.company_id == company_id,
            OpsPeriodCharge.term_id == deleting_term_id,
            or_(OpsPeriodCharge.period == OpsPeriodClose.period,
                OpsPeriodCharge.closed_in_period == OpsPeriodClose.period),
        )))
    if not intersections:
        return
    with db.no_autoflush:
        closed = await db.scalar(select(OpsPeriodClose.id).where(
            OpsPeriodClose.company_id == company_id,
            OpsPeriodClose.status.in_(CLOSED_STATUSES),
            or_(*intersections),
        ).limit(1))
    if closed is not None:
        raise ValueError("Условие затрагивает закрытый период")
