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
from app.routers.equipment_router import ScopeQ, _scope_location_ids, _vendor_col


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


def test_station_code_is_matched_by_passport_number_too():
    """Код станции из фильтра — это `charge_sessions.station_code`.

    С `service_locations.code` он совпадает лишь у 88 станций из 461, у остальных
    номер лежит в паспорте (441 совпадение). Сверка только по `code` давала бы
    пустой список на большинстве станций — и выглядела бы как «оборудования нет».
    """
    sql = _sql(_scope_location_ids(uuid4(), [], ["648"], []))

    assert "service_locations.code IN ('648')" in sql
    assert "extra_metadata" in sql and "number" in sql
    assert " OR " in sql


def test_equipment_scope_keeps_company_boundary():
    """Компания в подзапросе обязательна: иначе чужие точки расширят контур."""
    cid = uuid4()
    sql = _sql(_scope_location_ids(cid, ["Приморский край"], [], []))

    assert f"service_locations.company_id = '{cid}'" in sql
    assert f"regions.company_id = '{cid}'" in sql


def test_equipment_scope_is_shared_by_the_whole_section():
    """Один приёмник контура на раздел: парк, склады и движения читают его одинаково."""
    q = ScopeQ(region_ids="Приморский край", station_codes="648", location_ids=None)

    assert not q.empty
    assert q.regions == ["Приморский край"] and q.codes == ["648"]
    assert ScopeQ(None, None, None).empty
    assert ScopeQ(None, None, None).unit_cond(uuid4()) is None


def test_equipment_unit_in_scope_by_its_own_region_too():
    """Склад стоит в регионе, но точкой сети не является — его нельзя терять."""
    sql = _sql(ScopeQ(region_ids="Приморский край", station_codes=None,
                      location_ids=None).unit_cond(uuid4()))

    assert "current_location_id IN" in sql
    assert "ezs_equipment_units.region IN ('Приморский край')" in sql
    assert " OR " in sql


def test_equipment_scope_by_codes_only_does_not_widen_by_region():
    """Без регионов расширять выдачу собственным регионом единицы нечем."""
    sql = _sql(ScopeQ(region_ids=None, station_codes="648", location_ids=None).unit_cond(uuid4()))

    assert "ezs_equipment_units.region" not in sql


def test_vendor_grouping_uses_one_expression():
    """Разрез по производителю: SELECT и GROUP BY обязаны совпасть буквально.

    Каждый вызов `_vendor_col()` заводит СВОЙ bind-параметр для `nullif(vendor, '')`,
    и Postgres перестаёт узнавать выражение в GROUP BY — обзор оборудования падал
    целиком (GroupingError), пока колонка бралась двумя вызовами.
    """
    from sqlalchemy import func, select

    def raw(stmt) -> str:
        return str(stmt.compile(dialect=postgresql.dialect()))

    two = raw(select(_vendor_col(), func.count()).group_by(_vendor_col()))
    col = _vendor_col()
    one = raw(select(col, func.count()).group_by(col))

    sel_two, grp_two = two.split("GROUP BY")
    sel_one, grp_one = one.split("GROUP BY")

    assert grp_one.strip() in sel_one          # один вызов — выражения совпали
    assert grp_two.strip() not in sel_two      # два вызова — разошлись
