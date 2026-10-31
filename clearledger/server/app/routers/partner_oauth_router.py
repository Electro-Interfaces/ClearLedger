"""Thin FastAPI transport for Authlib; consent is always an explicit Core action."""
from __future__ import annotations

import time
import uuid
from collections import OrderedDict, deque
from datetime import timedelta
from urllib.parse import parse_qsl

from authlib.oauth2.rfc6749 import InvalidClientError, InvalidRequestError, InvalidScopeError, OAuth2Error
from authlib.oauth2.rfc6749.util import extract_basic_authorization
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import current_token_claims
from app.database import get_db
from app.models import App, Company, CompanyApp, User
from app.models_partner import PartnerAuthorizationRequest, PartnerGrant, PartnerInstallation
from app.schemas_partner import ApproveConsent
from app.services.partner_identity import (NO_STORE, SCOPE_DESCRIPTIONS, PartnerAuthorizationServer, PartnerProblem, PartnerRoute,
    ProtocolRequest, eligible_scopes, get_verified_partner_token, live_grant, now, partner_bearer_headers, public_jwks,
    require_core_user, require_enabled, settings, user_info, validate_scopes)

router = APIRouter(prefix="/oauth2", tags=["Partner OAuth/OIDC"], route_class=PartnerRoute)
well_known_router = APIRouter(tags=["Partner discovery"], route_class=PartnerRoute)
consent_router = APIRouter(prefix="/developer/authorization-requests", tags=["Partner consent"], route_class=PartnerRoute)

_hits: OrderedDict[str, deque] = OrderedDict()


def protocol_error(error: str, status: int = 400):
    headers = {**NO_STORE, **({"WWW-Authenticate": "Basic"} if status == 401 else {})}
    return JSONResponse({"error": error}, status_code=status, headers=headers)


def result_response(result):
    status, body, headers = result
    headers = {**dict(headers), **NO_STORE}
    if status >= 400:
        # Library descriptions may contain untrusted URI/client data.
        body = {"error": body.get("error", "invalid_request")}
    return JSONResponse(body, status_code=status, headers=headers)


def throttle(request: Request):
    require_enabled()
    # Per-process cap, no spoofable X-Forwarded-For. Edge should additionally
    # limit by verified remote IP when deployed with multiple workers.
    key = request.client.host if request.client else "unknown"
    stamp = time.monotonic()
    hits = _hits.setdefault(key, deque())
    _hits.move_to_end(key)
    while hits and hits[0] < stamp - 60:
        hits.popleft()
    if len(hits) >= 120:
        raise HTTPException(429, "Too many OAuth requests", headers={**NO_STORE, "Retry-After": "60"})
    hits.append(stamp)
    while len(_hits) > 10000:
        _hits.popitem(last=False)


def parameters(pairs):
    data = {}
    if len(pairs) > 24:
        raise InvalidRequestError()
    for key, value in pairs:
        if key in data or len(key) > 64 or len(value) > 8192 or not key:
            raise InvalidRequestError()
        data[key] = value
    return data


async def form_request(request: Request) -> ProtocolRequest:
    throttle(request)
    if request.query_params or request.headers.get("content-type", "").split(";")[0].lower() != "application/x-www-form-urlencoded":
        raise InvalidRequestError()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 16384:
            raise InvalidRequestError()
    try:
        data = parameters(parse_qsl(body.decode("utf-8"), keep_blank_values=True, strict_parsing=True, max_num_fields=24))
    except (ValueError, UnicodeError):
        raise InvalidRequestError() from None
    if "authorization" in request.headers and ("client_secret" in data or "client_id" in data):
        # One client authentication method per request (RFC 6749 2.3).
        raise InvalidRequestError()
    if len(request.headers.get("authorization", "")) > 8192:
        raise InvalidRequestError()
    try:
        extract_basic_authorization(request.headers)
    except UnicodeError:
        # Authlib's Basic parser handles bad base64 but lets invalid UTF-8
        # escape. Keep this transport-decoding error inside OAuth responses.
        raise InvalidClientError(status_code=401) from None
    # Authlib reads Authorization case-insensitively through this ASGI adapter.
    return ProtocolRequest("POST", data, request.headers)


