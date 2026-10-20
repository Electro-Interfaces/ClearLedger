"""Opt-in scoped вход окна Support; не обменивает grant на общую Core сессию."""
import json
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
import jwt
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.auth import KEY_SCOPES, get_current_user
from app.database import get_db
from app.models import App, CompanyApp, User
from app.routers.users_router import require_company_admin
from app.services import support_context as svc
from app.services.support_context_models import ContextGrant
from app.services.support_context_protocol import (
    Admit, Configure, Inspect, MAX_REQUEST, Postcall, Prepare, Renew, Revoke, ServiceTokenRequest,
    fail, proof, thumbprint, verify,
)

# Штатный экран именных ключей использует этот же каталог, не второй secret store.
KEY_SCOPES.update({
    "support-context.prepare": "Узел: подготовка контекста Поддержки без действий оператора",
    "support-context.introspect": "Поддержка: проверка текущих допусков контекста",
})


class ContextRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def guarded(request: Request):
            try:
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > MAX_REQUEST:
                        fail(413, "request_too_large")
                request._body = bytes(raw)
                if request.method in ("POST", "PUT"):
                    try:
                        data = json.loads(raw)
                    except ValueError:
                        fail(400, "invalid_json")
                    if not isinstance(data, dict):
                        fail(422, "invalid_request")
                    if "version" not in data or "schemaVersion" not in data:
                        fail(428, "version_required")
                    if (data["version"] != svc.VERSION or type(data["schemaVersion"]) is not int
                            or data["schemaVersion"] != 1):
                        fail(426, "version_unsupported")
                response = await handler(request)
            except HTTPException as e:
                error = e.detail if isinstance(e.detail, dict) and "code" in e.detail else {
                    "code": "access_denied" if e.status_code in (401, 403) else "invalid_request",
                    "retryable": e.status_code in (503, 504),
                }
                response = JSONResponse(svc.envelope(error=error, requestRef=uuid.uuid4().hex),
                                        status_code=e.status_code, headers=e.headers)
            except RequestValidationError:
                response = JSONResponse(svc.envelope(error={"code": "invalid_request", "retryable": False},
                                                     requestRef=uuid.uuid4().hex), status_code=422)
            response.headers["Cache-Control"] = "private, no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

        return guarded


router = APIRouter(prefix="/support-context/v1", route_class=ContextRoute,
                   tags=["Контекст Поддержки"])


@router.put("/config")
async def configure(company_id: str, body: Configure, db=Depends(get_db),
                    user: User = Depends(get_current_user)):
    cid = await require_company_admin(company_id, user, db)
    body = body.config
    # Нельзя сохранить ссылки на ключи другой компании или станции.
    from app.models import SpaceInboundKey
    for key_id, scope in [(body.introspectionKeyId, "support-context.introspect"),
                          *((n.prepareKeyId, "support-context.prepare") for n in body.nodes)]:
        key = await db.get(SpaceInboundKey, svc.uuid_or_fail(key_id))
        if (key is None or key.company_id != cid or key.revoked_at or key.station_id is not None
                or scope not in (key.scopes or [])):
            fail(403, "trust_key_invalid")
    row = await db.scalar(select(CompanyApp).join(App, App.id == CompanyApp.app_id).where(
        CompanyApp.company_id == cid, App.code == "voice"))
    if row is None:
        fail(403, "product_disabled")
    row.config = {**(row.config or {}), "supportContext": body.model_dump()}
    from app.audit import log_audit
    await log_audit(db, actor=user, company_id=cid, action="support_context.configure",
                    target="voice", details={"enabled": body.enabled})
    await db.commit()
    return svc.envelope(config=body.model_dump())


@router.get("/config")
async def get_config(company_id: str, db=Depends(get_db), user: User = Depends(get_current_user)):
    cid = await require_company_admin(company_id, user, db)
    row = await db.scalar(select(CompanyApp).join(App, App.id == CompanyApp.app_id).where(
        CompanyApp.company_id == cid, App.code == "voice"))
    return svc.envelope(config=(row.config or {}).get("supportContext") if row else None)


