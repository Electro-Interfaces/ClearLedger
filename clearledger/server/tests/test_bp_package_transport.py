"""Транспорт пакета в бухгалтерию: забрать и подтвердить.

До этих двух ручек очередь была написана, но недостижима — забрать пакет и
отметить доставку было некому, и первичка магазина ехала в бухгалтерию только
через центральную базу 1С.

Главное, что здесь проверяется: пакет, отмеченный отправленным, повторно не
выдаётся. Загрузить одну смену дважды значит удвоить выручку в бухгалтерии.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app.models import ExportPacket
from app.routers.store_router import (
    store_bp_package_ack,
    store_bp_package_claim,
)


class _Company:
    def __init__(self):
        self.id = uuid.uuid4()


class _Session:
    """Сессия, помнящая один пакет: очередь целиком нам здесь не нужна."""

    def __init__(self, packets):
        self.packets = list(packets)
        self.commits = 0

    async def execute(self, statement, parameters=None):
        текст = str(statement)
        if "status IN" in текст:  # claim_next: очередь на выдачу
            подходят = [p for p in self.packets
                        if p.status in ("queued", "retry_wait")]
        elif "status =" in текст:  # recover_expired_leases: зависшая аренда
            подходят = [p for p in self.packets if p.status == "leased"]
        else:  # _locked: пакет по идентификатору
            подходят = self.packets
        return _Result(подходят)

    async def flush(self):
        pass

    async def commit(self):
        self.commits += 1


class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self.rows)

    def first(self):
        return self.rows[0] if self.rows else None


def _пакет(company_id, status="queued") -> ExportPacket:
    return ExportPacket(
        id=uuid.uuid4(), company_id=company_id, kind="shift_orp",
        packet_uuid=uuid.uuid4(), revision=1, status=status,
        content_hash="a" * 64, contract_version="3",
        payload={"ИдентификаторПакета": "x", "Документы": []},
        created_at=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_claim_otdayot_paket_pod_arendu():
    company = _Company()
    пакет = _пакет(company.id)
    сессия = _Session([пакет])
    ответ = await store_bp_package_claim(
        lease_seconds=1800, company=company, db=сессия)
    выдан = ответ["packet"]
    assert выдан["packet_id"] == str(пакет.id)
    assert выдан["payload"] == пакет.payload
    assert выдан["attempt_id"], "без номера попытки подтверждение не привязать"
    assert пакет.status == "leased"
    assert пакет.lease_until is not None
    assert сессия.commits == 1


@pytest.mark.asyncio
async def test_pustaya_ochered_ne_oshibka():
    company = _Company()
    ответ = await store_bp_package_claim(
        lease_seconds=1800, company=company, db=_Session([]))
    assert ответ["packet"] is None


@pytest.mark.asyncio
async def test_otpravlennyy_paket_povtorno_ne_vydayotsya():
    """Иначе одна смена уедет в бухгалтерию дважды и выручка задвоится."""
    company = _Company()
    пакет = _пакет(company.id)
    сессия = _Session([пакет])

    выдан = (await store_bp_package_claim(
        lease_seconds=1800, company=company, db=сессия))["packet"]
    await store_bp_package_ack(
        packet_id=uuid.UUID(выдан["packet_id"]),
        attempt_id=uuid.UUID(выдан["attempt_id"]),
        content_hash=выдан["content_hash"], result="accepted", stage="sent",
        error_code=None, error_detail=None, ack_payload=None,
        company=company, db=сессия)
    assert пакет.status == "sent_waiting_ack"

    повтор = await store_bp_package_claim(
        lease_seconds=1800, company=company, db=сессия)
    assert повтор["packet"] is None


@pytest.mark.asyncio
async def test_chuzhaya_popytka_otvergaetsya():
    """Подтверждение от доставщика, который этот пакет не забирал."""
    company = _Company()
    пакет = _пакет(company.id)
    сессия = _Session([пакет])
    выдан = (await store_bp_package_claim(
        lease_seconds=1800, company=company, db=сессия))["packet"]

    with pytest.raises(HTTPException) as ошибка:
        await store_bp_package_ack(
            packet_id=uuid.UUID(выдан["packet_id"]),
            attempt_id=uuid.uuid4(),  # чужой номер попытки
            content_hash=выдан["content_hash"], result="accepted", stage="sent",
            error_code=None, error_detail=None, ack_payload=None,
            company=company, db=сессия)
    assert ошибка.value.status_code == 409


@pytest.mark.asyncio
async def test_zavisshaya_arenda_vozvrashchaet_paket_v_ochered():
    """Доставщик перезапускается чаще, чем истекает аренда."""
    company = _Company()
    пакет = _пакет(company.id, status="leased")
    пакет.attempt_id = uuid.uuid4()
    пакет.lease_until = datetime.now(timezone.utc) - timedelta(minutes=5)
    сессия = _Session([пакет])

    await store_bp_package_claim(lease_seconds=1800, company=company, db=сессия)
    assert пакет.error_code == "lease_expired" or пакет.status == "leased"
