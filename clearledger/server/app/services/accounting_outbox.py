from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    AccountingBusinessGroup,
    AccountingClaimRequest,
    BusinessShift,
    ExportPacket,
    DataEntry,
)
from app.services.accounting_contract_v3 import (
    AccountingContractError,
    ack_hash,
    accounting_packet_uuid,
    business_key_hash,
    business_projection_hash,
    claim_request_hash,
    validate_ack_v3,
    validate_top_level_v3,
)


ACCOUNTING_KINDS = (
    "food_accounting_group",
    "store_accounting_group",
)
FACT_ORIGINS = (
    "edge",
    "store",
    "onec_legacy",
    "edo",
    "cash",
)
ACCOUNTING_FSM = {
    "draft": frozenset({"validated"}),
    "validated": frozenset({"queued", "retry_wait"}),
    "queued": frozenset({"leased"}),
    "retry_wait": frozenset({"leased"}),
    "leased": frozenset({"sent_waiting_ack", "retry_wait"}),
    "sent_waiting_ack": frozenset({
        "accepted", "rejected", "blocked_mapping", "retry_wait", "needs_review",
    }),
    "blocked_mapping": frozenset({"leased"}),
    "accepted": frozenset(),
    "rejected": frozenset(),
    "needs_review": frozenset(),
}
TERMINAL_ACCOUNTING_STATUSES = frozenset({
    "accepted", "rejected", "needs_review",
})
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_CANONICAL_LOCK = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
)
_OUTBOX_LOCK = text(
    "SELECT pg_advisory_xact_lock(hashtextextended(:scope_key, 0))"
)


class AccountingRevisionConflict(ValueError):
    pass


@dataclass(frozen=True)
class RevisionResult:
    row: DataEntry | ExportPacket
    created: bool


@dataclass(frozen=True)
class ClaimResult:
    consumer_id: str
    claim_request_id: uuid.UUID
    attempt_id: uuid.UUID | None
    packet: ExportPacket | None
    lease_until: datetime | None
    created: bool


def _hash64(value: object, field: str) -> str:
    result = str(value or "").strip().lower()
    if result.startswith("sha256:"):
        result = result[7:]
    if not _HASH_RE.fullmatch(result):
        raise AccountingRevisionConflict(f"{field} должен содержать SHA-256")
    return result


