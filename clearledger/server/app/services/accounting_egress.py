from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AccountingSourcePolicy, CutoverManifest, ExportPacket
from app.services.accounting_outbox import (
    AccountingOutboxService,
    AccountingRevisionConflict,
)
from app.services.bp_canon import packet_hash
from app.services.store_document_contract import ACCOUNTING_DOCUMENT_KINDS


ACCOUNTING_PACKET_KINDS = (
    "food_accounting_group",
    "store_accounting_group",
)
POLICY_GROUP = "sidegoods_foodservice"
_SCOPE_LOCK_STATEMENT = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
)
_SHIFT_FACT_KINDS = frozenset({
    "retail_sale_sidegoods",
    "production_release",
    "ingredients_writeoff",
    "recipe",
})
_FOOD_DOCUMENT_KINDS = frozenset({
    "production_release",
    "ingredients_writeoff",
    "recipe",
})


class AccountingEgressDenied(ValueError):
    pass


@dataclass(frozen=True)
class AccountingEgressDecision:
    policy_id: uuid.UUID
    revision: int
    manifest_hash: str
    station_id: int
    fact_at_from: datetime
    fact_at_to: datetime


@dataclass(frozen=True)
class AccountingQueueResult:
    packet: ExportPacket
    created: bool
    decision: AccountingEgressDecision


