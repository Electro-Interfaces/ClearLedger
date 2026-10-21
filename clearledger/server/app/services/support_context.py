"""Вход support-context через существующие Core SSO, компанию и реестр приложений.

Все HTTP выполняются после окончания транзакции чтения, без row locks. Права
не кэшируются: каждый introspect заново читает Core/Node/Support. Линейная точка
операции — положительный introspect; локальный business lock принадлежит Support.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import Field, ValidationError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert

from app.auth import _named_key, resolve_member_modules
from app.models import App, CompanyApp, SpaceInboundKey, User, UserCompany
from app.services import app_registry, sso
from app.services.support_scope import support_company_id
from app.services.support_context_models import ContextBinding, ContextGrant, ContextReplay
from app.services.support_context_protocol import (
    Action, Actor, CallRef, ContextRef, Envelope, Text, Trust, VERSION,
    digest, fail, sign, verify,
)

PREFIX = "/api/eco/support-context/v1"
SUPPORT_PREFIX = "/api/v1/eco/support-context/v1"
NODE_PREFIX = "/cc/v0/support-context/v1/admission"


class NodeEvidence(Envelope):
    admissionRef: Text
    callRef: CallRef
    contextRef: ContextRef
    connectionId: Text
    act: Actor
    jkt: Text
    assignmentVersion: int = Field(ge=1, strict=True)
    phase: str
    allowedActions: list[Action]
    amr: list[str]
    phaseDeadline: datetime | None
    endedAt: datetime | None
    active: bool = Field(strict=True)
    revoked: bool = Field(strict=True)


class ActorEvidence(Envelope):
    callRef: CallRef
    contextRef: ContextRef
    connectionId: Text
    bindingRef: Text
    coreActorSub: Text
    supportUserRef: Text
    bindingVersion: int = Field(ge=1, strict=True)
    permissionsVersion: int = Field(ge=1, strict=True)
    capabilities: list[Action]
    fieldMask: str
    membership: bool = Field(strict=True)
    active: bool = Field(strict=True)
    ticketRefs: list[Text]


def envelope(**kwargs):
    return {"version": VERSION, "schemaVersion": 1, **kwargs}


def uuid_or_fail(value):
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        fail(404, "company_unavailable")


async def configuration(db, core_cid):
    cid = uuid_or_fail(core_cid)
    apps = await app_registry.company_apps(db, cid)
    enabled = {a["code"] for a in apps if a["enabled"]}
    if not {"support", "voice"} <= enabled:
        fail(403, "product_disabled")
    rows = (await db.execute(select(App, CompanyApp).join(
        CompanyApp, CompanyApp.app_id == App.id).where(
        CompanyApp.company_id == cid, App.code.in_(["voice", "support"]),
    ))).all()
    by_code = {a.code: (a, ca) for a, ca in rows}
    try:
        raw = (by_code["voice"][1].config or {})["supportContext"]
        trust = Trust.model_validate(raw)
        if not trust.enabled:
            fail(403, "feature_disabled")
        app, ca = by_code["support"]
        # Только настроенное приложение; не default URL и не ключ другой компании.
        from app.services.support_context_protocol import trusted_url
        base = trusted_url((ca.config or {}).get("internalUrl") or (app.config or {})["internalUrl"])
    except (KeyError, TypeError, ValueError):
        fail(503, "trust_unconfigured")
    support_cid = await support_company_id(db, cid)
    if not support_cid:
        fail(403, "company_unmapped")
    return trust, str(support_cid), base


def node_for(trust, call):
    node = next((n for n in trust.nodes if n.nodeId == call["nodeId"]
                 and n.connectorId == call["connectorId"]), None)
    if node is None:
        fail(404, "call_unavailable")
    return node


async def named_caller(db, raw, scope):
    key = await _named_key(raw or "", db)
    if key is None or key.station_id is not None:
        fail(401, "invalid_service_key")
    if scope not in (key.scopes or []):
        fail(403, "service_scope_denied")
    return key


def service_token(scope, core_cid, cid, call=None, **extra):
    now = int(time.time())
    audience = ("node-support-admission" if scope == "support-context.admission"
                else "core-support-context" if scope == "support-context.introspect"
                else "support-context")
    payload = {"version": VERSION, "iss": sso.settings.sso_issuer,
                 "aud": audience, "sub": "service:" + scope, "svc": scope,
                 "coreCid": str(core_cid), "cid": cid,
                 "iat": now, "nbf": now, "exp": now + 120, "jti": uuid.uuid4().hex, **extra}
    if call is not None:
        payload["callRef"] = call
    return sign(payload)


async def exchange(db, raw):
    key = await named_caller(db, raw, "support-context.introspect")
    trust, cid, _base = await configuration(db, key.company_id)
    if str(key.id) != trust.introspectionKeyId:
        fail(403, "service_not_trusted")
    key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return service_token("support-context.introspect", key.company_id, cid, keyId=str(key.id))


async def json_http(url, token, body, *, limit=128 * 1024):
    """Bounded response, fixed destination, no redirects/errors/body logging."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0),
                                     follow_redirects=False, trust_env=False) as client:
            async with client.stream("POST", url, headers={"Authorization": "Bearer " + token},
                                     json=body) as response:
                if response.status_code in (401, 403, 404, 409):
                    fail(response.status_code, "upstream_denied")
                if response.status_code not in (200, 202):
                    fail(503, "upstream_unavailable")
                raw = bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw) > limit:
                        fail(503, "upstream_invalid")
        import json
        result = json.loads(raw)
        if not isinstance(result, dict):
            fail(503, "upstream_invalid")
        return result
    except httpx.TimeoutException:
        fail(504, "upstream_timeout")
    except (httpx.HTTPError, ValueError):
        fail(503, "upstream_invalid")


