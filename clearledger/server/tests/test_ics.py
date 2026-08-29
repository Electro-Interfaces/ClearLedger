"""Календарное приглашение: где формат ломается молча.

Файл `.ics` либо открывается, либо нет, и «не открылся» отлаживать некому:
получатель просто не придёт. Ломается он на трёх вещах — незаэкранированной
запятой в адресе, слишком длинной строке и неверном времени.

Без БД: сборка файла — чистая функция.
"""
from datetime import datetime, timezone

from app.services.ics import event_ics

НАЧАЛО = datetime(2026, 8, 31, 7, 0, tzinfo=timezone.utc)
КОНЕЦ = datetime(2026, 8, 31, 8, 0, tzinfo=timezone.utc)


def собрать(**kw) -> str:
    основа = dict(uid="ev-1@trek", title="Планёрка",
                  starts_at=НАЧАЛО, ends_at=КОНЕЦ)
    основа.update(kw)
    return event_ics(**основа)


def test_каркас_на_месте():
    текст = собрать()
    for обязательное in ("BEGIN:VCALENDAR", "VERSION:2.0", "BEGIN:VEVENT",
                         "UID:ev-1@trek", "END:VEVENT", "END:VCALENDAR"):
        assert обязательное in текст


def test_время_в_utc_с_зулусом():
    текст = собрать()
    assert "DTSTART:20260831T070000Z" in текст
    assert "DTEND:20260831T080000Z" in текст


def test_наивное_время_считается_utc():
    текст = собрать(starts_at=datetime(2026, 8, 31, 7, 0))
    assert "DTSTART:20260831T070000Z" in текст


def test_запятая_в_адресе_не_рвёт_свойство():
    # «Москва, Тверская, 1» без экранирования превращается в три значения, и
    # часть календарей на этом спотыкается.
    текст = собрать(location="Москва, Тверская, 1")
    assert "LOCATION:Москва\\, Тверская\\, 1" in текст


def test_перевод_строки_в_описании_экранируется():
    текст = собрать(description="Первое\nВторое")
    assert "DESCRIPTION:Первое\\nВторое" in текст
    # И не появляется настоящего переноса внутри значения.
    строки = [s for s in текст.split("\r\n") if s.startswith("DESCRIPTION")]
    assert len(строки) == 1


def test_длинная_строка_складывается_продолжением():
    текст = собрать(title="П" * 200)
    строки = текст.split("\r\n")
    assert all(len(s.encode("utf-8")) <= 75 for s in строки), "строка длиннее предела"
    # Продолжение начинается с пробела — по нему получатель и склеит обратно.
    assert any(s.startswith(" ") for s in строки)


def test_склейка_восстанавливает_исходный_текст():
    заголовок = "Совещание " + "Я" * 150
    текст = собрать(title=заголовок)
    собрано = ""
    беру = False
    for s in текст.split("\r\n"):
        if s.startswith("SUMMARY:"):
            собрано = s[len("SUMMARY:"):]
            беру = True
        elif беру and s.startswith(" "):
            собрано += s[1:]
        elif беру:
            break
    assert собрано == заголовок


def test_отмена_помечается_и_не_путается_с_живой():
    живая = собрать()
    отменённая = собрать(cancelled=True, sequence=1)
    assert "STATUS:CONFIRMED" in живая and "METHOD:PUBLISH" in живая
    assert "STATUS:CANCELLED" in отменённая and "METHOD:CANCEL" in отменённая
    # Тот же UID и больший SEQUENCE — иначе у получателя останутся обе.
    assert "UID:ev-1@trek" in отменённая
    assert "SEQUENCE:1" in отменённая


def test_организатор_подписан_именем():
    текст = собрать(organizer_email="a@b.ru", organizer_name="Иванов И.")
    assert "ORGANIZER;CN=Иванов И.:mailto:a@b.ru" in текст


def test_файл_кончается_переводом_строки():
    assert собрать().endswith("\r\n")
