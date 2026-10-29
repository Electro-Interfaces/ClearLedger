"""Partner OAuth/OIDC provider: Authlib protocol + Core persistence/policy adapter.

The synchronous Authlib callbacks execute ONLY SQLAlchemy I/O via
AsyncSession.run_sync, on the caller's transaction and PostgreSQL connection.
No global server/request state, thread pools, independent transactions or fake
Core users. Consumers receive the immutable VerifiedPartnerToken below.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Literal, Mapping
from urllib.parse import urlsplit

import jwt
from authlib.oauth2.rfc6749 import AuthorizationServer, InvalidGrantError, InvalidRequestError, InvalidScopeError, OAuth2Request
from authlib.oauth2.rfc6749.grants import AuthorizationCodeGrant, ClientCredentialsGrant, RefreshTokenGrant
from authlib.oauth2.rfc6749.requests import BasicOAuth2Payload
from authlib.oauth2.rfc7009 import RevocationEndpoint
from authlib.oauth2.rfc7636 import CodeChallenge
from authlib.oidc.core import UserInfo
from authlib.oidc.core.grants import OpenIDCode
from fastapi import Depends, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.auth import MAX_SESSION_DAYS, current_token_claims, get_current_user
from app.config import get_settings
from app.database import get_db
from app.models import App, Company, CompanyApp, CompanyRole, ServiceLocation, User, UserCompany, Counterparty, Contract, DocCard, EzsEquipmentUnit
from app.models_partner import (PartnerClient, PartnerCode, PartnerCredential,
    PartnerGrant, PartnerInstallation, PartnerInstallationLocation, PartnerResourceItem, PartnerResourceScope, PartnerSubject, PartnerToken, PartnerTokenFamily)

settings = get_settings()
NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}
# New scopes require reviewed mappings here, then domain policy in M03.
SCOPE_DESCRIPTIONS = {
    "openid": "Вход через пространство", "profile": "Имя пользователя",
    "email": "Адрес электронной почты", "offline_access": "Продление согласованного доступа",
    "docs:read": "Чтение документации API",
    "objects:read": "Чтение объектов компании", "equipment:read": "Чтение оборудования компании",
    "counterparties:read": "Чтение контрагентов компании", "contracts:read": "Чтение договоров компании",
    "documents:read": "Чтение карточек документов", "documents.files:download": "Скачивание файлов документов",
}
IDENTITY_SCOPES = frozenset({"openid", "profile", "email", "offline_access"})
RESOURCE_MODELS = {"objects": (ServiceLocation, "object_id"), "equipment": (EzsEquipmentUnit, "equipment_id"),
    "counterparties": (Counterparty, "counterparty_id"), "contracts": (Contract, "contract_id"), "documents": (DocCard, "document_id")}


class PartnerProblem(Exception):
    def __init__(self, status: int, code: str, detail: str):
        self.status, self.code, self.detail = status, code, detail


async def problem_handler(request, error: PartnerProblem):
    return JSONResponse({"type": "about:blank", "title": error.detail, "status": error.status,
        "code": error.code, "detail": error.detail, "requestId": getattr(request.state, "request_id", None) or uuid.uuid4().hex},
        status_code=error.status, media_type="application/problem+json", headers=NO_STORE)


class PartnerRoute(APIRoute):
    """Keep auth/schema errors on this boundary private too, without altering Core."""
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except HTTPException as exc:
                exc.headers = {**(exc.headers or {}), **NO_STORE}
                raise
            except RequestValidationError:
                if "/developer/authorization-requests/" in request.url.path:
                    error = (PartnerProblem(404, "AUTH_REQUEST_NOT_FOUND", "Запрос авторизации не найден")
                        if request.method == "GET" else PartnerProblem(422, "INVALID_AUTHORIZATION_SELECTION", "Некорректная компания или права"))
                    return await problem_handler(request, error)
                return JSONResponse({"detail": "Invalid partner request"}, status_code=422, headers=NO_STORE)
            response.headers.update(NO_STORE)
            return response

        return handler


def now() -> datetime:
    return datetime.now(timezone.utc)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_enabled() -> None:
    if not settings.partner_oauth_enabled:
        raise PartnerProblem(503, "PARTNER_API_DISABLED", "Доступ внешних приложений выключен")
    try:
        # urlsplit strips some raw controls and delays port validation until
        # .port is accessed. Do both before any registry/token side effect.
        if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in settings.partner_oauth_issuer) or "\\" in settings.partner_oauth_issuer:
            raise ValueError("Invalid issuer characters")
        issuer = urlsplit(settings.partner_oauth_issuer)
        if issuer.port is not None and issuer.port < 1:
            raise ValueError("Invalid issuer port")
    except ValueError:
        raise HTTPException(503, "Partner identity is not configured", headers=NO_STORE) from None
    if (issuer.scheme != "https" or not issuer.hostname or issuer.query or issuer.fragment
            or issuer.path or issuer.username is not None or issuer.password is not None or not settings.partner_oauth_audience
            or settings.partner_oauth_audience == settings.partner_oauth_issuer
            or not (settings.partner_oauth_signing_key or settings.sso_signing_key)):
        raise HTTPException(503, "Partner identity is not configured", headers=NO_STORE)
    # Validate the configured asymmetric key before any registration/grant write.
    try:
        key = jwt.algorithms.RSAAlgorithm.from_jwk(public_jwks()["keys"][0])
        if key.key_size < 2048:
            raise ValueError("weak RSA key")
    except Exception as exc:
        raise HTTPException(503, "Partner identity is not configured", headers=NO_STORE) from exc


def signing_key() -> str:
    return base64.b64decode(settings.partner_oauth_signing_key or settings.sso_signing_key, validate=True).decode("ascii")


def public_jwks() -> dict:
    from cryptography.hazmat.primitives import serialization
    private = serialization.load_pem_private_key(signing_key().encode(), password=None)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key(), as_dict=True)
    jwk.update(kid=settings.partner_oauth_kid, use="sig", alg="RS256")
    return {"keys": [jwk]}


def validate_redirect(uri: str) -> None:
    try:
        p = urlsplit(uri)
    except ValueError:
        raise HTTPException(400, "Invalid exact redirect URI", headers=NO_STORE) from None
    local = (settings.partner_oauth_allow_localhost and settings.app_env != "prod"
             and p.hostname in {"localhost", "127.0.0.1", "::1"} and p.scheme == "http")
    if (len(uri) > 2048 or not p.hostname or (p.scheme != "https" and not local)
            or p.fragment or p.username is not None or p.password is not None or "*" in uri or "\\" in uri
            or any(ord(c) <= 32 or ord(c) == 127 for c in uri)):
        raise HTTPException(400, "Invalid exact redirect URI", headers=NO_STORE)
    try:
        p.port
    except ValueError as exc:
        raise HTTPException(400, "Invalid redirect port", headers=NO_STORE) from exc


def validate_scopes(scopes) -> set[str]:
    values = set(scopes)
    if not values or not values <= SCOPE_DESCRIPTIONS.keys():
        raise InvalidScopeError()
    if values & {"profile", "email", "offline_access"} and "openid" not in values:
        raise InvalidScopeError()
    return values


def fresh(db: Session, model, key):
    return db.get(model, key, populate_existing=True)


def active_user(user: User | None) -> bool:
    # Core has no is_active column: mail_only/no password/lock/delete and tv
    # are the actual account-disable mechanisms in this schema.
    return bool(user and not user.mail_only and user.password_hash
                and (user.locked_until is None or user.locked_until <= now()))


def admin(db: Session, user: User, company_id: uuid.UUID) -> None:
    if not active_user(fresh(db, User, user.id)) or not fresh(db, Company, company_id):
        raise HTTPException(403, "Company administrator required", headers=NO_STORE)
    member = fresh(db, UserCompany, (user.id, company_id))
    if not user.is_superadmin and (member is None or member.role != "admin"):
        raise HTTPException(403, "Company administrator required", headers=NO_STORE)


def eligible_scopes(db: Session, user: User, company_id: uuid.UUID) -> set[str]:
    if not active_user(user):
        return set()
    member = fresh(db, UserCompany, (user.id, company_id))
    if member is None:
        # An actual company membership is required even for a Core superadmin.
        return set()
    allowed = set(IDENTITY_SCOPES)
    if user.is_superadmin or member.role == "admin":
        return set(SCOPE_DESCRIPTIONS)
    modules = member.modules
    if member.role_id is not None:
        role = fresh(db, CompanyRole, member.role_id)
        if role is None or role.company_id != company_id:
            return set()
        modules = role.modules
    if modules is None or "developer" in modules or "developer:docs" in modules:
        allowed.add("docs:read")
    # Each domain keeps its finer resource/field policy in M03. Do not infer
    # domain rights from an unrelated product or a generic membership.
    domain_modules = {"objects:read": "equipment", "equipment:read": "equipment",
        "counterparties:read": "references", "contracts:read": "references",
        "documents:read": "docs", "documents.files:download": "docs"}
    for scope, module in domain_modules.items():
        if modules is None or module in modules:
            allowed.add(scope)
    return allowed


@dataclass(frozen=True, slots=True)
class VerifiedResourceScope:
    mode: Literal["ALL", "SET", "EMPTY"]
    ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class VerifiedPartnerToken:
    client_id: str
    app_id: uuid.UUID
    installation_id: uuid.UUID
    company_id: uuid.UUID
    grant_id: uuid.UUID
    user_id: uuid.UUID | None
    scopes: frozenset[str]
    # None = ALL, frozenset() = EMPTY; never collapse an empty set to ALL.
    location_ids: frozenset[str] | None
    subject: str
    token_id: uuid.UUID
    expires_at: datetime
    is_machine: bool
    resource_scopes: Mapping[str, VerifiedResourceScope]
    own_organization_id: uuid.UUID | None = None


@dataclass(frozen=True)
class LiveGrant:
    grant: PartnerGrant
    client: PartnerClient
    installation: PartnerInstallation
    company_app: CompanyApp
    user: User | None
    location_ids: frozenset[str] | None
    own_organization_id: uuid.UUID | None
    resource_scopes: Mapping[str, VerifiedResourceScope]


def resource_scopes(db: Session, installation_id, company_id, member_locations):
    result = {}
    for kind, (model, column) in RESOURCE_MODELS.items():
        profile = fresh(db, PartnerResourceScope, (installation_id, kind))
        mode = profile.mode if profile else "EMPTY"
        ids = frozenset()
        if mode == "SET":
            raw = db.scalars(select(getattr(PartnerResourceItem, column)).where(
                PartnerResourceItem.installation_id == installation_id, PartnerResourceItem.kind == kind)).all()
            ids = frozenset(str(v) for v in raw)
            valid = frozenset(str(v) for v in db.scalars(select(model.id).where(
                model.company_id == company_id, model.id.in_(raw))).all())
            if ids != valid:
                raise InvalidGrantError()
            if not ids:
                mode = "EMPTY"
        if kind == "objects" and member_locations is not None:
            ids = member_locations if mode == "ALL" else ids & member_locations
            mode = "SET" if ids else "EMPTY"
        result[kind] = VerifiedResourceScope(mode, ids)
    return MappingProxyType(result)


def live_grant(db: Session, grant_id: uuid.UUID, *, family: PartnerTokenFamily | None = None,
               scope: str | None = None) -> LiveGrant:
    denied = InvalidGrantError()
    grant = fresh(db, PartnerGrant, grant_id)
    if grant is None or not grant.approved:
        raise denied
    client = fresh(db, PartnerClient, grant.client_id)
    installation = fresh(db, PartnerInstallation, grant.installation_id)
    company_app = fresh(db, CompanyApp, grant.installation_id)
    if (client is None or not client.enabled or installation is None or not installation.approved
            or company_app is None or not company_app.enabled or installation.client_id != client.id
            or company_app.app_id != client.app_id or installation.company_id != company_app.company_id
            or grant.company_id != company_app.company_id or not fresh(db, Company, company_app.company_id)):
        raise denied
    app = fresh(db, App, client.app_id)
    scopes = set((scope or " ".join(grant.scopes)).split())
    if (app is None or not app.is_active or app.kind != "partner" or not scopes
            or not scopes <= set(grant.scopes) & set(installation.scopes) & set(client.allowed_scopes)
            or not scopes <= SCOPE_DESCRIPTIONS.keys()):
        raise denied
    ids = frozenset(db.scalars(select(PartnerInstallationLocation.location_id).where(
        PartnerInstallationLocation.installation_id == installation.id)).all())
    if ids:
        valid = set(db.scalars(select(ServiceLocation.id).where(
            ServiceLocation.id.in_(ids), ServiceLocation.company_id == company_app.company_id)).all())
        if valid != ids:
            raise denied
    location_ids = None if installation.all_locations else ids
    user = None
    own_org = None
    if grant.kind == "user":
        user = fresh(db, User, grant.user_id)
        if not active_user(user) or not scopes <= eligible_scopes(db, user, company_app.company_id):
            raise denied
        member = fresh(db, UserCompany, (user.id, company_app.company_id))
        own_org = member.own_organization_id
        if not user.is_superadmin and member.role != "admin" and member.object_scope:
            member_ids = frozenset(str(v) for v in member.object_scope)
            location_ids = member_ids if location_ids is None else location_ids & member_ids
        if family and (family.token_version != user.token_version or family.auth_time is None
                       or family.auth_time + MAX_SESSION_DAYS * 86400 <= time.time()):
            raise denied
    elif (grant.kind != "machine" or scopes & IDENTITY_SCOPES or client.auth_method != "client_secret_basic"
          or scopes & {"documents:read", "documents.files:download"}):
        raise denied
    if family:
        if family.revoked or family.expires_at <= now() or family.grant_id != grant.id:
            raise denied
        if client.auth_method != "none":
            credential = fresh(db, PartnerCredential, family.credential_id)
            if (credential is None or not credential.enabled or credential.client_id != client.id
                    or credential.expires_at <= now()):
                raise denied
    resources = resource_scopes(db, installation.id, company_app.company_id, location_ids)
    return LiveGrant(grant, client, installation, company_app, user, location_ids, own_org, resources)


def pairwise_subject(db: Session, user_id: uuid.UUID, client_id: str) -> str:
    # Stable per client, unrelated to email and unlinkable across applications.
    existing = db.get(PartnerSubject, (user_id, client_id))
    if existing:
        return existing.subject
    db.execute(insert(PartnerSubject).values(user_id=user_id, client_id=client_id,
        subject=secrets.token_urlsafe(32)).on_conflict_do_nothing(index_elements=["user_id", "client_id"]))
    return db.get(PartnerSubject, (user_id, client_id)).subject


class ClientAdapter:
    def __init__(self, model: PartnerClient, server: "PartnerAuthorizationServer"):
        self.model, self.server = model, server
        self.credential_id = None

    def get_client_id(self):
        return self.model.id

    def check_redirect_uri(self, uri):
        if uri not in self.model.redirect_uris:
            return False
        # Registration does not freeze development-only exceptions forever.
        # Reclassify the exact persisted target at every authorization sink.
        try:
            validate_redirect(uri)
        except HTTPException:
            return False
        return True

    def get_default_redirect_uri(self):
        # Explicit redirect required even for a single registered redirect.
        return None

    def check_client_secret(self, secret):
        credential = self.server.db.scalar(select(PartnerCredential).where(
            PartnerCredential.client_id == self.model.id,
            PartnerCredential.secret_hash == digest(secret), PartnerCredential.enabled.is_(True),
            PartnerCredential.expires_at > now()))
        if credential:
            self.credential_id = credential.id
        return credential is not None

    def check_endpoint_auth_method(self, method, endpoint):
        return method == self.model.auth_method

    def check_response_type(self, response_type):
        return response_type == "code"

    def check_grant_type(self, grant_type):
        return grant_type in {"authorization_code", "refresh_token"} or (
            grant_type == "client_credentials" and self.model.auth_method == "client_secret_basic")

    def get_allowed_scope(self, scope):
        values = validate_scopes((scope or "").split())
        if not values <= set(self.model.allowed_scopes):
            raise InvalidScopeError()
        return " ".join(sorted(values))


class ProtocolRequest(OAuth2Request):
    def __init__(self, method: str, parameters: dict, headers: dict | None = None):
        # Trusted configured canonical issuer, never Host/X-Forwarded-Proto.
        super().__init__(method, settings.partner_oauth_issuer + "/protocol", headers=headers)
        self.payload = BasicOAuth2Payload(parameters)

    @property
    def form(self):
        return self.payload.data if self.method == "POST" else {}

    @property
    def args(self):
        return self.payload.data if self.method == "GET" else {}


class S256Challenge(CodeChallenge):
    SUPPORTED_CODE_CHALLENGE_METHOD = ["S256"]

    def validate_code_challenge(self, grant, redirect_uri):
        if (not grant.request.payload.data.get("code_challenge")
                or grant.request.payload.data.get("code_challenge_method") != "S256"):
            raise InvalidRequestError("PKCE S256 is required")
        return super().validate_code_challenge(grant, redirect_uri)


class CodeGrant(AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_basic", "none"]

    def save_authorization_code(self, code, request):
        server = self.server
        claims = server.parent_claims
        parent_expiry = min(float(claims["exp"]), float(claims["at"]) + MAX_SESSION_DAYS * 86400)
        server.db.add(PartnerCode(code_hash=digest(code), grant_id=server.approved_grant.id,
            client_id=request.client.model.id, redirect_uri=request.payload.redirect_uri,
            scope=request.scope, code_challenge=request.payload.data["code_challenge"],
            code_challenge_method="S256", nonce=request.payload.data.get("nonce"),
            auth_time=int(claims["at"]), token_version=int(claims["tv"]),
            parent_expires_at=datetime.fromtimestamp(parent_expiry, timezone.utc),
            expires_at=min(now() + timedelta(seconds=120), datetime.fromtimestamp(parent_expiry, timezone.utc))))

    def query_authorization_code(self, code, client):
        row = self.server.db.scalar(select(PartnerCode).where(
            PartnerCode.code_hash == digest(code), PartnerCode.client_id == client.model.id
        ).with_for_update().execution_options(populate_existing=True))
        if row is None or row.consumed or row.expires_at <= now() or row.parent_expires_at <= now():
            return None
        if not client.check_redirect_uri(row.redirect_uri):
            return None
        self.server.code = row
        return row

    def delete_authorization_code(self, code):
        code.consumed = True
        self.server.db.flush()

    def authenticate_user(self, code):
        live = live_grant(self.server.db, code.grant_id, scope=code.scope)
        if live.user is None or code.token_version != live.user.token_version:
            raise InvalidGrantError()
        self.server.live = live
        return live.user


@dataclass
class RefreshHandle:
    row: PartnerToken
    client_id: str

    def check_client(self, client):
        return self.client_id == client.model.id

    def get_scope(self):
        return self.row.scope


class RotatingRefreshGrant(RefreshTokenGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_basic", "none"]
    INCLUDE_NEW_REFRESH_TOKEN = True

    def authenticate_refresh_token(self, value):
        db = self.server.db
        row = db.scalar(select(PartnerToken).where(PartnerToken.refresh_hash == digest(value)))
        if row is None:
            return None
        # Family first: all rotations/revocations serialize on the same row.
        family = db.scalar(select(PartnerTokenFamily).where(PartnerTokenFamily.id == row.family_id)
            .with_for_update().execution_options(populate_existing=True))
        if family is None:
            return None
        row = fresh(db, PartnerToken, row.id)
        grant = fresh(db, PartnerGrant, family.grant_id)
        if row is None or grant is None or grant.client_id != self.request.client.model.id:
            return None
        if row.refresh_used:
            family.revoked = True
            db.flush()  # OAuth error response commits the reuse revocation.
            return None
        if row.revoked:
            return None
        self.server.live = live_grant(db, grant.id, family=family, scope=row.scope)
        if "offline_access" not in row.scope.split() or self.server.live.user is None:
            return None
        self.server.family = family
        return RefreshHandle(row, grant.client_id)

    def authenticate_user(self, credential):
        return self.server.live.user

    def revoke_old_credential(self, credential):
        credential.row.refresh_used = True
        self.server.db.flush()


class MachineGrant(ClientCredentialsGrant):
    def validate_token_request(self):
        super().validate_token_request()
        try:
            grant_id = uuid.UUID(self.request.form.get("grant_id", ""))
        except ValueError:
            raise InvalidGrantError() from None
        live = live_grant(self.server.db, grant_id, scope=self.request.payload.scope)
        if (live.grant.kind != "machine" or live.client.id != self.request.client.model.id
                or not self.request.payload.scope):
            raise InvalidGrantError()
        self.server.live = live


class PartnerOpenIDCode(OpenIDCode):
    def __init__(self, server):
        super().__init__(require_nonce=True)
        self.server = server

    def exists_nonce(self, nonce, request):
        # Serialize approvals for a (client, nonce), then check the persisted
        # one-use code. An authorization-page GET creates no code reservation.
        lock_key = int(digest(request.payload.client_id + ":" + nonce)[:16], 16)
        if lock_key >= 2**63:
            lock_key -= 2**64
        self.server.db.execute(select(func.pg_advisory_xact_lock(lock_key)))
        return self.server.db.scalar(select(PartnerCode.code_hash).where(
            PartnerCode.client_id == request.payload.client_id, PartnerCode.nonce == nonce).limit(1)) is not None

    def resolve_client_private_key(self, client):
        from joserfc.jwk import RSAKey
        return RSAKey.import_key(signing_key())

    def get_client_algorithm(self, client):
        return "RS256"

    def get_encode_header(self, client):
        return {"alg": "RS256", "kid": settings.partner_oauth_kid, "typ": "JWT"}

    def get_client_claims(self, client):
        family = self.server.family
        return {"iss": settings.partner_oauth_issuer, "aud": client.model.id,
                "token_use": "partner_id", "exp": min(int(time.time()) + 300, int(family.expires_at.timestamp()))}

    def generate_user_info(self, user, scope):
        return UserInfo(**user_info(self.server.db, user, self.server.live.client.id, set(scope.split())))


class RevokeEndpoint(RevocationEndpoint):
    CLIENT_AUTH_METHODS = ["client_secret_basic", "none"]

    def query_token(self, token_string, token_type_hint):
        db = self.server.db
        h = digest(token_string)
        row = db.scalar(select(PartnerToken).where(
            (PartnerToken.access_hash == h) | (PartnerToken.refresh_hash == h)))
        if row is None:
            return None
        family = db.scalar(select(PartnerTokenFamily).where(PartnerTokenFamily.id == row.family_id)
            .with_for_update().execution_options(populate_existing=True))
        if family is None:
            return None
        self.server.family = family
        grant = fresh(db, PartnerGrant, family.grant_id)
        if grant is None:
            return None
        return RefreshHandle(row, grant.client_id)

    def revoke_token(self, token, request):
        self.server.family.revoked = True
        self.server.db.flush()


class PartnerAuthorizationServer(AuthorizationServer):
    def __init__(self, db: Session):
        super().__init__(list(SCOPE_DESCRIPTIONS))
        self.db = db
        self.code = self.family = self.live = self.approved_grant = None
        self.parent_claims = None
        self.register_grant(CodeGrant, [S256Challenge(), PartnerOpenIDCode(self)])
        self.register_grant(RotatingRefreshGrant)
        self.register_grant(MachineGrant)
        self.register_endpoint(RevokeEndpoint)
        self.register_token_generator("default", self.issue_token)

    def query_client(self, client_id):
        client = fresh(self.db, PartnerClient, client_id)
        if client is None or not client.enabled:
            return None
        app = fresh(self.db, App, client.app_id)
        if app is None or not app.is_active or app.kind != "partner":
            return None
        return ClientAdapter(client, self)

    def create_oauth2_request(self, request):
        return request

    def handle_response(self, status, body, headers):
        return status, body, headers

    def send_signal(self, name, *args, **kwargs):
        pass

    def issue_token(self, grant_type, client, user=None, scope=None, expires_in=None, include_refresh_token=True):
        scopes = validate_scopes((scope or "").split())
        live = self.live
        if not scopes <= set(live.grant.scopes):
            raise InvalidScopeError()
        if self.family is None:
            expiry = now() + timedelta(seconds=300)
            tv = auth_time = None
            if self.code:
                expiry = self.code.parent_expires_at
                tv, auth_time = self.code.token_version, self.code.auth_time
            self.family = PartnerTokenFamily(id=uuid.uuid4(), grant_id=live.grant.id,
                credential_id=client.credential_id, token_version=tv, auth_time=auth_time,
                expires_at=expiry, revoked=False)
            self.db.add(self.family)
            self.db.flush()
        expiry = min(now() + timedelta(seconds=300), self.family.expires_at)
        if expiry <= now():
            raise InvalidGrantError()
        token_id = uuid.uuid4()
        subject = pairwise_subject(self.db, user.id, client.model.id) if user else "client:" + client.model.id
        payload = {"iss": settings.partner_oauth_issuer, "aud": settings.partner_oauth_audience,
            "sub": subject, "client_id": client.model.id, "jti": str(token_id),
            "iat": int(time.time()), "exp": int(expiry.timestamp()), "token_use": "partner_access",
            "scope": " ".join(sorted(scopes))}
        access = jwt.encode(payload, signing_key(), algorithm="RS256",
            headers={"typ": "at+jwt", "kid": settings.partner_oauth_kid})
        refresh = secrets.token_urlsafe(48) if (include_refresh_token and user
            and "offline_access" in scopes and grant_type != "client_credentials") else None
        self.db.add(PartnerToken(id=token_id, family_id=self.family.id, access_hash=digest(access),
            refresh_hash=digest(refresh) if refresh else None, scope=payload["scope"], expires_at=expiry))
        self.db.flush()
        result = {"access_token": access, "token_type": "Bearer", "expires_in": max(0, int(expiry.timestamp()) - int(time.time())),
                  "scope": payload["scope"]}
        if refresh:
            result["refresh_token"] = refresh
        return result

    def save_token(self, token, request):
        # issue_token persists the token atomically with code/refresh consumption.
        self.db.flush()


def user_info(db: Session, user: User, client_id: str, scopes: set[str]) -> dict:
    info = {"sub": pairwise_subject(db, user.id, client_id)}
    if "profile" in scopes:
        info["name"] = user.name
    if "email" in scopes:
        info["email"] = user.email
        # Core has no verified email assertion; do not invent email_verified.
    return info


async def require_core_user(user: User = Depends(get_current_user)) -> User:
    require_enabled()
    claims = current_token_claims() or {}
    if (claims.get("scp") or claims.get("token_use") or not active_user(user)
            or any(k not in claims for k in ("at", "exp", "tv", "iat"))):
        raise HTTPException(403, "An ordinary Core session is required", headers=NO_STORE)
    return user


def verify_access(db: Session, token: str) -> VerifiedPartnerToken:
    require_enabled()
    denied = HTTPException(401, "Invalid partner access token", headers={**NO_STORE, "WWW-Authenticate": 'Bearer error="invalid_token"'})
    try:
        header = jwt.get_unverified_header(token)
        if header.get("typ") != "at+jwt" or header.get("kid") != settings.partner_oauth_kid or header.get("alg") != "RS256":
            raise ValueError()
        key = jwt.algorithms.RSAAlgorithm.from_jwk(public_jwks()["keys"][0])
        payload = jwt.decode(token, key, algorithms=["RS256"], issuer=settings.partner_oauth_issuer,
            audience=settings.partner_oauth_audience, options={"require": ["iss", "aud", "sub", "jti", "exp", "iat", "client_id", "token_use", "scope"], "strict_aud": True})
        if payload["token_use"] != "partner_access":
            raise ValueError()
        row = fresh(db, PartnerToken, uuid.UUID(payload["jti"]))
        if (row is None or row.revoked or row.expires_at <= now()
                or not secrets.compare_digest(row.access_hash, digest(token)) or row.scope != payload["scope"]):
            raise ValueError()
        family = fresh(db, PartnerTokenFamily, row.family_id)
        if family is None:
            raise ValueError()
        live = live_grant(db, family.grant_id, family=family, scope=row.scope)
        if payload["client_id"] != live.client.id:
            raise ValueError()
        if live.user:
            subject = fresh(db, PartnerSubject, (live.user.id, live.client.id))
            if subject is None:
                raise ValueError()
            expected_sub = subject.subject
        else:
            expected_sub = "client:" + live.client.id
        if payload["sub"] != expected_sub:
            raise ValueError()
        return VerifiedPartnerToken(client_id=live.client.id, app_id=live.client.app_id,
            installation_id=live.installation.id, company_id=live.company_app.company_id,
            grant_id=live.grant.id, user_id=live.user.id if live.user else None,
            scopes=frozenset(row.scope.split()), location_ids=live.location_ids, subject=expected_sub,
            token_id=row.id, expires_at=row.expires_at, is_machine=live.user is None,
            own_organization_id=live.own_organization_id, resource_scopes=live.resource_scopes)
    except (jwt.InvalidTokenError, ValueError, TypeError, InvalidGrantError, KeyError):
        raise denied from None


async def verify_partner_access_token(token: str, db: AsyncSession) -> VerifiedPartnerToken:
    if len(token) > 8192:
        raise HTTPException(401, "Invalid partner access token", headers=NO_STORE)
    return await db.run_sync(verify_access, token)


partner_bearer = HTTPBearer(auto_error=False)


async def get_verified_partner_token(credentials: HTTPAuthorizationCredentials | None = Depends(partner_bearer),
                                     db: AsyncSession = Depends(get_db)) -> VerifiedPartnerToken:
    if credentials is None:
        raise HTTPException(401, "Partner bearer required", headers={**NO_STORE, "WWW-Authenticate": "Bearer"})
    return await verify_partner_access_token(credentials.credentials, db)
