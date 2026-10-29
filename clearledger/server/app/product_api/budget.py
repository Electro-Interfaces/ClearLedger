"""Opt-in PostgreSQL fixed windows, after live identity/ACL and before domain I/O.

One tuple owns one counter across processes, tokens, grants and product routes.
Windows start at the first admitted request; up to 2L requests can straddle a
boundary. This is request admission, not concurrent execution/byte accounting.
"""
import asyncio
from dataclasses import dataclass
import secrets
import uuid

from sqlalchemy import text
from starlette.exceptions import HTTPException

# Declarations only; also registers with the offline schema-only Base adapter.
from app.models_product_budget import ProductAPIBudget  # noqa: F401

CLEANUP_LIMIT = 64
CLEANUP_SAMPLE = 128


@dataclass(frozen=True)
class Policy:
    enabled: bool = False
    request_limit: int = 120
    window_seconds: int = 60
    timeout_ms: int = 1000

    def __post_init__(self):
        if type(self.enabled) is not bool:
            raise ValueError("Budget enabled must be boolean")
        for value, lower, upper in ((self.request_limit, 1, 1_000_000),
                (self.window_seconds, 1, 3600), (self.timeout_ms, 50, 5000)):
            if type(value) is not int or not lower <= value <= upper:
                raise ValueError("Product budget configuration is out of bounds")


@dataclass(frozen=True)
class Key:
    company_id: uuid.UUID
    installation_id: uuid.UUID
    client_id: str


class BudgetExceeded(HTTPException):
    def __init__(self, retry_after: int):
        super().__init__(429, "Product request budget exhausted", headers={"Retry-After": str(retry_after)})


def configured_policy():
    from app.config import get_settings
    settings = get_settings()
    return Policy(settings.partner_api_budget_enabled, settings.partner_api_budget_limit,
                  settings.partner_api_budget_window_seconds, settings.partner_api_budget_timeout_ms)


# The correlated subquery runs in ON CONFLICT's locked UPDATE, not in an
# earlier CTE/EXCLUDED timestamp that might predate a wait on the conflicting row.
# OFFSET 0 prevents flattening: the volatile DB clock is evaluated once for all
# SET values. Active policy drift fails closed rather than reopening a window.
CONSUME = text("""
INSERT INTO product_api_budgets AS b
    (company_id, installation_id, client_id, used, reset_at, request_limit, window_seconds)
VALUES (:company_id, :installation_id, :client_id, 1,
        clock_timestamp() + make_interval(secs => :window_seconds), :request_limit, :window_seconds)
ON CONFLICT (company_id, installation_id, client_id) DO UPDATE
SET (used, reset_at, request_limit, window_seconds) = (
    SELECT
        CASE WHEN b.reset_at <= tick.at THEN 1
             WHEN b.request_limit = :request_limit AND b.window_seconds = :window_seconds
                  THEN LEAST(b.used + 1, :request_limit + 1)
             ELSE b.used END,
        CASE WHEN b.reset_at <= tick.at
             THEN tick.at + make_interval(secs => :window_seconds) ELSE b.reset_at END,
        CASE WHEN b.reset_at <= tick.at THEN :request_limit ELSE b.request_limit END,
        CASE WHEN b.reset_at <= tick.at THEN :window_seconds ELSE b.window_seconds END
    FROM (SELECT clock_timestamp() AS at OFFSET 0) AS tick
)
RETURNING used, request_limit, window_seconds,
          GREATEST(1, CEIL(EXTRACT(EPOCH FROM reset_at - clock_timestamp())))::integer AS retry_after
""")

CLEANUP = text("""
WITH expired AS (
    SELECT company_id, installation_id, client_id FROM product_api_budgets
    WHERE reset_at < statement_timestamp() - interval '24 hours'
    ORDER BY reset_at LIMIT 64 FOR UPDATE SKIP LOCKED
)
DELETE FROM product_api_budgets AS b USING expired AS e
WHERE b.company_id=e.company_id AND b.installation_id=e.installation_id AND b.client_id=e.client_id
""")


async def enforce(policy: Policy, sessions, key: Key):
    if not policy.enabled:
        return  # No session, clock lookup, cleanup or quota SQL while disabled.
    try:
        # Covers connection checkout as well as SQL/commit; DB timeouts bound
        # lock/statement waits too. Cancellation rolls back the short transaction.
        async with asyncio.timeout(policy.timeout_ms / 1000):
            async with sessions() as db:
                async with db.begin():
                    await db.execute(text("SELECT set_config('statement_timeout', :ms, true), "
                        "set_config('lock_timeout', :ms, true)"), {"ms": str(policy.timeout_ms)})
                    row = (await db.execute(CONSUME, {"company_id": key.company_id,
                        "installation_id": key.installation_id, "client_id": key.client_id,
                        "request_limit": policy.request_limit, "window_seconds": policy.window_seconds})).mappings().one()
                    if (row["request_limit"], row["window_seconds"]) != (policy.request_limit, policy.window_seconds):
                        raise ValueError("Active product budget policy differs")
                    if secrets.randbelow(CLEANUP_SAMPLE) == 0:
                        await db.execute(CLEANUP)
        # Commit admission independently of subsequent validation/domain outcomes.
    except Exception:
        raise HTTPException(503, "Product request budget is unavailable") from None
    if row["used"] > policy.request_limit:
        raise BudgetExceeded(row["retry_after"])
