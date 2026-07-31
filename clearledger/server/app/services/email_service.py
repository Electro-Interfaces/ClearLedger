"""
Отправка писем (приглашения сотрудников) через SMTP (Mailcow).

aiosmtplib (async). На проде Mailcow на том же хосте — SMTP_HOST=10.10.70.51,
587 STARTTLS. Сертификат выписан на mail.dataworker.ru, а ходим по IP → проверку
хоста отключаем (внутренняя LAN-связь контейнер→хост). Без SMTP_HOST — dev-режим:
ссылка печатается в лог (как kka-site `[mail:dev]`), регистрация не блокируется.
"""
import logging
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

from app.config import get_settings

logger = logging.getLogger("clearledger.email")
settings = get_settings()

_ROLE_LABEL = {"admin": "Администратор", "user": "Сотрудник"}


def invite_link(token: str) -> str:
    base = settings.app_public_url.rstrip("/")
    return f"{base}/invite/{token}"


async def send_invite(
    to_email: str, token: str, company_name: str,
    inviter: str | None, role: str, expires_at: datetime | None = None,
) -> bool:
    """Отправляет приглашение в компанию. Возвращает True при отправке,
    False — если SMTP не сконфигурирован (ссылка ушла в лог, dev-режим)."""
    link = invite_link(token)
    role_label = _ROLE_LABEL.get(role, role)
    # Срок — прямо в письме: человек открывает его через неделю, видит «ссылка
    # недействительна» и решает, что она битая, хотя она просто истекла.
    valid_until = f" Ссылка действует до {expires_at.strftime('%d.%m.%Y')}." if expires_at else ""
    # Без брендов платформы в письме: человек получает приглашение в пространство
    # СВОЕЙ компании, чужие имена (TradeLedger/ElsyPlus) в почте — white-label-дыра.
    subject = f"Приглашение в рабочее пространство — {company_name}"
    who = f"{inviter} приглашает" if inviter else "Вас приглашают"
    text = (
        f"{who} присоединиться к рабочему пространству компании «{company_name}» "
        f"в роли «{role_label}».\n\n"
        f"Перейдите по ссылке, чтобы принять приглашение:\n{link}\n\n"
        f"По ссылке вы укажете своё ФИО, при необходимости поправите должность "
        f"и зададите пароль. Изменить нельзя только адрес почты — приглашение "
        f"выписано на него.{valid_until}\n\n"
        f"Если приглашение вышлют повторно, работать будет только новая ссылка.\n"
        f"Если вы не ожидали это письмо — просто проигнорируйте его."
    )
    html = f"""\
<div style="font-family:system-ui,Arial,sans-serif;max-width:480px;margin:0 auto;color:#1f2937">
  <h2 style="color:#2563eb;margin:0 0 8px">Рабочее пространство</h2>
  <p>{who} присоединиться к рабочему пространству компании <b>«{company_name}»</b> в роли <b>{role_label}</b>.</p>
  <p style="margin:24px 0">
    <a href="{link}" style="background:#2563eb;color:#fff;text-decoration:none;
       padding:12px 20px;border-radius:8px;display:inline-block">Принять приглашение</a>
  </p>
  <p style="color:#6b7280;font-size:13px">По ссылке вы укажете своё ФИО, при необходимости
    поправите должность и зададите пароль. Изменить нельзя только адрес почты —
    приглашение выписано на него.{valid_until}</p>
  <p style="color:#6b7280;font-size:13px">Или скопируйте ссылку:<br>
    <a href="{link}" style="color:#2563eb">{link}</a></p>
  <p style="color:#9ca3af;font-size:12px;margin-top:24px">
    Если приглашение вышлют повторно, работать будет только новая ссылка.
    Если вы не ожидали это письмо — просто проигнорируйте его.</p>
</div>"""

    if not settings.smtp_host:
        logger.warning("[mail:dev] приглашение для %s: %s", to_email, link)
        return False

    import aiosmtplib  # ленивый импорт — нужен только при реальной отправке

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    # Date и Message-ID обязательны: без них mail.ru/Gmail кладут письмо в спам
    # (rspamd: MISSING_DATE/MISSING_MID). Ни Python, ни Mailcow на submission их не дописывают.
    from_domain = parseaddr(settings.smtp_from)[1].split("@")[-1] or "localhost"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_domain)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    # Внутренний Mailcow по IP: cert на mail.dataworker.ru, проверку хоста снимаем.
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    common = dict(
        hostname=settings.smtp_host, port=settings.smtp_port,
        username=settings.smtp_user or None, password=settings.smtp_password or None,
        tls_context=ctx, timeout=20,
    )
    if settings.smtp_secure:
        await aiosmtplib.send(msg, use_tls=True, **common)
    else:
        await aiosmtplib.send(msg, start_tls=True, **common)
    logger.info("Приглашение отправлено: %s (компания %s)", to_email, company_name)
    return True


