"""Opt-in versioned read API. Never mounts itself onto the legacy application."""
from dataclasses import dataclass
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
from . import access, dto, files, monitoring
from .queries import Query


@dataclass(frozen=True)
class Settings:
    sessions: object
    verifier: object
    enabled: object
    upload_dir: Path
    cursor_key: bytes
    issuer: str | None
    source_revision: str


def _problem(request, status):
    codes = {400: "invalid_cursor", 401: "invalid_credentials", 403: "access_denied",
             404: "not_found", 405: "method_not_allowed", 422: "invalid_request", 503: "api_unavailable"}
    safe = {400: "Cursor is invalid or belongs to another query", 401: "Valid partner Bearer credentials are required",
            403: "Access is denied", 404: "Resource was not found", 422: "Request parameters are invalid",
            503: "Partner API is unavailable"}
    value = dto.Problem(title=HTTPStatus(status).phrase, status=status,
        code=codes.get(status, "internal_error"), request_id=getattr(request.state, "request_id", str(uuid.uuid4())),
        detail=safe.get(status, "Request could not be completed"))
    return JSONResponse(value.model_dump(by_alias=True), status_code=status,
                        media_type="application/problem+json",
                        headers={"WWW-Authenticate": "Bearer"} if status == 401 else None)


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
                       cursor_key=None, issuer=None, source_revision="unverified") -> FastAPI:
    key = secrets.token_bytes(32) if cursor_key is None else cursor_key
    if not isinstance(key, bytes) or len(key) < 32:
        raise ValueError("Cursor signing key must contain at least 32 bytes")
    app = create_policy_app(context_resolver=access.resolve, title="ElsyPlus Product Read API", version="1.0.0")
    app.state.product_settings = Settings(
        session_factory or access.configured_sessions, verifier or access.configured_verifier,
        access.configured_enabled if enabled is None else (enabled if callable(enabled) else lambda: enabled is True),
        Path(upload_dir or os.environ.get("UPLOAD_DIR", "/app/uploads")), key, issuer, source_revision)

    @app.middleware("http")
    async def request_id(request, call_next):
        request.state.request_id = str(uuid.uuid4())
        response = await call_next(request)
        response.headers["X-Request-Id"] = request.state.request_id
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(HTTPException)
    async def http_problem(request, error):
        return _problem(request, error.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_problem(request, error):
        return _problem(request, 422)

    @app.exception_handler(Exception)
    async def internal_problem(request, error):
        return _problem(request, 500)

    router = PolicyRouter(context_resolver=access.resolve)
    problems = {status: {"model": dto.Problem, "content": {"application/problem+json": {}}}
                for status in (400, 401, 403, 404, 422, 503)}

    def operation(path, resource, operation_id, response_model=None, action="read", extra_scopes=(), **kwargs):
        return router.operation(path, policy=_policy(resource, action, extra_scopes), methods=["GET"],
            operation_id=operation_id, response_model=response_model, responses={**problems, **kwargs.pop("responses", {})},
            openapi_extra={"x-elsy-owner": resource, "x-elsy-access-class": "partner",
                "x-elsy-resource-policy": f"{resource}:{action}", "x-elsy-readiness": "candidate"}, **kwargs)

    @operation("/objects", "objects", "listObjects", dto.Page[dto.Object])
    async def objects(params: Annotated[dto.ListQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return await query.listing("objects", params)

    @operation("/objects/{objectId}", "objects", "getObject", dto.Object)
    async def object_detail(objectId: dto.Id, params: Annotated[dto.EmptyQuery, QueryParams()], query: Query = Depends(query_dependency)):
        return (await query.project("objects", [await query.detail("objects", objectId)]))[0]

    @operation("/objects/{objectId}/monitoring", "objects", "getObjectMonitoring", dto.Monitoring,
               extra_scopes={monitoring.SCOPE}, summary="Read object charging status",
               description="Energy profile only. Current catalog status; object-scoped observed data boundary. "
                   "Inclusive MSK interval [asOf - days, asOf], days 1..366. asOf date caps the endpoint at "
                   "23:59:59.999999 MSK, or earlier observed data. Successful visit: any attempt energy > 0. "
                   "No financial, ticket, customer or raw session data.")
    async def object_monitoring(objectId: dto.Id, params: Annotated[dto.MonitoringQuery, QueryParams()],
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
    policy_registry(app)
    schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
    for path in schema["paths"].values():
        for operation in path.values():
            for status, response in operation["responses"].items():
                if status in {"400", "401", "403", "404", "422", "503"}:
                    response["content"] = {"application/problem+json": {"schema": {"$ref": "#/components/schemas/Problem"}}}
                elif operation["operationId"] == "downloadDocumentVersion" and status == "200":
                    response["content"].pop("application/json", None)
    schema["servers"] = [{"url": issuer.rstrip("/") + "/api/v1"}]
    schema.setdefault("components", {}).setdefault("securitySchemes", {})["ProductOAuth"] = {
        "type": "oauth2", "flows": {"authorizationCode": {
            "authorizationUrl": issuer.rstrip("/") + "/api/oauth2/authorize",
            "tokenUrl": issuer.rstrip("/") + "/api/oauth2/token",
            "scopes": {**{access.READ_SCOPES[key]: f"Read {key}" for key in access.RESOURCES},
                       access.DOWNLOAD_SCOPE: "Download an authorized document version",
                       monitoring.SCOPE: monitoring.DESCRIPTION}}}}
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
    return schema
