"""Календарное приглашение в формате iCalendar (RFC 5545).

Без него внешний участник не придёт: письмо со ссылкой он прочтёт, а в свой
календарь встречу не положит — и в нужный час будет занят другим. Файл `.ics`
кладёт её туда одним нажатием, независимо от того, чем человек пользуется.

Делаем ровно `VEVENT`, и делаем его руками: библиотека ради полутора десятков
строк потянула бы свою модель времени и свои представления о часовых поясах, а
у нас они уже есть (`space_time`). Полного iMIP тут нет — `METHOD:REQUEST` с
разбором ответов это отдельная работа; здесь честная выгрузка встречи.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

# Длина строки по стандарту — 75 октетов; всё, что длиннее, складывается
# продолжением. Календари, которым это безразлично, встречаются, но Outlook к
# длинным строкам придирчив, и «файл не открылся» отлаживать некому.
_ПРЕДЕЛ = 73


def _escape(value: str) -> str:
    """Экранирование по стандарту: запятая, точка с запятой и перевод строки —
    служебные символы, и место встречи «Москва, Тверская, 1» без этого рвёт
    свойство на три."""
    return (value or "").replace("\\", "\\\\").replace("\n", "\\n") \
        .replace(",", "\\,").replace(";", "\\;")


def _fold(line: str) -> str:
    """Свернуть длинную строку продолжением (пробел в начале следующей)."""
    out = []
    while len(line.encode("utf-8")) > _ПРЕДЕЛ:
        # Режем по символам, а не по байтам: разрубленный посередине символ
        # превращает файл в мусор.
        кусок = line
        while len(кусок.encode("utf-8")) > _ПРЕДЕЛ:
            кусок = кусок[:-1]
        out.append(кусок)
        line = " " + line[len(кусок):]
    out.append(line)
    return "\r\n".join(out)


def _stamp(value: datetime) -> str:
    """UTC в виде `20260831T100000Z`. Всё уходит в UTC намеренно: пояс встречи
    остаётся в её собственном поле, а календарь получателя покажет её по своим
    часам — это и есть правильное поведение."""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _with_join(description: str | None, location: str | None,
               join_url: str | None) -> tuple[str | None, str | None]:
    """Ссылка на видеовстречу — в «Место» и в описание.

    Поле `URL` календари почти не показывают: в Outlook, VK и Gmail встреча
    приходила с «Местом: Конференция» и без ссылки, и в нужный час войти было
    не с чего (QA 27.10.2026). Ссылку в «Месте» они делают нажимаемой, в
    описании её видят все остальные.
    """
    if not join_url:
        return description, location
    if join_url not in (description or ""):
        description = f"{description}\n\nВидеовстреча: {join_url}" if description else f"Видеовстреча: {join_url}"
    return description, location or join_url


def _when(starts_at: datetime, ends_at: datetime, all_day: bool, tz: str | None) -> list[str]:
    """`DTSTART`/`DTEND`. Событие на весь день — датами (`VALUE=DATE`), а не
    моментами: иначе VK, Outlook и Google кладут его встречей «00:00–00:00» по
    часам получателя, а у живущего в другом поясе оно съезжает на соседний день.
    Конец по стандарту исключительный: день ПОСЛЕ последнего (QA 27.10.2026)."""
    if not all_day:
        return [f"DTSTART:{_stamp(starts_at)}", f"DTEND:{_stamp(ends_at)}"]
    from app.services import space_time

    пояс = space_time.zone(tz)
    первый = space_time.as_utc(starts_at).astimezone(пояс)
    конец = space_time.as_utc(ends_at).astimezone(пояс)
    после = конец.date() if конец.time() == datetime.min.time() else конец.date() + timedelta(days=1)
    после = max(после, первый.date() + timedelta(days=1))
    return [f"DTSTART;VALUE=DATE:{первый:%Y%m%d}", f"DTEND;VALUE=DATE:{после:%Y%m%d}"]


def event_ics(*, uid: str, title: str, starts_at: datetime, ends_at: datetime,
              description: str | None = None, location: str | None = None,
              url: str | None = None, organizer_email: str | None = None,
              organizer_name: str | None = None,
              attendees: list[tuple[str, str | None]] | None = None,
              invite: bool = False,
              cancelled: bool = False, sequence: int = 0,
              all_day: bool = False, tz: str | None = None,
              join_url: str | None = None) -> str:
    """Одна встреча файлом.

    `SEQUENCE` и `STATUS:CANCELLED` — то, чем отмена доезжает до чужого
    календаря. Прислать отмену тем же `UID` с большим `SEQUENCE` значит убрать
    встречу у получателя; прислать новый `UID` значит оставить у него обе.

    `invite=True` превращает файл в приглашение (`METHOD:REQUEST`): почтовый
    клиент показывает «Принять · Может быть · Отклонить» только у него, у
    `PUBLISH` кнопок не бывает — это «вот встреча, положи себе». Приглашение
    без `ATTENDEE` тоже кнопок не даёт: клиенту нужно увидеть В СПИСКЕ себя,
    иначе он считает, что письмо не про него.
    """
    метод = ("CANCEL" if cancelled else "REQUEST" if invite else "PUBLISH")
    строки = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ElsyPlus//Trek//RU",
        "CALSCALE:GREGORIAN",
        f"METHOD:{метод}",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{_stamp(datetime.now(timezone.utc))}",
        *_when(starts_at, ends_at, all_day, tz),
        f"SEQUENCE:{sequence}",
        f"SUMMARY:{_escape(title)}",
        f"STATUS:{'CANCELLED' if cancelled else 'CONFIRMED'}",
    ]
    description, location = _with_join(description, location, join_url)
    if description:
        строки.append(f"DESCRIPTION:{_escape(description)}")
    if location:
        строки.append(f"LOCATION:{_escape(location)}")
    if url:
        строки.append(f"URL:{_escape(url)}")
    if organizer_email:
        имя = _escape(organizer_name or organizer_email)
        строки.append(f"ORGANIZER;CN={имя}:mailto:{organizer_email}")
    for почта, имя_гостя in (attendees or []):
        # `RSVP=TRUE` — просьба ответить, `NEEDS-ACTION` — ответа ещё не было.
        # Без них клиент показывает встречу как уже принятую, и человек не
        # понимает, что от него чего-то ждут.
        строки.append(
            f"ATTENDEE;CN={_escape(имя_гостя or почта)};ROLE=REQ-PARTICIPANT;"
            f"PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{почта}")
    строки += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(s) for s in строки) + "\r\n"


def calendar_ics(events: list[dict], *, name: str = "Трек") -> str:
    """Много встреч одним календарём — для ленты подписки.

    `X-WR-CALNAME` не входит в стандарт, но именно его читают Google, Apple и
    Outlook, показывая имя подписки. Без него лента называется у человека своим
    адресом, и три подписки становятся неразличимы.

    `REFRESH-INTERVAL` — просьба, а не обязательство: Google обновляет подписки
    раз в 12–48 часов, и обещать человеку большее нечестно.
    """
    строки = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//ElsyPlus//Trek//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{_escape(name)}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT1H",
        "X-PUBLISHED-TTL:PT1H",
    ]
    for e in events:
        строки += [
            "BEGIN:VEVENT",
            f"UID:{e['uid']}",
            f"DTSTAMP:{_stamp(datetime.now(timezone.utc))}",
            *_when(e["starts_at"], e["ends_at"], e.get("all_day", False), e.get("tz")),
            f"SUMMARY:{_escape(e['title'])}",
            f"STATUS:{'CANCELLED' if e.get('cancelled') else 'CONFIRMED'}",
        ]
        описание, место = _with_join(e.get("description"), e.get("location"), e.get("join_url"))
        if описание:
            строки.append(f"DESCRIPTION:{_escape(описание)}")
        if место:
            строки.append(f"LOCATION:{_escape(место)}")
        if e.get("url"):
            строки.append(f"URL:{_escape(e['url'])}")
        строки.append("END:VEVENT")
    строки.append("END:VCALENDAR")
    return "\r\n".join(_fold(x) for x in строки) + "\r\n"