async def send_notice(
    to_emails: list[str], subject: str, text: str, html: str | None = None,
) -> bool:
    """Служебное письмо-оповещение нескольким адресатам (события пространства).

    Отдельно от `send_invite`: у приглашения свой шаблон и свой смысл, а здесь письмо
    про то, что произошло в пространстве. Возвращает False, если SMTP не сконфигурирован
    (тогда текст уходит в лог, как и остальная dev-почта) — вызывающий не должен считать
    это ошибкой доставки.
    """
    if not to_emails:
        return False
    if not settings.smtp_host:
        logger.warning("[mail:dev] оповещение для %s: %s — %s",
                       ", ".join(to_emails), subject, text)
        return False

    import aiosmtplib  # ленивый импорт — нужен только при реальной отправке

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = ", ".join(to_emails)
    msg["Subject"] = subject
    # Date и Message-ID обязательны: без них внешние почтовики кладут письмо в спам.
    from_domain = parseaddr(settings.smtp_from)[1].split("@")[-1] or "localhost"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_domain)
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    common = dict(
        hostname=settings.smtp_host, port=settings.smtp_port,
        username=settings.smtp_user or None, password=settings.smtp_password or None,
        tls_context=ctx, timeout=20,
    )
    if settings.smtp_secure:
        await aiosmtplib.send(msg, use_tls=True, **common)
    else:
        await aiosmtplib.send(msg, start_tls=True, **common)
    logger.info("Оповещение отправлено: %s (%s)", ", ".join(to_emails), subject)
    return True


def reset_link(token: str) -> str:
    base = settings.app_public_url.rstrip("/")
    return f"{base}/reset-password/{token}"


async def send_password_reset(to_email: str, token: str) -> bool:
    """Письмо для восстановления пароля. True при отправке через SMTP,
    False — если SMTP не сконфигурирован (dev-режим: ссылка в лог)."""
    link = reset_link(token)
    subject = "Восстановление пароля — рабочее пространство"
    text = (
        "Вы запросили восстановление пароля в рабочем пространстве.\n\n"
        f"Чтобы задать новый пароль, перейдите по ссылке:\n{link}\n\n"
        "Ссылка действует 1 час. Если вы не запрашивали восстановление — "
        "просто проигнорируйте это письмо."
    )
    html = f"""\
<div style="font-family:system-ui,Arial,sans-serif;max-width:480px;margin:0 auto;color:#1f2937">
  <h2 style="color:#2563eb;margin:0 0 8px">Рабочее пространство</h2>
  <p>Вы запросили <b>восстановление пароля</b>. Чтобы задать новый пароль:</p>
  <p style="margin:24px 0">
    <a href="{link}" style="background:#2563eb;color:#fff;text-decoration:none;
       padding:12px 20px;border-radius:8px;display:inline-block">Задать новый пароль</a>
  </p>
  <p style="color:#6b7280;font-size:13px">Или скопируйте ссылку:<br>
    <a href="{link}" style="color:#2563eb">{link}</a></p>
  <p style="color:#9ca3af;font-size:12px;margin-top:24px">
    Ссылка действует 1 час. Если вы не запрашивали восстановление — проигнорируйте письмо.</p>
</div>"""

    if not settings.smtp_host:
        logger.warning("[mail:dev] сброс пароля для %s: %s", to_email, link)
        return False

    import aiosmtplib  # ленивый импорт — нужен только при реальной отправке

    msg = EmailMessage()
    msg["From"] = settings.smtp_from
    msg["To"] = to_email
    msg["Subject"] = subject
    from_domain = parseaddr(settings.smtp_from)[1].split("@")[-1] or "localhost"
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_domain)
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    common = dict(
        hostname=settings.smtp_host, port=settings.smtp_port,
        username=settings.smtp_user or None, password=settings.smtp_password or None,
        tls_context=ctx, timeout=20,
    )
    if settings.smtp_secure:
        await aiosmtplib.send(msg, use_tls=True, **common)
    else:
        await aiosmtplib.send(msg, start_tls=True, **common)
    logger.info("Сброс пароля отправлен: %s", to_email)
    return True
