"""Скоуп данных по объектам: границы видимости участника.

Проверяем чистую логику `app/scope.py` — контекст запроса, условия сужения и проверку
одиночного объекта. Интеграция (что ручки реально режут) проверяется сквозным
сценарием на стенде: локальной БД в этих тестах нет.

⚠ id объектов — строковые nanoid (`ezs-7b09aa…`), НЕ UUID. Первая версия скоупа
приводила их к UUID и молча теряла весь набор — отсюда тесты именно на такие id.
"""
import pytest

from app.models import ServiceLocation
from app.scope import (
    _as_ids, current_object_scope, in_scope, scope_location_conds, set_request_scope,
)

A = "ezs-7b09aa860388ba9f0b17"
B = "rh-9aaDn40_wUCv0mg9YPYs5w"
C = "ezs-c5a16101e35bed765eac"


@pytest.fixture(autouse=True)
def _clean_scope():
    """Скоуп — контекст запроса; между тестами сбрасываем, иначе они текут."""
    set_request_scope(None)
    yield
    set_request_scope(None)


def test_без_скоупа_ограничений_нет():
    assert current_object_scope() is None
    assert scope_location_conds(ServiceLocation.id) == []
    assert in_scope(A) is True
    assert in_scope(None) is True


def test_скоуп_пускает_только_свои_объекты():
    set_request_scope([A, B])
    assert len(scope_location_conds(ServiceLocation.id)) == 1
    assert in_scope(A) is True
    assert in_scope(B) is True
    assert in_scope(C) is False


def test_строковые_id_не_теряются():
    """nanoid не UUID: набор обязан сохраниться целиком."""
    assert _as_ids([A, B, C]) == [A, B, C]


def test_запись_без_объекта_со_скоупом_не_видна():
    """Строка без привязки к объекту относится ко всей сети — участнику со скоупом
    её показывать нельзя, иначе через «общие» записи утекут чужие данные."""
    set_request_scope([A])
    assert in_scope(None) is False


def test_пустой_скоуп_это_вся_сеть_а_не_ничего():
    """Случайно сохранённый пустой набор не должен отрезать человека от всего."""
    assert _as_ids([]) is None
    assert _as_ids(None) is None
    set_request_scope(_as_ids([]))
    assert in_scope(C) is True
