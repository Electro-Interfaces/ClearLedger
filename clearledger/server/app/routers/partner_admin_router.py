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
from app.auth import bearer_scheme

from app.database import get_db
from app.models import App, CompanyApp, ServiceLocation
from app.models_partner import (PartnerClient, PartnerCredential, PartnerGrant, PartnerInstallation,
    PartnerInstallationLocation, PartnerResourceScope, PartnerResourceItem)
from app.schemas_partner import ApproveInstallation, ApproveMachineGrant, RegisterClient, SetEnabled
from app.services.partner_identity import (IDENTITY_SCOPES, NO_STORE, RESOURCE_MODELS, PartnerRoute, admin, digest, now,
    require_core_user, validate_redirect, validate_scopes, _prepare_partner_write,
    _native_authority, _writer_drift)
from app.services.contract_write_locks import ScopedLockError

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


def finish(writer, result):
    writer.checkpoint()
    writer.db.flush()
    writer.checkpoint()  # FK/unique/sets waits have now completed.
    return result


def owned_client(sync, client_id, user, native, mutation):
    # The shared composer discovers the actual owner inside the frozen graph.
    writer = _prepare_partner_write(sync, client_id=client_id, actor=user,
        native=native, mutation=mutation)
    client = sync.get(PartnerClient, client_id)
    if client is None:
        raise HTTPException(404, "Client not found", headers=NO_STORE)
    admin(sync, user, client.owner_company_id)
    return client, writer


@router.post("/clients", status_code=201)
async def register(body: RegisterClient, user=Depends(require_core_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme)):
    for uri in body.redirectUris:
        validate_redirect(uri)
    scopes = scope_set(body.scopes)
    native = _native_authority(db, credentials, user)
    app_id, client_id = uuid.uuid4(), secrets.token_urlsafe(32)
    def create(sync):
        writer = _prepare_partner_write(sync, company_id=body.companyId, actor=user, native=native,
            admin_company=body.companyId, new_app=app_id, new_client=client_id, mutation="register")
        admin(sync, user, body.companyId)
        app = App(id=app_id, code="ext-" + secrets.token_hex(12), name=body.name, kind="partner", is_active=True)
        sync.add(app)
        sync.flush()
        writer.checkpoint()
        client = PartnerClient(id=client_id, app_id=app.id, owner_company_id=body.companyId,
            redirect_uris=list(dict.fromkeys(body.redirectUris)), allowed_scopes=sorted(scopes),
            auth_method=body.authMethod, enabled=False)
        sync.add(client)
        sync.flush()
        return finish(writer, {"clientId": client.id, "appId": str(app.id), "enabled": False,
                "authMethod": client.auth_method, "redirectUris": client.redirect_uris, "scopes": client.allowed_scopes})
    return await committed_response(db, create, 201)


@router.post("/clients/{client_id}/status")
async def client_status(client_id: str, body: SetEnabled, user=Depends(require_core_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme)):
    native = _native_authority(db, credentials, user)
    def change(sync):
        client, writer = owned_client(sync, client_id, user, native, "client_status")
        client.enabled = body.enabled
        return finish(writer, {"clientId": client.id, "enabled": client.enabled})
    return await committed_response(db, change)


@router.post("/clients/{client_id}/credentials", status_code=201)
async def issue_credential(client_id: str, user=Depends(require_core_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme)):
    native = _native_authority(db, credentials, user)
    def issue(sync):
        client, writer = owned_client(sync, client_id, user, native, "issue_credential")
        if not client.enabled or client.auth_method != "client_secret_basic":
            raise HTTPException(409, "Active confidential client required", headers=NO_STORE)
        secret = secrets.token_urlsafe(48)
        credential = PartnerCredential(client_id=client.id, secret_hash=digest(secret),
            enabled=True, expires_at=now() + timedelta(days=90))
        sync.add(credential)
        sync.flush()
        return finish(writer, {"credentialId": str(credential.id), "clientId": client.id, "clientSecret": secret,
                "expiresAt": credential.expires_at.isoformat()})
    # Secret returned once over this authenticated response, never persisted raw.
    return await committed_response(db, issue, 201)


