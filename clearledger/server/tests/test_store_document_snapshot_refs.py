"""Черновичный ключ карточки не должен ронять снимок документов станции.

Строка документа ссылается на карточку по `nomenclature_ref`. У карточки,
заведённой на станции и ещё не признанной в сети, ключ выглядит как
«draft-1787761317373436900» — это не UUID. Postgres на таком значении валит
ВЕСЬ запрос к edge.item, а с ним и сборку снимка: станция 208 из-за одной такой
строки месяцами не получала ни одного документа.
"""
from app.services.store_document_snapshot import _ПОХОЖ_НА_UUID


def test_chernovik_ne_prohodit_v_zapros():
    assert _ПОХОЖ_НА_UUID.fullmatch("draft-1787761317373436900") is None


def test_nastoyashchiy_uuid_prohodit():
    assert _ПОХОЖ_НА_UUID.fullmatch("000e1302-00e6-11ed-a5c5-002590317e3f")


def test_musor_ne_prohodit():
    for мусор in ("", "0", "не-uuid", "00000000-0000-0000-0000", "x" * 36):
        assert _ПОХОЖ_НА_UUID.fullmatch(мусор) is None