def _utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise AccountingEgressDenied("Время policy/manifest должно содержать timezone")
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_fact_at(value: object, field: str) -> datetime:
    raw = str(value or "").strip()
    if not raw:
        raise AccountingEgressDenied(f"Не заполнено время хозяйственного факта: {field}")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AccountingEgressDenied(f"Некорректное время хозяйственного факта: {field}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AccountingEgressDenied(f"Время хозяйственного факта без timezone: {field}")
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def canonical_manifest_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def manifest_payload_for_policy(
    policy: AccountingSourcePolicy,
    *,
    approvals: list[dict],
    operational_cutover_at: datetime,
    accounting_transport_cutover_at: datetime,
    late_arrival_until: datetime | None = None,
    arm_deadline: datetime | None = None,
) -> dict:
    return {
        "policy_id": str(policy.id),
        "revision": policy.revision,
        "policy_group": policy.policy_group,
        "company_id": str(policy.company_id),
        "station_id": policy.station_id,
        "intervals": [{
            "effective_from": _utc_iso(policy.effective_from),
            "effective_to": _utc_iso(policy.effective_to),
            "transport_producer": policy.transport_producer,
        }],
        "operational_cutover_at": _utc_iso(operational_cutover_at),
        "accounting_transport_cutover_at": _utc_iso(accounting_transport_cutover_at),
        "late_arrival_until": _utc_iso(late_arrival_until),
        "arm_deadline": _utc_iso(arm_deadline),
        "approvals": approvals,
    }


def accounting_packet_kind(packet: dict) -> str:
    documents = packet.get("Документы") or []
    for document in documents:
        kind = str(document.get("Тип") or "")
        if kind in _FOOD_DOCUMENT_KINDS:
            return "food_accounting_group"
        if kind == "retail_sale_sidegoods" and any(
            bool(line.get("ЭтоБлюдо")) for line in (document.get("Товары") or [])
        ):
            return "food_accounting_group"
    return "store_accounting_group"


def accounting_packet_station(packet: dict) -> int:
    shift = packet.get("Смена") or {}
    raw_station = str(shift.get("КодАЗС") or "").strip()
    if not raw_station.isdigit():
        raise AccountingEgressDenied("Пакет не содержит числовой КодАЗС")
    return int(raw_station)


def _packet_fact_times(packet: dict) -> list[datetime]:
    shift = packet.get("Смена") or {}
    documents = packet.get("Документы") or []
    if not documents:
        raise AccountingEgressDenied("Пустая бухгалтерская группа не ставится в очередь")
    shift_fact_at = shift.get("Закрытие") or shift.get("Открытие")
    fact_times = []
    for index, document in enumerate(documents):
        kind = str(document.get("Тип") or "").strip()
        if not kind:
            raise AccountingEgressDenied(f"Документ {index + 1} не содержит Тип")
        if kind not in ACCOUNTING_DOCUMENT_KINDS:
            raise AccountingEgressDenied(
                f"Тип документа {kind} не разрешён для бухгалтерской группы сопутки/общепита"
            )
        raw_fact_at = shift_fact_at if kind in _SHIFT_FACT_KINDS else document.get("Дата")
        fact_times.append(_parse_fact_at(raw_fact_at, f"Документы[{index}].{kind}"))
    return fact_times


def _assert_no_overlaps(policies: list[AccountingSourcePolicy]) -> None:
    ordered = sorted(policies, key=lambda item: item.effective_from)
    for previous, current in zip(ordered, ordered[1:]):
        if previous.effective_to is None or current.effective_from < previous.effective_to:
            raise AccountingEgressDenied("Обнаружены перекрывающиеся AccountingSourcePolicy")


def _approval_identities(approvals: list) -> set[str]:
    identities = set()
    for approval in approvals:
        if not isinstance(approval, dict) or not approval.get("approved_at"):
            continue
        identity = str(approval.get("approver_id") or "").strip()
        if identity:
            identities.add(identity)
    return identities


class AccountingEgressGuard:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    @staticmethod
    def deny_direct_file_write() -> None:
        raise AccountingEgressDenied(
            "Прямая запись бухгалтерского пакета в файл запрещена; используйте guarded queue"
        )

    async def _lock_scope(self, station_id: int) -> None:
        scope_key = f"{self.company_id}:{station_id}:{POLICY_GROUP}"
        await self.session.execute(
            _SCOPE_LOCK_STATEMENT, {"scope_key": scope_key},
        )

    async def authorize_packet(
        self,
        packet: dict,
        requested_manifest_hash: str | None,
    ) -> AccountingEgressDecision:
        if str(packet.get("ВерсияФормата") or "") != "3":
            raise AccountingEgressDenied(
                "Central Ledger может ставить в бухгалтерскую очередь только контракт v3"
            )
        if not requested_manifest_hash:
            raise AccountingEgressDenied("Не передан manifest_hash effective-policy")
        declared_hash = str(packet.get("ХешПакета") or "").strip().lower()
        actual_hash = packet_hash(packet)
        if not declared_hash or declared_hash != actual_hash:
            raise AccountingEgressDenied("ХешПакета не совпадает с каноническим содержимым")

        station_id = accounting_packet_station(packet)
        await self._lock_scope(station_id)
        fact_times = _packet_fact_times(packet)
        policies = (await self.session.execute(
            select(AccountingSourcePolicy).where(
                AccountingSourcePolicy.company_id == self.company_id,
                AccountingSourcePolicy.station_id == station_id,
                AccountingSourcePolicy.policy_group == POLICY_GROUP,
            ).order_by(AccountingSourcePolicy.effective_from).with_for_update()
        )).scalars().all()
        _assert_no_overlaps(policies)

        matched = []
        for fact_at in fact_times:
            candidates = [
                policy for policy in policies
                if policy.effective_from <= fact_at
                and (policy.effective_to is None or fact_at < policy.effective_to)
            ]
            if len(candidates) != 1:
                raise AccountingEgressDenied(
                    "Для хозяйственного факта отсутствует однозначная effective-policy"
                )
            matched.append(candidates[0])
        policy = matched[0]
        if any(item.id != policy.id for item in matched[1:]):
            raise AccountingEgressDenied("Пакет пересекает интервалы AccountingSourcePolicy")
        if policy.transport_producer != "central_ledger":
            raise AccountingEgressDenied("Effective-policy оставляет транспорт за legacy_epf")

        manifests = (await self.session.execute(
            select(CutoverManifest).where(CutoverManifest.policy_id == policy.id)
            .with_for_update()
        )).scalars().all()
        if len(manifests) != 1:
            raise AccountingEgressDenied("Для effective-policy отсутствует однозначный CutoverManifest")
        manifest = manifests[0]
        if str(packet.get("ИдентификаторПолитики") or "") != str(policy.id):
            raise AccountingEgressDenied("ИдентификаторПолитики пакета не совпадает с policy")
        if packet.get("РевизияПолитики") != policy.revision:
            raise AccountingEgressDenied("РевизияПолитики пакета не совпадает с policy")
        if str(packet.get("ХешПолитики") or "") != manifest.manifest_hash:
            raise AccountingEgressDenied("ХешПолитики пакета не совпадает с manifest")
        self._validate_manifest(manifest, policy, requested_manifest_hash, min(fact_times))
        return AccountingEgressDecision(
            policy_id=policy.id,
            revision=policy.revision,
            manifest_hash=manifest.manifest_hash,
            station_id=station_id,
            fact_at_from=min(fact_times),
            fact_at_to=max(fact_times),
        )

    def _validate_manifest(
        self,
        manifest: CutoverManifest,
        policy: AccountingSourcePolicy,
        requested_manifest_hash: str,
        first_fact_at: datetime,
    ) -> None:
        if manifest.state != "effective":
            raise AccountingEgressDenied("CutoverManifest не находится в состоянии effective")
        if manifest.company_id != self.company_id or manifest.station_id != policy.station_id:
            raise AccountingEgressDenied("Scope CutoverManifest не совпадает с policy")
        if manifest.policy_group != policy.policy_group or manifest.revision != policy.revision:
            raise AccountingEgressDenied("Revision CutoverManifest не совпадает с policy")
        if requested_manifest_hash != manifest.manifest_hash:
            raise AccountingEgressDenied("manifest_hash запроса не совпадает с effective manifest")
        if canonical_manifest_hash(manifest.canonical_payload) != manifest.manifest_hash:
            raise AccountingEgressDenied("Содержимое CutoverManifest не совпадает с manifest_hash")
        if manifest.prepare_ack_hash != manifest.manifest_hash:
            raise AccountingEgressDenied("Нет exact prepare_ack для CutoverManifest")
        if manifest.arm_ack_hash != manifest.manifest_hash:
            raise AccountingEgressDenied("Нет exact arm_ack для CutoverManifest")
        if len(_approval_identities(manifest.approvals or [])) < 2:
            raise AccountingEgressDenied("CutoverManifest не подтверждён двумя разными лицами")
        if (manifest.canonical_payload or {}).get("approvals") != (manifest.approvals or []):
            raise AccountingEgressDenied("Approvals CutoverManifest не совпадают с canonical payload")
        expected = manifest_payload_for_policy(
            policy,
            approvals=manifest.approvals or [],
            operational_cutover_at=manifest.operational_cutover_at,
            accounting_transport_cutover_at=manifest.accounting_transport_cutover_at,
            late_arrival_until=manifest.late_arrival_until,
            arm_deadline=manifest.arm_deadline,
        )
        if manifest.canonical_payload != expected:
            raise AccountingEgressDenied("CutoverManifest не описывает exact policy interval")
        now = datetime.now(timezone.utc)
        if manifest.arm_deadline is None:
            raise AccountingEgressDenied("Effective CutoverManifest не содержит arm_deadline")
        if manifest.armed_at is None:
            raise AccountingEgressDenied("Effective CutoverManifest не содержит armed_at")
        if manifest.effective_at is None:
            raise AccountingEgressDenied("Effective CutoverManifest не содержит effective_at")
        for field, value in (
            ("arm_deadline", manifest.arm_deadline),
            ("armed_at", manifest.armed_at),
            ("effective_at", manifest.effective_at),
        ):
            if value.tzinfo is None or value.utcoffset() is None:
                raise AccountingEgressDenied(f"{field} CutoverManifest не содержит timezone")
        if manifest.armed_at > manifest.arm_deadline:
            raise AccountingEgressDenied("CutoverManifest armed после arm_deadline")
        if manifest.effective_at < manifest.accounting_transport_cutover_at:
            raise AccountingEgressDenied("CutoverManifest effective раньше accounting cutover")
        if manifest.effective_at > now:
            raise AccountingEgressDenied("CutoverManifest effective_at находится в будущем")
        if manifest.accounting_transport_cutover_at > now:
            raise AccountingEgressDenied("Accounting transport cutover ещё не наступил")
        if first_fact_at < manifest.accounting_transport_cutover_at:
            raise AccountingEgressDenied("Факт относится к периоду до accounting transport cutover")
        if manifest.accounting_transport_cutover_at != policy.effective_from:
            raise AccountingEgressDenied("Граница manifest не совпадает с effective_from policy")

    async def queue_packet(
        self,
        packet: dict,
        requested_manifest_hash: str | None,
    ) -> AccountingQueueResult:
        decision = await self.authorize_packet(packet, requested_manifest_hash)
        from app.services.store_receipt_accounting import (
            ReceiptAccountingError,
            assert_purchase_documents_ready,
        )
        try:
            try:
                uuid.UUID(str(packet.get("ИдентификаторПакета") or ""))
            except ValueError as exc:
                raise AccountingRevisionConflict(
                    "ИдентификаторПакета должен быть корректным UUID"
                ) from exc
            await assert_purchase_documents_ready(self.session, self.company_id, packet)
            outbox = AccountingOutboxService(self.session, self.company_id)
            revision = await outbox.append_validated_revision(
                packet, accounting_packet_kind(packet),
            )
            if revision.row.status == "validated":
                revision.row.status = "queued"
                await self.session.flush()
        except (AccountingRevisionConflict, ReceiptAccountingError) as exc:
            raise AccountingEgressDenied(str(exc)) from exc
        return AccountingQueueResult(revision.row, revision.created, decision)
