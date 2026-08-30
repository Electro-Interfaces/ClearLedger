"""Кто попадёт в очередь обращений, а кто нет.

Правило «всё остальное — в очередь» стоит последним и ловит письма, для которых
не нашлось своего правила. Ошибка здесь дорогая в обе стороны: пустишь роботов —
оператор перестанет читать очередь, где половина строк не требует ответа;
отсечёшь лишнего — обращение живого человека молча не доедет.

Запуск: cd server && py -3 -m pytest tests/test_mail_robot_sender.py -v
"""
from app.services.mail_routing import is_robot_sender


def test_people_get_through():
    for address in ("ivanov@tsm.ru", "test-client@dataworker.ru",
                    "a.petrova@rushydro.ru", "info@gig.local",
                    # «no» и «reply» сами по себе — обычные адреса живых людей.
                    "noda@example.com", "replyman@example.com"):
        assert not is_robot_sender(address), address


def test_robots_are_stopped():
    for address in ("noreply@elsyplus.ru", "no-reply@bank.ru",
                    "mailer-daemon@mail.dataworker.ru", "postmaster@corp.ru",
                    "bounces+123@sendgrid.net", "dmarc-report@google.com",
                    "notifications@github.com", "DoNotReply@Vendor.COM"):
        assert is_robot_sender(address), address


def test_empty_address_is_not_a_person():
    # Письмо без разбираемого отправителя — не обращение: отвечать некуда.
    assert is_robot_sender("")
    assert is_robot_sender(None)
    assert is_robot_sender("@example.com")
