"""Станцию находят по любому её номеру: новому, бухгалтерскому, прежним.

Витрина АСУиМ переводит парк на номер по приказу: Тайшет был «359», стал
«381-0019». Сессии прошлых дней остаются под старым номером, новые приходят под
новым. Пока фильтр сравнивал текст номера, «381-0019» давал 36 сессий Тайшета из
630, а «359» — 594 (сверка 25.09.2026 на rushydro). Сам запрос проверен на живой
базе; здесь — что он собирается и не теряет своих правил.
"""
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from app.models import ChargeSession as S
from app.services.session_scope import (
    session_scope_conds, station_locations_sql, station_match)

CID = "3fa2698f-eb02-4c21-9e26-c51a0ae62268"


def test_ищет_по_основному_бухгалтерскому_и_прежним_номерам():
    sql = station_locations_sql()
    assert "sl.station_number = ANY" in sql
    assert "'buNumber'" in sql
    assert "'numberHistory'" in sql
    # Номер, который есть только на сессиях, ведёт к станции этих сессий.
    assert "s9.station_code" in sql


def test_чужой_текущий_номер_не_подменяется_старым():
    # Прежний и бухгалтерский номер работают, только если этот номер сейчас
    # никому не принадлежит как основной: иначе «580» подмешал бы зарядки
    # другой карточки, у которой 580 когда-то был.
    sql = station_locations_sql()
    assert "NOT EXISTS (SELECT 1 FROM service_locations o" in sql
    assert "o.station_number = x" in sql


def test_два_условия_в_одном_запросе_не_делят_параметры():
    q = select(S.id).where(
        station_match(S.station_code, S.location_id, CID, ["359"]),
        *session_scope_conds(CID, ["591-0019", "708"]))
    c = q.compile(dialect=postgresql.asyncpg.dialect())
    assert c.params["st_codes_1"] == ["359"]
    assert c.params["st_codes_2"] == ["591-0019", "708"]
