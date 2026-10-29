"""Opt-in versioned read API. Never mounts itself onto the legacy application."""
from dataclasses import dataclass
from copy import deepcopy
from http import HTTPStatus
import os
from pathlib import Path
import secrets
from typing import Annotated
from urllib.parse import urlsplit
import uuid

from fastapi import Depends, FastAPI, Query as QueryParams, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.openapi.utils import get_openapi
from sqlalchemy import select
from starlette.exceptions import HTTPException

from app.api_contracts import (AccessContext, PolicyRouter, PrincipalKind, RoutePolicy,
                               create_policy_app, get_access_context, policy_registry)
from . import access, budget, dto, files, monitoring
from .queries import Query


RESOURCE_TAGS = {"objects": "Объекты ЭЗС", "equipment": "Оборудование",
                 "counterparties": "Контрагенты", "contracts": "Договоры", "documents": "Документы"}
MONITORING_TAG = "Мониторинг"
OPENAPI_TAGS = [
    {"name": RESOURCE_TAGS["objects"], "description": "Точки обслуживания ЭЗС в пределах выданных разрешений."},
    {"name": RESOURCE_TAGS["equipment"], "description": "Станционное оборудование и разрешённые связи с объектами."},
    {"name": MONITORING_TAG, "description": "Состояние объекта и зарядные агрегаты за выбранный период. Без финансовых данных."},
    {"name": RESOURCE_TAGS["counterparties"], "description": "Карточки контрагентов доступной компании."},
    {"name": RESOURCE_TAGS["contracts"], "description": "Карточки договоров и разрешённые связи с контрагентами и объектами."},
    {"name": RESOURCE_TAGS["documents"], "description": "Карточки документов и разрешённые версии файлов. Требуется пользовательское согласие."},
]


@dataclass(frozen=True)
class Settings:
    sessions: object
    verifier: object
    enabled: object
    upload_dir: Path
    cursor_key: bytes
    issuer: str | None
    source_revision: str
    budget_policy: object


def _problem(request, status, error_headers=None, *, budget_exceeded=False):
    codes = {400: "invalid_cursor", 401: "invalid_credentials", 403: "access_denied",
             404: "not_found", 405: "method_not_allowed", 422: "invalid_request", 503: "api_unavailable"}
    safe = {400: "Cursor is invalid or belongs to another query", 401: "Valid partner Bearer credentials are required",
            403: "Access is denied", 404: "Resource was not found", 422: "Request parameters are invalid",
            503: "Partner API is unavailable"}
    value = dto.Problem(title=HTTPStatus(status).phrase, status=status,
        code="rate_limited" if budget_exceeded else codes.get(status, "internal_error"),
        request_id=getattr(request.state, "request_id", str(uuid.uuid4())),
        detail="Product request budget is exhausted" if budget_exceeded else safe.get(status, "Request could not be completed"))
    # Preserve protocol metadata, not arbitrary exception headers or debug data.
    allowed = {401: {"www-authenticate"}, 403: {"www-authenticate"}, 405: {"allow"},
               429: {"retry-after"}, 503: {"retry-after"}}.get(status, set())
    headers = {name.lower(): content for name, content in (error_headers or {}).items() if name.lower() in allowed}
    if status in (401, 403) and (not headers.get("www-authenticate")
            or headers["www-authenticate"].strip().lower() == "bearer"):
        # RFC6750 challenge parameters; never infer invalid_token/insufficient_scope
        # from a generic denial. Preserve a canonical verifier's precise challenge.
        headers["www-authenticate"] = 'Bearer realm="product-api"'
    # ServerErrorMiddleware invokes the 500 handler outside user middleware.
    headers.update({"Cache-Control": "no-store", "X-Request-Id": value.request_id})
    return JSONResponse(value.model_dump(by_alias=True), status_code=status,
                        media_type="application/problem+json", headers=headers)


async def query_dependency(request: Request, context: AccessContext = Depends(get_access_context)):
    settings = request.app.state.product_settings
    async with settings.sessions() as db:
        yield Query(db, request.state.product_facts, context, settings.cursor_key)


