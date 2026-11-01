"""Docs-only cookie delegates live policy to M10; no JWT or business ACL copy."""
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import secrets

from authlib.oauth2.rfc6749 import InvalidClientError, InvalidGrantError
from fastapi import HTTPException, Request
from sqlalchemy import delete, select

from app.config import get_settings
from app.models_docs_portal import DocsPortalSession
from app.models_partner import PartnerClient, PartnerToken, PartnerTokenFamily
from app.services import partner_identity as identity
from app.services.contract_write_locks import ScopedLockError

settings = get_settings()
PREFIX = "/api/developer/docs"
COOKIE = "__Secure-elsy_docs"
ASSETS = Path(__file__).parent.parent / "docs_portal_assets"
HEADERS = {**identity.NO_STORE, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


def enabled():
    if not getattr(settings, "partner_docs_enabled", False):
        raise identity.PartnerProblem(503, "DOCS_DISABLED", "Документация API выключена")
    identity.require_enabled()


def issuer():
    enabled()
    return identity.settings.partner_oauth_issuer.rstrip("/")


def client_config(db):
    client_id = getattr(settings, "partner_docs_client_id", "")
    client = identity.fresh(db, PartnerClient, client_id) if client_id else None
    origin = issuer()
    callbacks = {origin + "/developer/api/callback", origin + PREFIX + "/oauth2-redirect"}
    if (not client or not client.enabled or client.auth_method != "none"
            or not {"openid", "docs:read"} <= set(client.allowed_scopes)
            or set(client.redirect_uris) != callbacks):
        return None
    return client


def metadata(db):
    client = client_config(db)
    origin = issuer()
    environment = getattr(settings, "partner_docs_environment", "unconfigured")
    if environment not in {"sandbox", "production", "unconfigured"}:
        environment = "unconfigured"
    sandbox = (environment == "sandbox" and getattr(settings, "partner_docs_sandbox_api_url", "") == origin + "/api/v1"
        and getattr(identity.settings, "partner_api_enabled", False))
    missing = ([] if client else ["docs-client"]) + ([] if sandbox else ["sandbox-api"])
    return {"ready": client is not None, "environment": environment, "sandboxReady": sandbox,
        "setupRequired": missing, "clientId": client.id if client else None,
        "authorizationUrl": origin + "/api/oauth2/authorize", "tokenUrl": origin + "/api/oauth2/token",
        "revokeUrl": origin + "/api/oauth2/revoke", "redirectUri": origin + "/developer/api/callback",
        "docsScopes": ["openid", "docs:read"], "browserOAuthProfile": "authorization_code_pkce",
        "serverContractUrl": PREFIX + "/openapi.server.json"}


def mutation_origin(request: Request):
    # Host/X-Forwarded-Host and caller query never define trusted Origin.
    if request.headers.get("origin") != issuer():
        raise HTTPException(403, "Same-space Origin required", headers=HEADERS)


def csrf(raw_cookie):
    return identity.digest("docs-csrf:" + raw_cookie)


def verification_profile():
    # The raw JWT is never persisted. A cookie cannot outlive a verification-key/
    # issuer/audience rotation which would invalidate that originally checked JWT.
    return identity.digest(json.dumps({"issuer": identity.settings.partner_oauth_issuer,
        "audience": identity.settings.partner_oauth_audience, "kid": identity.settings.partner_oauth_kid,
        "jwks": identity.public_jwks()}, sort_keys=True))


def check_csrf(request, raw_cookie):
    mutation_origin(request)
    supplied = request.headers.get("x-docs-csrf", "")
    if not raw_cookie or not secrets.compare_digest(supplied, csrf(raw_cookie)):
        raise HTTPException(403, "Docs CSRF proof required", headers=HEADERS)


def live_session(db, raw_cookie):
    enabled()
    denied = HTTPException(401, "Valid docs session required", headers=HEADERS)
    if not raw_cookie or len(raw_cookie) > 256:
        raise denied
    row = identity.fresh(db, DocsPortalSession, identity.digest(raw_cookie))
    if row is None or row.revoked or row.expires_at <= identity.now() or row.verification_profile != verification_profile():
        raise denied
    token = identity.fresh(db, PartnerToken, row.token_id)
    if token is None or token.revoked or token.expires_at.replace(microsecond=0) <= identity.now():
        raise denied
    family = identity.fresh(db, PartnerTokenFamily, token.family_id)
    if family is None:
        raise denied
    try:
        live = identity.live_grant(db, family.grant_id, family=family, scope=token.scope)
    except InvalidGrantError:
        raise denied from None
    client = client_config(db)
    if (client is None or live.client.id != client.id or live.user is None
            or "docs:read" not in token.scope.split()):
        raise denied
    return row, token, family, live


def create_session(db, verified):
    enabled()
    client = client_config(db)
    if client is None:
        raise HTTPException(503, "Docs client setup required", headers=HEADERS)
    if verified.client_id != client.id or verified.is_machine or "docs:read" not in verified.scopes:
        raise HTTPException(403, "Configured public docs grant required", headers=HEADERS)
    token = db.scalar(select(PartnerToken).where(PartnerToken.id == verified.token_id)
        .with_for_update().execution_options(populate_existing=True))
    if token is None or token.revoked or token.expires_at <= identity.now():
        raise HTTPException(401, "Invalid docs token", headers=HEADERS)
    raw = secrets.token_urlsafe(48)
    expires = min(token.expires_at.replace(microsecond=0), identity.now() + timedelta(seconds=180))
    db.execute(delete(DocsPortalSession).where(DocsPortalSession.token_id == token.id))
    db.add(DocsPortalSession(cookie_hash=identity.digest(raw), token_id=token.id, verification_profile=verification_profile(), expires_at=expires, revoked=False))
    db.flush()
    live_session(db, raw)  # Re-read canonical grant before issuing the capability.
    return raw, expires


def session_info(db, raw):
    row, token, family, live = live_session(db, raw)
    config = metadata(db)
    return {"expiresAt": row.expires_at.isoformat(), "csrfToken": csrf(raw), "userId": str(live.user.id),
        "clientId": live.client.id, "companyId": str(live.company_app.company_id),
        "environment": config["environment"], "sandboxReady": config["sandboxReady"]}


def close_session(db, raw):
    # Reject before even an expired ORM attribute or a raw-cookie shortcut.
    if db.new or db.dirty or db.deleted:
        raise ScopedLockError("Docs logout requires clean discovery; roll back the entire root")
    if not raw:
        return
    with db.no_autoflush:
        cookie_hash = identity.digest(raw)
        candidate = identity.fresh(db, DocsPortalSession, cookie_hash)
        if candidate is None:
            return
        token_id = candidate.token_id
        try:
            writer = identity._prepare_partner_write(db, token_id=token_id, mutation="revoke")
        except InvalidClientError:
            # This protocol/native-free composer call has exactly one such
            # source path: no original graph yielded any typed requests.
            # A surviving orphan is not a no-plan mutation fallback.
            if db.scalar(select(DocsPortalSession.token_id).where(
                    DocsPortalSession.cookie_hash == cookie_hash)) is None:
                return  # Parent CASCADE may already have removed the cookie.
            identity._writer_drift(db)

        # All original parent rows, including Family UPDATE then Token SHARE,
        # are held before this last lock. Never follow a replacement token.
        row = db.scalar(select(DocsPortalSession).where(
            DocsPortalSession.cookie_hash == cookie_hash,
            DocsPortalSession.token_id == token_id)
            .with_for_update().execution_options(populate_existing=True))
        writer.checkpoint()
        if row is None:
            surviving = db.scalar(select(DocsPortalSession.token_id).where(
                DocsPortalSession.cookie_hash == cookie_hash))
            if surviving is not None:
                identity._writer_drift(db)
            return  # Actually absent: no family callback or pending write.

        original_token = next((spec for spec in writer.rows
            if spec.model is PartnerToken and spec.identity == (token_id,) and not spec.missing), None)
        if original_token is None:
            identity._writer_drift(db)
        family_id, = original_token.pointers
        original_family = next((spec for spec in writer.rows
            if spec.model is PartnerTokenFamily and spec.identity == (family_id,) and not spec.missing), None)
        token = identity.fresh(db, PartnerToken, token_id)
        family = identity.fresh(db, PartnerTokenFamily, family_id)
        if (original_family is None or token is None or token.family_id != family_id or family is None
                or (family.grant_id, family.credential_id) != original_family.pointers):
            identity._writer_drift(db)

        # Cookie + Origin/CSRF authorize cleanup even after live access expires
        # or is revoked. Do not turn current access eligibility into a gate.
        server = identity.PartnerAuthorizationServer(db, writer)
        server.family = family
        identity.RevokeEndpoint(server).revoke_token(identity.RefreshHandle(token, ""), None)
        # The callback flushes Family first; Docs never becomes dirty earlier.
        row.revoked = True
        db.flush()
        writer.checkpoint()


def product_schema(app, *, browser=True):
    # Deferred import: never publish generic main.openapi or a made-up schema.
    try:
        from app.product_api import curated_openapi
        from app.product_api.app import public_client_openapi
    except ImportError:
        raise HTTPException(503, "Product API setup required", headers=HEADERS) from None
    child = getattr(app.state, "product_api", None)
    if child is None:
        raise HTTPException(503, "Product API setup required", headers=HEADERS)
    try:
        schema = curated_openapi(child)
    except (ValueError, RuntimeError):
        raise HTTPException(503, "Product API setup required", headers=HEADERS) from None
    origin = issuer()
    if schema.get("servers") != [{"url": origin + "/api/v1"}]:
        raise HTTPException(503, "Same-space product issuer required", headers=HEADERS)
    try:
        return public_client_openapi(schema) if browser else schema
    except (KeyError, ValueError, TypeError):
        raise HTTPException(503, "Public documentation profile unavailable", headers=HEADERS) from None


def asset(name):
    allowed = {"swagger-ui-bundle.js", "swagger-ui.css", "portal-init.js", "oauth-callback.js"}
    if name not in allowed:
        raise HTTPException(404, "Asset not found", headers=HEADERS)
    file = ASSETS / name
    if not file.is_file():
        raise HTTPException(503, "Local docs assets unavailable", headers=HEADERS)
    try:
        content = file.read_bytes()
        if name in {"swagger-ui-bundle.js", "swagger-ui.css"}:
            manifest = json.loads((ASSETS / "manifest.json").read_text())
            if hashlib.sha256(content).hexdigest() != manifest["sha256"][name]:
                raise HTTPException(503, "Pinned docs assets mismatch", headers=HEADERS)
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Pinned docs assets unavailable", headers=HEADERS) from None
    return content
