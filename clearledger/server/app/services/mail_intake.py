"""Приём почты пространства: ящики компании, разбор писем, нити (docs/MAIL.md).

Один коннектор «Почта компании» — много ящиков. Механика одна: забрать по IMAP,
разобрать, понять от кого, сшить в нить, сохранить с вложениями. Различаются у
ящиков учётка, назначение и (следующей волной) правила.

Три вещи, которые здесь сделаны намеренно и без которых почта ломается:

  1. **UIDVALIDITY.** Сервер вправе перенумеровать ящик; сохранённый UID после
     этого указывает на чужое письмо. При смене значения приём начинается заново,
     а дубли отсекаются по `Message-ID`.
  2. **Нить по `References`, а не по теме.** Тему правят, переводят и дописывают
     «Re:» — по ней одна переписка разваливается на несколько.
  3. **Оригинал письма.** Тело и заголовки сохраняются как пришли: спор «что было
     в письме» решается оригиналом, а не нашей интерпретацией.

IMAP-клиент синхронный (`imaplib` из стандартной библиотеки), поэтому опрос
уходит в поток: тянуть асинхронную библиотеку ради одного поллера незачем.
"""
from __future__ import annotations

import asyncio
import email
import hashlib
import imaplib
import logging
import os
import re
from datetime import datetime, timezone
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parsedate_to_datetime, parseaddr, getaddresses
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.net_guard import assert_external_host
from app.models import (
    Counterparty, CounterpartyEmail, IntakeBatch, MailAccount, MailAttachment,
    MailMessage, MailRule, MailThread, Task,
)

logger = logging.getLogger("clearledger.mail")

# Вложения, которые не принимаем никогда: исполняемое из письма — это не документ.
_DENY_EXT = {".exe", ".scr", ".bat", ".cmd", ".com", ".pif", ".js", ".vbs", ".msi",
             ".jar", ".ps1", ".lnk"}
# Потолок на письмо и на вложение: чужой ящик присылает что угодно.
MAX_MESSAGE_BYTES = 25 * 1024 * 1024
MAX_ATTACH_BYTES = 15 * 1024 * 1024
# Сколько писем берём за один заход: первый опрос большого ящика иначе висит минуты.
BATCH = 50


