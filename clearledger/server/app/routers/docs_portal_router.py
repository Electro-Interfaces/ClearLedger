"""All documentation bytes have their own gate, separate from product scopes."""
import json
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.routing import APIRoute
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.database import get_db
from app.services import docs_portal as portal
from app.services import partner_identity as identity


class DocsRoute(APIRoute):
    async def handle(self, scope, receive, send):
        async def private_send(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.update(portal.HEADERS)
            await send(message)
        try:
            await super().handle(scope, receive, private_send)
        except StarletteHTTPException as error:
            response = JSONResponse({"detail": error.detail}, status_code=error.status_code,
                headers={**(error.headers or {}), **portal.HEADERS})
            await response(scope, receive, send)

    def get_route_handler(self):
        original = super().get_route_handler()

        async def guarded(request):
            try:
                response = await original(request)
            except identity.PartnerProblem as error:
                response = await identity.problem_handler(request, error)
            except HTTPException as error:
                response = JSONResponse({"detail": error.detail}, status_code=error.status_code, headers=error.headers)
            except RequestValidationError:
                response = JSONResponse({"detail": "Invalid docs request"}, status_code=422)
            response.headers.update(portal.HEADERS)
            return response
        return guarded


router = APIRouter(prefix="/developer/docs", tags=["Private developer docs"], route_class=DocsRoute, include_in_schema=False)


async def docs_session(request: Request, db: AsyncSession = Depends(get_db)):
    await db.run_sync(lambda sync: portal.live_session(sync, request.cookies.get(portal.COOKIE)))
    return db


def no_overrides(request):
    if request.query_params:
        raise HTTPException(400, "Documentation configuration overrides are forbidden")


@router.get("/metadata")
async def metadata(request: Request, user=Depends(identity.require_core_user), db: AsyncSession = Depends(get_db)):
    no_overrides(request)
    data = await db.run_sync(portal.metadata)
    data["coreUserId"] = str(user.id)
    try:
        portal.product_schema(request.app)
    except HTTPException:
        data["ready"] = False
        data["setupRequired"].append("product-api")
    return data


@router.post("/session")
async def create_session(request: Request, verified=Depends(identity.get_verified_partner_token), db: AsyncSession = Depends(get_db)):
    no_overrides(request)
    portal.mutation_origin(request)
    if request.headers.get("x-docs-csrf") != "bootstrap":
        raise HTTPException(403, "Explicit docs bootstrap header required")
    raw, expires = await db.run_sync(lambda sync: portal.create_session(sync, verified))
    await db.commit()
    response = JSONResponse({"expiresAt": expires.isoformat(), "csrfToken": portal.csrf(raw)})
    response.set_cookie(portal.COOKIE, raw, secure=True, httponly=True, samesite="strict", path=portal.PREFIX,
        max_age=max(0, int((expires - identity.now()).total_seconds())))
    return response


@router.get("/session")
async def current_session(request: Request, db=Depends(docs_session)):
    no_overrides(request)
    return await db.run_sync(lambda sync: portal.session_info(sync, request.cookies.get(portal.COOKIE)))


@router.delete("/session")
async def close_session(request: Request, db: AsyncSession = Depends(get_db)):
    no_overrides(request)
    raw = request.cookies.get(portal.COOKIE)
    portal.check_csrf(request, raw)
    await db.run_sync(lambda sync: portal.close_session(sync, raw))
    await db.commit()
    response = Response(status_code=204)
    response.delete_cookie(portal.COOKIE, secure=True, httponly=True, samesite="strict", path=portal.PREFIX)
    return response


@router.get("/openapi.json")
async def spec(request: Request, db=Depends(docs_session)):
    no_overrides(request)
    return portal.product_schema(request.app)


@router.get("/openapi.server.json")
async def server_spec(request: Request, db=Depends(docs_session)):
    no_overrides(request)
    return portal.product_schema(request.app, browser=False)


@router.get("/assets/{name}")
async def asset(name: str, request: Request, db=Depends(docs_session)):
    no_overrides(request)
    content = portal.asset(name)
    return Response(content, media_type="text/css" if name.endswith(".css") else "text/javascript", headers=portal.HEADERS)


@router.get("/ui", response_class=HTMLResponse)
async def ui(request: Request, db=Depends(docs_session)):
    no_overrides(request)
    schema = portal.product_schema(request.app)
    config = await db.run_sync(portal.metadata)
    scopes = schema["components"]["securitySchemes"]["ProductOAuth"]["flows"]["authorizationCode"]["scopes"]
    config.update({"businessScopes": list(scopes), "apiUrl": portal.issuer() + "/api/v1",
        "swaggerRedirectUri": portal.issuer() + portal.PREFIX + "/oauth2-redirect"})
    safe = json.dumps(config).replace("<", "\\u003c")
    html = f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Документация API</title><link rel="stylesheet" href="{portal.PREFIX}/assets/swagger-ui.css">
<style>body{{font:14px system-ui,sans-serif;margin:16px}} input[data-name="clientSecret"],label[for^="client_secret_"]{{display:none!important}} #docs-auth-logout{{min-height:36px;padding:0 12px;border:1px solid #cbd5e1;border-radius:8px;background:white;color:#172033}}</style></head>
<body><p id="docs-mode"></p><button id="docs-auth-logout" type="button">Завершить доступ к API</button><div id="swagger-ui"></div>
<script id="docs-config" type="application/json">{safe}</script>
<script src="{portal.PREFIX}/assets/swagger-ui-bundle.js"></script><script src="{portal.PREFIX}/assets/portal-init.js"></script></body></html>'''
    response = HTMLResponse(html)
    response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
    return response


@router.get("/oauth2-redirect", response_class=HTMLResponse)
async def oauth_redirect(request: Request, db=Depends(docs_session)):
    # OAuth code/state are parsed only in the callback script, never reflected into HTML.
    response = HTMLResponse(f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><title>Возврат в документацию</title></head>
<body><p id="oauth-result">Проверяем ответ авторизации…</p><script src="{portal.PREFIX}/assets/oauth-callback.js"></script></body></html>''')
    response.headers["Content-Security-Policy"] = "default-src 'none'; script-src 'self'; base-uri 'none'; frame-ancestors 'none'"
    return response
