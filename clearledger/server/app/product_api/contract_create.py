"""Request-owned HTTP CREATE lifetime; the actual SQL consumer owns all writes.

Imports of identity/authority/consumer happen only at runtime, never during
app/OpenAPI assembly. No retry after an unknown commit, savepoint or new B.
"""
from contextlib import asynccontextmanager

from anyio import CancelScope
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.api_contracts.context import CREATE_PREFLIGHT_KEY
from . import access, budget, dto
from .contract_create_body import ContractCreateBodyError, parse_contract_create_body

_DB_KEY = "elsy.product.create_db"
_CONTEXT_KEY = "elsy.product.create_context"
_BEARER_KEY = "elsy.product.create_bearer"


async def _rollback(db):
    # ASGI cancellation may be level-triggered by AnyIO. Shield rollback from
    # that cancelled scope so it finishes before the Session context closes.
    with CancelScope(shield=True):
        await db.rollback()


@asynccontextmanager
async def request_lifetime(request: Request):
    settings = request.app.state.product_settings
    bearer = access.request_bearer(request)
    # This connection is closed before the separately committed quota checkout.
    async with settings.sessions() as read_db:
        token, _ = await access.create_preflight(request, read_db, bearer)
        key = budget.Key(token.company_id, token.installation_id, token.client_id)
    await budget.enforce(settings.budget_policy(), settings.sessions, key)
    db = None
    try:
        # Guard, parser, SQL consumer, response serialization, commit and close
        # all live under this lifetime. A response escapes only after completion.
        async with settings.sessions() as db:
            try:
                await db.begin()
                _, context = await access.create_preflight(request, db, bearer, bind=True)
                request.scope[_DB_KEY] = db
                request.scope[_CONTEXT_KEY] = context
                request.scope[_BEARER_KEY] = bearer
                yield
                await db.commit()
            except BaseException:
                await _rollback(db)
                raise
    except BaseException:
        # Includes cancellation, guard/handler failures and commit failures.
        # An acknowledgement loss remains unknown; the caller retries same key
        # in a NEW root with fresh current auth, never with an old SQL stamp.
        if db is not None:
            await _rollback(db)
        raise
    finally:
        for key in (_DB_KEY, _CONTEXT_KEY, _BEARER_KEY, CREATE_PREFLIGHT_KEY):
            request.scope.pop(key, None)


async def create(request: Request) -> JSONResponse:
    from app.services.partner_contract_commands import create_partner_contract

    try:
        body = await parse_contract_create_body(request)  # Sole wire reader.
    except ContractCreateBodyError as error:
        raise HTTPException(error.status, error.code) from None
    result = await create_partner_contract(request.scope[_DB_KEY], request.scope[_BEARER_KEY], body)
    # Explicit allowlist and JSON encoding occur before caller commit. Neither
    # intent/profile/grant/generation nor hidden duplicate IDs can be exposed.
    value = dto.ContractCreateResult(contract_id=result.contract_id, replayed=result.replayed)
    return JSONResponse(value.model_dump(mode="json", by_alias=True),
                        status_code=200 if result.replayed else 201)