@router.post("/prepare", status_code=202)
async def prepare(body: Prepare, db=Depends(get_db),
                  api_key: str | None = Header(None, alias="X-Cloud-API-Key")):
    return await svc.prepare(db, api_key, body)


@router.post("/service-token")
async def service_token(body: ServiceTokenRequest, db=Depends(get_db),
                        api_key: str | None = Header(None, alias="X-Cloud-API-Key")):
    token = await svc.exchange(db, api_key)
    return svc.envelope(token=token, tokenType="Bearer", expiresIn=120)


@router.post("/admit")
async def admit(body: Admit, db=Depends(get_db), dpop: str | None = Header(None)):
    _core, trust, _cid, _base, _node = await svc.node_configuration(db, body.nodeId)
    if not dpop:
        fail(401, "dpop_required")
    try:
        jkt = thumbprint(jwt.get_unverified_header(dpop)["jwk"])
    except (jwt.PyJWTError, KeyError, TypeError):
        fail(401, "invalid_dpop")
    replay_key = proof(dpop, jkt=jkt,
                       htu=trust.publicOrigin + svc.PREFIX + "/admit", access_token=None)
    await svc.replay(db, replay_key)
    return await svc.admit(db, body, jkt)


def dpop_token(authorization):
    if not authorization or not authorization.startswith("DPoP "):
        fail(401, "dpop_required")
    return authorization[5:]


@router.post("/renew")
async def renew(body: Renew, db=Depends(get_db), authorization: str | None = Header(None),
                dpop: str | None = Header(None)):
    token = dpop_token(authorization)
    claims = verify(token, "support-context")
    if claims["grantId"] != body.grantId or claims["callRef"]["nodeId"] != body.nodeId:
        fail(403, "grant_mismatch")
    trust, _cid, _base = await svc.configuration(db, claims["coreCid"])
    if not dpop:
        fail(401, "dpop_required")
    replay_key = proof(dpop, jkt=claims["cnf"]["jkt"],
                       htu=trust.publicOrigin + svc.PREFIX + "/renew", access_token=token)
    await svc.replay(db, replay_key)
    if claims["scp"] != "support_context":
        fail(403, "live_grant_required")
    await svc.current(db, token, allow_phase_change=True)
    return await svc.admit(db, body, claims["cnf"]["jkt"], renew_claims=claims)


@router.post("/postcall")
async def postcall(body: Postcall, db=Depends(get_db), dpop: str | None = Header(None)):
    source = await db.get(ContextGrant, body.grantId)
    if source is None:
        fail(404, "grant_unavailable")
    trust, _cid, _base = await svc.configuration(db, source.claims["coreCid"])
    if not dpop:
        fail(401, "dpop_required")
    replay_key = proof(dpop, jkt=source.claims["cnf"]["jkt"],
                       htu=trust.publicOrigin + svc.PREFIX + "/postcall", access_token=None)
    await svc.replay(db, replay_key)
    return await svc.postcall(db, body.grantId, body.ticketRef)


@router.post("/introspect")
async def introspect(body: Inspect, db=Depends(get_db), authorization: str | None = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        fail(401, "service_required")
    return await svc.introspect(db, authorization[7:], body)


@router.post("/revoke")
async def revoke(body: Revoke, db=Depends(get_db), user: User = Depends(get_current_user)):
    row = await db.get(ContextGrant, body.grantId)
    if row is None:
        fail(404, "grant_unavailable")
    c = row.claims
    if str(user.id) != c["sub"]:
        await require_company_admin(c["coreCid"], user, db)
    row.revoked_at = datetime.now(timezone.utc)
    if row.authority.get("sourceGrantId"):
        root = await db.get(ContextGrant, row.authority["sourceGrantId"])
        if root is not None:
            root.revoked_at = row.revoked_at
    from app.audit import log_audit
    await log_audit(db, actor=user, company_id=uuid.UUID(c["coreCid"]),
                    action="support_context.revoke", target=body.grantId)
    await db.commit()
    return svc.envelope(revoked=True)