@router.get("/authorize")
async def authorize(request: Request, db: AsyncSession = Depends(get_db)):
    throttle(request)
    try:
        if len(request.url.query) > 8192:
            raise InvalidRequestError()
        data = parameters(list(request.query_params.multi_items()))
        if set(data) - {"response_type", "client_id", "redirect_uri", "scope", "state", "nonce", "code_challenge", "code_challenge_method", "prompt"}:
            raise InvalidRequestError()
        if (not data.get("state") or len(data["state"]) > 256 or len(data.get("nonce", "")) > 256
                or data.get("prompt", "consent") != "consent"):
            raise InvalidRequestError()
        def create(sync):
            server = PartnerAuthorizationServer(sync)
            server.get_consent_grant(ProtocolRequest("GET", data))
            pending = PartnerAuthorizationRequest(client_id=data["client_id"], parameters=data,
                expires_at=now() + timedelta(minutes=5))
            sync.add(pending)
            sync.flush()
            return pending.id
        rid = await db.run_sync(create)
        await db.commit()
        return RedirectResponse("/developer/authorize?requestId=" + str(rid), status_code=302, headers=NO_STORE)
    except OAuth2Error as exc:
        # Invalid callbacks never receive a redirect. SPA URL is fixed.
        return protocol_error(exc.error)