async def replay(db, key, seconds=120):
    now = datetime.now(timezone.utc)
    await db.execute(delete(ContextReplay).where(ContextReplay.expires_at < now))
    result = await db.execute(insert(ContextReplay).values(
        key=key, expires_at=now + timedelta(seconds=seconds),
    ).on_conflict_do_nothing().returning(ContextReplay.key))
    applied = result.scalar_one_or_none()
    await db.commit()  # до ответа/HTTP: replay переживает другой процесс и rollback вызывающего
    if applied is None:
        fail(401, "replay")


async def prepare(db, raw_key, body):
    key = await named_caller(db, raw_key, "support-context.prepare")
    core_cid = str(key.company_id)
    trust, cid, base = await configuration(db, core_cid)
    call = body.callRef.model_dump()
    node = node_for(trust, call)
    if str(key.id) != node.prepareKeyId:
        fail(403, "node_key_mismatch")
    key.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    data = await json_http(base + SUPPORT_PREFIX + "/prepare",
                           service_token("support-context.prepare", core_cid, cid, call),
                           body.model_dump(mode="json"))
    # Do not relay arbitrary upstream data to Node. Only opaque routing metadata.
    try:
        from pydantic import TypeAdapter
        ref = TypeAdapter(ContextRef).validate_python(data["contextRef"])
        if (data["version"] != VERSION or type(data["schemaVersion"]) is not int or data["schemaVersion"] != 1
                or data["callRef"] != call or type(data["contextVersion"]) is not int
                or data["contextVersion"] < 1 or type(data["state"]) is not str
                # Повтор prepare возвращает текущее persisted state (C02 clarifier).
                or data["state"] not in ("preparing", "ready", "partial", "unavailable")):
            raise ValueError("prepare shape")
        prepared = datetime.fromisoformat(data["preparedAt"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(data["expiresAt"].replace("Z", "+00:00"))
        if (prepared.tzinfo is None or expires.tzinfo is None
                or not timedelta(0) < expires - prepared <= timedelta(hours=24)
                or expires <= datetime.now(timezone.utc)
                or type(data["retryAfterMs"]) is not int or not 0 <= data["retryAfterMs"] <= 60000):
            raise ValueError("expiry")
    except (KeyError, ValueError, TypeError):
        fail(503, "upstream_invalid")
    values = dict(context_ref=ref, core_cid=core_cid, support_cid=cid,
                  node_id=call["nodeId"], connector_id=call["connectorId"],
                  contact_id=call["nodeContactId"], expires_at=expires)
    inserted = (await db.execute(insert(ContextBinding).values(**values)
                                .on_conflict_do_nothing().returning(ContextBinding.context_ref))).scalar_one_or_none()
    if inserted is None:
        existing = await db.scalar(select(ContextBinding).where(
            ContextBinding.core_cid == core_cid, ContextBinding.support_cid == cid,
            ContextBinding.node_id == call["nodeId"], ContextBinding.connector_id == call["connectorId"],
            ContextBinding.contact_id == call["nodeContactId"]))
        if existing is None or existing.context_ref != ref or existing.expires_at != expires:
            await db.rollback()
            fail(409, "call_context_conflict")
    await db.commit()
    return {k: data[k] for k in ("version", "schemaVersion", "contextRef", "callRef",
                                 "contextVersion", "state", "preparedAt", "expiresAt", "retryAfterMs")}


async def binding(db, core_cid, cid, call, context_ref=None):
    row = await db.scalar(select(ContextBinding).where(
        ContextBinding.core_cid == str(core_cid), ContextBinding.support_cid == cid,
        ContextBinding.node_id == call["nodeId"], ContextBinding.connector_id == call["connectorId"],
        ContextBinding.contact_id == call["nodeContactId"]))
    if row is None or (context_ref is not None and row.context_ref != context_ref):
        fail(404, "context_unavailable")
    if row.expires_at <= datetime.now(timezone.utc):
        fail(403, "context_expired")
    return row


def check_node(data, trust, call, context_ref, jkt, previous=None):
    try:
        evidence = NodeEvidence.model_validate(data)
    except ValidationError:
        fail(503, "node_invalid")
    n = evidence.model_dump(mode="json")
    if n["callRef"] != call or n["contextRef"] != context_ref or n["jkt"] != jkt:
        fail(403, "node_binding_mismatch")
    if not n["active"] or n["revoked"]:
        fail(403, "assignment_revoked")
    if previous and any(n[k] != previous[k] for k in ("connectionId", "act", "assignmentVersion")):
        fail(403, "assignment_changed")
    now = datetime.now(timezone.utc)
    # Node attests verified amr; freshness is the 30s one-use code, never
    # a fabricated authentication time inferred from requireMfa policy.
    if trust.requireMfa and "otp" not in n["amr"]:
        fail(403, "mfa_required")
    phase = n["phase"]
    actions = set(n["allowedActions"]) & {"context.read", "context.details", "context.select",
                                          "context.clarify", "ticket.create", "ticket.append"}
    deadline = now + timedelta(seconds=120)
    tickets = []
    if phase in ("offering", "consult"):
        actions &= {"context.read", "context.details"}
    elif phase == "connected":
        pass
    elif phase == "wrapup":
        if (evidence.phaseDeadline is None or evidence.phaseDeadline.tzinfo is None
                or evidence.phaseDeadline <= now):
            fail(403, "wrapup_expired")
        deadline = min(deadline, evidence.phaseDeadline)
    else:
        fail(403, "phase_denied")
    if phase == "offering":
        if (evidence.phaseDeadline is None or evidence.phaseDeadline.tzinfo is None
                or evidence.phaseDeadline <= now):
            fail(403, "offer_expired")
        deadline = min(deadline, evidence.phaseDeadline)
    return n, actions, deadline, tickets


async def actor_resolve(base, core_cid, cid, call, context_ref, node, previous=None, ticket_refs=None):
    versions = ({"expectedBindingVersion": previous["bindingVersion"],
                 "expectedPermissionsVersion": previous["permissionsVersion"]} if previous else {})
    if ticket_refs is not None:
        versions["ticketRefs"] = ticket_refs
    data = await json_http(base + SUPPORT_PREFIX + "/actor-resolve",
                           service_token("support-context.actor-resolve", core_cid, cid, call,
                                         contextRef=context_ref, connectionId=node["connectionId"], act=node["act"],
                                         phase=node["phase"], assignmentVersion=node["assignmentVersion"]),
                           envelope(callRef=call, contextRef=context_ref, phase=node["phase"],
                                    assignmentVersion=node["assignmentVersion"], connectionId=node["connectionId"],
                                    act=node["act"], **versions))
    try:
        evidence = ActorEvidence.model_validate(data).model_dump()
    except ValidationError:
        fail(503, "actor_invalid")
    if any(evidence[k] != v for k, v in {"callRef": call, "contextRef": context_ref,
                                       "connectionId": node["connectionId"]}.items()):
        fail(403, "actor_binding_mismatch")
    if not evidence["active"] or not evidence["membership"]:
        fail(403, "actor_revoked")
    return evidence


async def node_configuration(db, node_id):
    rows = (await db.execute(select(CompanyApp.company_id).join(App, App.id == CompanyApp.app_id).where(
        App.code == "voice", CompanyApp.enabled.is_(True),
        CompanyApp.config["supportContext"]["nodes"].contains([{"nodeId": node_id}]),
    ))).scalars().all()
    if len(rows) != 1:
        fail(404, "node_unavailable")
    core_cid = str(rows[0])
    trust, cid, base = await configuration(db, core_cid)
    nodes = [n for n in trust.nodes if n.nodeId == node_id]
    if len(nodes) != 1:
        fail(403, "node_ambiguous")
    return core_cid, trust, cid, base, nodes[0]


async def core_actor(db, sub, core_cid):
    user = await db.get(User, uuid_or_fail(sub), populate_existing=True)
    now = datetime.now(timezone.utc)
    if (user is None or user.mail_only or not user.password_hash
            or (user.locked_until and user.locked_until > now)):
        fail(403, "core_actor_inactive")
    # Делегирование требует реального членства даже у superadmin; SSO admin не
    # является основанием доступа к звонкам произвольного заказчика.
    member = await db.get(UserCompany, (user.id, uuid_or_fail(core_cid)), populate_existing=True)
    if member is None:
        fail(403, "core_membership_revoked")
    mods = await resolve_member_modules(member, db)
    allowed = await app_registry.effective_apps(db, uuid_or_fail(core_cid), mods)
    if "support" not in allowed:
        fail(403, "core_module_denied")
    snapshot = {"role": member.role, "roleId": str(member.role_id), "modules": mods,
                "objectScope": member.object_scope, "ownOrg": str(member.own_organization_id),
                "partyType": member.party_type, "organization": str(member.organization_id),
                "appRoles": member.app_roles, "allowed": sorted(allowed)}
    # Передаётся Support как ограничение, никогда не расширяется Core по названию роли.
    return user, member, digest(snapshot)


def phase_mask_change(previous_phase, phase, previous_mask, mask):
    """Только фазовая проекция live grant; identity/versions проверяются отдельно."""
    masks = {"offering": "consult", "consult": "consult", "connected": "operator", "wrapup": "operator"}
    return (previous_phase != phase and previous_mask == masks.get(previous_phase)
            and mask == masks.get(phase))


async def admit(db, body, jkt, *, renew_claims=None):
    core_cid, trust, cid, base, node = await node_configuration(db, body.nodeId)
    await db.commit()
    data = await json_http(node.admissionBaseUrl + NODE_PREFIX + "/consume",
                           service_token("support-context.admission", core_cid, cid,
                                         nodeId=node.nodeId, connectorId=node.connectorId),
                           envelope(nodeId=body.nodeId, admissionCode=body.admissionCode, jkt=jkt))
    try:
        evidence = NodeEvidence.model_validate(data)
    except ValidationError:
        fail(503, "node_invalid")
    call = evidence.callRef.model_dump()
    node_for(trust, call)
    bound = await binding(db, core_cid, cid, call, evidence.contextRef)
    context_ref, context_exp = bound.context_ref, bound.expires_at
    await db.commit()
    n, actions, deadline, tickets = check_node(data, trust, call, context_ref, jkt)
    if renew_claims and any(renew_claims[k] != v for k, v in {
        "coreCid": core_cid, "cid": cid, "callRef": call, "contextRef": context_ref,
        "act": n["act"], "connectionId": n["connectionId"],
        "assignmentVersion": n["assignmentVersion"], "cnf": {"jkt": jkt},
    }.items()):
        fail(403, "renew_binding_mismatch")
    actor = await actor_resolve(base, core_cid, cid, call, context_ref, n, renew_claims)
    user, member, permission_digest = await core_actor(db, actor["coreActorSub"], core_cid)
    actions &= set(actor["capabilities"])
    if actor["fieldMask"] not in ("operator", "consult"):
        # A CC admission is not an assigned-ticket/vendor entitlement.
        fail(403, "actor_mask_denied")
    if actor["fieldMask"] == "consult":
        actions &= {"context.read", "context.details"}
    if tickets and not set(tickets) <= set(actor["ticketRefs"]):
        fail(403, "postcall_ticket_denied")
    claims = {"version": VERSION, "iss": sso.settings.sso_issuer, "aud": "support-context",
              "sub": str(user.id), "act": n["act"], "scp": "support_context",
              "coreCid": core_cid, "cid": cid, "callRef": call, "contextRef": context_ref,
              "connectionId": n["connectionId"], "grantId": uuid.uuid4().hex,
              "jti": uuid.uuid4().hex, "assignmentVersion": n["assignmentVersion"],
              "bindingVersion": actor["bindingVersion"], "permissionsVersion": actor["permissionsVersion"],
              "phase": n["phase"], "actions": sorted(actions), "ticketRefs": tickets,
              "cnf": {"jkt": jkt}, "amr": n["amr"]}
    authority = {"admissionRef": n["admissionRef"], "bindingRef": actor["bindingRef"],
                 "supportUserRef": actor["supportUserRef"], "fieldMask": actor["fieldMask"]}
    if renew_claims:
        old = await db.scalar(select(ContextGrant).where(
            ContextGrant.grant_id == renew_claims["grantId"]).with_for_update().execution_options(populate_existing=True))
        if (old is None or old.revoked_at or old.expires_at <= datetime.now(timezone.utc)
                or old.token_version != user.token_version or old.permissions_digest != permission_digest
                or str(user.id) != renew_claims["sub"]
                or actor["bindingVersion"] != renew_claims["bindingVersion"]
                or actor["permissionsVersion"] != renew_claims["permissionsVersion"]
                or any(actor[k] != old.authority[k] for k in ("bindingRef", "supportUserRef"))
                or (actor["fieldMask"] != old.authority["fieldMask"] and not phase_mask_change(
                    renew_claims["phase"], n["phase"], old.authority["fieldMask"], actor["fieldMask"]))):
            fail(403, "renew_revoked")
        old.revoked_at = datetime.now(timezone.utc)
    # Object restrictions are checked in Support against Core's current membership
    # via actor-resolve constraints (see introspection below).
    return await persist_grant(db, claims, authority, user.token_version, permission_digest,
                               min(deadline, context_exp))


async def persist_grant(db, claims, authority, token_version, permission_digest, deadline):
    now = int(time.time())
    claims.update(iat=now, nbf=now, exp=min(now + 120, int(deadline.timestamp())))
    if claims["exp"] <= now or not claims["actions"]:
        fail(403, "no_capabilities")
    token = sign(claims)
    db.add(ContextGrant(grant_id=claims["grantId"], digest=digest(token), claims=claims, authority=authority,
                        token_version=token_version, permissions_digest=permission_digest,
                        expires_at=datetime.fromtimestamp(claims["exp"], timezone.utc)))
    from app.audit import log_audit
    user = await db.get(User, uuid.UUID(claims["sub"]))
    await log_audit(db, actor=user, company_id=uuid.UUID(claims["coreCid"]),
                    action="support_context.admit", target=claims["grantId"],
                    details={"phase": claims["phase"], "actions": claims["actions"],
                             "assignmentVersion": claims["assignmentVersion"]})
    await db.commit()
    return envelope(token=token, tokenType="DPoP", expiresIn=claims["exp"] - now,
                    grantId=claims["grantId"], contextRef=claims["contextRef"],
                    phase=claims["phase"], actions=claims["actions"])


def check_postcall_node(data, trust, c, authority, *, allow_pending=False):
    try:
        evidence = NodeEvidence.model_validate(data)
    except ValidationError:
        fail(503, "node_invalid")
    n = evidence.model_dump(mode="json")
    if (n["revoked"] or any(n[k] != c[k] for k in (
        "callRef", "contextRef", "connectionId", "act", "assignmentVersion"))
            or n["jkt"] != c["cnf"]["jkt"] or n["admissionRef"] != authority["admissionRef"]):
        fail(403, "postcall_revoked")
    if n["phase"] != "ended":
        if not allow_pending or authority.get("postcallDeadline") or n["phase"] != "wrapup":
            fail(403, "postcall_revoked")
        if trust.postcallMaxSec == 0:
            fail(403, "postcall_expired")
        # Только первоначальный переход. Живой wrapup обязан по-прежнему
        # подтверждать assignment/active/MFA и ещё не истёкший Node deadline.
        check_node(data, trust, c["callRef"], c["contextRef"], c["cnf"]["jkt"], c)
        return n, evidence.phaseDeadline
    ended = evidence.endedAt
    now = datetime.now(timezone.utc)
    if ended is None or ended.tzinfo is None or ended > now:
        fail(403, "postcall_unavailable")
    deadline = ended + timedelta(seconds=trust.postcallMaxSec)
    # Закрепляем endedAt/hard deadline при первой выдаче. Новый ответ узла не
    # расширяет ранее выданное ticket право под тем же call.
    if authority.get("postcallDeadline"):
        deadline = min(deadline, datetime.fromisoformat(authority["postcallDeadline"]))
    if deadline <= now:
        fail(403, "postcall_expired")
    return n, deadline


async def postcall(db, grant_id, ticket_ref):
    source = await db.get(ContextGrant, grant_id, populate_existing=True)
    if source is None or source.revoked_at:
        fail(403, "grant_revoked")
    if source.claims["scp"] == "ticket_postcall" and source.claims["ticketRefs"] != [ticket_ref]:
        fail(403, "postcall_ticket_denied")
    root_id = source.authority.get("sourceGrantId", source.grant_id)
    root = await db.get(ContextGrant, root_id, populate_existing=True)
    if root is None or root.revoked_at:
        fail(403, "grant_revoked")
    c, authority = dict(root.claims), {**root.authority, **source.authority}
    source_version, source_permissions = root.token_version, root.permissions_digest
    trust, cid, base = await configuration(db, c["coreCid"])
    if cid != c["cid"]:
        fail(403, "company_mapping_changed")
    bound = await binding(db, c["coreCid"], cid, c["callRef"], c["contextRef"])
    context_exp = bound.expires_at
    user, _member, pd = await core_actor(db, c["sub"], c["coreCid"])
    if user.token_version != source_version or pd != source_permissions:
        fail(403, "core_permissions_changed")
    node = node_for(trust, c["callRef"])
    await db.commit()
    data = await json_http(node.admissionBaseUrl + NODE_PREFIX + "/status",
                           service_token("support-context.admission", c["coreCid"], cid, c["callRef"],
                                         nodeId=node.nodeId),
                           envelope(admissionRef=authority["admissionRef"], contextRef=c["contextRef"],
                                    callRef=c["callRef"], connectionId=c["connectionId"], act=c["act"]))
    n, deadline = check_postcall_node(data, trust, c, authority,
                                     allow_pending=source.claims["scp"] == "support_context")
    pending = n["phase"] == "wrapup"
    n["phase"] = "postcall"
    actor = await actor_resolve(base, c["coreCid"], cid, c["callRef"], c["contextRef"], n, c,
                                ticket_refs=[ticket_ref])
    if (actor["coreActorSub"] != c["sub"] or actor["bindingRef"] != authority["bindingRef"]
            or actor["supportUserRef"] != authority["supportUserRef"]
            or actor["bindingVersion"] != c["bindingVersion"]
            or actor["permissionsVersion"] != c["permissionsVersion"]
            or actor["ticketRefs"] != [ticket_ref]
            or actor["fieldMask"] not in ("assigned_ticket", "vendor")):
        fail(403, "postcall_ticket_denied")
    actions = sorted({"ticket.read", "ticket.append"} & set(actor["capabilities"]))
    if not actions:
        fail(403, "no_capabilities")
    # После HTTP ещё раз проверяем локальный source grant и Core ACL.
    root = await db.scalar(select(ContextGrant).where(ContextGrant.grant_id == root_id)
                           .with_for_update().execution_options(populate_existing=True))
    user, _member, pd = await core_actor(db, c["sub"], c["coreCid"])
    if root is None or root.revoked_at or user.token_version != source_version or pd != source_permissions:
        fail(403, "grant_revoked")
    if root.authority.get("postcallDeadline"):
        if pending:
            fail(403, "postcall_revoked")
        deadline = min(deadline, datetime.fromisoformat(root.authority["postcallDeadline"]))
    if pending:
        if min(deadline, context_exp) <= datetime.now(timezone.utc):
            fail(403, "wrapup_expired")
        # HTTP409 не выдаёт право и не изменяет источник/deadline. DPoP уже
        # durable consumed роутером; следующий запрос требует нового proof.
        await db.commit()
        fail(409, "postcall_pending", retryable=True)
    authority.update(sourceGrantId=root_id, postcallDeadline=min(deadline, context_exp).isoformat(),
                     fieldMask=actor["fieldMask"])
    # Запоминаем hard deadline и на источнике: новый /postcall исходного grantId
    # не может продлить период изменением endedAt или политики.
    root.authority = {**root.authority, "postcallDeadline": authority["postcallDeadline"]}
    c.update(grantId=uuid.uuid4().hex, jti=uuid.uuid4().hex, scp="ticket_postcall", phase="postcall",
             actions=actions, ticketRefs=[ticket_ref])
    return await persist_grant(db, c, authority, source_version, pd, min(deadline, context_exp))


async def current(db, token, *, allow_phase_change=False):
    c = verify(token, "support-context")
    row = await db.get(ContextGrant, c["grantId"], populate_existing=True)
    if row is None or row.revoked_at or row.digest != digest(token) or row.claims != c:
        fail(403, "grant_revoked")
    authority = dict(row.authority)
    if c["scp"] == "ticket_postcall":
        root = await db.get(ContextGrant, authority["sourceGrantId"], populate_existing=True)
        if root is None or root.revoked_at:
            fail(403, "grant_revoked")
    trust, cid, base = await configuration(db, c["coreCid"])
    if cid != c["cid"]:
        fail(403, "company_mapping_changed")
    bound = await binding(db, c["coreCid"], cid, c["callRef"], c["contextRef"])
    context_exp = bound.expires_at
    node = node_for(trust, c["callRef"])
    user, member, permission_digest = await core_actor(db, c["sub"], c["coreCid"])
    if user.token_version != row.token_version or permission_digest != row.permissions_digest:
        fail(403, "core_permissions_changed")
    from app.scope import resolve_object_scope
    object_scope = await resolve_object_scope(user, uuid_or_fail(c["coreCid"]), db)
    organization = (str(member.own_organization_id)
                    if not user.is_superadmin and member.role != "admin" and member.own_organization_id else None)
    token_version = user.token_version
    await db.commit()
    ndata = await json_http(node.admissionBaseUrl + NODE_PREFIX + "/status",
                            service_token("support-context.admission", c["coreCid"], cid, c["callRef"],
                                          nodeId=c["callRef"]["nodeId"], connectorId=c["callRef"]["connectorId"]),
                            envelope(admissionRef=authority["admissionRef"], callRef=c["callRef"],
                                     contextRef=c["contextRef"], connectionId=c["connectionId"], act=c["act"]))
    if c["scp"] == "ticket_postcall":
        n, deadline = check_postcall_node(ndata, trust, c, authority)
        actions, tickets = {"ticket.read", "ticket.append"}, c["ticketRefs"]
        n["phase"] = "postcall"
    else:
        n, actions, deadline, tickets = check_node(ndata, trust, c["callRef"], c["contextRef"], c["cnf"]["jkt"], c)
    if n["admissionRef"] != authority["admissionRef"]:
        fail(403, "admission_changed")
    if (not allow_phase_change and n["phase"] != c["phase"]) or tickets != c["ticketRefs"]:
        fail(409, "phase_changed")
    actor = await actor_resolve(base, c["coreCid"], cid, c["callRef"], c["contextRef"], n, c,
                                ticket_refs=tickets if c["scp"] == "ticket_postcall" else None)
    if any(actor[k] != c[v] for k, v in (("coreActorSub", "sub"), ("bindingVersion", "bindingVersion"),
                                        ("permissionsVersion", "permissionsVersion"))):
        fail(403, "support_permissions_changed")
    if any(actor[k] != authority[k] for k in ("supportUserRef", "bindingRef")):
        fail(403, "support_binding_changed")
    # Только renew допускает закономерную смену live-проекции при новой фазе.
    # Старый access не получает ни новую маску, ни actions: ниже остаётся
    # пересечение с его claims, а выдача требует нового consume + actor-resolve.
    if actor["fieldMask"] != authority["fieldMask"] and not (
        allow_phase_change and c["scp"] == "support_context" and phase_mask_change(
            c["phase"], n["phase"], authority["fieldMask"], actor["fieldMask"])
    ):
        fail(403, "support_binding_changed")
    if tickets and not set(tickets) <= set(actor["ticketRefs"]):
        fail(403, "postcall_ticket_denied")
    actions &= set(actor["capabilities"]) & set(c["actions"])
    if not actions:
        fail(403, "no_capabilities")
    # Повторно читаем Core после HTTP, без lock. Revoke до положительного ответа
    # не теряется из-за snapshot identity-map первого SELECT.
    row = await db.get(ContextGrant, c["grantId"], populate_existing=True)
    user, member, fresh_digest = await core_actor(db, c["sub"], c["coreCid"])
    if row is None or row.revoked_at or user.token_version != token_version or fresh_digest != permission_digest:
        fail(403, "grant_revoked")
    if c["scp"] == "ticket_postcall":
        root = await db.get(ContextGrant, authority["sourceGrantId"], populate_existing=True)
        if root is None or root.revoked_at:
            fail(403, "grant_revoked")
    if min(datetime.fromtimestamp(c["exp"], timezone.utc), deadline, context_exp) <= datetime.now(timezone.utc):
        fail(401, "token_expired")
    await db.commit()
    return c, sorted(actions), min(deadline, context_exp), authority, object_scope, organization


async def introspect(db, service, body):
    s = verify(service, "core-support-context")
    required = {"svc", "coreCid", "cid", "keyId"}
    if (not required <= s.keys() or s["svc"] != "support-context.introspect"
            or s["sub"] != "service:support-context.introspect"):
        fail(401, "invalid_service")
    token = body.token
    c = verify(token, "support-context")
    if body.contextRef != c["contextRef"] or body.callRef.model_dump() != c["callRef"]:
        fail(404, "context_unavailable")
    if any(s[k] != c[k] for k in ("coreCid", "cid")):
        fail(403, "service_binding_mismatch")
    # Именной bootstrap отозван — новые introspection не проходят, включая ранее
    # выпущенный service JWT. Никакого положительного кэша в v1.
    trust, _cid, _base = await configuration(db, c["coreCid"])
    key = await db.get(SpaceInboundKey, uuid_or_fail(trust.introspectionKeyId))
    if (key is None or s["keyId"] != str(key.id) or key.revoked_at or str(key.company_id) != c["coreCid"]
            or "support-context.introspect" not in (key.scopes or [])):
        fail(403, "service_revoked")
    c, actions, deadline, authority, object_scope, organization = await current(db, token)
    return envelope(active=True, grantId=c["grantId"], coreActorSub=c["sub"],
                    supportUserRef=authority["supportUserRef"], bindingRef=authority["bindingRef"],
                    fieldMask=authority["fieldMask"], contextRef=c["contextRef"], callRef=c["callRef"], actions=actions,
                    assignmentVersion=c["assignmentVersion"], bindingVersion=c["bindingVersion"],
                    permissionsVersion=c["permissionsVersion"], phase=c["phase"], ticketRefs=c["ticketRefs"],
                    expiresAt=datetime.fromtimestamp(min(c["exp"], int(deadline.timestamp())), timezone.utc).isoformat(),
                    objectScope=object_scope, ownOrganizationId=organization)
