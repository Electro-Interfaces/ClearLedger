"""Границы доверия автоматической обработки входящей почты."""
import email

from app.services import mail_intake


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
