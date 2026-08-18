from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountingSourcePolicy, CutoverApproval, CutoverManifest
from app.services.accounting_contract_v3 import canonical_hash


POLICY_GROUP = "sidegoods_foodservice"
DEFAULT_STATION_TIMEZONE = "Europe/Moscow"
_SCOPE_LOCK = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
)


class CutoverPolicyError(ValueError):
    def __init__(self, detail: str, status_code: int = 409):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


@dataclass(frozen=True)
class CutoverAxesDecision:
    fact_origin: str
    transport_producer: str


def _aware_utc(value: datetime, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CutoverPolicyError(f"{field} должен содержать timezone")
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _utc_iso(value: datetime) -> str:
    return _aware_utc(value, "datetime").isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _station_zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise CutoverPolicyError(f"Неизвестный timezone станции: {name}") from exc


def operational_cutover_utc(business_date: date, station_timezone: str) -> datetime:
    zone = _station_zone(station_timezone)
    return datetime.combine(business_date, time.min, tzinfo=zone).astimezone(
        timezone.utc
    )


def canonical_manifest_hash(payload: dict) -> str:
    return canonical_hash(payload)


def manifest_payload_for_policy(
    policy: AccountingSourcePolicy,
) -> dict:
    fact_date = getattr(policy, "fact_cutover_business_date", None)
    station_timezone = (
        getattr(policy, "station_timezone", None) or DEFAULT_STATION_TIMEZONE
    )
    if fact_date is None:
        raise CutoverPolicyError("Не задан fact cutover по BusinessDate")
    transport_cutover = getattr(policy, "transport_cutover_at", None)
    if transport_cutover is None:
        raise CutoverPolicyError("Не задан transport cutover по delivery time")
    return {
        "schema": "ledger-tradeledger-cutover-policy/v1",
        "policy_id": str(policy.id),
        "revision": policy.revision,
        "policy_group": policy.policy_group,
        "company_id": str(policy.company_id),
        "station_id": policy.station_id,
        "fact_rule": {
            "station_timezone": station_timezone,
            "business_date_cutover": fact_date.isoformat(),
            "before": getattr(policy, "fact_origin_before", None) or "onec_legacy",
            "on_or_after": getattr(policy, "fact_origin_after", None) or "edge",
        },
        "transport_rule": {
            "delivery_cutover_at": _utc_iso(transport_cutover),
            "before": (
                getattr(policy, "transport_producer_before", None) or "legacy_epf"
            ),
            "on_or_after": policy.transport_producer,
        },
        "allowed_transport_producer": policy.transport_producer,
        "shadow_validation_enabled": bool(policy.shadow_validation_enabled),
    }


def decide_policy_axes(
    policy: AccountingSourcePolicy,
    *,
    business_date: date,
    delivery_at: datetime,
    existing_fact_origin: str | None = None,
) -> CutoverAxesDecision:
    if existing_fact_origin is not None:
        if existing_fact_origin not in {"edge", "onec_legacy"}:
            raise CutoverPolicyError("Существующий FactOrigin недопустим")
        fact_origin = existing_fact_origin
    else:
        fact_origin = (
            policy.fact_origin_after
            if business_date >= policy.fact_cutover_business_date
            else policy.fact_origin_before
        )
    delivered = _aware_utc(delivery_at, "delivery_at")
    transport_cutover = _aware_utc(
        policy.transport_cutover_at, "transport_cutover_at"
    )
    producer = (
        policy.transport_producer
        if delivered >= transport_cutover
        else policy.transport_producer_before
    )
    return CutoverAxesDecision(fact_origin, producer)


def trusted_manifest_export(
    manifest: CutoverManifest,
    approvals: list[CutoverApproval],
) -> dict:
    ordered = sorted(approvals, key=lambda row: (row.approved_at, str(row.user_id)))
    payload = manifest.canonical_payload
    return {
        "policy": payload,
        "policy_hash": manifest.manifest_hash,
        "state": manifest.state,
        "approvals": [
            {
                "user_id": str(row.user_id),
                "approved_at": _utc_iso(row.approved_at),
            }
            for row in ordered
        ],
        "prepared_ack_hash": manifest.prepare_ack_hash,
        "armed_ack_hash": manifest.arm_ack_hash,
        "armed_at": _utc_iso(manifest.armed_at) if manifest.armed_at else None,
        "effective_at": (
            _utc_iso(manifest.effective_at) if manifest.effective_at else None
        ),
    }


class CutoverPolicyService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    async def _lock_scope(self, station_id: int) -> None:
        await self.session.execute(
            _SCOPE_LOCK,
            {
                "scope_key": (
                    f"{self.company_id}:{station_id}:{POLICY_GROUP}"
                )
            },
        )

    async def _manifest_under_lock(
        self, manifest_id: uuid.UUID, station_id: int | None = None
    ) -> CutoverManifest:
        probe = (await self.session.execute(
            select(CutoverManifest).where(
                CutoverManifest.id == manifest_id,
                CutoverManifest.company_id == self.company_id,
            )
        )).scalars().first()
        if probe is None:
            raise CutoverPolicyError("Cutover manifest не найден", 404)
        if station_id is not None and probe.station_id != station_id:
            raise CutoverPolicyError("Cutover manifest не найден", 404)
        await self._lock_scope(probe.station_id)
        manifest = (await self.session.execute(
            select(CutoverManifest).where(
                CutoverManifest.id == manifest_id,
                CutoverManifest.company_id == self.company_id,
            ).with_for_update()
        )).scalars().first()
        if manifest is None:
            raise CutoverPolicyError("Cutover manifest не найден", 404)
        return manifest

    async def _policy_under_lock(
        self, manifest: CutoverManifest
    ) -> AccountingSourcePolicy:
        policy = (await self.session.execute(
            select(AccountingSourcePolicy).where(
                AccountingSourcePolicy.id == manifest.policy_id,
                AccountingSourcePolicy.company_id == self.company_id,
                AccountingSourcePolicy.station_id == manifest.station_id,
            ).with_for_update()
        )).scalars().first()
        if policy is None:
            raise CutoverPolicyError("Policy для manifest не найдена", 404)
        return policy

    async def _approvals(
        self, manifest_id: uuid.UUID, *, for_update: bool = False
    ) -> list[CutoverApproval]:
        statement = select(CutoverApproval).where(
            CutoverApproval.manifest_id == manifest_id,
            CutoverApproval.company_id == self.company_id,
        ).order_by(CutoverApproval.approved_at, CutoverApproval.user_id)
        if for_update:
            statement = statement.with_for_update()
        return (await self.session.execute(statement)).scalars().all()

    async def prepare(
        self,
        *,
        station_id: int,
        fact_cutover_business_date: date,
        transport_cutover_at: datetime,
        station_timezone: str = DEFAULT_STATION_TIMEZONE,
        arm_deadline: datetime | None = None,
        shadow_validation_enabled: bool = True,
    ) -> tuple[AccountingSourcePolicy, CutoverManifest]:
        _station_zone(station_timezone)
        transport_cutover_at = _aware_utc(
            transport_cutover_at, "transport_cutover_at"
        )
        if arm_deadline is None:
            arm_deadline = transport_cutover_at - timedelta(minutes=5)
        arm_deadline = _aware_utc(arm_deadline, "arm_deadline")
        if arm_deadline >= transport_cutover_at:
            raise CutoverPolicyError("arm_deadline должен быть раньше transport cutover")

        await self._lock_scope(station_id)
        policies = (await self.session.execute(
            select(AccountingSourcePolicy).where(
                AccountingSourcePolicy.company_id == self.company_id,
                AccountingSourcePolicy.station_id == station_id,
                AccountingSourcePolicy.policy_group == POLICY_GROUP,
            ).order_by(AccountingSourcePolicy.revision).with_for_update()
        )).scalars().all()
        active_candidates = [
            row for row in policies if row.state in {"prepared", "approved", "armed"}
        ]
        if active_candidates:
            raise CutoverPolicyError("Для станции уже подготовлен незавершённый cutover")
        revision = max((row.revision for row in policies), default=0) + 1
        policy = AccountingSourcePolicy(
            company_id=self.company_id,
            station_id=station_id,
            policy_group=POLICY_GROUP,
            revision=revision,
            state="prepared",
            fact_cutover_business_date=fact_cutover_business_date,
            station_timezone=station_timezone,
            fact_origin_before="onec_legacy",
            fact_origin_after="edge",
            effective_from=transport_cutover_at,
            effective_to=None,
            transport_cutover_at=transport_cutover_at,
            transport_producer_before="legacy_epf",
            transport_producer="central_ledger",
            shadow_validation_enabled=shadow_validation_enabled,
        )
        self.session.add(policy)
        await self.session.flush()
        payload = manifest_payload_for_policy(policy)
        manifest_hash = canonical_manifest_hash(payload)
        manifest = CutoverManifest(
            policy_id=policy.id,
            company_id=self.company_id,
            station_id=station_id,
            policy_group=POLICY_GROUP,
            revision=revision,
            state="prepared",
            canonical_payload=payload,
            manifest_hash=manifest_hash,
            approvals=[],
            operational_cutover_at=operational_cutover_utc(
                fact_cutover_business_date, station_timezone
            ),
            accounting_transport_cutover_at=transport_cutover_at,
            late_arrival_until=None,
            arm_deadline=arm_deadline,
            prepare_ack_hash=manifest_hash,
        )
        self.session.add(manifest)
        await self.session.flush()
        return policy, manifest

    async def approve(
        self, manifest_id: uuid.UUID, user_id: uuid.UUID, approved_at: datetime,
        *, station_id: int | None = None,
    ) -> tuple[CutoverManifest, list[CutoverApproval], bool]:
        manifest = await self._manifest_under_lock(manifest_id, station_id)
        policy = await self._policy_under_lock(manifest)
        approvals = await self._approvals(manifest.id, for_update=True)
        if any(row.user_id == user_id for row in approvals):
            if manifest.state not in {"prepared", "approved"}:
                raise CutoverPolicyError(
                    f"Повтор approval недопустим из состояния {manifest.state}"
                )
            return manifest, approvals, False
        if manifest.state not in {"prepared", "approved"}:
            raise CutoverPolicyError(
                f"Approval недопустим из состояния {manifest.state}"
            )
        approval = CutoverApproval(
            manifest_id=manifest.id,
            company_id=self.company_id,
            user_id=user_id,
            approved_at=_aware_utc(approved_at, "approved_at"),
        )
        self.session.add(approval)
        await self.session.flush()
        approvals = await self._approvals(manifest.id, for_update=True)
        if len({row.user_id for row in approvals}) >= 2:
            manifest.state = "approved"
            policy.state = "approved"
        await self.session.flush()
        return manifest, approvals, True

    async def arm(
        self, manifest_id: uuid.UUID, manifest_hash: str, armed_at: datetime,
        *, station_id: int | None = None,
    ) -> tuple[AccountingSourcePolicy, CutoverManifest, list[CutoverApproval]]:
        manifest = await self._manifest_under_lock(manifest_id, station_id)
        policy = await self._policy_under_lock(manifest)
        approvals = await self._approvals(manifest.id, for_update=True)
        if manifest.state != "approved":
            raise CutoverPolicyError(f"Arm недопустим из состояния {manifest.state}")
        if manifest_hash != manifest.manifest_hash:
            raise CutoverPolicyError("Arm hash не совпадает с trusted manifest")
        if len({row.user_id for row in approvals}) < 2:
            raise CutoverPolicyError("Для arm нужны два разных согласующих")
        armed_at = _aware_utc(armed_at, "armed_at")
        if manifest.arm_deadline is None or armed_at > manifest.arm_deadline:
            raise CutoverPolicyError("Истёк arm_deadline")
        manifest.state = "armed"
        manifest.arm_ack_hash = manifest_hash
        manifest.armed_at = armed_at
        policy.state = "armed"
        await self.session.flush()
        return policy, manifest, approvals

    async def make_effective(
        self, manifest_id: uuid.UUID, manifest_hash: str, effective_at: datetime,
        *, station_id: int | None = None,
    ) -> tuple[AccountingSourcePolicy, CutoverManifest, list[CutoverApproval]]:
        manifest = await self._manifest_under_lock(manifest_id, station_id)
        policy = await self._policy_under_lock(manifest)
        approvals = await self._approvals(manifest.id, for_update=True)
        if manifest.state != "armed":
            raise CutoverPolicyError(
                f"Effective недопустим из состояния {manifest.state}"
            )
        if manifest_hash != manifest.manifest_hash:
            raise CutoverPolicyError("Effective hash не совпадает с trusted manifest")
        if len({row.user_id for row in approvals}) < 2:
            raise CutoverPolicyError("Для effective нужны два разных согласующих")
        effective_at = _aware_utc(effective_at, "effective_at")
        if effective_at < policy.transport_cutover_at:
            raise CutoverPolicyError("Transport cutover ещё не наступил")

        policies = (await self.session.execute(
            select(AccountingSourcePolicy).where(
                AccountingSourcePolicy.company_id == self.company_id,
                AccountingSourcePolicy.station_id == policy.station_id,
                AccountingSourcePolicy.policy_group == policy.policy_group,
            ).order_by(AccountingSourcePolicy.revision).with_for_update()
        )).scalars().all()
        previous = [
            row for row in policies
            if row.id != policy.id and row.state == "effective"
            and row.effective_to is None
        ]
        if len(previous) > 1:
            raise CutoverPolicyError("Найдено несколько открытых effective policy")
        if previous:
            if previous[0].effective_from >= policy.transport_cutover_at:
                raise CutoverPolicyError("Новая policy пересекает действующую")
            previous[0].effective_to = policy.transport_cutover_at
            await self.session.flush()
        manifest.state = "effective"
        manifest.effective_at = effective_at
        policy.state = "effective"
        await self.session.flush()
        return policy, manifest, approvals

    async def export_manifest(
        self, manifest_id: uuid.UUID, *, station_id: int | None = None
    ) -> tuple[CutoverManifest, list[CutoverApproval], dict]:
        manifest = await self._manifest_under_lock(manifest_id, station_id)
        approvals = await self._approvals(manifest.id)
        if canonical_manifest_hash(manifest.canonical_payload) != manifest.manifest_hash:
            raise CutoverPolicyError("Trusted manifest повреждён")
        return manifest, approvals, trusted_manifest_export(manifest, approvals)
