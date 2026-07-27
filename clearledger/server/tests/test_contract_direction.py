"""Направление договора выводится из вида (`Contract.kind`), отдельной колонки нет.

Проверка нужна потому, что на этом выводе стоит фильтр «Входящие/Исходящие» в
реестре договоров пространства: ошибка в карте видов молча показывает арендодателя
как покупателя.

Запуск: cd server && py -3 -m pytest tests/test_contract_direction.py -v
"""
from app.services.space_registry import contract_direction


def test_direction_by_kind():
    assert contract_direction("СПоставщиком") == "in"       # мы платим (аренда, энергия)
    assert contract_direction("СТранспортнойКомпанией") == "in"
    assert contract_direction("СПокупателем") == "out"      # платят нам (корпклиент ЭЗС)
    assert contract_direction("СКомиссионером") == "out"
    assert contract_direction(None) == "unknown"            # вид не задан
    assert contract_direction("") == "unknown"
    assert contract_direction("НечтоНовое") == "unknown"    # неизвестный вид не врёт
