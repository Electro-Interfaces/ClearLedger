"""Границы доверия автоматической обработки входящей почты."""
import email
import uuid
from contextlib import AbstractAsyncContextManager

import pytest
from fastapi import HTTPException

from app.models import MailAccount, MailMessage, MailRule
from app.routers import mail_router
from app.services import mail_intake


class _GapImap:
    def __init__(self):
        self.fetched = []

    def select(self, *_args, **_kwargs):
        return "OK", [b"2"]

    def status(self, *_args):
        return "OK", [b"INBOX (UIDVALIDITY 7)"]

    def uid(self, command, *args):
        if command == "search":
            return "OK", [b"10 11"]
        uid = int(args[0])
        if args[1] == "(RFC822.SIZE)":
            return "OK", [f"{uid} (UID {uid} RFC822.SIZE 32)".encode()]
        self.fetched.append(uid)
        if uid == 10:
            return "NO", []
        return "OK", [(b"RFC822", b"From: ok@example.org\r\n\r\nok")]

    def logout(self):
        return "BYE", []


def test_imap_cursor_не_перескакивает_fetch_gap(monkeypatch):
    conn = _GapImap()
    monkeypatch.setattr(mail_intake, "_connect_imap", lambda *_args: conn)
    letters, validity, error = mail_intake._fetch_sync({
        "imap_host": "mail.example.org",
        "imap_port": 993,
        "imap_folder": "INBOX",
        "imap_security": "ssl",
        "login": "docs@example.org",
        "password": "secret",
        "last_uid": 9,
        "uid_validity": 7,
    })

    assert letters == []
    assert validity == 7
    assert "UID 10" in error
    assert conn.fetched == [10]


class _OversizeImap(_GapImap):
    def uid(self, command, *args):
        if command == "search":
            return "OK", [b"10 11"]
        uid = int(args[0])
        if args[1] == "(RFC822.SIZE)":
            size = mail_intake.MAX_MESSAGE_BYTES + 1 if uid == 10 else 32
            return "OK", [f"{uid} (UID {uid} RFC822.SIZE {size})".encode()]
        self.fetched.append(uid)
        return "OK", [(b"RFC822", b"From: ok@example.org\r\n\r\nok")]


def test_imap_отклоняет_слишком_большое_письмо_без_загрузки_и_читает_хвост(
    monkeypatch,
):
    conn = _OversizeImap()
    monkeypatch.setattr(mail_intake, "_connect_imap", lambda *_args: conn)
    letters, validity, error = mail_intake._fetch_sync({
        "imap_host": "mail.example.org",
        "imap_port": 993,
        "imap_folder": "INBOX",
        "imap_security": "ssl",
        "login": "docs@example.org",
        "password": "secret",
        "last_uid": 9,
        "uid_validity": 7,
    })

    assert error is None
    assert validity == 7
    assert letters[0][0] == 10 and letters[0][1] is None
    assert "превышает предел" in letters[0][2]
    assert letters[1][0] == 11 and letters[1][1]
    assert letters[1][2] is None
    assert conn.fetched == [11]


class _Nested(AbstractAsyncContextManager):
    async def __aexit__(self, *_args):
        return False


class _PollDb:
    def __init__(self):
        self.commits = 0

    async def scalar(self, *_args, **_kwargs):
        return True

    def begin_nested(self):
        return _Nested()

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_imap_фиксирует_отказ_и_продвигает_курсор_до_следующего_письма(
    monkeypatch,
):
    account = MailAccount(
        id=uuid.uuid4(), company_id=uuid.uuid4(), address="docs@example.org",
        mode="in", is_active=True, imap_host="mail.example.org", imap_port=993,
        imap_folder="INBOX", imap_security="ssl", login="docs@example.org",
        last_uid=9, uid_validity=7,
    )
    rejected = []
    saved = []

    monkeypatch.setattr("app.services.mail_secrets.password_of", lambda *_args: "secret")
    monkeypatch.setattr(mail_intake, "_fetch_sync", lambda *_args: (
        [(10, None, "слишком большое письмо"), (11, b"valid", None)], 7, None,
    ))

    async def save_rejected(_db, _account, uid, reason):
        rejected.append((uid, reason))
        return True

    async def save_message(_db, _account, uid, raw):
        saved.append((uid, raw))
        return True

    monkeypatch.setattr(mail_intake, "_save_rejected_message", save_rejected)
    monkeypatch.setattr(mail_intake, "_save_message", save_message)

    result = await mail_intake.poll_account(_PollDb(), account)

    assert result == {"fetched": 2, "saved": 1, "rejected": 1}
    assert rejected == [(10, "слишком большое письмо")]
    assert saved == [(11, b"valid")]
    assert account.last_uid == 11


def test_заголовок_неизвестного_сервера_не_считается_проверкой(monkeypatch):
    monkeypatch.setattr(mail_intake.settings, "mail_authserv_ids", "mx.company.ru")
    message = email.message_from_bytes(
        b"Authentication-Results: attacker.example; dkim=pass; spf=pass\r\n\r\n")
    assert mail_intake.auth_verdict(message) == ("unknown", None)