def _policy(resource, action="read", extra_scopes=()):
    scopes = {access.READ_SCOPES[resource], *extra_scopes}
    if action == "download":
        scopes.add(access.DOWNLOAD_SCOPE)
    return RoutePolicy(owner=resource, accepted_kinds=({PrincipalKind.PARTNER} if resource == "documents"
        else {PrincipalKind.PARTNER, PrincipalKind.SERVICE}), resource_type=resource, action=action,
        required_scopes=scopes, policy_version=access.POLICY_VERSION, tenant_required=True,
        security_scheme="ProductOAuth")


def create_product_api(*, session_factory=None, verifier=None, enabled=None, upload_dir=None,
                       cursor_key=None, issuer=None, source_revision="unverified", budget_policy=None) -> FastAPI:
    key = secrets.token_bytes(32) if cursor_key is None else cursor_key
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("Cursor signing key must contain at least 32 bytes")
    app = create_policy_app(context_resolver=access.resolve, title="ElsyPlus Product Read API", version="1.0.0")
    app.state.product_settings = Settings(
        session_factory or access.configured_sessions, verifier or access.configured_verifier,
        access.configured_enabled if enabled is None else (enabled if callable(enabled) else lambda: enabled is True),
        Path(upload_dir or os.environ.get("UPLOAD_DIR", "/app/uploads")), key, issuer, source_revision,
        budget.configured_policy if budget_policy is None else (
            budget_policy if callable(budget_policy) else lambda: budget_policy))

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_problem(request, error):
        return _problem(request, error.status_code, error.headers, budget_exceeded=isinstance(error, budget.BudgetExceeded))

    @app.exception_handler(RequestValidationError)
    async def validation_problem(request, error):
        return _problem(request, 422)

    @app.exception_handler(Exception)
    async def internal_problem(request, error):
        return _problem(request, 500)

    router = PolicyRouter(context_resolver=access.resolve)
    problems = {status: {"model": dto.Problem, "content": {"application/problem+json": {}}}
                for status in (400, 401, 403, 404, 422, 429, 503)}

    def operation(path, resource, operation_id, response_model=None, action="read", extra_scopes=(), **kwargs):
        return router.operation(path, policy=_policy(resource, action, extra_scopes), methods=["GET"],
            tags=kwargs.pop("tags", [RESOURCE_TAGS[resource]]),
            operation_id=operation_id, response_model=response_model, responses={**problems, **kwargs.pop("responses", {})},
            openapi_extra={"x-elsy-owner": resource, "x-elsy-access-class": "partner",
                "x-elsy-resource-policy": f"{resource}:{action}", "x-elsy-readiness": "candidate"}, **kwargs)

    @operation("/objects", "objects", "listObjects", dto.Page[dto.Object])
    async def objects(params: Annotated[dto.ListQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return await query.listing("objects", params)

    @operation("/objects/{objectId}", "objects", "getObject", dto.Object)
    async def object_detail(objectId: dto.ObjectId, params: Annotated[dto.EmptyQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return (await query.project("objects", [await query.detail("objects", objectId)]))[0]

    @operation("/objects/{objectId}/monitoring", "objects", "getObjectMonitoring", dto.Monitoring,
               extra_scopes={monitoring.SCOPE}, tags=[MONITORING_TAG], summary="Read object charging status",
               description="Energy profile only. Current catalog status; object-scoped observed data boundary. "
                   "Inclusive MSK interval [asOf - days, asOf], days 1..366. asOf date caps the endpoint at "
                   "23:59:59.999999 MSK, or earlier observed data. Successful visit: any attempt energy > 0. "
                   "No financial, ticket, customer or raw session data.")
    async def object_monitoring(objectId: dto.ObjectId, params: Annotated[dto.MonitoringQuery, QueryParams()],
                                query: Query = Depends(query_dependency)):
        return await monitoring.detail(query, objectId, params)

    @operation("/equipment", "equipment", "listEquipment", dto.Page[dto.Equipment])
    async def equipment(params: Annotated[dto.ListQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return await query.listing("equipment", params)

    @operation("/equipment/{equipmentId}", "equipment", "getEquipment", dto.Equipment)
    async def equipment_detail(equipmentId: dto.Id, params: Annotated[dto.EmptyQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return (await query.project("equipment", [await query.detail("equipment", equipmentId)]))[0]

    @operation("/counterparties", "counterparties", "listCounterparties", dto.Page[dto.Counterparty])
    async def counterparties(params: Annotated[dto.ListQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return await query.listing("counterparties", params)

    @operation("/counterparties/{counterpartyId}", "counterparties", "getCounterparty", dto.Counterparty)
    async def counterparty_detail(counterpartyId: dto.Id, params: Annotated[dto.EmptyQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return (await query.project("counterparties", [await query.detail("counterparties", counterpartyId)]))[0]

    @operation("/contracts", "contracts", "listContracts", dto.Page[dto.Contract])
    async def contracts(params: Annotated[dto.ListQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return await query.listing("contracts", params)

    @operation("/contracts/{contractId}", "contracts", "getContract", dto.Contract)
    async def contract_detail(contractId: dto.Id, params: Annotated[dto.EmptyQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return (await query.project("contracts", [await query.detail("contracts", contractId)]))[0]

    @operation("/documents", "documents", "listDocuments", dto.Page[dto.Document])
    async def documents(params: Annotated[dto.ListQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return await query.listing("documents", params)

    @operation("/documents/{docId}", "documents", "getDocument", dto.DocumentDetail)
    async def document_detail(docId: dto.Id, params: Annotated[dto.EmptyQuery, QueryParams()], query: Query = Depends(query_dependency)):
        from app.models import DocVersion
        row = await query.detail("documents", docId)
        item = (await query.project("documents", [row]))[0]
        versions = list((await query.db.scalars(select(DocVersion).where(
            DocVersion.company_id == query.facts.company_id, DocVersion.doc_id == row.id,
            DocVersion.is_current.is_(True), DocVersion.tombstoned_at.is_(None),
            DocVersion.archive_purged_at.is_(None)).order_by(DocVersion.revision, DocVersion.id).limit(201))).all())
        return dto.DocumentDetail(**item.model_dump(), versions=[dto.Version(
            id=str(v.id), revision=v.revision, role=v.role, file_name=v.file_name, mime_type=v.mime,
            size_bytes=v.size_bytes) for v in versions[:200]], versions_truncated=len(versions) > 200)

    @operation("/documents/{docId}/versions/{versionId}/content", "documents", "downloadDocumentVersion", action="download",
               responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
    async def document_content(docId: dto.Id, versionId: dto.Id, params: Annotated[dto.EmptyQuery, QueryParams()],
                               request: Request, query: Query = Depends(query_dependency)):
        return await files.content(query, docId, versionId, request.app.state.product_settings.upload_dir)

    app.include_router(router)
    return app


def export_runtime_registry(app, *, prefix=""):
    entries = policy_registry(app)
    return {"kind": "policy-runtime-registry", "sourceRevision": app.state.product_settings.source_revision, "mountPath": "/api/v1",
            "operations": [{"method": method, "path": prefix + entry["path"], "operationId": entry["operationId"],
                "owner": entry["owner"], "accessClass": "partner"} for entry in entries for method in entry["methods"]]}


def _describe_http_responses(schema):
    """Curated application metadata only; does not install handlers or edge policy."""
    components = schema.setdefault("components", {})
    headers = {
        "ProductCacheControl": {"description": "Application response caching policy.", "required": True,
            "schema": {"type": "string", "const": "no-store"}, "example": "no-store"},
        "ProductRequestId": {"description": "Server-generated request ID; equals requestId in Problem bodies.",
            "required": True, "schema": {"type": "string", "format": "uuid"},
            "example": "00000000-0000-4000-8000-000000000001"},
        "ProductBearerChallenge": {"description": "Bearer challenge with parameters (RFC 6750 section 3). "
            "Generic denials use realm only; precise trusted verifier parameters are preserved, never inferred.",
            "required": True, "schema": {"type": "string", "pattern": "^Bearer .+$"},
            "examples": {"generic": {"value": 'Bearer realm="product-api"'},
                         "trustedVerifier": {"value": 'Bearer error="invalid_token"'}}},
        "ProductRetryAfter": {"description": "Optional upstream application retry delay or HTTP-date; "
            "the enabled product quota always supplies integer delay-seconds >=1 on exhaustion. "
            "Generic injected HTTP429/503 only carry this header when supplied by a trusted HTTPException.",
            "required": False, "schema": {"type": "string", "minLength": 1}, "example": "17"},
        "ProductAllow": {"description": "Methods permitted on a matched application path (RFC 9110 section 15.5.6).",
            "required": True, "schema": {"type": "string", "const": "GET"}, "example": "GET"},
        "ProductContentDisposition": {"description": "Attachment basename encoded as UTF-8 filename* (RFC 6266).",
            "required": True, "schema": {"type": "string", "pattern": "^attachment; filename\\*=UTF-8''"},
            "example": "attachment; filename*=UTF-8''%D0%A1%D0%BA%D0%B0%D0%BD%201.pdf"},
        "ProductNoSniff": {"description": "Application binary content must not be MIME-sniffed.", "required": True,
            "schema": {"type": "string", "const": "nosniff"}, "example": "nosniff"},
    }
    components.setdefault("headers", {}).update(headers)

    def header(name):
        return {"$ref": "#/components/headers/" + name}

    common = {"Cache-Control": header("ProductCacheControl"), "X-Request-Id": header("ProductRequestId")}
    examples = {
        400: ("invalid_cursor", "Cursor is invalid or belongs to another query"),
        401: ("invalid_credentials", "Valid partner Bearer credentials are required"),
        403: ("access_denied", "Access is denied"), 404: ("not_found", "Resource was not found"),
        405: ("method_not_allowed", "Request could not be completed"),
        422: ("invalid_request", "Request parameters are invalid"),
        429: ("internal_error", "Request could not be completed"),
        500: ("internal_error", "Request could not be completed"),
        503: ("api_unavailable", "Partner API is unavailable"),
    }

    def problem_content(status):
        code, detail = examples[status]
        return {"application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"},
            "example": {"type": "about:blank", "title": HTTPStatus(status).phrase, "status": status,
                "code": code, "requestId": headers["ProductRequestId"]["example"], "detail": detail}}}

    def budget_content():
        content = problem_content(429)
        media = content["application/problem+json"]
        generic = media.pop("example")
        media["examples"] = {
            "quotaExhausted": {"summary": "Enabled shared product quota exhausted", "value": {
                **generic, "code": "rate_limited", "detail": "Product request budget is exhausted"}},
            "injectedHTTP429": {"summary": "Generic application HTTPException(429)", "value": generic},
        }
        return content

    for path in schema["paths"].values():
        for operation in path.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            responses = operation["responses"]
            responses["500"] = {"description": "Internal application error before response streaming starts."}
            for status, response in responses.items():
                response.setdefault("headers", {}).update(common)
                if status in {"400", "401", "403", "404", "422", "500", "503"}:
                    response["content"] = problem_content(int(status))
                if status == "429":
                    response["description"] = "Enabled shared PostgreSQL product quota exhausted (rate_limited), " \
                        "or generic injected application HTTP429 (internal_error). Quota is disabled by default."
                    response["content"] = budget_content()
                    response["headers"]["Retry-After"] = header("ProductRetryAfter")
                if status in {"401", "403"}:
                    response["headers"]["WWW-Authenticate"] = header("ProductBearerChallenge")
                if status == "503":
                    response["headers"]["Retry-After"] = header("ProductRetryAfter")
                if status == "200" and operation["operationId"] == "downloadDocumentVersion":
                    response["headers"].update({"Content-Disposition": header("ProductContentDisposition"),
                                               "X-Content-Type-Options": header("ProductNoSniff")})

    components.setdefault("responses", {}).update({
        "ProductMethodNotAllowed": {"description": "Unsupported method on a known application path; "
            "this is not a registered write operation.",
            "headers": {**common, "Allow": header("ProductAllow")}, "content": problem_content(405)},
        "ProductInjectedRateLimit": {"description": "Only an explicitly raised application HTTPException(429). "
            "The generic code is internal_error; the opt-in product quota instead returns rate_limited. "
            "Proxy-generated 429 responses are outside this contract.",
            "headers": {**common, "Retry-After": header("ProductRetryAfter")}, "content": problem_content(429)},
    })
    schema["x-elsy-http-profile"] = {
        "scope": "product-child-application",
        "knownPaths": {"methods": ["GET"], "unsupportedMethodResponse": {"$ref": "#/components/responses/ProductMethodNotAllowed"}},
        "injectedApplicationRateLimit": {"response": {"$ref": "#/components/responses/ProductInjectedRateLimit"},
                                        "builtInLimiter": False},
        "productRequestBudget": {"defaultEnabled": False, "store": "PostgreSQL",
            "key": ["verified.company_id", "verified.installation_id", "verified.client_id"],
            "algorithm": "fixed window; at most 2L requests may straddle a boundary",
            "exhaustedCode": "rate_limited", "retryAfter": "integer delay-seconds, ceiling, minimum 1",
            "storeFailureStatus": 503, "placement": "after live identity/ACL, before domain/parameter validation"},
        "edgeErrors": "Proxy/nginx errors, including HTML 429, are outside this application contract.",
        "streamingErrors": "Errors after response headers start cannot be replaced with a Problem response.",
    }


def curated_openapi(app):
    issuer = app.state.product_settings.issuer
    try:
        if not isinstance(issuer, str) or any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in issuer) or "\\" in issuer:
            raise ValueError("Invalid issuer characters")
        parsed = urlsplit(issuer)
        if parsed.port is not None and parsed.port < 1:
            raise ValueError("Invalid issuer port")
    except ValueError:
        raise ValueError("Configured HTTPS space issuer is required for curated OpenAPI") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise ValueError("Configured HTTPS space issuer is required for curated OpenAPI")
    entries = policy_registry(app)
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes, tags=OPENAPI_TAGS)
    for path in schema["paths"].values():
        for operation in path.values():
            for status, response in operation["responses"].items():
                if status in {"400", "401", "403", "404", "422", "503"}:
                    response["content"] = {"application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}}
                elif operation["operationId"] == "downloadDocumentVersion" and status == "200":
                    response["content"].pop("application/json", None)
    schema["servers"] = [{"url": issuer.rstrip("/") + "/api/v1"}]
    descriptions = {**{access.READ_SCOPES[key]: f"Read {key}" for key in access.RESOURCES},
                    access.DOWNLOAD_SCOPE: "Download an authorized document version",
                    monitoring.SCOPE: monitoring.DESCRIPTION}
    service_scopes = {scope for entry in entries if PrincipalKind.SERVICE.value in entry["principalKinds"]
                      for scope in entry["scopes"]}
    schemes = schema.setdefault("components", {}).setdefault("securitySchemes", {})
    schemes["ProductOAuth"] = {
        "description": "User authorization. Public documentation client uses Authorization Code with PKCE S256; "
            "no client secret. Resource and current user/company permissions remain mandatory.",
        "type": "oauth2", "flows": {"authorizationCode": {
            "authorizationUrl": issuer.rstrip("/") + "/api/oauth2/authorize",
            "tokenUrl": issuer.rstrip("/") + "/api/oauth2/token",
            "scopes": descriptions}}}
    schemes["ProductServiceOAuth"] = {
        "type": "oauth2", "description": "Server-to-server confidential client only; never enter credentials in Swagger. "
            "POST form grant_type=client_credentials, explicit grant_id UUID and nonempty scope. "
            "Authenticate the registered client using client_secret_basic (HTTP Basic), not body/query credentials. "
            "grant_id is an application-specific required extension, not a standard OAuth parameter. "
            "The approved machine grant, installation and live resource scopes are still required. "
            "No user identity scopes, document access or refresh token; client secret is not an API Bearer token.",
        "flows": {"clientCredentials": {"tokenUrl": issuer.rstrip("/") + "/api/oauth2/token",
            "scopes": {scope: descriptions[scope] for scope in sorted(service_scopes)}}},
        "x-elsy-token-request": {
            "method": "POST", "contentType": "application/x-www-form-urlencoded",
            "clientAuthentication": "client_secret_basic", "browserExecution": False,
            "body": {"type": "object", "required": ["grant_type", "grant_id", "scope"], "properties": {
                "grant_type": {"type": "string", "const": "client_credentials"},
                "grant_id": {"type": "string", "format": "uuid", "description": "Required custom extension: approved machine grant of this client and installation."},
                "scope": {"type": "string", "minLength": 1, "description": "Space-separated explicit requested business scopes; all required operation scopes must be granted."}}},
            "forbiddenCredentialLocations": ["query", "body.client_id", "body.client_secret"],
            "refreshTokenIssued": False},
        "x-elsy-protocol-reference": "https://www.rfc-editor.org/rfc/rfc6749.html#section-4.4",
    }
    # OpenAPI alternatives describe the very same runtime policy: OR between
    # principal profiles, AND between scopes inside each security requirement.
    for entry in entries:
        alternatives = []
        for kind, name in ((PrincipalKind.PARTNER.value, "ProductOAuth"),
                           (PrincipalKind.SERVICE.value, "ProductServiceOAuth")):
            if kind in entry["principalKinds"]:
                alternatives.append({name: sorted(entry["scopes"])})
        if not alternatives:
            raise ValueError("Product principal policy has no documented OAuth profile")
        for method in entry["methods"]:
            schema["paths"][entry["path"]][method.lower()]["security"] = deepcopy(alternatives)
    schema["info"]["description"] = ("Canonical product contract. User Authorization Code and confidential "
        "server client_credentials are alternatives only where the runtime accepts that principal kind. "
        "Machine requests need the custom grant_id form parameter and HTTP Basic client authentication at the token endpoint. "
        "Documents require a user grant. The browser documentation uses a separate public Code+PKCE execution projection.")
    schema["x-elsy-runtime-registry"] = export_runtime_registry(app)
    schema["x-elsy-capabilities"] = {
        "implemented": {"servicePoint": "ServiceLocation read", "station": "EzsEquipmentUnit(kind=station) read",
            "counterparty": "read", "contract": "read", "document": "user read and native authorized version content",
            "monitoring": "energy service-point status and non-financial charging aggregates"},
        "gaps": {"site": "not exposed", "evse": "not exposed", "connector": "not exposed",
            "machineDocumentAccess": "denied", "sharedDomainFileContent": "denied pending canonical shared-file policy",
            "writes": "not implemented", "historicalVersionListing": "not exposed",
            "monitoringFinance": "not exposed; separate financial scopes required",
            "monitoringTickets": "not exposed; separate ticket scopes required"}}
    _describe_http_responses(schema)
    return schema


def public_client_openapi(schema):
    """Deep-copy the canonical contract into a public Code+PKCE execution view.

    Confidential profiles remain readable metadata, never Swagger auth widgets.
    Refuse a future server-only operation until it has an explicit browser view.
    """
    projected = deepcopy(schema)
    schemes = projected["components"]["securitySchemes"]
    service = schemes.pop("ProductServiceOAuth")
    if set(schemes) != {"ProductOAuth"} or set(schemes["ProductOAuth"]["flows"]) != {"authorizationCode"}:
        raise ValueError("Public docs require the public authorization-code profile")
    for path in projected["paths"].values():
        for operation in path.values():
            if not isinstance(operation, dict) or "operationId" not in operation:
                continue
            alternatives = [item for item in operation["security"] if set(item) == {"ProductOAuth"}]
            if len(alternatives) != 1:
                raise ValueError("Operation has no unambiguous public-client projection")
            operation["security"] = alternatives
    projected["x-elsy-authentication-projection"] = {
        "kind": "public-code-pkce", "executionSecuritySchemes": ["ProductOAuth"],
        "canonicalContract": "/api/developer/docs/openapi.server.json",
        "serverOnlyProfiles": {"ProductServiceOAuth": service},
    }
    projected["info"]["description"] += "\n\nThis is the public Code+PKCE browser execution projection. " \
        "[Download the full server contract](/api/developer/docs/openapi.server.json) " \
        "with the same protected documentation session. Machine authentication is documented for server developers only."
    return projected
