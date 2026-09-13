"""Ставка НДС для строки чека добирается из карточки станции.

Агент кладёт в строку `vat_rate: null` — контур он проставляет, ставку нет.
Одна такая строка уводила в карантин весь чек, а с ним и смену: на 208 так
стояли 784 чека из 1155, и НДС не был посчитан ни у одного.
"""
from decimal import Decimal

from app.services.store_documents import (
    ИМЯ_ПРЕФИКС,
    _ключ_имени,
    cheque_lines_from_catalog,
    goods_only_cheque_totals,
)

СИГАРЕТЫ = "ece7df4b-ff0e-11ef-bdd7-0050568cc25a"
БУЛОЧКА = "11111111-2222-3333-4444-555555555555"


def строка(uuid_: str, сумма: str, **прочее) -> dict:
    """Строка чека в том виде, в каком её реально шлёт агент 208."""
    return {
        "qty": 1.0, "name": "позиция", "price": float(сумма),
        "amount": float(сумма), "ns_code": 737, "section": 2,
        "scope": "store", "scope_source": "edge_fiscal_receipts_filtered_v1",
        "item_uuid": uuid_, "vat_rate": None, "vat_amount": None,
        **прочее,
    }


def test_bez_stavki_ves_chek_v_karantine():
    итоги = goods_only_cheque_totals([строка(СИГАРЕТЫ, "210")], had_fuel=False)
    assert итоги["quarantined"] is True
    assert итоги["vat_amount"] is None


def test_stavka_iz_spravochnika_podnimaet_chek():
    строки = cheque_lines_from_catalog(
        [строка(СИГАРЕТЫ, "210")], {СИГАРЕТЫ: {"vat_rate": "НДС22"}})
    итоги = goods_only_cheque_totals(строки, had_fuel=False)
    assert итоги["quarantined"] is False
    assert итоги["amount"] == Decimal("210.00")
    assert итоги["vat_amount"] == Decimal("37.87")  # 210 × 22/122
    assert строки[0]["enriched_from"] == "catalog"


def test_raznye_stavki_schitayutsya_kazhdaya_svoey():
    строки = cheque_lines_from_catalog(
        [строка(СИГАРЕТЫ, "210"), строка(БУЛОЧКА, "110")],
        {СИГАРЕТЫ: {"vat_rate": "НДС22"}, БУЛОЧКА: {"vat_rate": "НДС10"}})
    итоги = goods_only_cheque_totals(строки, had_fuel=False)
    assert итоги["quarantined"] is False
    assert итоги["amount"] == Decimal("320.00")
    assert итоги["vat_amount"] == Decimal("47.87")  # 37.87 + 10.00


def test_stanciya_glavnee_spravochnika():
    """Если станция ставку прислала — свою не навязываем."""
    своя = строка(СИГАРЕТЫ, "210")
    своя["vat_rate"] = "НДС10"
    строки = cheque_lines_from_catalog([своя], {СИГАРЕТЫ: {"vat_rate": "НДС22"}})
    assert строки[0]["vat_rate"] == "НДС10"
    assert "enriched_from" not in строки[0]


def test_neizvestnaya_kartochka_ostavlyaet_karantin():
    """Молча обнулять НДС нельзя — чек должен остаться на виду."""
    строки = cheque_lines_from_catalog([строка(БУЛОЧКА, "110")], {СИГАРЕТЫ: {"vat_rate": "НДС22"}})
    итоги = goods_only_cheque_totals(строки, had_fuel=False)
    assert итоги["quarantined"] is True


def test_pustoy_spravochnik_nichego_ne_menyaet():
    исходные = [строка(СИГАРЕТЫ, "210")]
    assert cheque_lines_from_catalog(исходные, {}) is исходные


def test_kontur_iz_spravochnika_dlya_staryh_chekov():
    """У чеков старше внедрения фильтра нет и контура — карточка даёт его тоже.

    Иначе контур держится только на побайтовом совпадении с сырым пакетом,
    и чистка архива пакетов обнуляет выручку задним числом.
    """
    старая = строка(СИГАРЕТЫ, "210")
    del старая["scope"], старая["scope_source"]
    строки = cheque_lines_from_catalog(
        [старая], {СИГАРЕТЫ: {"vat_rate": "НДС22", "scope": "store"}})
    итоги = goods_only_cheque_totals(строки, had_fuel=False)
    assert итоги["quarantined"] is False
    assert итоги["amount"] == Decimal("210.00")
    assert итоги["vat_amount"] == Decimal("37.87")