def test_доверенный_сервер_подтверждает_spf_и_dkim(monkeypatch):
    monkeypatch.setattr(mail_intake.settings, "mail_authserv_ids", "mx.company.ru")
    message = email.message_from_bytes(
        b"From: sender@example.org\r\n"
        b"Authentication-Results: mx.company.ru; dmarc=pass header.from=example.org\r\n\r\n")
    verdict, evidence = mail_intake.auth_verdict(message)
    assert verdict == "pass"
    assert "dmarc=pass" in evidence


def test_spf_чужого_домена_не_подтверждает_видимого_отправителя(monkeypatch):
    monkeypatch.setattr(mail_intake.settings, "mail_authserv_ids", "mx.company.ru")
    message = email.message_from_bytes(
        b"From: known@example.org\r\n"
        b"Authentication-Results: mx.company.ru; spf=pass smtp.mailfrom=evil.test; "
        b"dmarc=none header.from=example.org\r\n\r\n")
    verdict, _ = mail_intake.auth_verdict(message)
    assert verdict == "unknown"


def test_без_списка_доверия_авторегистрация_закрыта(monkeypatch):
    monkeypatch.setattr(mail_intake.settings, "mail_authserv_ids", "")
    message = email.message_from_bytes(
        b"From: sender@example.org\r\n"
        b"Authentication-Results: mx.company.ru; dmarc=pass header.from=example.org\r\n\r\n")
    assert mail_intake.auth_verdict(message) == ("unknown", None)


def test_транспортные_заголовки_не_размножают_письмо_без_message_id():
    first = email.message_from_bytes(
        b"Received: from relay-a\r\nDelivered-To: one@example.org\r\n"
        b"From: sender@example.org\r\nTo: docs@example.org\r\n"
        b"Date: Mon, 17 Aug 2026 10:00:00 +0300\r\nSubject: Act\r\n\r\nbody")
    second = email.message_from_bytes(
        b"Received: from relay-b\r\nDelivered-To: two@example.org\r\n"
        b"From: sender@example.org\r\nTo: docs@example.org\r\n"
        b"Date: Mon, 17 Aug 2026 10:00:00 +0300\r\nSubject: Act\r\n\r\nbody")
    assert mail_intake.message_dedup_key(first) == mail_intake.message_dedup_key(second)


@pytest.mark.asyncio
async def test_системный_дубль_нельзя_маршрутизировать_повторно():
    cid = uuid.uuid4()
    duplicate = MailMessage(
        company_id=cid, direction="in", status="accepted", routed_to="duplicate",
    )
    assert await mail_intake.retry_doc_route(None, cid, duplicate) is False


@pytest.mark.asyncio
async def test_системно_отклонённое_письмо_нельзя_маршрутизировать():
    cid = uuid.uuid4()
    rejected = MailMessage(
        company_id=cid, direction="in", status="accepted", routed_to="imap_rejected",
    )
    assert await mail_intake.retry_doc_route(None, cid, rejected) is False


class _RuleRows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _RuleDb:
    def __init__(self, rows):
        self.rows = rows
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _RuleRows(self.rows)


@pytest.mark.asyncio
async def test_выключенное_правило_не_маршрутизирует_письмо():
    cid = uuid.uuid4()
    account = MailAccount(id=uuid.uuid4(), company_id=cid, address="docs@example.org")
    message = MailMessage(company_id=cid, direction="in", from_email="sender@example.org")
    db = _RuleDb([])

    assert await mail_intake.apply_rules(db, account, message, True) is None
    assert "mail_rules.is_active IS true" in str(db.statement)


@pytest.mark.asyncio
async def test_правило_ящика_не_срабатывает_на_соседнем_ящике():
    cid = uuid.uuid4()
    account = MailAccount(id=uuid.uuid4(), company_id=cid, address="info@example.org")
    rule = MailRule(
        company_id=cid, account_id=uuid.uuid4(), name="только docs",
        action="doc", is_active=True,
    )
    message = MailMessage(company_id=cid, direction="in", from_email="sender@example.org")

    assert await mail_intake.apply_rules(_RuleDb([rule]), account, message, True) is None


@pytest.mark.asyncio
async def test_правило_ящика_срабатывает_только_на_своём_ящике():
    cid = uuid.uuid4()
    account = MailAccount(id=uuid.uuid4(), company_id=cid, address="docs@example.org")
    rule = MailRule(
        company_id=cid, account_id=account.id, name="только docs",
        action="doc", is_active=True,
    )
    message = MailMessage(company_id=cid, direction="in", from_email="sender@example.org")

    assert await mail_intake.apply_rules(_RuleDb([rule]), account, message, True) is rule


@pytest.mark.asyncio
async def test_активное_правило_документа_требует_доверенный_mx(monkeypatch):
    monkeypatch.setattr(mail_intake.settings, "mail_authserv_ids", "")
    body = mail_router.RuleIn(action="doc", is_active=True)

    with pytest.raises(HTTPException) as exc:
        await mail_router._validate_rule_refs(None, uuid.uuid4(), body)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_выключенное_правило_документа_можно_подготовить_без_mx(monkeypatch):
    monkeypatch.setattr(mail_intake.settings, "mail_authserv_ids", "")
    body = mail_router.RuleIn(action="doc", is_active=False)

    await mail_router._validate_rule_refs(None, uuid.uuid4(), body)
