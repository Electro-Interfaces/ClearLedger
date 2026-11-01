"""Advisory CREATE domains on one read-only REPEATABLE READ snapshot.

No write admission, receipt, locks or body. Canonical runtime imports remain
inside request calls so offline OpenAPI assembly does not import identity.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
import hashlib
import hmac
import time
from uuid import UUID

from anyio import CancelScope
from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api_contracts.context import CREATE_OPTIONS_KEY
from . import access, budget, dto

DEADLINE_SECONDS = 10
CURSOR_TTL_SECONDS = 300
MAX_DOMAIN = 100
RESOURCES = ("organization", "counterparty", "location", "type")
_DB = "elsy.product.options_db"
_CONTEXT = "elsy.product.options_context"
_TOKEN = "elsy.product.options_token"
_BEARER = "elsy.product.options_bearer"
_OWNER = "elsy.product.options_owner"
_DEADLINE = "elsy.product.options_deadline"


def _unavailable():
    raise HTTPException(503, "CREATE options are unavailable")


def _invalid_cursor():
    raise HTTPException(400, "Invalid CREATE options cursor")


def _pack(value):
    """Typed, length-prefixed UTF8; sets sorted by encoded bytes, no normalization."""
    if value is None:
        tag, content = b"n", b""
    elif type(value) is bool:
        tag, content = b"b", b"1" if value else b"0"
    elif type(value) is int:
        tag, content = b"i", str(value).encode("ascii")
    elif isinstance(value, UUID):
        tag, content = b"u", str(value).encode("ascii")
    elif type(value) is str:
        tag, content = b"s", value.encode("utf-8", errors="strict")
    elif isinstance(value, (tuple, list)):
        tag, content = b"t", b"".join(_pack(item) for item in value)
    elif isinstance(value, (set, frozenset)):
        tag, content = b"e", b"".join(sorted(_pack(item) for item in value))
    else:
        raise TypeError("Unsupported options binding")
    return tag + len(content).to_bytes(8, "big") + content


def _b64(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _unb64(value):
    raw = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(raw) != value:
        raise ValueError("Noncanonical base64")
    return raw


def _mac(key, domain, value):
    if type(key) is not bytes or len(key) < 32:
        _unavailable()
    return hmac.new(key, b"options-v1\x00" + _pack((domain, value)), hashlib.sha256).digest()


def selection_version(key, binding):
    return _b64(_mac(key, "selection", binding))


def encode_cursor(key, binding, resource, page_size, last_value, expires):
    # Opaque v2: version/resource/pageSize (1 byte each), expiry (8), UTF8
    # byte length (2), selection digest (32), then unchanged UTF8 lastValue.
    # At most 45 + 256*4 = 1069 bytes => 1426 base64 + dot + 43 MAC = 1470.
    if (type(resource) is not str or resource not in RESOURCES
            or type(page_size) is not int or not 1 <= page_size <= 100
            or type(expires) is not int or not 0 <= expires < 2**64
            or type(last_value) is not str or "\x00" in last_value
            or not 1 <= len(last_value) <= (256 if resource == "type" else 40)
            or (resource == "type" and not last_value.strip())
            or (resource in RESOURCES[:2] and str(UUID(last_value)) != last_value)):
        _unavailable()
    value = last_value.encode("utf-8", errors="strict")
    raw = (bytes((2, RESOURCES.index(resource), page_size)) + expires.to_bytes(8, "big")
        + len(value).to_bytes(2, "big") + _mac(key, "selection", binding) + value)
    encoded = _b64(raw)
    return encoded + "." + _b64(_mac(key, "cursor-v2", (binding, encoded)))


def decode_cursor(cursor, key, binding, resource, page_size, now):
    try:
        if type(cursor) is not str or not 1 <= len(cursor) <= 2048:
            raise ValueError()
        encoded, signature = cursor.split(".")
        raw, mac = _unb64(encoded), _unb64(signature)
        if not hmac.compare_digest(mac, _mac(key, "cursor-v2", (binding, encoded))):
            raise ValueError()
        if (not 45 <= len(raw) <= 1069 or raw[0] != 2
                or type(resource) is not str or resource not in RESOURCES
                or raw[1] != RESOURCES.index(resource)
                or type(page_size) is not int or not 1 <= page_size <= 100 or raw[2] != page_size
                or int.from_bytes(raw[11:13], "big") != len(raw) - 45
                or not hmac.compare_digest(raw[13:45], _mac(key, "selection", binding))):
            raise ValueError()
        expires = int.from_bytes(raw[3:11], "big")
        last_value = raw[45:].decode("utf-8", errors="strict")
        if (not now < expires <= now + CURSOR_TTL_SECONDS
                or "\x00" in last_value
                or not 1 <= len(last_value) <= (256 if resource == "type" else 40)
                or (resource == "type" and not last_value.strip())
                or (resource in RESOURCES[:2] and str(UUID(last_value)) != last_value)):
            raise ValueError()
        return last_value, expires
    except (ValueError, TypeError, KeyError, UnicodeError):
        _invalid_cursor()


def _binding(token, profile, domains, member_scope):
    grants = tuple((kind, scope.mode, frozenset(scope.ids))
        for kind, scope in sorted(token.resource_scopes.items()))
    return ("GET", "/api/v1/contracts/create-options", "getContractCreateOptions", access.POLICY_VERSION,
        token.company_id, token.app_id, token.client_id, token.installation_id, token.grant_id,
        "machine" if token.is_machine else "user", token.client_id if token.is_machine else token.user_id,
        token.token_id, token.scopes, profile["id"], profile["policy_generation"],
        domains, token.own_organization_id, grants, token.location_ids, member_scope)


def _rows(db, statement, limit=MAX_DOMAIN):
    result = tuple(tuple(row) for row in db.execute(statement.limit(limit + 1)))
    if len(result) > limit:
        _unavailable()
    return result


def _profile(db, current):
    from sqlalchemy import select
    from app.models_partner_contracts import PartnerContractCreateProfile as Profile
    from app.services import partner_contract_authority as authority
    from app.services.partner_contract_profiles import _PROFILE, _CHILDREN
    parent = _rows(db, select(*(getattr(Profile, n) for n in _PROFILE)).where(
        Profile.installation_id == current.installation_id), 1)
    if not parent:
        authority._deny()
    profile = dict(zip(_PROFILE, parent[0]))
    if (profile["company_id"], profile["client_id"], profile["installation_id"]) != (
            current.company_id, current.client_id, current.installation_id):
        authority._deny()
    model, names = _CHILDREN[0]
    principals = tuple(row for kind in ("user", "machine") for row in _rows(db, select(
        *(getattr(model, n) for n in names)).where(model.profile_id == profile["id"], model.actor_kind == kind)))
    return parent, profile, principals


def _coarse(db, current):
    from app.services import partner_contract_authority as authority
    with db.no_autoflush:
        parent, _, principals = _profile(db, current)
        authority._require_coarse_create(db, current, (parent, (principals, (), ())))


async def require_coarse(db, current):
    # Bounded options-specific SQL loader; the existing E owns the allow policy.
    await db.run_sync(_coarse, current)


def _load(db, current):
    """Whole CREATE profile closure, no second allow policy and no foreign walk.

    Missing unrelated User/Member/home is stable absence, as in E.discover's
    canonical get composer. Present foreign Role and required refs/grants deny.
    The canonical verifier is independently deadline-bounded, not claimed to be
    SQL-row-bounded by this loader's limit+1 projection.
    """
    from sqlalchemy import select
    from app.models import Company, CompanyRole, Counterparty, Organization, ServiceLocation, User, UserCompany
    from app.models_partner import PartnerGrant
    from app.services import partner_contract_authority as authority
    from app.services.partner_contract_profiles import _CHILDREN

    with db.no_autoflush:
        parent, profile, principals = _profile(db, current)
        ref_model, ref_names = _CHILDREN[1]
        refs = tuple(row for kind in RESOURCES[:3] for row in _rows(db, select(
            *(getattr(ref_model, n) for n in ref_names)).where(
                ref_model.profile_id == profile["id"], ref_model.kind == kind)))
        type_model, type_names = _CHILDREN[2]
        types = _rows(db, select(*(getattr(type_model, n) for n in type_names)).where(
            type_model.profile_id == profile["id"]))
        authority._require_coarse_create(db, current, (parent, (principals, refs, types)))
        # Load every profile user, including unrelated principals. Do not turn
        # absence/inactivity of unrelated accounts into a new policy veto.
        member_scope = None
        users = {r[3] for r in principals if r[3] is not None}
        if current.user_id is not None:
            users.add(current.user_id)
        for uid in sorted(users):
            user = db.get(User, uid, populate_existing=True)
            member = db.get(UserCompany, (uid, current.company_id), populate_existing=True)
            if user is not None and user.company_id is not None:
                db.get(Company, user.company_id, populate_existing=True)
            if member is not None and member.role_id is not None:
                role = db.scalar(select(CompanyRole).where(CompanyRole.id == member.role_id,
                    CompanyRole.company_id == current.company_id).execution_options(populate_existing=True))
                if role is None:
                    authority._deny()
            if uid == current.user_id and member is not None:
                member_scope = None if member.object_scope is None else frozenset(member.object_scope)
        for gid in sorted({r[4] for r in principals if r[4] is not None}):
            grant = db.get(PartnerGrant, gid, populate_existing=True)
            if grant is None or (grant.company_id, grant.client_id, grant.installation_id, grant.kind, grant.user_id) != (
                    current.company_id, current.client_id, current.installation_id, "machine", None):
                authority._deny()
        for model, offset in ((Organization, 3), (Counterparty, 4), (ServiceLocation, 5)):
            ids = {r[offset] for r in refs if r[offset] is not None}
            actual = _rows(db, select(model.id).where(model.company_id == current.company_id, model.id.in_(ids)))
            if {r[0] for r in actual} != ids:
                authority._deny()
        codes = {r[1] for r in types}
        # Core catalog has a unique code; SQLAlchemy select permits a bound
        # limit+1 even though this legacy catalog has no ORM class.
        from sqlalchemy import column, table
        catalog_table = table("contract_types", column("code"), column("is_active"), schema="core")
        loaded = _rows(db, select(catalog_table.c.code, catalog_table.c.is_active).where(catalog_table.c.code.in_(codes)))
        catalog = {code: ((code, active),) for code, active in loaded}
        domains = authority.select_create_domains(current, refs, types, catalog, member_scope)
        canonical = tuple(frozenset(str(item) for item in domain) for domain in domains)
        return canonical, _binding(current, profile, canonical, member_scope)


async def _rollback(db):
    with CancelScope(shield=True):
        await db.rollback()


def _check_owner(db, owner):
    root, connection = owner
    if (db.sync_session.get_transaction() is not root or root is None or not root.is_active
            or db.sync_session.get_nested_transaction() is not None
            or db.new or db.dirty or db.deleted
            or connection.engine is not db.bind.sync_engine
            or not root._connections
            or any(value[0] is not connection or not value[2] or not value[3]
                   for value in root._connections.values())):
        _unavailable()
    return connection


@asynccontextmanager
async def request_lifetime(request: Request):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
    settings = request.app.state.product_settings
    db = None
    try:
        async with asyncio.timeout(DEADLINE_SECONDS) as deadline:
            request.scope[_DEADLINE] = deadline
            bearer = access.request_bearer(request)
            async with settings.sessions() as preflight:
                try:
                    if (not isinstance(preflight, AsyncSession) or not isinstance(preflight.bind, AsyncEngine)
                            or preflight.in_transaction() or preflight.new or preflight.dirty or preflight.deleted):
                        _unavailable()
                    token, _ = await access.options_preflight(request, preflight, bearer)
                    key = budget.Key(token.company_id, token.installation_id, token.client_id)
                finally:
                    await _rollback(preflight)
            await budget.enforce(settings.budget_policy(), settings.sessions, key)
            # Separate clean actual Session. Set connection characteristics
            # before ANY SQL, including canonical auth, so one MVCC t0 owns all.
            async with settings.sessions() as db:
                try:
                    if (not isinstance(db, AsyncSession) or not isinstance(db.bind, AsyncEngine)
                            or db.in_transaction()
                            or db.new or db.dirty or db.deleted):
                        _unavailable()
                    connection = await db.connection(execution_options={
                        "isolation_level": "REPEATABLE READ", "postgresql_readonly": True})
                    owner = (db.sync_session.get_transaction(), connection.sync_connection)
                    remaining = int((deadline.when() - asyncio.get_running_loop().time()) * 1000)
                    if remaining <= 0:
                        _unavailable()
                    await db.execute(text("SELECT set_config('statement_timeout', :ms, true), pg_current_snapshot()"), {"ms": str(remaining)})
                    token, context = await access.options_preflight(request, db, bearer, bind=True)
                    request.scope.update({_DB: db, _CONTEXT: context, _TOKEN: token, _BEARER: bearer, _OWNER: owner})
                    yield
                    _check_owner(db, owner)
                    if (await db.connection()).sync_connection is not owner[1] or asyncio.get_running_loop().time() >= deadline.when():
                        _unavailable()
                finally:
                    await _rollback(db)
    except (StarletteHTTPException, RequestValidationError):
        raise
    except Exception:
        _unavailable()
    finally:
        for key in (_DB, _CONTEXT, _TOKEN, _BEARER, _OWNER, _DEADLINE, CREATE_OPTIONS_KEY):
            request.scope.pop(key, None)


async def options(request: Request, params: dto.ContractCreateOptionsQuery) -> JSONResponse:
    db, token = request.scope[_DB], request.scope[_TOKEN]
    owner, deadline = request.scope[_OWNER], request.scope[_DEADLINE]
    _check_owner(db, owner)
    domains, binding = await db.run_sync(_load, token)
    # Repeat the SAME canonical JWT/expiry/process-gate verifier before DTO.
    # All database reads still see t0; this is deliberately not fresh post-wait DB.
    access.request_bearer(request)
    current, _ = await access.options_preflight(request, db, request.scope[_BEARER])
    if current != token:
        _unavailable()
    _check_owner(db, owner)
    if (await db.connection()).sync_connection is not owner[1] or asyncio.get_running_loop().time() >= deadline.when():
        _unavailable()
    key = request.app.state.product_settings.cursor_key
    now = int(time.time())
    values = sorted(domains[RESOURCES.index(params.resource)], key=lambda item: item.encode("utf-8"))
    expiry, last = now + CURSOR_TTL_SECONDS, None
    if params.cursor is not None:
        last, expiry = decode_cursor(params.cursor, key, binding, params.resource, params.pageSize, now)
        if last not in values:
            _invalid_cursor()
        values = [item for item in values if item.encode("utf-8") > last.encode("utf-8")]
    selected = values[:params.pageSize]
    continuation = encode_cursor(key, binding, params.resource, params.pageSize, selected[-1], expiry) if len(values) > len(selected) else None
    value = dto.ContractCreateOptions(resource=params.resource, items=[dto.ContractCreateOption(value=item) for item in selected],
        selection_version=selection_version(key, binding), next_cursor=continuation)
    return JSONResponse(value.model_dump(mode="json", by_alias=True))
