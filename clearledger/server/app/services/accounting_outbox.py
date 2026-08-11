from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DataEntry, ExportPacket
from app.services.bp_canon import packet_hash


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
    "sent_waiting_ack": frozenset({"accepted", "rejected", "needs_review"}),
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
        packet.get("ИсточникФакта") or packet.get("fact_origin") or ""
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
        try:
            packet_uuid = uuid.UUID(str(packet.get("ИдентификаторПакета") or ""))
        except ValueError as exc:
            raise AccountingRevisionConflict(
                "ИдентификаторПакета должен быть корректным UUID"
            ) from exc
        revision = _positive_revision(packet.get("РевизияПакета"), "РевизияПакета")
        content_hash = _hash64(packet.get("ХешПакета"), "ХешПакета")
        if packet_hash(packet) != content_hash:
            raise AccountingRevisionConflict(
                "ХешПакета не совпадает с каноническим содержимым"
            )
        fact_origin = _fact_origin(packet)
        await self.session.execute(_OUTBOX_LOCK, {
            "scope_key": f"accounting-outbox:{self.company_id}:{packet_uuid}",
        })
        rows = (await self.session.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == self.company_id,
                ExportPacket.packet_uuid == packet_uuid,
                ExportPacket.kind.in_(ACCOUNTING_KINDS),
            ).order_by(ExportPacket.revision.desc()).with_for_update()
        )).scalars().all()
        for existing in rows:
            if existing.content_hash == content_hash:
                return RevisionResult(existing, False)
        latest = rows[0] if rows else None
        if latest is not None:
            if kind != latest.kind:
                raise AccountingRevisionConflict(
                    "Kind существующего packet_uuid нельзя изменить новой ревизией"
                )
            if revision <= latest.revision:
                raise AccountingRevisionConflict(
                    "Новый ХешПакета требует большей РевизииПакета"
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
        )
        self.session.add(row)
        await self.session.flush()
        _transition(row, "validated")
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

    async def recover_expired_leases(
        self, *, now: datetime | None = None,
    ) -> list[ExportPacket]:
        now = now or datetime.now(timezone.utc)
        rows = (await self.session.execute(
            select(ExportPacket).where(
                ExportPacket.company_id == self.company_id,
                ExportPacket.kind.in_(ACCOUNTING_KINDS),
                ExportPacket.status == "leased",
                ExportPacket.lease_until <= now,
            ).order_by(ExportPacket.created_at)
            .with_for_update(skip_locked=True)
        )).scalars().all()
        for row in rows:
            _transition(row, "retry_wait")
            row.attempt_id = None
            row.lease_until = None
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
    ) -> ExportPacket:
        row = await self._locked(packet_id)
        self._require_attempt(row, attempt_id)
        _transition(row, "sent_waiting_ack")
        row.sent_at = now or datetime.now(timezone.utc)
        row.lease_until = None
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
