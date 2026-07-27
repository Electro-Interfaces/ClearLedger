"""Сопоставление ролей с карточками контрагентов держится на двух вещах: конфиге
`_LINKS` (какое текстовое поле какой ссылке соответствует) и фильтре `_usable`.

Ошибка в паре полей молча свяжет не то (подрядчика запишет в поставщики), а дырявый
фильтр заведёт в общем справочнике карточки «-» и «информация уточняется» — их потом
руками не вычистить, потому что на них уже будут ссылки.

Запуск: cd server && py -3 -m pytest tests/test_space_links.py -v
"""
from app.services.space_links import _LINKS, _usable


def test_config_consistent():
    keys = []
    for key, label, model, text_col, fk_col, alias in _LINKS:
        keys.append(key)
        assert label and alias, f"связь {key} описана не полностью"
        assert hasattr(model, "company_id"), f"{key}: у модели нет company_id"
        # Оба поля — той же таблицы, иначе UPDATE уйдёт мимо.
        assert text_col.parent.class_ is model, f"{key}: текстовое поле из другой модели"
        assert fk_col.parent.class_ is model, f"{key}: поле ссылки из другой модели"
        assert fk_col.key.endswith("counterparty_id"), f"{key}: ссылка ведёт не на контрагента"
    assert len(keys) == len(set(keys)), "ключи связей повторяются"


def test_usable_filters_junk():
    assert _usable('ООО "Ромашка"')
    assert _usable("ИП Иванов И.И.")
    for junk in ("-", "—", "", "  ", "нет", "н/д", "информация уточняется",
                 "не определен", "отсутствует", "..."):
        assert not _usable(junk), f"мусор прошёл фильтр: {junk!r}"
