"""Контур рабочей области доезжает до экранов, которые его показывают.

Класс дефекта, ради которого написан файл: панель фильтров сверху обещает
«Приморский край · ЭЗС 648», а экран под ней считает по всей сети. Так вели себя
«Платежи и чеки» (27 887 платежей и 5 млн ₽ на 11 станциях МЗК) и «Оборудование»
(склады Хабаровска при выбранном Приморье) — жалобы заказчика 24–25.08.2026.

Проверяем не «есть ли параметр», а собранный SQL: параметр можно принять и
потерять.
"""
from uuid import uuid4

from sqlalchemy.dialects import postgresql

from app.routers.charge_sessions_router import _payment_scope_cond
from app.routers.equipment_router import _scope_location_ids


def _sql(clause) -> str:
    return str(clause.compile(dialect=postgresql.dialect(),
                              compile_kwargs={"literal_binds": True}))


def test_payments_without_scope_are_not_narrowed():
    """Пустой контур не сужает: иначе платежи без сессии молча исчезли бы всегда."""
    assert _payment_scope_cond(uuid4(), [], []) is None


def test_payments_narrow_through_their_session():
    """У платежа нет своей станции — связь только через session_ext_id."""
    sql = _sql(_payment_scope_cond(uuid4(), ["694", "677"], []))

    assert "charge_payments.session_ext_id IN" in sql
    assert "FROM charge_sessions" in sql
    assert "station_code IN ('694', '677')" in sql


def test_payments_narrow_by_region_through_object_registry():
    """Регион — только каноном (объект → regions.name), не денорм-колонкой."""
    sql = _sql(_payment_scope_cond(uuid4(), [], ["Московская область"]))

    assert "service_locations" in sql and "regions" in sql
    assert "charge_sessions.region" not in sql


def test_equipment_without_scope_is_not_narrowed():
    assert _scope_location_ids(uuid4(), [], [], []) is None


def test_equipment_scope_is_union_of_dimensions():
    """Точка входит в контур по любому измерению — как на карте."""
    sql = _sql(_scope_location_ids(uuid4(), ["Приморский край"], ["648"], ["loc-1"]))

    assert "regions.name IN ('Приморский край')" in sql
    assert "service_locations.code IN ('648')" in sql
    assert "service_locations.id IN ('loc-1')" in sql
    assert sql.count(" OR ") == 2


def test_equipment_scope_keeps_company_boundary():
    """Компания в подзапросе обязательна: иначе чужие точки расширят контур."""
    cid = uuid4()
    sql = _sql(_scope_location_ids(cid, ["Приморский край"], [], []))

    assert f"service_locations.company_id = '{cid}'" in sql
    assert f"regions.company_id = '{cid}'" in sql
