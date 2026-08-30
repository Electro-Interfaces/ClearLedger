"""Календарный файл приглашения: от него зависит, покажет ли почта кнопки.

Разница между «вот встреча, положи себе» и «ответьте, придёте ли» — это
`METHOD`. У `PUBLISH` кнопок «Принять · Может быть · Отклонить» не бывает ни в
одном клиенте, и приглашение превращается в уведомление. Второе условие —
`ATTENDEE`: клиент показывает кнопки, только увидев в списке САМОГО получателя,
иначе считает, что письмо не про него.

Проверка держит и обратную сторону: отмена уходит тем же `UID` с бо́льшим
`SEQUENCE`, иначе встреча не пропадёт у получателя, а удвоится.
"""
from datetime import datetime, timezone

from app.services.ics import event_ics

НАЧАЛО = datetime(2026, 9, 3, 7, 0, tzinfo=timezone.utc)
КОНЕЦ = datetime(2026, 9, 3, 8, 0, tzinfo=timezone.utc)

ОСНОВА = dict(uid="ev-1@trek", title="Планёрка", starts_at=НАЧАЛО,
              ends_at=КОНЕЦ, organizer_email="mag@dataworker.ru",
              organizer_name="МАГ")

#: Продолжение свёрнутой строки по RFC 5545: перевод строки плюс пробел.
ПЕРЕНОС = "\r\n "


def _сырой(**kw) -> str:
    """Файл как есть — для проверки самой свёртки."""
    return event_ics(**{**ОСНОВА, **kw})


def _файл(**kw) -> str:
    """Развёрнутый файл: содержимое проверяем по смыслу, свёртку — отдельно.

    Стандарт рвёт строку на 75 октетах и продолжает её пробелом. Искать в
    свёрнутом тексте `RSVP=TRUE` бессмысленно — оно может оказаться разрезано
    пополам, и проверка упадёт на правильном файле.
    """
    return _сырой(**kw).replace(ПЕРЕНОС, "")


def test_приглашение_просит_ответа():
    ics = _файл(invite=True, attendees=[("guest@example.com", "Гость")])
    assert "METHOD:REQUEST" in ics, (
        "без REQUEST почтовый клиент не покажет кнопок ответа")
    assert "PARTSTAT=NEEDS-ACTION" in ics, "ответа ещё не было — так и надо сказать"
    assert "RSVP=TRUE" in ics, "ответа не просят — клиент промолчит"
    assert "mailto:guest@example.com" in ics, (
        "получателя нет в списке — клиент решит, что письмо не про него")
    assert "ORGANIZER;CN=МАГ:mailto:mag@dataworker.ru" in ics


def test_без_приглашения_метод_прежний():
    """Лента и «положи себе» остаются PUBLISH: там отвечать некому."""
    ics = _файл()
    assert "METHOD:PUBLISH" in ics
    assert "ATTENDEE" not in ics


def test_отмена_убирает_встречу_а_не_удваивает():
    ics = _файл(cancelled=True, sequence=1,
                attendees=[("guest@example.com", None)])
    assert "METHOD:CANCEL" in ics
    assert "STATUS:CANCELLED" in ics
    assert "SEQUENCE:1" in ics, (
        "отмена с прежним SEQUENCE не заменит встречу у получателя")
    assert "UID:ev-1@trek" in ics, "другой UID оставит у получателя обе встречи"


def test_отмена_главнее_приглашения():
    """Отменённая встреча не может уехать как просьба ответить."""
    ics = _файл(invite=True, cancelled=True,
                attendees=[("guest@example.com", None)])
    assert "METHOD:CANCEL" in ics
    assert "METHOD:REQUEST" not in ics


def test_имя_без_почты_подставляется_адресом():
    ics = _файл(invite=True, attendees=[("guest@example.com", None)])
    assert "CN=guest@example.com" in ics


def test_строки_складываются_по_стандарту():
    """Строка длиннее 75 октетов обязана переноситься, иначе файл не читается."""
    ics = _сырой(title="П" * 200, invite=True,
                 attendees=[("guest@example.com", None)])
    for строка in ics.split("\r\n"):
        assert len(строка.encode("utf-8")) <= 75 or строка.startswith(" "), (
            f"строка длиннее 75 октетов и не свёрнута: {строка[:40]}…")
