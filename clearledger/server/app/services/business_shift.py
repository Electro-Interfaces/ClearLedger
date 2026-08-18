from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingBusinessGroup,
    AccountingSourceDecision,
    BusinessShift,
    BusinessShiftAlias,
)
from app.services.accounting_contract_v3 import (
    AccountingContractError,
    accounting_packet_uuid,
    alias_hash,
    business_key_hash,
)


_ALIAS_FIELDS = {
    "business-shift-alias-v1": {
        "company_id", "station_id", "internal_shift_no", "business_date",
    },
    "business-shift-common-alias-v1": {
        "company_id", "station_id", "ose", "business_date",
    },
}
_FACT_ORIGINS = {"edge", "onec_legacy"}
_ALIAS_LOCK = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
)


class BusinessShiftConflict(ValueError):
    pass


@dataclass(frozen=True)
class BusinessShiftResolution:
    shift: BusinessShift | None
    group: AccountingBusinessGroup | None
    decision: AccountingSourceDecision
    created: bool

    @property
    def needs_review(self) -> bool:
        return self.decision.status == "needs_review"


def _business_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError as exc:
        raise BusinessShiftConflict("BusinessDate должен быть YYYY-MM-DD") from exc
    if parsed.isoformat() != str(value):
        raise BusinessShiftConflict("BusinessDate должен быть YYYY-MM-DD")
    return parsed


def _validated_aliases(
    aliases: list[dict],
    *,
    company_key: str,
    station_id: str,
    business_date: date,
) -> list[dict]:
    if not aliases:
        raise BusinessShiftConflict("BusinessShiftAliases не может быть пустым")
    result = []
    seen = set()
    for item in aliases:
        algorithm = str(item.get("Algorithm") or "")
        required = _ALIAS_FIELDS.get(algorithm)
        if required is None:
            raise BusinessShiftConflict("Неизвестный алгоритм алиаса смены")
        attributes = item.get("Attributes")
        if not isinstance(attributes, dict) or set(attributes) != required:
            raise BusinessShiftConflict(
                f"Некорректные Attributes для {algorithm}"
            )
        if str(attributes["company_id"]) != company_key:
            raise BusinessShiftConflict("company_id алиаса не совпадает с CompanyID")
        if str(attributes["station_id"]) != station_id:
            raise BusinessShiftConflict("station_id алиаса не совпадает с StationID")
        if str(attributes["business_date"]) != business_date.isoformat():
            raise BusinessShiftConflict(
                "business_date алиаса не совпадает с BusinessDate"
            )
        try:
            calculated = alias_hash(algorithm, attributes)
        except AccountingContractError as exc:
            raise BusinessShiftConflict(str(exc)) from exc
        supplied = str(item.get("AliasHash") or "").lower()
        if supplied != calculated:
            raise BusinessShiftConflict("AliasHash не совпадает с Attributes")
        key = (algorithm, supplied)
        if key in seen:
            raise BusinessShiftConflict("BusinessShiftAliases содержит дубль")
        seen.add(key)
        result.append({
            "Algorithm": algorithm,
            "AliasHash": supplied,
            "Attributes": attributes,
        })
    return sorted(result, key=lambda row: (row["Algorithm"], row["AliasHash"]))


