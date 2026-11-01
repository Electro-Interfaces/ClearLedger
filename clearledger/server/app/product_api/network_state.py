"""Product admission/transport for the operational network owner projection."""
import asyncio
import base64
import binascii
from datetime import datetime
import hmac
import json

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.models import Company
from app.services.network_state import (
    NetworkStateAdmissionExceeded, operational_network_state,
)
from . import dto
from .queries import Query

VERSION = "network-state-1"
BUSINESS_SECONDS = 5


def _encode(key, value):
    # Same established SHA256 HMAC envelope and validated application key as
    # Query; a different operation/version payload, never a created_at cursor.
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(hmac.digest(key, payload, "sha256") + payload).decode().rstrip("=")


def _decode(key, raw, binding):
    try:
        data = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
        signature, payload = data[:32], data[32:]
        if not hmac.compare_digest(signature, hmac.digest(key, payload, "sha256")):
            raise ValueError()
        value = json.loads(payload)
        if (set(value) != {"version", "binding", "lastId", "dataThrough", "point"}
                or value["version"] != VERSION or value["binding"] != binding
                or not isinstance(value["lastId"], str)
                or not 1 <= len(value["lastId"]) <= 40 or "\x00" in value["lastId"]):
            raise ValueError()
        value["lastId"].encode("utf-8")
        point = datetime.fromisoformat(value["point"])
        if point.utcoffset() is None or point.utcoffset().total_seconds() != 10800:
            raise ValueError()
        if value["dataThrough"] is not None:
            through = datetime.fromisoformat(value["dataThrough"])
            if through.utcoffset() is None or through.utcoffset().total_seconds() != 10800:
                raise ValueError()
        return value
    except (ValueError, TypeError, KeyError, UnicodeError, AttributeError, binascii.Error):
        raise HTTPException(400, "Invalid cursor") from None


async def read(request, context, params: dto.NetworkStateQuery) -> dto.NetworkState:
    """Live auth/quota has already completed via get_access_context, every page.

    A fresh request-owned transaction is always rolled back, including after
    success; PostgreSQL LOCAL settings cannot escape into the pool. No domain
    helper borrows the independent identity/quota transaction.
    """
    settings = request.app.state.product_settings
    try:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + BUSINESS_SECONDS
        async with asyncio.timeout(BUSINESS_SECONDS):
            # Stream, rejecting at the first nonempty chunk, without body buffering.
            async for chunk in request.stream():
                if chunk:
                    raise HTTPException(422, "GET body is not supported")
            async with settings.sessions() as db:
                if db.in_transaction():
                    raise HTTPException(503, "Read transaction is unavailable")
                transaction = await db.begin()
                try:
                    await db.execute(text("SET TRANSACTION READ ONLY"))
                    await db.execute(text("SET LOCAL statement_timeout = '5s'"))
                    query = Query(db, request.state.product_facts, context, settings.cursor_key)
                    profile = await db.scalar(select(Company.profile_id).where(
                        Company.id == query.facts.company_id))
                    if profile != "energy":
                        raise HTTPException(404, "Not found")
                    selector = await query.conditions("objects")
                    # Query.binding includes live principal/company/client/install/
                    # grant/scopes/object/org/policy and exact filters/pageSize.
                    binding = query.binding(f"{VERSION}:{context.principal.kind.value}", params)
                    cursor = _decode(query.cursor_key, params.cursor, binding) if params.cursor else None
                    projection = await operational_network_state(
                        db, query.facts.company_id, selector=selector, region=params.region,
                        only_problems=params.onlyProblems, as_of=params.asOf,
                        empty_point=(datetime.fromisoformat(cursor["point"])
                                     if cursor and cursor["dataThrough"] is None else None))
                    boundary = projection["context"]
                    if cursor and (cursor["dataThrough"] != boundary["dataThrough"]
                                   or cursor["point"] != boundary["asOf"]):
                        raise HTTPException(400, "Cursor boundary changed; restart")
                    items = projection["items"]
                    if cursor:
                        items = [item for item in items
                                 if item["objectId"].encode("utf-8") > cursor["lastId"].encode("utf-8")]
                    page = items[:params.pageSize]
                    continuation = _encode(query.cursor_key, {
                        "version": VERSION, "binding": binding, "lastId": page[-1]["objectId"],
                        "dataThrough": boundary["dataThrough"], "point": boundary["asOf"],
                    }) if len(items) > params.pageSize else None
                    result = dto.NetworkState(items=page, summary=projection["summary"],
                                              context=boundary, next_cursor=continuation)
                    # CPU projection/validation also counts towards the deadline.
                    if loop.time() >= deadline:
                        raise TimeoutError()
                    return result
                finally:
                    # Await cleanup to completion even under request cancellation;
                    # do not return a connection with an aborted SQL transaction.
                    cleanup = asyncio.create_task(transaction.rollback())
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        await cleanup
                        raise
    except (TimeoutError, NetworkStateAdmissionExceeded, DBAPIError):
        raise HTTPException(503, "Network read is unavailable") from None
