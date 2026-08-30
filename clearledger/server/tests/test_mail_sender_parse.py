"""Разбор отправителя письма.

Ошибка здесь не видна: письмо принимается, но приходит «ни от кого» —
корреспондент не опознан, правила не срабатывают, обращение не заводится, и в
журнале при этом ни одной ошибки. Поэтому проверяем именно те формы заголовка,
которые пишут живые люди.

Запуск: cd server && py -3 -m pytest tests/test_mail_sender_parse.py -v
"""
from email.header import Header
from email.message import Message

from app.services.mail_intake import sender_of


def _msg(from_header: str) -> Message:
    m = Message()
    m["From"] = from_header
    return m


def test_plain_address():
    assert sender_of(_msg("ivanov@romashka.ru"))[1] == "ivanov@romashka.ru"


def test_name_and_address():
    name, address = sender_of(_msg("Иван Иванов <ivanov@romashka.ru>"))
    assert address == "ivanov@romashka.ru"
    assert "Иванов" in name


def test_comma_in_name_does_not_eat_the_address():
    # Так подписывается каждый второй: должность или компания через запятую.
    for header in ("Иванов И.И., ООО Ромашка <ivanov@romashka.ru>",
                   "Сидорова Анна, ООО ГИГ <inbox@gig.dataworker.ru>",
                   "Petrov, Sales <petrov@example.com>"):
        _, address = sender_of(_msg(header))
        assert "@" in address, header


def test_encoded_name():
    header = f"{Header('Сидорова Анна, ООО ГИГ', 'utf-8')} <inbox@gig.dataworker.ru>"
    _, address = sender_of(_msg(header))
    assert address == "inbox@gig.dataworker.ru"


def test_no_address_stays_empty():
    assert sender_of(_msg("Аноним"))[1] == ""
