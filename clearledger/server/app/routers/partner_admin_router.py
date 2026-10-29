"""Core-bearer administration; no UI-only role checks or dynamic registration."""
import secrets
import uuid
from datetime import timedelta

from authlib.oauth2.rfc6749 import InvalidScopeError
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import App, CompanyApp, ServiceLocation
from app.models_partner import (PartnerClient, PartnerCredential, PartnerGrant, PartnerInstallation,
    PartnerInstallationLocation, PartnerResourceScope, PartnerResourceItem)
from app.schemas_partner import ApproveInstallation, ApproveMachineGrant, RegisterClient, SetEnabled
from app.services.partner_identity import (IDENTITY_SCOPES, NO_STORE, RESOURCE_MODELS, PartnerRoute, admin, digest, now,
    require_core_user, validate_redirect, validate_scopes)

router = APIRouter(prefix="/developer", tags=["Partner administration"], route_class=PartnerRoute)


async def committed_response(db, operation, status=200):
    result = await db.run_sync(operation)
    await db.commit()
    return JSONResponse(result, status_code=status, headers=NO_STORE)


def scope_set(values):
    try:
        return validate_scopes(values)
    except InvalidScopeError:
        raise HTTPException(422, "Invalid scopes", headers=NO_STORE) from None


def owned_client(sync, client_id, user):
    client = sync.get(PartnerClient, client_id)
    if client is None:
        raise HTTPException(404, "Client not found", headers=NO_STORE)
    admin(sync, user, client.owner_company_id)
    return client