class BusinessShiftResolver:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    async def resolve(
        self,
        *,
        company_key: str,
        station_id: str | int,
        business_date: date | str,
        aliases: list[dict],
        winner_fact_id: str | None,
        loser_fact_ids: list[str] | None,
        fact_origin: str | None,
        reason: str,
        shadow_status: str = "not_applicable",
        policy_id: uuid.UUID | None = None,
        policy_revision: int | None = None,
        policy_hash: str | None = None,
        manifest_id: uuid.UUID | None = None,
        manifest_hash: str | None = None,
    ) -> BusinessShiftResolution:
        station_key = str(station_id)
        day = _business_date(business_date)
        checked = _validated_aliases(
            aliases,
            company_key=company_key,
            station_id=station_key,
            business_date=day,
        )
        if fact_origin is not None and fact_origin not in _FACT_ORIGINS:
            raise BusinessShiftConflict("FactOrigin должен быть edge|onec_legacy")

        for alias in checked:
            await self.session.execute(_ALIAS_LOCK, {
                "scope_key": (
                    f"business-shift-alias:{self.company_id}:"
                    f"{alias['Algorithm']}:{alias['AliasHash']}"
                ),
            })

        conditions = [
            and_(
                BusinessShiftAlias.algorithm == alias["Algorithm"],
                BusinessShiftAlias.alias_hash == alias["AliasHash"],
            )
            for alias in checked
        ]
        existing_aliases = (await self.session.execute(
            select(BusinessShiftAlias).where(
                BusinessShiftAlias.company_id == self.company_id,
                or_(*conditions),
            ).with_for_update()
        )).scalars().all()
        shift_ids = sorted(
            {row.business_shift_id for row in existing_aliases}, key=str,
        )
        shifts = []
        if shift_ids:
            shifts = (await self.session.execute(
                select(BusinessShift).where(
                    BusinessShift.company_id == self.company_id,
                    BusinessShift.id.in_(shift_ids),
                ).with_for_update()
            )).scalars().all()

        if len(shift_ids) > 1:
            for shift in shifts:
                shift.status = "needs_review"
            decision = self._decision(
                None, checked, winner_fact_id, loser_fact_ids, fact_origin,
                policy_id, policy_revision, policy_hash, manifest_id,
                manifest_hash, reason, "blocked", "needs_review", shift_ids,
            )
            self.session.add(decision)
            await self.session.flush()
            return BusinessShiftResolution(None, None, decision, False)

        created = False
        if shifts:
            shift = shifts[0]
            if (
                shift.company_key != company_key
                or shift.station_id != station_key
                or shift.business_date != day
            ):
                shift.status = "needs_review"
                decision = self._decision(
                    shift, checked, winner_fact_id, loser_fact_ids, fact_origin,
                    policy_id, policy_revision, policy_hash, manifest_id,
                    manifest_hash, reason, "blocked", "needs_review", [shift.id],
                )
                self.session.add(decision)
                await self.session.flush()
                return BusinessShiftResolution(shift, None, decision, False)
        else:
            shift = BusinessShift(
                id=uuid.uuid4(), company_id=self.company_id,
                company_key=company_key, station_id=station_key,
                business_date=day, status="resolved",
            )
            self.session.add(shift)
            await self.session.flush()
            created = True

        existing_keys = {
            (row.algorithm, row.alias_hash) for row in existing_aliases
        }
        for alias in checked:
            key = (alias["Algorithm"], alias["AliasHash"])
            if key in existing_keys:
                continue
            self.session.add(BusinessShiftAlias(
                id=uuid.uuid4(), company_id=self.company_id,
                business_shift_id=shift.id, algorithm=alias["Algorithm"],
                alias_hash=alias["AliasHash"], attributes=alias["Attributes"],
            ))

        group = (await self.session.execute(
            select(AccountingBusinessGroup).where(
                AccountingBusinessGroup.company_id == self.company_id,
                AccountingBusinessGroup.business_shift_id == shift.id,
            ).with_for_update()
        )).scalars().first()
        if group is None:
            group = AccountingBusinessGroup(
                id=uuid.uuid4(), company_id=self.company_id,
                business_shift_id=shift.id,
                business_key_hash=business_key_hash(
                    shift.id, company_key, station_key,
                ),
                packet_uuid=accounting_packet_uuid(shift.id),
                status="active",
            )
            self.session.add(group)

        decision = self._decision(
            shift, checked, winner_fact_id, loser_fact_ids, fact_origin,
            policy_id, policy_revision, policy_hash, manifest_id, manifest_hash,
            reason, shadow_status, "resolved", [shift.id],
        )
        self.session.add(decision)
        await self.session.flush()
        return BusinessShiftResolution(shift, group, decision, created)

    def _decision(
        self,
        shift: BusinessShift | None,
        aliases: list[dict],
        winner_fact_id: str | None,
        loser_fact_ids: list[str] | None,
        fact_origin: str | None,
        policy_id: uuid.UUID | None,
        policy_revision: int | None,
        policy_hash: str | None,
        manifest_id: uuid.UUID | None,
        manifest_hash: str | None,
        reason: str,
        shadow_status: str,
        status: str,
        candidates: list[uuid.UUID],
    ) -> AccountingSourceDecision:
        return AccountingSourceDecision(
            id=uuid.uuid4(), company_id=self.company_id,
            business_shift_id=shift.id if shift is not None else None,
            candidate_business_shift_ids=[str(item) for item in candidates],
            winner_fact_id=winner_fact_id,
            loser_fact_ids=list(loser_fact_ids or []), fact_origin=fact_origin,
            policy_id=policy_id, policy_revision=policy_revision,
            policy_hash=policy_hash, manifest_id=manifest_id,
            manifest_hash=manifest_hash, reason=reason,
            shadow_status=shadow_status, status=status, aliases=aliases,
        )