@router.delete("/clients/{client_id}/credentials/{credential_id}")
async def revoke_credential(client_id: str, credential_id: uuid.UUID, user=Depends(require_core_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme)):
    native = _native_authority(db, credentials, user)
    def revoke(sync):
        _, writer = owned_client(sync, client_id, user, native, "revoke_credential")
        credential = sync.get(PartnerCredential, credential_id)
        if credential is None or credential.client_id != client_id:
            raise HTTPException(404, "Credential not found", headers=NO_STORE)
        credential.enabled = False
        return finish(writer, {"revoked": True})
    return await committed_response(db, revoke)


def _installation_selection(sync, client_id, body, user, scopes):
    """Read-only legacy policy, before discovery and again from held current rows.

    The first guard precedes even an expired actor attribute load. Returned IDs
    close discovery, but never authorize a write without the second validation.
    """
    if sync.new or sync.dirty or sync.deleted:
        raise ScopedLockError("Partner writer requires clean discovery; roll back the entire root")
    with sync.no_autoflush:
        admin(sync, user, body.companyId)
        client = sync.get(PartnerClient, client_id, populate_existing=True)
        if client is None or not client.enabled or not scopes <= set(client.allowed_scopes):
            raise HTTPException(422, "Invalid client or scopes", headers=NO_STORE)
        ids = frozenset(body.locationIds or [])
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
                typed_ids = frozenset(selection.ids) if kind == "objects" else frozenset(uuid.UUID(v) for v in selection.ids)
            except ValueError:
                raise HTTPException(422, "Invalid resource ID type", headers=NO_STORE) from None
            actual = set(sync.scalars(select(model.id).where(model.company_id == body.companyId,
                model.id.in_(typed_ids))).all()) if typed_ids else set()
            if actual != typed_ids:
                raise HTTPException(422, "Invalid company resource IDs", headers=NO_STORE)
            resources.append((kind, selection.mode, column, typed_ids))
        return client, ids, tuple(resources)


@router.post("/clients/{client_id}/installations", status_code=201)
async def approve_installation(client_id: str, body: ApproveInstallation, user=Depends(require_core_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme)):
    scopes = scope_set(body.scopes)
    native = _native_authority(db, credentials, user)
    def approve(sync):
        _, ids, resources = _installation_selection(sync, client_id, body, user, scopes)
        selections = ((ServiceLocation, ids),) + tuple((RESOURCE_MODELS[kind][0], values)
            for kind, mode, column, values in resources)
        writer = _prepare_partner_write(sync, client_id=client_id, company_id=body.companyId,
            actor=user, native=native, admin_company=body.companyId, mutation="approve_installation", selections=selections)
        # _prepare has acquired the complete plan, canonical rows and current
        # native actor. Reuse the exact policy; preflight is not write authority.
        client, ids, resources = _installation_selection(sync, client_id, body, writer.actor, scopes)
        ca_id = writer.ca_id
        writer.checkpoint()
        sync.execute(insert(CompanyApp).values(id=ca_id, app_id=client.app_id, company_id=body.companyId,
            enabled=True).on_conflict_do_nothing(index_elements=["company_id", "app_id"]))
        # Read actual conflict winner WITHOUT locking a newly observed CA.
        actual_id = sync.scalar(select(CompanyApp.id).where(CompanyApp.company_id == body.companyId,
            CompanyApp.app_id == client.app_id))
        if actual_id != ca_id:
            _writer_drift(sync)
        writer.checkpoint()
        company_app = sync.scalar(select(CompanyApp).where(CompanyApp.company_id == body.companyId,
            CompanyApp.app_id == client.app_id, CompanyApp.id == ca_id).with_for_update()
            .execution_options(populate_existing=True))
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
        return finish(writer, {"installationId": str(install.id), "companyId": str(body.companyId), "scopes": sorted(scopes), "approved": True})
    return await committed_response(db, approve, 201)