def _decode(value: str | None) -> str:
    """Заголовок в читаемый вид: `=?utf-8?B?...?=` приезжает почти в каждом письме."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 — кривой заголовок не повод терять письмо
        return value


def _body(msg: Message) -> tuple[str, str]:
    """Текст и html письма. Части перебираем сами: `get_body` не видит вложенные
    multipart от некоторых отправителей."""
    text_parts, html_parts = [], []
    for part in msg.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get_filename():
            continue
        ctype = part.get_content_type()
        try:
            payload = part.get_payload(decode=True) or b""
            charset = part.get_content_charset() or "utf-8"
            body = payload.decode(charset, errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if ctype == "text/plain":
            text_parts.append(body)
        elif ctype == "text/html":
            html_parts.append(body)
    return "\n".join(text_parts).strip(), "\n".join(html_parts).strip()


def _attachments(msg: Message) -> list[dict[str, Any]]:
    out = []
    for part in msg.walk():
        name = part.get_filename()
        if not name:
            continue
        name = _decode(name)
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        payload = part.get_payload(decode=True) or b""
        if ext in _DENY_EXT:
            logger.warning("вложение %s отклонено по расширению", name)
            continue
        if len(payload) > MAX_ATTACH_BYTES:
            logger.warning("вложение %s отклонено по размеру (%s)", name, len(payload))
            continue
        out.append({
            "name": name,
            "content_type": part.get_content_type(),
            "size": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "content": payload,
        })
    return out


def auth_verdict(msg: Message) -> tuple[str, str | None]:
    """Что почтовый сервер сказал о подлинности письма.

    Проверять SPF/DKIM самим нечем и незачем: их уже проверил принимающий сервер и
    записал результат в `Authentication-Results`. Наше дело — прочитать вердикт и
    не пускать в ленту то, что не прошло: подделать адрес отправителя проще, чем
    кажется, а письмо «от контрагента» с реквизитами для оплаты — классика.

    Возвращает `pass` | `fail` | `unknown` и текст вердикта.
    """
    values = [v for k, v in msg.items() if k.lower() == "authentication-results"]
    trusted = {value.strip().lower() for value in settings.mail_authserv_ids.split(";")
               if value.strip()}
    raw = next((value for value in values
                if value.split(";", 1)[0].strip().lower() in trusted), "")
    if not raw:
        return "unknown", None
    low = raw.lower()
    if "dmarc=fail" in low:
        return "fail", raw[:300]
    if "dmarc=pass" in low:
        _, from_email = parseaddr(_decode(msg.get("From")))
        from_domain = from_email.rsplit("@", 1)[-1].lower().rstrip(".") \
            if "@" in from_email else ""
        match = re.search(r"\bdmarc=pass\b[^;]*\bheader\.from=([^\s;]+)", low)
        aligned = match.group(1).strip('"').rstrip(".") if match else ""
        if from_domain and aligned == from_domain:
            return "pass", raw[:300]
    return "unknown", raw[:300]


def _refs(msg: Message) -> list[str]:
    """Цепочка предков письма: `References` + `In-Reply-To`."""
    raw = " ".join(filter(None, [msg.get("References", ""), msg.get("In-Reply-To", "")]))
    return re.findall(r"<[^>]+>", raw)


# Сокет без таймаута ждёт вечно: хост, который принимает TCP и молчит (файрвол
# с DROP, зависший почтовик), намертво вешал поток опроса — и весь приём почты
# останавливался беззвучно. У SMTP в этом же файле таймаут был, у IMAP не было.
IMAP_TIMEOUT = 20


def _connect_imap(account: dict[str, Any], password: str):
    """Соединение с ящиком. Обычный порт 143 без шифрования встречается только во
    внутренних почтовиках, но встречается — поэтому режим выбирается настройкой."""
    assert_external_host(account["imap_host"])
    if account.get("imap_security") == "none":
        conn = imaplib.IMAP4(account["imap_host"], account["imap_port"],
                             timeout=IMAP_TIMEOUT)
    else:
        conn = imaplib.IMAP4_SSL(account["imap_host"], account["imap_port"],
                                 timeout=IMAP_TIMEOUT)
    # Пароль с кириллицей или знаками юникода валит login на кодировке ascii —
    # imaplib отдаёт строку как есть. Отправляем байтами: сервер ждёт utf-8.
    conn.login(account["login"], password.encode("utf-8") if password else "")
    return conn


def _fetch_sync(account: dict[str, Any]) -> tuple[list[tuple[int, bytes]], int | None, str | None]:
    """Синхронный заход в ящик: вернуть новые письма, UIDVALIDITY и ошибку."""
    password = account.get("password") or ""
    if not (account["imap_host"] and account["login"] and password):
        return [], None, "не заданы адрес IMAP, логин или пароль"
    try:
        conn = _connect_imap(account, password)
        conn.select(account["imap_folder"], readonly=True)

        validity = None
        typ, data = conn.status(account["imap_folder"], "(UIDVALIDITY)")
        if typ == "OK" and data:
            m = re.search(rb"UIDVALIDITY (\d+)", data[0] or b"")
            if m:
                validity = int(m.group(1))

        # Смена UIDVALIDITY означает перенумерацию: начинаем с начала, дубли
        # отсечёт Message-ID.
        last_uid = account["last_uid"] or 0
        if validity and account["uid_validity"] and validity != account["uid_validity"]:
            last_uid = 0

        typ, data = conn.uid("search", None, f"UID {last_uid + 1}:*")
        uids = [int(u) for u in (data[0] or b"").split() if int(u) > last_uid]
        out: list[tuple[int, bytes]] = []
        for uid in uids[:BATCH]:
            typ, msg_data = conn.uid("fetch", str(uid), "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            raw = msg_data[0][1]
            if raw and len(raw) <= MAX_MESSAGE_BYTES:
                out.append((uid, raw))
        conn.logout()
        return out, validity, None
    except Exception as e:  # noqa: BLE001 — ошибку показываем в карточке ящика
        return [], None, str(e)[:400]


def _test_sync(account: dict[str, Any], password: str) -> dict[str, Any]:
    """Синхронная проверка: доходим до ящика и до SMTP, каждый шаг — своим ответом."""
    out: dict[str, Any] = {"imap": None, "smtp": None}
    if account["imap_host"] and account["login"] and password:
        try:
            conn = _connect_imap(account, password)
            typ, data = conn.select(account["imap_folder"], readonly=True)
            count = int(data[0]) if typ == "OK" and data and data[0] else 0
            conn.logout()
            out["imap"] = {"ok": True, "text": f"подключение есть, писем в папке: {count}"}
        except Exception as e:  # noqa: BLE001 — текст ошибки и есть ответ человеку
            out["imap"] = {"ok": False, "text": _human_error(str(e))}
    else:
        out["imap"] = {"ok": False, "text": "не заполнены сервер, логин или пароль"}

    if account["smtp_host"]:
        try:
            import smtplib
            if account["smtp_security"] == "ssl":
                srv = smtplib.SMTP_SSL(account["smtp_host"], account["smtp_port"], timeout=15)
            else:
                srv = smtplib.SMTP(account["smtp_host"], account["smtp_port"], timeout=15)
                if account["smtp_security"] == "starttls":
                    import ssl as _ssl
                    # Сертификат не проверяем только у внутреннего релея стека:
                    # при проверке ящика провайдера пароль уходит наружу, и канал
                    # без проверки сертификата отдаёт его первому, кто встал в
                    # середину.
                    internal = "." not in (account["smtp_host"] or "")
                    srv.starttls(context=(_ssl._create_unverified_context() if internal
                                          else _ssl.create_default_context()))
            # На внутреннем релее аутентификации нет вовсе: попытка войти даёт
            # отказ и выглядит как «неверный пароль», хотя пароль тут ни при чём.
            if password and account["login"] and account["smtp_security"] != "none":
                srv.login(account["login"], password)
            srv.quit()
            out["smtp"] = {"ok": True, "text": "подключение есть"}
        except Exception as e:  # noqa: BLE001
            out["smtp"] = {"ok": False, "text": _human_error(str(e))}
    else:
        out["smtp"] = {"ok": False, "text": "сервер отправки не задан"}
    return out


def _human_error(text: str) -> str:
    """Ошибку почтового сервера человек читать не должен — он должен понять, что чинить."""
    low = text.lower()
    if "authenticationfailed" in low or "invalid credentials" in low or "auth" in low:
        return "сервер не принял логин или пароль"
    if "certificate" in low:
        return "сертификат сервера не проверяется — проверьте режим шифрования"
    if "timed out" in low or "timeout" in low:
        return "сервер не отвечает — проверьте адрес и порт"
    if "name or service not known" in low or "getaddrinfo" in low:
        return "адрес сервера не найден"
    if "connection refused" in low:
        return "порт закрыт — проверьте номер порта"
    return text[:200]


async def test_account(db: AsyncSession, account: MailAccount) -> dict[str, Any]:
    """Проверить настройки ящика: сотрудник должен видеть результат сразу, а не
    узнавать о неверном пароле по пустой ленте через час."""
    from app.services.mail_secrets import password_of
    snapshot = {
        "imap_host": account.imap_host, "imap_port": account.imap_port,
        "imap_folder": account.imap_folder, "login": account.login,
        "imap_security": account.imap_security,
        "smtp_host": account.smtp_host, "smtp_port": account.smtp_port,
        "smtp_security": account.smtp_security,
    }
    res = await asyncio.to_thread(_test_sync, snapshot, password_of(account))
    # Результат проверки — в карточку ящика: он же ответ на «почему не идут письма».
    account.last_error = None if res["imap"]["ok"] else res["imap"]["text"]
    await db.commit()
    return res


async def poll_account(db: AsyncSession, account: MailAccount) -> dict[str, Any]:
    """Забрать новые письма ящика, разобрать и сохранить."""
    if account.mode == "out" or not account.is_active:
        return {"fetched": 0, "saved": 0, "skipped": "ящик не принимает почту"}
    got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"),
                          {"ns": POLL_LOCK_NS, "key": account.id.int % (2 ** 31)})
    if not got:
        return {"fetched": 0, "saved": 0, "skipped": "ящик уже опрашивается"}

    from app.services.mail_secrets import password_of

    snapshot = {
        "imap_host": account.imap_host, "imap_port": account.imap_port,
        "imap_folder": account.imap_folder, "login": account.login,
        "imap_security": account.imap_security,
        # Пароль достаём ЗДЕСЬ, в асинхронном коде: поток разбора не должен знать,
        # откуда он берётся — из окружения стека или из базы под шифром.
        "password": password_of(account),
        "last_uid": account.last_uid, "uid_validity": account.uid_validity,
    }
    letters, validity, error = await asyncio.to_thread(_fetch_sync, snapshot)

    account.last_sync_at = datetime.now(timezone.utc)
    account.last_error = error
    if not error:
        # Когда почта РЕАЛЬНО приходила. `last_sync_at` — это «когда пытались», по
        # нему считается расписание, и на витрине он врал: неудачная попытка
        # выглядела свежим обменом.
        account.last_ok_at = account.last_sync_at
    if validity:
        account.uid_validity = validity
    if error:
        await db.commit()
        return {"fetched": 0, "saved": 0, "error": error}

    saved = 0
    for uid, raw in letters:
        try:
            async with db.begin_nested():
                if await _save_message(db, account, uid, raw):
                    saved += 1
        except Exception as e:  # noqa: BLE001 — одно кривое письмо не рвёт приём
            # UID нельзя продвигать мимо письма, которое не сохранилось: иначе
            # следующая синхронизация уже никогда его не увидит. SAVEPOINT выше
            # оставляет основную транзакцию и блокировку ящика живыми.
            account.last_error = f"Письмо UID {uid} не сохранено: {str(e)[:450]}"
            logger.exception("письмо uid=%s не сохранено: %s", uid, e)
            break
        account.last_uid = max(account.last_uid or 0, uid)
    await db.commit()
    return {"fetched": len(letters), "saved": saved}


# Сколько писем от одного адреса принимаем за сутки: сорвавшийся автоответчик
# или рассылка иначе заполняют ленту за час.
DAILY_LIMIT_PER_SENDER = 200

# Пространство имён блокировки опроса: своё, чтобы не пересечься с
# планировщиками задач и каналов.
POLL_LOCK_NS = 4711


async def _save_message(db: AsyncSession, account: MailAccount, uid: int,
                        raw: bytes) -> bool:
    msg = email.message_from_bytes(raw)
    message_id = ((msg.get("Message-ID") or "").strip()
                  or f"sha256:{hashlib.sha256(raw).hexdigest()}")

    # Два ящика компании могут одновременно получить одно письмо. Блокировка по
    # компании+идентификатору закрывает check/insert даже на старой базе, где
    # уникальный индекс не создался из-за прежних дублей. Для письма без
    # Message-ID тем же стабильным ключом служит хеш исходника.
    lock_digest = hashlib.sha256(
        f"{account.company_id}:{message_id}".encode("utf-8")).digest()
    lock_key = int.from_bytes(lock_digest[:8], "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
    exists = (await db.execute(select(MailMessage.id).where(
        MailMessage.company_id == account.company_id,
        MailMessage.message_id == message_id))).scalars().first()
    if exists:
        return False

    from_name, from_email = parseaddr(_decode(msg.get("From")))

    # Потолок на отправителя: лента — рабочий инструмент, и залить её рассылкой
    # не должно быть возможно. Письма сверх лимита не теряются — они просто не
    # принимаются, и это видно в журнале ящика.
    if from_email:
        today = datetime.now(timezone.utc).date()
        seen = (await db.execute(select(func.count()).select_from(MailMessage).where(
            MailMessage.company_id == account.company_id,
            func.lower(MailMessage.from_email) == from_email.lower(),
            func.date(MailMessage.created_at) == today))).scalar_one()
        if seen >= DAILY_LIMIT_PER_SENDER:
            logger.warning("лимит писем от %s за сутки исчерпан (%s)", from_email, seen)
            return False
    to_all = [addr for _, addr in getaddresses([_decode(msg.get("To") or ""),
                                                _decode(msg.get("Cc") or "")]) if addr]
    subject = _decode(msg.get("Subject"))[:500]
    try:
        sent_at = parsedate_to_datetime(msg.get("Date")) if msg.get("Date") else None
    except Exception:  # noqa: BLE001
        sent_at = None

    text_body, html_body = _body(msg)
    atts = _attachments(msg)

    # Кто написал: адрес → карточка контрагента. Неизвестный адрес не ошибка —
    # это работа для человека (следующая волна: обучение адресов).
    cp_id = await _guess_counterparty(db, account.company_id, from_email)

    thread = await _thread_for(db, account, msg, subject, message_id, from_email, cp_id)

    row = MailMessage(
        company_id=account.company_id, account_id=account.id, thread_id=thread.id,
        direction="in", uid=uid, message_id=message_id,
        in_reply_to=(msg.get("In-Reply-To") or "").strip() or None,
        subject=subject, from_name=from_name[:300] or None, from_email=from_email or None,
        to_emails=to_all, sent_at=sent_at,
        body_text=text_body[:200000] or None, body_html=html_body[:400000] or None,
        counterparty_id=cp_id,
        # Заголовки целиком: по ним разбираются спорные случаи и проверки SPF/DKIM.
        headers={k: _decode(v)[:1000] for k, v in msg.items()},
        has_attachments=bool(atts),
        # Оригинал письма: разбор — наша интерпретация, а спор решается исходником.
        raw_eml=raw if len(raw) <= MAX_MESSAGE_BYTES else None,
        status="new",
    )

    # Подлинность: письмо, не прошедшее проверку сервера, в ленту не идёт — оно
    # ложится в карантин, даже если правило говорит «принять». Подделать адрес
    # отправителя несложно, а письмо «от контрагента» с новыми реквизитами для
    # оплаты — самая частая схема обмана в деловой переписке.
    verdict, auth_text = auth_verdict(msg)
    row.headers = {**(row.headers or {}), "_auth_status": verdict,
                   "_auth_verdict": auth_text or verdict}
    if verdict == "fail":
        row.status = "quarantine"
        row.headers = {**(row.headers or {}), "_auth_verdict": auth_text or "fail"}

    # Правила: первое сработавшее решает судьбу письма и может сразу проставить
    # контрагента и договор — это и есть ответ «что, кому и куда отнести».
    rule = await apply_rules(db, account, row, bool(atts))
    if rule is not None:
        decided = {"reject": "rejected", "quarantine": "quarantine"}.get(
            rule.action, "accepted")
        # Карантин по подлинности правило не отменяет: оно знает про отправителя
        # то, что написано в письме, а вердикт — то, что проверил сервер.
        row.status = "quarantine" if verdict == "fail" else decided
        if rule.set_counterparty_id and not row.counterparty_id:
            row.counterparty_id = rule.set_counterparty_id
            cp_id = rule.set_counterparty_id
        if rule.action == "doc" and verdict != "pass":
            row.status = "quarantine"
            row.route_error = ("Автосоздание документа остановлено: принимающий "
                               "почтовый сервер не подтвердил подлинность письма")

    db.add(row)
    await db.flush()

    saved_atts = []
    for a in atts:
        att = MailAttachment(
            company_id=account.company_id, message_id=row.id,
            file_name=a["name"][:500], content_type=a["content_type"],
            size=a["size"], sha256=a["sha256"], content=a["content"],
        )
        db.add(att)
        saved_atts.append(att)

    # Доставка: плюс-адрес (ответ почтового участника в комнату или задачу) или
    # правило (в комнату, в заявку). Ошибка доставки не рвёт приём — письмо уже
    # сохранено, и потерять его из-за удалённой комнаты было бы хуже.
    # Карантин ОСТАНАВЛИВАЕТ доставку. Раньше письмо с провалившейся проверкой
    # подлинности пряталось из ленты, но всё равно уезжало сообщением в комнату
    # чата, дописывалось в задачу и заводило заявку — то есть ровно то, ради чего
    # карантин и делался (подделанное письмо «от контрагента» с новыми реквизитами
    # оплаты), доезжало до людей другим путём.
    route_actions = {"chat", "ticket", "task", "intake", "doc"}
    if rule is not None and rule.action in route_actions:
        row.route_attempts = (row.route_attempts or 0) + 1
        row.route_attempted_at = datetime.now(timezone.utc)
    if row.status in ("quarantine", "rejected"):
        logger.info("письмо %s не доставляется: статус %s", row.id, row.status)
    else:
        try:
            from app.services import mail_routing
            async with db.begin_nested():
                routed = await mail_routing.route(db, account.company_id, row, rule)
            if routed:
                row.routed_to = routed
                row.route_error = None
        except Exception as e:  # noqa: BLE001
            row.route_error = f"Маршрут не выполнен: {str(e)[:450]}"
            logger.exception("письмо %s не доставлено по маршруту: %s", row.id, e)

    # Правило сказало «в задачу» — заводим НОВУЮ задачу из письма. Ответ в
    # существующую задачу приходит плюс-адресом и обработан выше.
    if rule is not None and rule.action == "task" and row.routed_to is None:
        try:
            async with db.begin_nested():
                await _task_from_message(db, account.company_id, row)
            row.routed_to = "task"
            row.route_error = None
        except Exception as e:  # noqa: BLE001 — задача не заводится, письмо остаётся
            row.route_error = f"Задача не создана: {str(e)[:450]}"
            logger.exception("задача из письма %s не создана: %s", row.id, e)

    # Правило сказало «в приёмку» — вложения сразу становятся кандидатами. В учёт
    # они не попадают: приём документа остаётся отдельным решением человека
    # (docs/INTAKE.md), а письмо остаётся его основанием.
    if rule is not None and rule.action == "intake" and saved_atts:
        await db.flush()
        try:
            async with db.begin_nested():
                await attachments_to_intake(db, account.company_id, row, saved_atts)
            row.routed_to = "intake"
            row.route_error = None
        except Exception as e:  # noqa: BLE001 — разбор не должен рвать приём почты
            row.route_error = f"Вложения не переданы в приёмку: {str(e)[:420]}"
            logger.exception("вложения письма %s не разобраны: %s", row.id, e)

    if rule is not None and rule.action == "doc" and row.status not in (
            "quarantine", "rejected") and row.routed_to is None and row.route_error is None:
        if row.counterparty_id is None:
            row.route_error = "Документ не создан: корреспондент не опознан"
        elif not saved_atts:
            row.route_error = "Документ не создан: нет непустого допустимого вложения"
        else:
            row.route_error = "Документ не создан: нет активного входящего вида"
    if rule is not None and rule.action in ("chat", "ticket") \
            and row.status not in ("quarantine", "rejected") \
            and row.routed_to is None and row.route_error is None:
        row.route_error = "Маршрут правила не настроен или цель недоступна"
    if rule is not None and rule.action == "intake" and not saved_atts:
        row.route_error = "В приёмку нечего передавать: допустимых вложений нет"

    route_ok = (rule is not None and (
        rule.action not in route_actions or row.routed_to is not None))
    if route_ok:
        rule.hits = (rule.hits or 0) + 1

    thread.messages_count = (thread.messages_count or 0) + 1
    thread.last_message_at = sent_at or datetime.now(timezone.utc)
    if cp_id and not thread.counterparty_id:
        thread.counterparty_id = cp_id
    return True


async def retry_doc_route(db: AsyncSession, cid, row: MailMessage) -> bool:
    """Повторить неуспешный mail→doc после исправления справочника или вида."""
    if row.company_id != cid or row.status in ("quarantine", "rejected"):
        return False
    account = await db.get(MailAccount, row.account_id) if row.account_id else None
    if account is None or account.company_id != cid:
        row.route_error = "Почтовый ящик маршрута больше недоступен"
        return False
    attachments = (await db.execute(select(MailAttachment).where(
        MailAttachment.company_id == cid,
        MailAttachment.message_id == row.id))).scalars().all()
    rule = await apply_rules(db, account, row, bool(attachments))
    if rule is None or rule.action != "doc":
        row.route_error = "Подходящее правило «в документ» не найдено"
        return False
    row.route_attempts = (row.route_attempts or 0) + 1
    row.route_attempted_at = datetime.now(timezone.utc)
    try:
        from app.services import mail_routing
        async with db.begin_nested():
            routed = await mail_routing.route(db, cid, row, rule)
    except Exception as exc:  # noqa: BLE001 — ошибка остаётся retryable
        row.route_error = f"Документ не создан: {str(exc)[:450]}"
        return False
    if routed != "doc":
        row.route_error = ("Документ не создан: нужен известный корреспондент, "
                           "непустое вложение и активный входящий вид")
        return False
    row.routed_to = "doc"
    row.route_error = None
    rule.hits = (rule.hits or 0) + 1
    return True


async def _thread_for(db: AsyncSession, account: MailAccount, msg: Message,
                      subject: str, message_id: str | None,
                      from_email: str | None, cp_id) -> MailThread:
    """Найти нить по предкам письма или завести новую."""
    refs = _refs(msg)
    if refs:
        found = (await db.execute(select(MailThread).where(
            MailThread.company_id == account.company_id,
            MailThread.root_message_id.in_(refs)))).scalars().first()
        if found:
            return found
        # Ответ пришёл раньше, чем мы увидели исходное письмо: нить заводится по
        # самому старому предку, к ней же приклеится оригинал, когда дойдёт.
        thread = MailThread(
            company_id=account.company_id, account_id=account.id,
            subject=re.sub(r"^(re|fwd?|ответ|пересылка)[:\s]+", "", subject, flags=re.I)[:500],
            root_message_id=refs[0], counterparty_id=cp_id,
            participants=[from_email] if from_email else [],
        )
        db.add(thread)
        await db.flush()
        return thread

    thread = MailThread(
        company_id=account.company_id, account_id=account.id,
        subject=subject or "(без темы)", root_message_id=message_id,
        counterparty_id=cp_id, participants=[from_email] if from_email else [],
    )
    db.add(thread)
    await db.flush()
    return thread


async def _guess_counterparty(db: AsyncSession, cid, from_email: str | None):
    """Опознать отправителя: выученный адрес → адрес карточки → домен.

    Выученное человеком стоит первым и намеренно: он знает, что «бухгалтер Ирина
    с личной почты» — это ТСМ, а справочник об этом не догадается никогда.
    """
    if not from_email or "@" not in from_email:
        return None
    addr = from_email.lower().strip()
    domain = addr.split("@")[-1]

    learned = (await db.execute(select(CounterpartyEmail.counterparty_id).where(
        CounterpartyEmail.company_id == cid,
        func.lower(CounterpartyEmail.address) == addr))).scalars().first()
    if learned:
        return learned

    exact = (await db.execute(select(Counterparty.id).where(
        Counterparty.company_id == cid,
        func.lower(Counterparty.email) == addr))).scalars().first()
    if exact:
        return exact

    # Домен — слабее адреса, поэтому берём его, только если он ведёт к ОДНОЙ
    # карточке: на mail.ru и yandex.ru сидит половина контрагентов сразу.
    same = (await db.execute(select(Counterparty.id).where(
        Counterparty.company_id == cid,
        func.lower(Counterparty.email).like(f"%@{domain}")))).scalars().all()
    return same[0] if len(same) == 1 else None


async def _task_from_message(db: AsyncSession, cid, row: MailMessage) -> None:
    """Завести задачу по письму: тема — название, текст — описание, письмо — след.

    Номер задачи выдаёт последовательность (`Task.number`), поэтому здесь его не
    трогаем: ручная нумерация в двух местах рано или поздно расходится.
    """
    body = (row.body_text or "").strip()
    task = Task(
        company_id=cid,
        title=(row.subject or "Письмо без темы")[:300],
        description=(f"Письмо от {row.from_email or 'неизвестного отправителя'}"
                     f"\n\n{body[:4000]}"),
        priority="medium",
        status="open",
    )
    db.add(task)
    await db.flush()


async def attachments_to_intake(db: AsyncSession, cid, message: MailMessage,
                                attachments: list[MailAttachment]) -> dict[str, Any]:
    """Разобрать вложения письма как пакет приёмки первички.

    Письмо — законный источник документов наравне с файлом с диска, поэтому разбор
    идёт тем же кодом (`services/intake_docs`) и попадает на тот же экран. Разница
    одна и она в пользу почты: контрагент уже известен из письма, и кандидатам,
    в чьих таблицах его нет, он проставляется сразу.
    """
    from app.services import intake_docs

    table_atts = [a for a in attachments
                  if a.file_name.lower().endswith((".xlsx", ".xlsm", ".csv"))]
    if not table_atts:
        # Счёт в PDF или скан таблицей не разобрать. Возвращаем имена: без них
        # ответ «ничего не разобрано» читается как поломка, а не как отказ по сути.
        return {"batches": 0, "items": 0,
                "skipped": [a.file_name for a in attachments]}

    made = items_total = 0
    for att in table_atts:
        rows, columns = intake_docs.parse_table(att.content or b"", att.file_name)
        if not rows:
            continue
        batch = IntakeBatch(
            company_id=cid, source="email", file_name=att.file_name,
            uploaded_by=message.from_email, status="parsed",
            stats={"rows": len(rows), "columns": columns},
            note=f"Письмо «{message.subject or ''}» от {message.from_email or ''}",
        )
        db.add(batch)
        await db.flush()

        items = await intake_docs.build_items(db, cid, batch.id, rows, None)
        # Контрагент письма — подсказка для строк, где его не написали: в таблице
        # часто нет ни имени, ни ИНН, зато письмо пришло от конкретного юрлица.
        if message.counterparty_id:
            for it in items:
                if not it.counterparty_name and not it.counterparty_inn:
                    it.counterparty_id = message.counterparty_id
        await intake_docs.match_and_verify(db, cid, items)
        for it in items:
            db.add(it)
        batch.stats = {**(batch.stats or {}), "items": len(items)}
        att.intake_batch_id = batch.id
        made += 1
        items_total += len(items)

    await db.flush()
    return {"batches": made, "items": items_total}


async def apply_rules(db: AsyncSession, account: MailAccount, row: MailMessage,
                      has_attachments: bool) -> MailRule | None:
    """Найти первое подходящее правило. Пустое условие условием не считается."""
    rules = (await db.execute(select(MailRule).where(
        MailRule.company_id == account.company_id,
        MailRule.is_active.is_(True)).order_by(
            MailRule.sort, MailRule.created_at, MailRule.id))).scalars().all()

    sender = (row.from_email or "").lower()
    domain = sender.split("@")[-1] if "@" in sender else ""
    subject = (row.subject or "").lower()

    for r in rules:
        if r.account_id and r.account_id != account.id:
            continue
        if r.from_email and r.from_email.lower() != sender:
            continue
        if r.from_domain and r.from_domain.lower().lstrip("@") != domain:
            continue
        if r.subject_like and r.subject_like.lower() not in subject:
            continue
        if r.has_attachment is not None and r.has_attachment != has_attachments:
            continue
        if r.unknown_sender is not None and r.unknown_sender != (row.counterparty_id is None):
            continue
        return r
    return None


async def learn_address(db: AsyncSession, cid, address: str, counterparty_id,
                        user: str | None = None) -> dict[str, Any]:
    """Запомнить, чей это адрес, и применить знание к УЖЕ полученным письмам.

    Обучение без обратной силы бесполезно: человек размечает адрес именно тогда,
    когда смотрит на непонятое письмо, и ждёт, что вся переписка встанет на место.
    """
    addr = address.lower().strip()
    exists = (await db.execute(select(CounterpartyEmail).where(
        CounterpartyEmail.company_id == cid,
        func.lower(CounterpartyEmail.address) == addr))).scalars().first()
    if exists:
        exists.counterparty_id = counterparty_id
    else:
        db.add(CounterpartyEmail(company_id=cid, counterparty_id=counterparty_id,
                                 address=addr, source="learned", created_by=user))

    msgs = (await db.execute(select(MailMessage).where(
        MailMessage.company_id == cid,
        func.lower(MailMessage.from_email) == addr))).scalars().all()
    threads = set()
    for m in msgs:
        m.counterparty_id = counterparty_id
        if m.thread_id:
            threads.add(m.thread_id)
    for t in (await db.execute(select(MailThread).where(
        MailThread.company_id == cid, MailThread.id.in_(threads)))).scalars().all() if threads else []:
        t.counterparty_id = counterparty_id
    await db.commit()
    return {"address": addr, "messages": len(msgs), "threads": len(threads)}


async def poll_due(db: AsyncSession) -> dict[str, Any]:
    """Опросить ящики, которым пора: интервал у каждого свой.

    Регулярный опрос — единственное, что превращает коннектор из «кнопки» в канал:
    письма должны приходить сами, иначе про них вспоминают, когда уже поздно.
    """
    now = datetime.now(timezone.utc)
    accounts = (await db.execute(select(MailAccount).where(
        MailAccount.is_active.is_(True),
        MailAccount.poll_interval_min > 0))).scalars().all()
    done = 0
    for a in accounts:
        if a.mode == "out":
            continue
        due = (a.last_sync_at is None
               or (now - a.last_sync_at).total_seconds() >= a.poll_interval_min * 60)
        if not due:
            continue
        try:
            await poll_account(db, a)
            done += 1
        except Exception as e:  # noqa: BLE001 — один ящик не роняет остальные
            await db.rollback()
            logger.exception("опрос ящика %s не удался: %s", a.address, e)
    return {"polled": done, "checked": len(accounts)}


async def poll_all(db: AsyncSession, company_id) -> dict[str, Any]:
    """Опросить все активные ящики компании."""
    accounts = (await db.execute(select(MailAccount).where(
        MailAccount.company_id == company_id,
        MailAccount.is_active.is_(True)))).scalars().all()
    out = {}
    for a in accounts:
        out[a.address] = await poll_account(db, a)
    return {"accounts": len(accounts), "result": out}