def _positive_revision(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise AccountingRevisionConflict(f"{field} должен быть положительным целым")
    try:
        revision = int(value)
    except (TypeError, ValueError) as exc:
        raise AccountingRevisionConflict(
            f"{field} должен быть положительным целым"
        ) from exc
    if revision <= 0 or str(value).strip() != str(revision):
        raise AccountingRevisionConflict(f"{field} должен быть положительным целым")
    return revision


def _fact_origin(packet: dict) -> str:
    origin = str(
        packet.get("FactOrigin") or packet.get("ИсточникФакта")
        or packet.get("fact_origin") or ""
    ).strip()
    if origin not in FACT_ORIGINS:
        raise AccountingRevisionConflict(
            "ИсточникФакта должен быть edge|store|onec_legacy|edo|cash"
        )
    return origin


def _transition(row: ExportPacket, target: str) -> None:
    if target not in ACCOUNTING_FSM.get(row.status, frozenset()):
        raise AccountingRevisionConflict(
            f"Недопустимый переход accounting-outbox: {row.status} -> {target}"
        )
    row.status = target


async def append_canonical_fact(
    session: AsyncSession,
    entry: DataEntry,
    *,
    document_id: uuid.UUID,
    revision: int,
    content_hash: str,
    fact_origin: str,
) -> RevisionResult:
    if fact_origin not in FACT_ORIGINS:
        raise AccountingRevisionConflict("Недопустимый fact_origin")
    revision = _positive_revision(revision, "revision")
    content_hash = _hash64(content_hash, "content_hash")
    scope_key = f"canonical-fact:{entry.company_id}:{document_id}"
    await session.execute(_CANONICAL_LOCK, {"scope_key": scope_key})
    rows = (await session.execute(
        select(DataEntry).where(
            DataEntry.company_id == entry.company_id,
            DataEntry.document_id == document_id,
        ).order_by(DataEntry.revision.desc()).with_for_update()
    )).scalars().all()
    for existing in rows:
        if existing.content_hash == content_hash:
            return RevisionResult(existing, False)
    latest = rows[0] if rows else None
    if latest is not None and revision <= latest.revision:
        raise AccountingRevisionConflict(
            "Новый canonical content_hash требует большей revision"
        )
    entry.document_id = document_id
    entry.revision = revision
    entry.content_hash = content_hash
    entry.fact_origin = fact_origin
    entry.layer = "clean"
    entry.supersedes_entry_id = latest.id if latest is not None else None
    if latest is not None:
        latest.status = "superseded"
    session.add(entry)
    await session.flush()
    return RevisionResult(entry, True)


class AccountingOutboxService:
    def __init__(self, session: AsyncSession, company_id: uuid.UUID):
        self.session = session
        self.company_id = company_id

    async def append_validated_revision(
        self, packet: dict, kind: str,
    ) -> RevisionResult:
        if kind not in ACCOUNTING_KINDS:
            raise AccountingRevisionConflict("Недопустимый accounting kind")
        if packet.get("ВерсияФормата") != "3" or packet.get("ВерсияКонтракта") != "3.0.0":
            raise AccountingRevisionConflict("Accounting outbox принимает только контракт 3.0.0")
        try:
            validate_top_level_v3(packet)
        except AccountingContractError as exc:
            raise AccountingRevisionConflict(str(exc)) from exc
        try:
            packet_uuid = uuid.UUID(str(packet.get("ИдентификаторПакета") or ""))
            business_shift_id = uuid.UUID(str(packet.get("BusinessShiftID") or ""))
        except ValueError as exc:
            raise AccountingRevisionConflict(
                "ИдентификаторПакета и BusinessShiftID должны быть корректными UUID"
            ) from exc
        revision = _positive_revision(packet.get("РевизияПакета"), "РевизияПакета")
        content_hash = _hash64(packet.get("ХешПакета"), "ХешПакета")
        try:
            calculated_hash = business_projection_hash(packet)
        except AccountingContractError as exc:
            raise AccountingRevisionConflict(str(exc)) from exc
        if calculated_hash != content_hash:
            raise AccountingRevisionConflict(
                "ХешПакета не совпадает с каноническим содержимым"
            )
        fact_origin = _fact_origin(packet)
        if fact_origin not in {"edge", "onec_legacy"}:
            raise AccountingRevisionConflict("FactOrigin v3 должен быть edge|onec_legacy")
        if packet.get("TransportProducer") != "central_ledger":
            raise AccountingRevisionConflict(
                "TransportProducer v3 должен быть central_ledger"
            )
        await self.session.execute(_OUTBOX_LOCK, {
            "scope_key": f"accounting-outbox:{self.company_id}:{business_shift_id}",
        })
        group = (await self.session.execute(
            select(AccountingBusinessGroup).where(
                AccountingBusinessGroup.company_id == self.company_id,
                AccountingBusinessGroup.business_shift_id == business_shift_id,
            ).with_for_update()
        )).scalars().first()
        if group is None:
            raise AccountingRevisionConflict(
                "BusinessShift не разрешён в AccountingBusinessGroup"
            )
        shift = (await self.session.execute(
            select(BusinessShift).where(
                BusinessShift.company_id == self.company_id,
                BusinessShift.id == business_shift_id,
            ).with_for_update()
        )).scalars().first()
        if shift is None or shift.status != "resolved" or group.status != "active":
            raise AccountingRevisionConflict("BusinessShift требует проверки")
        company_key = str(packet.get("CompanyID") or "")
        station_id = str(packet.get("StationID") or "")
        if (
            company_key != shift.company_key
            or station_id != shift.station_id
            or str(packet.get("BusinessDate") or "") != shift.business_date.isoformat()
        ):
            raise AccountingRevisionConflict("Identity пакета не совпадает с BusinessShift")
        expected_business_key = business_key_hash(
            business_shift_id, company_key, station_id,
        )
        if _hash64(packet.get("BusinessKeyHash"), "BusinessKeyHash") != expected_business_key:
            raise AccountingRevisionConflict("BusinessKeyHash не совпадает с identity")
        if group.business_key_hash != expected_business_key:
            raise AccountingRevisionConflict("BusinessKeyHash не совпадает с group")
        if packet_uuid != group.packet_uuid or packet_uuid != accounting_packet_uuid(business_shift_id):
            raise AccountingRevisionConflict("ИдентификаторПакета не совпадает с BusinessShift")

        current = None
        if group.current_packet_id is not None:
            current = (await self.session.execute(
                select(ExportPacket).where(
                    ExportPacket.company_id == self.company_id,
                    ExportPacket.id == group.current_packet_id,
                    ExportPacket.accounting_group_id == group.id,
                ).with_for_update()
            )).scalars().first()
            if current is None:
                raise AccountingRevisionConflict("Current revision group повреждена")

        if group.current_revision is None:
            if revision != 1:
                raise AccountingRevisionConflict("revision_gap")
        else:
            if revision < group.current_revision:
                raise AccountingRevisionConflict("revision_stale")
            if revision == group.current_revision:
                if content_hash == group.current_content_hash and current is not None:
                    return RevisionResult(current, False)
                raise AccountingRevisionConflict("revision_hash_conflict")
            if revision > group.current_revision + 1:
                raise AccountingRevisionConflict("revision_gap")
            if content_hash == group.current_content_hash:
                raise AccountingRevisionConflict("revision_without_change")
            if current is not None and current.status in {
                "draft", "validated", "queued", "retry_wait", "leased",
                "sent_waiting_ack", "blocked_mapping",
            }:
                raise AccountingRevisionConflict(
                    "Предыдущая ревизия бухгалтерской группы ещё активна"
                )

        source_ids = [
            str(document.get("ИсточникUUID"))
            for document in (packet.get("Документы") or [])
            if document.get("ИсточникUUID")
        ]
        row = ExportPacket(
            id=uuid.uuid4(),
            company_id=self.company_id,
            kind=kind,
            idem_key=f"ACCOUNTING|{packet_uuid}|{content_hash}",
            source_entry_ids=source_ids,
            status="draft",
            payload=packet,
            packet_uuid=packet_uuid,
            revision=revision,
            contract_version=str(packet.get("ВерсияФормата")),
            content_hash=content_hash,
            fact_origin=fact_origin,
            transport_producer="central_ledger",
            accounting_group_id=group.id,
        )
        self.session.add(row)
        await self.session.flush()
        _transition(row, "validated")
        group.current_revision = revision
        group.current_content_hash = content_hash
        group.current_packet_id = row.id
        await self.session.flush()
        return RevisionResult(row, True)

    async def claim_next(
        self,
        *,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ExportPacket | None:
        if lease_seconds <= 0:
            raise AccountingRevisionConflict("lease_seconds должен быть положительным")
        now = now or datetime.now(timezone.utc)
        row = (await self.session.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == self.company_id,
                ExportPacket.kind.in_(ACCOUNTING_KINDS),
                ExportPacket.status.in_(("queued", "retry_wait")),
                or_(ExportPacket.lease_until.is_(None), ExportPacket.lease_until <= now),
            ).order_by(ExportPacket.created_at, ExportPacket.id)
            .limit(1).with_for_update(skip_locked=True)
        )).scalars().first()
        if row is None:
            return None
        _transition(row, "leased")
        row.attempt_id = uuid.uuid4()
        row.lease_until = now + timedelta(seconds=lease_seconds)
        row.error_code = None
        row.error_detail = None
        await self.session.flush()
        return row

    async def claim_request(
        self,
        *,
        consumer_id: str,
        claim_request_id: uuid.UUID,
        lease_seconds: int,
        now: datetime | None = None,
    ) -> ClaimResult:
        consumer_id = str(consumer_id).strip()
        if not consumer_id:
            raise AccountingRevisionConflict("ConsumerID не может быть пустым")
        if not 1 <= lease_seconds <= 3600:
            raise AccountingRevisionConflict("LeaseSeconds должен быть от 1 до 3600")
        try:
            claim_request_id = uuid.UUID(str(claim_request_id))
        except ValueError as exc:
            raise AccountingRevisionConflict("ClaimRequestID должен быть UUID") from exc
        request_hash = claim_request_hash(
            consumer_id, claim_request_id, lease_seconds,
        )
        await self.session.execute(_OUTBOX_LOCK, {
            "scope_key": (
                f"accounting-claim:{self.company_id}:"
                f"{consumer_id}:{claim_request_id}"
            ),
        })
        existing = (await self.session.execute(
            select(AccountingClaimRequest).where(
                AccountingClaimRequest.company_id == self.company_id,
                AccountingClaimRequest.consumer_id == consumer_id,
                AccountingClaimRequest.claim_request_id == claim_request_id,
            ).with_for_update()
        )).scalars().first()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise AccountingRevisionConflict("claim_request_conflict")
            packet = None
            if existing.packet_id is not None:
                packet = (await self.session.execute(
                    select(ExportPacket).where(
                        ExportPacket.company_id == self.company_id,
                        ExportPacket.id == existing.packet_id,
                        ExportPacket.kind.in_(ACCOUNTING_KINDS),
                    )
                )).scalars().first()
                if packet is None:
                    raise AccountingRevisionConflict(
                        "Идемпотентный claim ссылается на отсутствующий пакет"
                    )
            return ClaimResult(
                consumer_id, claim_request_id, existing.attempt_id,
                packet, existing.lease_until, False,
            )

        now = now or datetime.now(timezone.utc)
        row = (await self.session.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == self.company_id,
                ExportPacket.kind.in_(ACCOUNTING_KINDS),
                ExportPacket.status.in_(("queued", "retry_wait", "blocked_mapping")),
                ExportPacket.accounting_group_id.is_not(None),
                ExportPacket.id.in_(
                    select(AccountingBusinessGroup.current_packet_id).where(
                        AccountingBusinessGroup.company_id == self.company_id,
                        AccountingBusinessGroup.status == "active",
                    )
                ),
                or_(ExportPacket.lease_until.is_(None), ExportPacket.lease_until <= now),
            ).order_by(ExportPacket.created_at, ExportPacket.id)
            .limit(1).with_for_update(skip_locked=True)
        )).scalars().first()
        attempt_id = None
        lease_until = None
        if row is not None:
            _transition(row, "leased")
            attempt_id = uuid.uuid4()
            lease_until = now + timedelta(seconds=lease_seconds)
            row.attempt_id = attempt_id
            row.lease_until = lease_until
            row.error_code = None
            row.error_detail = None
        request = AccountingClaimRequest(
            id=uuid.uuid4(), company_id=self.company_id,
            consumer_id=consumer_id, claim_request_id=claim_request_id,
            request_hash=request_hash, lease_seconds=lease_seconds,
            attempt_id=attempt_id, packet_id=row.id if row is not None else None,
            lease_until=lease_until,
        )
        self.session.add(request)
        await self.session.flush()
        return ClaimResult(
            consumer_id, claim_request_id, attempt_id, row, lease_until, True,
        )

    async def recover_expired_leases(
        self, *, now: datetime | None = None,
    ) -> list[ExportPacket]:
        now = now or datetime.now(timezone.utc)
        rows = (await self.session.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == self.company_id,
                ExportPacket.kind.in_(ACCOUNTING_KINDS),
                or_(
                    and_(
                        ExportPacket.status == "leased",
                        ExportPacket.lease_until <= now,
                    ),
                    and_(
                        ExportPacket.status == "sent_waiting_ack",
                        or_(
                            ExportPacket.lease_until.is_(None),
                            ExportPacket.lease_until <= now,
                        ),
                    ),
                ),
            ).order_by(ExportPacket.created_at)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        for row in rows:
            previous_status = row.status
            _transition(row, "retry_wait")
            row.attempt_id = None
            row.lease_until = None
            if previous_status == "sent_waiting_ack":
                row.error_code = "ack_deadline_expired"
                row.error_detail = (
                    "ACK deadline истёк; разрешена повторная доставка того же пакета"
                )
            else:
                row.error_code = "lease_expired"
                row.error_detail = "Sender lease истёк до подтверждённой отправки"
        if rows:
            await self.session.flush()
        return rows

    async def mark_sent(
        self,
        packet_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        now: datetime | None = None,
        ack_timeout_seconds: int = 300,
    ) -> ExportPacket:
        if not 1 <= ack_timeout_seconds <= 86400:
            raise AccountingRevisionConflict(
                "ack_timeout_seconds должен быть от 1 до 86400",
            )
        row = await self._locked(packet_id)
        self._require_attempt(row, attempt_id)
        _transition(row, "sent_waiting_ack")
        row.sent_at = now or datetime.now(timezone.utc)
        row.lease_until = row.sent_at + timedelta(seconds=ack_timeout_seconds)
        await self.session.flush()
        return row

    async def fail_attempt(
        self,
        packet_id: uuid.UUID,
        attempt_id: uuid.UUID,
        *,
        retry_at: datetime,
        error_code: str,
        error_detail: str | None = None,
    ) -> ExportPacket:
        row = await self._locked(packet_id)
        self._require_attempt(row, attempt_id)
        _transition(row, "retry_wait")
        row.attempt_id = None
        row.lease_until = retry_at
        row.error_code = error_code
        row.error_detail = error_detail
        await self.session.flush()
        return row

    async def apply_ack(
        self,
        packet_id: uuid.UUID,
        *,
        attempt_id: uuid.UUID,
        content_hash: str,
        result: str,
        ack_payload: dict,
        component_result: dict | None = None,
        error_code: str | None = None,
        error_detail: str | None = None,
        now: datetime | None = None,
    ) -> ExportPacket:
        if result not in TERMINAL_ACCOUNTING_STATUSES:
            raise AccountingRevisionConflict("Недопустимый результат accounting ack")
        row = await self._locked(packet_id)
        if row.status != "sent_waiting_ack" or row.attempt_id != attempt_id:
            raise AccountingRevisionConflict("Устаревшая или чужая accounting ack")
        if row.content_hash != _hash64(content_hash, "content_hash ack"):
            raise AccountingRevisionConflict("Accounting ack относится к другому hash")
        _transition(row, result)
        row.acked_at = now or datetime.now(timezone.utc)
        row.ack_payload = ack_payload
        row.component_result = component_result
        row.error_code = error_code
        row.error_detail = error_detail
        row.reject_reason = error_detail if result == "rejected" else None
        row.lease_until = None
        await self.session.flush()
        return row

    async def apply_ack_contract(
        self,
        ack: dict,
        *,
        now: datetime | None = None,
    ) -> ExportPacket:
        try:
            validate_ack_v3(ack)
        except AccountingContractError as exc:
            raise AccountingRevisionConflict(str(exc)) from exc
        supplied_ack_hash = _hash64(ack.get("AckHash"), "AckHash")
        try:
            calculated_ack_hash = ack_hash(ack)
        except AccountingContractError as exc:
            raise AccountingRevisionConflict(str(exc)) from exc
        if supplied_ack_hash != calculated_ack_hash:
            raise AccountingRevisionConflict("AckHash не совпадает с телом ACK")
        try:
            packet_id = uuid.UUID(str(ack.get("PacketID") or ""))
            attempt_id = uuid.UUID(str(ack.get("AttemptID") or ""))
            claim_request_id = uuid.UUID(str(ack.get("ClaimRequestID") or ""))
            packet_uuid = uuid.UUID(str(ack.get("ИдентификаторПакета") or ""))
            business_shift_id = uuid.UUID(str(ack.get("BusinessShiftID") or ""))
        except ValueError as exc:
            raise AccountingRevisionConflict("ACK содержит некорректный UUID") from exc
        consumer_id = str(ack.get("ConsumerID") or "").strip()
        if not consumer_id:
            raise AccountingRevisionConflict("ACK не содержит ConsumerID")

        row = await self._locked(packet_id)
        claim = (await self.session.execute(
            select(AccountingClaimRequest).where(
                AccountingClaimRequest.company_id == self.company_id,
                AccountingClaimRequest.consumer_id == consumer_id,
                AccountingClaimRequest.claim_request_id == claim_request_id,
            ).with_for_update()
        )).scalars().first()
        if (
            claim is None
            or claim.packet_id != row.id
            or claim.attempt_id != attempt_id
        ):
            raise AccountingRevisionConflict("ACK не совпадает с claim identity")
        group = (await self.session.execute(
            select(AccountingBusinessGroup).where(
                AccountingBusinessGroup.company_id == self.company_id,
                AccountingBusinessGroup.id == row.accounting_group_id,
            ).with_for_update()
        )).scalars().first()
        if group is None:
            raise AccountingRevisionConflict("ACK относится к пакету без business group")
        if (
            row.attempt_id != attempt_id
            or row.packet_uuid != packet_uuid
            or group.business_shift_id != business_shift_id
            or group.business_key_hash != _hash64(
                ack.get("BusinessKeyHash"), "BusinessKeyHash ACK",
            )
            or row.revision != _positive_revision(
                ack.get("РевизияПакета"), "РевизияПакета ACK",
            )
            or row.content_hash != _hash64(ack.get("ХешПакета"), "ХешПакета ACK")
        ):
            raise AccountingRevisionConflict("ACK identity не совпадает с пакетом")

        if row.ack_payload is not None:
            previous_hash = str(row.ack_payload.get("AckHash") or "")
            if previous_hash == supplied_ack_hash:
                return row
            if row.status in {"accepted", "rejected", "needs_review"}:
                raise AccountingRevisionConflict("ACK конфликтует с терминальным результатом")
        if row.status != "sent_waiting_ack":
            raise AccountingRevisionConflict("Устаревшая или чужая accounting ACK")

        result = str(ack.get("Результат") or "")
        components = ack.get("Компоненты")
        if result == "accepted":
            expected = (
                (row.payload.get("ПолнотаГруппы") or {})
                .get("ОжидаемыеКомпоненты") or []
            )
            expected_keys = [
                (item.get("Порядок"), item.get("Тип"), item.get("ИсточникUUID"))
                for item in expected
            ]
            actual_keys = [
                (item.get("Порядок"), item.get("Тип"), item.get("ИсточникUUID"))
                for item in components
            ]
            if actual_keys != expected_keys:
                raise AccountingRevisionConflict(
                    "Accepted ACK содержит неполный состав компонентов"
                )
            production_hash = next((
                document.get("SourceHash")
                for document in (row.payload.get("Документы") or [])
                if document.get("Тип") == "production_release"
            ), None)
            retail_hash = next((
                document.get("SourceHash")
                for document in (row.payload.get("Документы") or [])
                if document.get("Тип") == "retail_sale_sidegoods"
            ), None)
            expected_hashes = [
                production_hash if item.get("Тип") == "assembly" else retail_hash
                for item in expected
            ]
            actual_hashes = [
                _hash64(item.get("SourceHash"), "SourceHash компонента ACK")
                for item in components
            ]
            if None in expected_hashes or actual_hashes != expected_hashes:
                raise AccountingRevisionConflict(
                    "Accepted ACK содержит чужой SourceHash компонента",
                )
            if any(
                not item.get("СсылкаБП")
                or not _hash64(item.get("TargetHash"), "TargetHash компонента ACK")
                or item.get("Проведен") is not False
                or item.get("Результат") != "accepted"
                for item in components
            ):
                raise AccountingRevisionConflict(
                    "Accepted ACK содержит некорректный результат компонента"
                )

        _transition(row, result)
        row.acked_at = now or datetime.now(timezone.utc)
        row.ack_payload = ack
        row.component_result = components
        row.error_code = ack.get("КодОшибки")
        row.error_detail = ack.get("ОписаниеОшибки")
        row.reject_reason = row.error_detail if result == "rejected" else None
        row.lease_until = None
        await self.session.flush()
        return row

    async def _locked(self, packet_id: uuid.UUID) -> ExportPacket:
        row = (await self.session.execute(
            select(ExportPacket).where(
                ExportPacket.id == packet_id,
                ExportPacket.company_id == self.company_id,
                ExportPacket.kind.in_(ACCOUNTING_KINDS),
            ).with_for_update()
        )).scalars().first()
        if row is None:
            raise AccountingRevisionConflict("Accounting-пакет не найден")
        return row

    @staticmethod
    def _require_attempt(row: ExportPacket, attempt_id: uuid.UUID) -> None:
        if row.status != "leased" or row.attempt_id != attempt_id:
            raise AccountingRevisionConflict("Устаревшая или чужая sender-попытка")