def test_toplivo_iz_spravochnika_ne_popadaet_v_tovarnuyu_summu():
    """Смешанный чек: топливная строка не должна раздувать выручку магазина."""
    товар = строка(СИГАРЕТЫ, "210")
    топливо = строка("99999999-0000-0000-0000-000000000000", "3000")
    del топливо["scope"], топливо["scope_source"]
    строки = cheque_lines_from_catalog(
        [товар, топливо],
        {СИГАРЕТЫ: {"vat_rate": "НДС22", "scope": "store"},
         "99999999-0000-0000-0000-000000000000": {"scope": "fuel"}})
    итоги = goods_only_cheque_totals(строки, had_fuel=True)
    assert итоги["quarantined"] is False
    assert итоги["amount"] == Decimal("210.00")
    assert итоги["fuel_lines"] == 1


# ─── Карточка сменила идентификатор ──────────────────────────────────
#
# Слияние дублей и перезаливка НСИ уносят прежний ключ карточки, а чек,
# пробитый до этого, хранит его навсегда. На 208 так встали 19 чеков и 6 смен
# за 26.08–03.09: двенадцать позиций (три «Любимых аромата», Coca-Cola, PEPSI,
# четыре черновика станции) искались по идентификаторам, которых больше нет ни
# в каталоге, ни на станции. Имя переживает и слияние, и перезаливку.

ПРОПАВШИЙ = "2cf111ac-1036-4281-9dcd-e8791c48b069"


def test_kartochka_nahoditsya_po_imeni_kogda_uuid_ustarel():
    строка_чека = строка(ПРОПАВШИЙ, "110")
    # Касса режет имя по сорока знакам, в каталоге оно полное.
    строка_чека["name"] = "Напиток Coca-Cola Вишня газ 0,33 л ж/б"
    справочник = {
        ИМЯ_ПРЕФИКС + _ключ_имени("Напиток Coca-Cola Вишня газ 0,33 л ж/б"):
            {"vat_rate": "НДС22", "scope": "store"},
    }
    строки = cheque_lines_from_catalog([строка_чека], справочник)
    итоги = goods_only_cheque_totals(строки, had_fuel=False)
    assert итоги["quarantined"] is False
    assert итоги["vat_amount"] == Decimal("19.84")  # 110 × 22/122
    assert строки[0]["enriched_from"] == "catalog"


def test_obrezannoe_kassoy_imya_nahodit_polnuyu_kartochku():
    строка_чека = строка("00000000-0000-0000-0000-000000000000", "65")
    строка_чека["name"] = "Напиток Coca-Cola Vanilla 0,33 л (Герман"
    справочник = {
        ИМЯ_ПРЕФИКС + _ключ_имени("Напиток Coca-Cola Vanilla 0,33 л (Германия)"):
            {"vat_rate": "НДС22", "scope": "store"},
    }
    строки = cheque_lines_from_catalog([строка_чека], справочник)
    assert goods_only_cheque_totals(строки, had_fuel=False)["quarantined"] is False


def test_svoy_uuid_glavnee_imeni():
    """Совпадение по идентификатору не должно уступать совпадению по имени."""
    строка_чека = строка(СИГАРЕТЫ, "210")
    строка_чека["name"] = "позиция"
    справочник = {
        СИГАРЕТЫ: {"vat_rate": "НДС22"},
        ИМЯ_ПРЕФИКС + _ключ_имени("позиция"): {"vat_rate": "НДС10"},
    }
    строки = cheque_lines_from_catalog([строка_чека], справочник)
    assert goods_only_cheque_totals(строки, had_fuel=False)["vat_amount"] == Decimal("37.87")


def test_tyozka_v_spravochnik_imen_ne_popadaet():
    """Имя, за которым стоят две живые карточки, обогащать не вправе.

    Ключ выбывает при сборке справочника (load_item_catalog), здесь проверяем
    договор: в справочнике его нет — строка остаётся в карантине, а не берёт
    ставку первой попавшейся карточки.
    """
    строка_чека = строка("11111111-1111-1111-1111-111111111111", "100")
    строка_чека["name"] = "Вода питьевая 0,5 л"
    строки = cheque_lines_from_catalog([строка_чека], {СИГАРЕТЫ: {"vat_rate": "НДС22"}})
    assert goods_only_cheque_totals(строки, had_fuel=False)["quarantined"] is True