@router.post("/token")
async def token(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        protocol = await form_request(request)
        result = await db.run_sync(lambda sync: PartnerAuthorizationServer(sync).create_token_response(protocol))
        # Commit before publishing tokens: code consumption/refresh rotation and
        # reuse revocation must be durable before another call can begin.
        await db.commit()
        return result_response(result)
    except OAuth2Error as exc:
        return protocol_error(exc.error, exc.status_code)


@router.post("/revoke")
async def revoke(request: Request, db: AsyncSession = Depends(get_db)):
    try:
        protocol = await form_request(request)
        result = await db.run_sync(lambda sync: PartnerAuthorizationServer(sync).create_endpoint_response("revocation", protocol))
        await db.commit()
        return result_response(result)
    except OAuth2Error as exc:
        return protocol_error(exc.error, exc.status_code)


@well_known_router.get("/.well-known/openid-configuration", include_in_schema=False)
@router.get("/.well-known/openid-configuration")
async def discovery():
    require_enabled()
    issuer = settings.partner_oauth_issuer
    root = issuer + "/api/oauth2"
    return JSONResponse({"issuer": issuer, "authorization_endpoint": root + "/authorize",
        "token_endpoint": root + "/token", "userinfo_endpoint": root + "/userinfo",
        "jwks_uri": root + "/jwks", "revocation_endpoint": root + "/revoke",
        "response_types_supported": ["code"], "response_modes_supported": ["query"],
        "grant_types_supported": ["authorization_code", "refresh_token", "client_credentials"],
        "subject_types_supported": ["pairwise"], "id_token_signing_alg_values_supported": ["RS256"],
        "token_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
        "revocation_endpoint_auth_methods_supported": ["none", "client_secret_basic"],
        "code_challenge_methods_supported": ["S256"], "scopes_supported": list(SCOPE_DESCRIPTIONS),
        "claims_supported": ["sub", "iss", "aud", "iat", "exp", "auth_time", "nonce", "at_hash", "name", "email"]}, headers=NO_STORE)


@router.get("/jwks")
async def jwks():
    require_enabled()
    return JSONResponse(public_jwks(), headers=NO_STORE)


@router.get("/userinfo")
async def userinfo(identity=Depends(get_verified_partner_token), db: AsyncSession = Depends(get_db)):
    if identity.is_machine or "openid" not in identity.scopes:
        return JSONResponse({"error": "insufficient_scope"}, status_code=403,
            headers=partner_bearer_headers("insufficient_scope"))
    return JSONResponse(await db.run_sync(lambda sync: user_info(sync, sync.get(User, identity.user_id),
        identity.client_id, set(identity.scopes))), headers=NO_STORE)


def pending_request(sync, rid, user):
    row = sync.scalar(select(PartnerAuthorizationRequest).where(PartnerAuthorizationRequest.id == rid)
        .with_for_update().execution_options(populate_existing=True))
    if row is None or (row.user_id and row.user_id != user.id):
        raise PartnerProblem(404, "AUTH_REQUEST_NOT_FOUND", "Запрос авторизации не найден")
    if row.finished:
        raise PartnerProblem(409, "AUTH_REQUEST_CONSUMED", "Запрос авторизации уже обработан")
    if row.expires_at <= now():
        raise PartnerProblem(410, "AUTH_REQUEST_EXPIRED", "Срок запроса авторизации истёк")
    if PartnerAuthorizationServer(sync).query_client(row.client_id) is None:
        raise PartnerProblem(403, "AUTHORIZATION_REVOKED", "Авторизация приложения отозвана")
    row.user_id = user.id
    return row


def eligible_installations(sync, row, user):
    rows = sync.execute(select(PartnerInstallation, CompanyApp, Company).join(
        CompanyApp, PartnerInstallation.id == CompanyApp.id).join(Company, Company.id == CompanyApp.company_id).where(
        PartnerInstallation.client_id == row.client_id, PartnerInstallation.approved.is_(True), CompanyApp.enabled.is_(True))).all()
    requested = set(row.parameters["scope"].split())
    client = PartnerAuthorizationServer(sync).query_client(row.client_id)
    if client is None:
        raise PartnerProblem(403, "AUTHORIZATION_REVOKED", "Авторизация приложения отозвана")
    return [(i, ca, c, requested & set(i.scopes) & set(client.model.allowed_scopes) & eligible_scopes(sync, user, c.id))
            for i, ca, c in rows if ca.app_id == client.model.app_id]


@consent_router.get("/{request_id}")
async def get_request(request_id: uuid.UUID, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    def detail(sync):
        row = pending_request(sync, request_id, user)
        # Revalidate persisted original parameters, including current client state.
        server = PartnerAuthorizationServer(sync)
        server.get_consent_grant(ProtocolRequest("GET", row.parameters))
        app = sync.get(App, server.query_client(row.client_id).model.app_id)
        companies = [{"id": str(c.id), "name": c.name, "eligibleScopes": sorted(scopes)}
            for i, ca, c, scopes in eligible_installations(sync, row, user) if scopes]
        if not companies:
            raise PartnerProblem(403, "AUTHORIZATION_REVOKED", "Нет действующего разрешения компании")
        return {"id": str(row.id), "clientName": app.name,
            "requestedScopes": [{"code": s, "description": SCOPE_DESCRIPTIONS[s]} for s in sorted(row.parameters["scope"].split())],
            "companies": companies,
            "expiresAt": row.expires_at.isoformat()}
    try:
        result = await db.run_sync(detail)
        await db.commit()
        return JSONResponse(result, headers=NO_STORE)
    except OAuth2Error as exc:
        return protocol_error(exc.error)


@consent_router.post("/{request_id}/approve")
async def approve(request_id: uuid.UUID, body: ApproveConsent, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    claims = dict(current_token_claims() or {})
    def accept(sync):
        row = pending_request(sync, request_id, user)
        try:
            requested = validate_scopes(body.scopes)
        except InvalidScopeError:
            raise PartnerProblem(422, "INVALID_AUTHORIZATION_SELECTION", "Выберите допустимые права") from None
        if "openid" in row.parameters["scope"].split() and "openid" not in requested:
            raise PartnerProblem(422, "INVALID_AUTHORIZATION_SELECTION", "Требуется подтверждение openid")
        known = sync.scalar(select(PartnerInstallation).where(PartnerInstallation.client_id == row.client_id,
            PartnerInstallation.company_id == body.companyId))
        if known and eligible_scopes(sync, user, body.companyId):
            company_app = sync.get(CompanyApp, known.id)
            if not known.approved or company_app is None or not company_app.enabled:
                raise PartnerProblem(403, "AUTHORIZATION_REVOKED", "Разрешение компании отозвано")
        choices = [(i, ca, c, s) for i, ca, c, s in eligible_installations(sync, row, user) if c.id == body.companyId]
        if len(choices) != 1 or not requested <= choices[0][3]:
            raise PartnerProblem(422, "INVALID_AUTHORIZATION_SELECTION", "Выбрана недоступная компания или права")
        install = choices[0][0]
        params = {**row.parameters, "scope": " ".join(sorted(requested))}
        server = PartnerAuthorizationServer(sync)
        protocol = ProtocolRequest("GET", params)
        grant = server.get_consent_grant(protocol, end_user=user)
        consent = PartnerGrant(installation_id=install.id, client_id=row.client_id,
            company_id=body.companyId, user_id=user.id, kind="user", scopes=sorted(requested), approved=True)
        sync.add(consent)
        sync.flush()
        live_grant(sync, consent.id)
        server.approved_grant, server.parent_claims = consent, claims
        result = server.create_authorization_response(protocol, grant_user=user, grant=grant)
        if result[0] != 302 or "Location" not in dict(result[2]):
            raise InvalidRequestError()
        row.finished = True
        sync.flush()
        return {"redirectUrl": dict(result[2])["Location"]}
    try:
        result = await db.run_sync(accept)
        await db.commit()
        return JSONResponse(result, headers=NO_STORE)
    except OAuth2Error as exc:
        await db.rollback()
        return protocol_error(exc.error)


@consent_router.post("/{request_id}/deny")
async def deny(request_id: uuid.UUID, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    def decline(sync):
        row = pending_request(sync, request_id, user)
        server = PartnerAuthorizationServer(sync)
        protocol = ProtocolRequest("GET", row.parameters)
        grant = server.get_consent_grant(protocol, end_user=user)
        result = server.create_authorization_response(protocol, grant_user=None, grant=grant)
        redirect = dict(result[2]).get("Location")
        if not redirect:
            raise InvalidRequestError()
        row.finished = True
        return {"redirectUrl": redirect}
    try:
        result = await db.run_sync(decline)
        await db.commit()
        return JSONResponse(result, headers=NO_STORE)
    except OAuth2Error as exc:
        return protocol_error(exc.error)
