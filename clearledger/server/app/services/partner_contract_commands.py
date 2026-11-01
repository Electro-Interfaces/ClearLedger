"""Internal same-root partner CREATE consumer; caller alone commits.

Cancellation/errors roll back the whole root. A failed commit has unknown
outcome: new root, same creationKey, fresh bearer verification and CREATE policy.
No native User adapter, audit.log_audit, notifications or background work.
"""
from dataclasses import dataclass, fields
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditEvent, Contract, ContractLocation
from app.models_partner_contracts import (
    PartnerContractSuccessIntent as Intent, PartnerContractIntentLocation as IntentLocation,
)
from app.product_api.contract_create_body import ContractCreateBody
from app.services.contract_card_creation import (
    ContractCardValues, create_contract_card, find_contract_card_duplicates,
)
from app.services.partner_contract_authority import (
    OPERATION, _deny, _one, _require, prepare_create, require_create,
)
from app.services.partner_identity import NO_STORE, now
from app.services.reference_identity import contract_identity


@dataclass(frozen=True, slots=True)
class PartnerContractCreateResult:
    contract_id: UUID
    replayed: bool


async def create_partner_contract(db: AsyncSession, bearer: str,
                                  body: ContractCreateBody) -> PartnerContractCreateResult:
    """Atomic card + locations + immutable intent + intent locations + audit.

    Source caller: ROOT-admitted test composition. There is no HTTP operation
    or activation endpoint in this cut. No returned receipt authorizes a write.
    """
    try:
        admission = await prepare_create(db, bearer, body)
        operation = await db.run_sync(_require, admission, body)
        checked = operation.body
        if operation.previous is not None:
            # Current complete eligibility and original grant/actor/refs have
            # already passed. Hash conflict alone never reveals a hidden intent.
            if operation.previous.request_hash != operation.request_hash:
                raise HTTPException(409, "Creation key has different content", headers=NO_STORE)
            await require_create(db, admission, checked)
            return PartnerContractCreateResult(operation.previous.newborn_id, True)
        identity = contract_identity(checked.number, checked.date, checked.type)
        if identity:
            duplicates = await find_contract_card_duplicates(db, operation.company_id,
                checked.counterpartyId, checked.organizationId, identity)
            await require_create(db, admission, checked)
            if duplicates:
                # IDs/existence of read-hidden contracts are not disclosed.
                raise HTTPException(409, "Contract identity conflicts", headers=NO_STORE)
        values = ContractCardValues(
            company_id=operation.company_id, creation_key=None, creation_actor_id=None,
            creation_request_hash=None, number=checked.number, date=checked.date,
            counterparty_id=checked.counterpartyId, organization_id=checked.organizationId,
            type=checked.type, type_code=checked.typeCode, amount_limit=None, kind=None,
            currency=None, valid_until=checked.validUntil, vat_rate=None, amount_incl_vat=None,
            settlement_kind=None, comment=checked.comment, basis=None, is_closed=False,
            scope_type="locations", signed=None, signed_at=None, payment_term_days=None,
            is_state_contract=None, igk=None, responsible_id=None, signer_our=None,
            signer_our_position=None, signer_cp=None, signer_cp_position=None, signer_cp_basis=None)
        await require_create(db, admission, checked)
        card = await create_contract_card(db, values)  # Parent first; actual FK/flush wait.
        await require_create(db, admission, checked)
        # Adopt only our exact newborn, after current auth. No new parent or B
        # key is discovered: the company RefComposite and legacy matcher guards
        # already cover creation. Native creation columns remain NULL.
        with db.no_autoflush:
            fresh = (await db.execute(select(Contract).where(Contract.id == card.id,
                Contract.company_id == operation.company_id).execution_options(populate_existing=True))).scalar_one()
            if any(getattr(fresh, f.name) != getattr(values, f.name) for f in fields(values)):
                _deny()
            operation.own_contract_id = card.id
            operation.own_card = await db.run_sync(_one, Contract, card.id)
        await require_create(db, admission, checked)
        locations = tuple(sorted(checked.coverage.locationIds))
        db.add_all([ContractLocation(id=uuid4(), company_id=operation.company_id,
            contract_id=card.id, location_id=loc) for loc in locations])
        operation.own_locations = tuple((operation.company_id, loc) for loc in locations)
        await db.flush()
        await require_create(db, admission, checked)
        txid = await db.scalar(text("SELECT pg_current_xact_id()::text"))
        intent = Intent(id=uuid4(), company_id=operation.company_id, app_id=operation.verified.app_id,
            installation_id=operation.installation_id, original_grant_id=operation.verified.grant_id,
            create_profile_id=operation.profile_id, client_id=operation.client_id, operation=OPERATION,
            creation_key=checked.creationKey,
            actor_kind="machine" if operation.verified.is_machine else "user",
            actor_key=operation.client_id if operation.verified.is_machine else str(operation.verified.user_id),
            current_user_id=operation.verified.user_id, newborn_id=card.id, current_contract_id=card.id,
            request_hash=operation.request_hash, hash_version=1,
            created_organization_id=checked.organizationId, created_counterparty_id=checked.counterpartyId,
            created_type_code=checked.typeCode, succeeded=True, created_at=now(), created_txid=txid)
        await require_create(db, admission, checked)
        operation.own_intent_id = intent.id
        operation.expected_receipt = ((tuple(getattr(intent, c.key) for c in Intent.__table__.c),), ())
        db.add(intent)
        await db.flush()  # Intent FK parent precedes immutable location children.
        await require_create(db, admission, checked)
        db.add_all([IntentLocation(intent_id=intent.id, location_id=loc) for loc in locations])
        operation.expected_receipt = (operation.expected_receipt[0], tuple((intent.id, loc) for loc in locations))
        db.add(AuditEvent(id=uuid4(), company_id=operation.company_id,
            user_id=intent.actor_key, user_name=operation.verified.subject,
            action="partner.contract.create", details=json.dumps({"contractId": str(card.id),
                "intentId": str(intent.id), "actorKind": intent.actor_kind}, sort_keys=True)))
        await db.flush()
        await require_create(db, admission, checked)
        return PartnerContractCreateResult(card.id, False)
    except BaseException:
        await db.rollback()
        raise