@router.post("/clients", status_code=201)
async def register(body: RegisterClient, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    for uri in body.redirectUris:
        validate_redirect(uri)
    scopes = scope_set(body.scopes)
    def create(sync):
        admin(sync, user, body.companyId)
        app = App(code="ext-" + secrets.token_hex(12), name=body.name, kind="partner", is_active=True)
        sync.add(app)
        sync.flush()
        client = PartnerClient(id=secrets.token_urlsafe(32), app_id=app.id, owner_company_id=body.companyId,
            redirect_uris=list(dict.fromkeys(body.redirectUris)), allowed_scopes=sorted(scopes),
            auth_method=body.authMethod, enabled=False)
        sync.add(client)
        sync.flush()
        return {"clientId": client.id, "appId": str(app.id), "enabled": False,
                "authMethod": client.auth_method, "redirectUris": client.redirect_uris, "scopes": client.allowed_scopes}
    return await committed_response(db, create, 201)


@router.post("/clients/{client_id}/status")
async def client_status(client_id: str, body: SetEnabled, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    def change(sync):
        client = owned_client(sync, client_id, user)
        client.enabled = body.enabled
        return {"clientId": client.id, "enabled": client.enabled}
    return await committed_response(db, change)


@router.post("/clients/{client_id}/credentials", status_code=201)
async def issue_credential(client_id: str, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    def issue(sync):
        client = owned_client(sync, client_id, user)
        if not client.enabled or client.auth_method != "client_secret_basic":
            raise HTTPException(409, "Active confidential client required", headers=NO_STORE)
        secret = secrets.token_urlsafe(48)
        credential = PartnerCredential(client_id=client.id, secret_hash=digest(secret),
            enabled=True, expires_at=now() + timedelta(days=90))
        sync.add(credential)
        sync.flush()
        return {"credentialId": str(credential.id), "clientId": client.id, "clientSecret": secret,
                "expiresAt": credential.expires_at.isoformat()}
    # Secret returned once over this authenticated response, never persisted raw.
    return await committed_response(db, issue, 201)


@router.delete("/clients/{client_id}/credentials/{credential_id}")
async def revoke_credential(client_id: str, credential_id: uuid.UUID, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    def revoke(sync):
        owned_client(sync, client_id, user)
        credential = sync.get(PartnerCredential, credential_id)
        if credential is None or credential.client_id != client_id:
            raise HTTPException(404, "Credential not found", headers=NO_STORE)
        credential.enabled = False
        return {"revoked": True}
    return await committed_response(db, revoke)


@router.post("/clients/{client_id}/installations", status_code=201)
async def approve_installation(client_id: str, body: ApproveInstallation, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    scopes = scope_set(body.scopes)
    def approve(sync):
        admin(sync, user, body.companyId)
        client = sync.get(PartnerClient, client_id)
        if client is None or not client.enabled or not scopes <= set(client.allowed_scopes):
            raise HTTPException(422, "Invalid client or scopes", headers=NO_STORE)
        ids = set(body.locationIds or [])
        if ids:
            valid = set(sync.scalars(select(ServiceLocation.id).where(
                ServiceLocation.company_id == body.companyId, ServiceLocation.id.in_(ids))).all())
            if ids != valid:
                raise HTTPException(422, "Invalid company resource IDs", headers=NO_STORE)
        resources = []
        for kind, selection in body.resourceScopes.items():
            model, column = RESOURCE_MODELS[kind]
            if (selection.mode == "SET") != bool(selection.ids):
                raise HTTPException(422, "SET requires IDs; ALL/EMPTY forbid IDs", headers=NO_STORE)
            try:
                typed_ids = set(selection.ids) if kind == "objects" else {uuid.UUID(v) for v in selection.ids}
            except ValueError:
                raise HTTPException(422, "Invalid resource ID type", headers=NO_STORE) from None
            actual = set(sync.scalars(select(model.id).where(model.company_id == body.companyId,
                model.id.in_(typed_ids))).all()) if typed_ids else set()
            if actual != typed_ids:
                raise HTTPException(422, "Invalid company resource IDs", headers=NO_STORE)
            resources.append((kind, selection.mode, column, typed_ids))
        ca_id = uuid.uuid4()
        sync.execute(insert(CompanyApp).values(id=ca_id, app_id=client.app_id, company_id=body.companyId,
            enabled=True).on_conflict_do_nothing(index_elements=["company_id", "app_id"]))
        company_app = sync.scalar(select(CompanyApp).where(CompanyApp.company_id == body.companyId,
            CompanyApp.app_id == client.app_id).with_for_update())
        company_app.enabled = True
        install = sync.get(PartnerInstallation, company_app.id)
        if install is None:
            install = PartnerInstallation(id=company_app.id, client_id=client.id, company_id=body.companyId)
            sync.add(install)
        elif install.company_id != body.companyId or install.client_id != client.id:
            raise HTTPException(409, "Installation company mismatch", headers=NO_STORE)
        install.approved, install.scopes, install.all_locations = True, sorted(scopes), body.locationIds is None
        sync.flush()
        sync.execute(delete(PartnerInstallationLocation).where(PartnerInstallationLocation.installation_id == install.id))
        sync.add_all([PartnerInstallationLocation(installation_id=install.id, location_id=v) for v in ids])
        sync.execute(delete(PartnerResourceScope).where(PartnerResourceScope.installation_id == install.id))
        for kind, mode, column, values in resources:
            sync.add(PartnerResourceScope(installation_id=install.id, kind=kind, mode=mode))
            sync.flush()
            sync.add_all([PartnerResourceItem(installation_id=install.id, kind=kind, **{column: v}) for v in values])
        return {"installationId": str(install.id), "companyId": str(body.companyId), "scopes": sorted(scopes), "approved": True}
    return await committed_response(db, approve, 201)


def admin_install(sync, installation_id, user):
    install = sync.get(PartnerInstallation, installation_id)
    company_app = sync.get(CompanyApp, installation_id)
    if install is None or company_app is None:
        raise HTTPException(404, "Installation not found", headers=NO_STORE)
    admin(sync, user, company_app.company_id)
    return install


@router.delete("/installations/{installation_id}")
async def revoke_installation(installation_id: uuid.UUID, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    def revoke(sync):
        admin_install(sync, installation_id, user).approved = False
        return {"revoked": True}
    return await committed_response(db, revoke)


@router.post("/installations/{installation_id}/machine-grants", status_code=201)
async def machine_grant(installation_id: uuid.UUID, body: ApproveMachineGrant, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    scopes = scope_set(body.scopes)
    def approve(sync):
        install = admin_install(sync, installation_id, user)
        client = sync.get(PartnerClient, install.client_id)
        if (not install.approved or not client.enabled or client.auth_method != "client_secret_basic"
                or scopes & IDENTITY_SCOPES or not scopes <= set(install.scopes) & set(client.allowed_scopes)
                or scopes & {"documents:read", "documents.files:download"}):
            raise HTTPException(422, "Invalid machine grant", headers=NO_STORE)
        grant = PartnerGrant(installation_id=install.id, client_id=client.id, company_id=install.company_id, kind="machine",
            user_id=None, scopes=sorted(scopes), approved=True)
        sync.add(grant)
        sync.flush()
        return {"grantId": str(grant.id), "scopes": grant.scopes}
    return await committed_response(db, approve, 201)


@router.delete("/grants/{grant_id}")
async def revoke_grant(grant_id: uuid.UUID, user=Depends(require_core_user), db: AsyncSession = Depends(get_db)):
    def revoke(sync):
        grant = sync.get(PartnerGrant, grant_id)
        if grant is None:
            raise HTTPException(404, "Grant not found", headers=NO_STORE)
        if grant.user_id != user.id:
            admin_install(sync, grant.installation_id, user)
        grant.approved = False
        return {"revoked": True}
    return await committed_response(db, revoke)