def admin_install(sync, installation_id, user, native, mutation):
    writer = _prepare_partner_write(sync, installation_id=installation_id, actor=user,
        native=native, mutation=mutation)
    install = sync.get(PartnerInstallation, installation_id)
    company_app = sync.get(CompanyApp, installation_id)
    if install is None or company_app is None:
        raise HTTPException(404, "Installation not found", headers=NO_STORE)
    admin(sync, user, company_app.company_id)
    return install, writer


@router.delete("/installations/{installation_id}")
async def revoke_installation(installation_id: uuid.UUID, user=Depends(require_core_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme)):
    native = _native_authority(db, credentials, user)
    def revoke(sync):
        install, writer = admin_install(sync, installation_id, user, native, "revoke_installation")
        install.approved = False
        return finish(writer, {"revoked": True})
    return await committed_response(db, revoke)


@router.post("/installations/{installation_id}/machine-grants", status_code=201)
async def machine_grant(installation_id: uuid.UUID, body: ApproveMachineGrant, user=Depends(require_core_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme)):
    scopes = scope_set(body.scopes)
    native = _native_authority(db, credentials, user)
    def approve(sync):
        install, writer = admin_install(sync, installation_id, user, native, "machine_grant")
        client = sync.get(PartnerClient, install.client_id)
        if (not install.approved or not client.enabled or client.auth_method != "client_secret_basic"
                or scopes & IDENTITY_SCOPES or not scopes <= set(install.scopes) & set(client.allowed_scopes)
                or scopes & {"documents:read", "documents.files:download"}):
            raise HTTPException(422, "Invalid machine grant", headers=NO_STORE)
        grant = PartnerGrant(installation_id=install.id, client_id=client.id, company_id=install.company_id, kind="machine",
            user_id=None, scopes=sorted(scopes), approved=True)
        sync.add(grant)
        sync.flush()
        return finish(writer, {"grantId": str(grant.id), "scopes": grant.scopes})
    return await committed_response(db, approve, 201)


@router.delete("/grants/{grant_id}")
async def revoke_grant(grant_id: uuid.UUID, user=Depends(require_core_user), db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme)):
    native = _native_authority(db, credentials, user)
    def revoke(sync):
        writer = _prepare_partner_write(sync, grant_id=grant_id, actor=user, native=native, mutation="revoke_grant")
        grant = sync.get(PartnerGrant, grant_id)
        if grant is None:
            raise HTTPException(404, "Grant not found", headers=NO_STORE)
        if grant.user_id != user.id:
            admin(sync, user, grant.company_id)
        grant.approved = False
        return finish(writer, {"revoked": True})
    return await committed_response(db, revoke)


# Separate closed profile prerequisite. Existing identity handlers/dependencies
# above retain their native behavior, including the presence-aware dependency.
from app.schemas_partner import ReplaceContractCreateProfile, ContractCreateProfileReadback
from app.services.partner_contract_profiles import profile_admin_request


@router.put("/installations/{installation_id}/contract-create-profile",
            response_model=ContractCreateProfileReadback)
async def replace_contract_create_profile(
    installation_id: uuid.UUID, body: ReplaceContractCreateProfile,
    db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme),
):
    return await profile_admin_request(db, installation_id, credentials, body)


@router.get("/installations/{installation_id}/contract-create-profile",
            response_model=ContractCreateProfileReadback)
async def read_contract_create_profile(
    installation_id: uuid.UUID,
    db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme),
):
    return await profile_admin_request(db, installation_id, credentials)


from app.schemas_partner import ActivateContractCreateProfile
from app.services.partner_contract_activation import activation_admin_request


@router.put("/installations/{installation_id}/contract-create-profile/activation",
            response_model=ContractCreateProfileReadback, include_in_schema=False)
async def activate_contract_create_profile(
    installation_id: uuid.UUID, body: ActivateContractCreateProfile,
    db: AsyncSession = Depends(get_db), credentials=Depends(bearer_scheme),
):
    return await activation_admin_request(db, installation_id, credentials, body)
