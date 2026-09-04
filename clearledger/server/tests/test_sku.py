"""Артикул сети: длина, контрольный разряд, внутренний штрихкод."""
import pytest

from app.services import sku


def test_dlina_vsegda_devyat_i_bez_vedushchih_nuley():
    for номер in (sku.ЦЕНТР_ОТ, sku.ЦЕНТР_ДО, sku.СТАНЦИИ_ОТ, sku.СТАНЦИИ_ДО):
        код = sku.собрать(номер)
        assert len(код) == 9
        assert код.isdigit()
        assert код[0] != "0"


def test_dlina_ne_sovpadaet_so_skaniruemymi():
    # Ровно ради этого выбрана девятка: 6 — старые внутренние, 8 — EAN-8,
    # 12 — UPC-A, 13 — EAN-13, 14 — ITF-14.
    assert sku.ДЛИНА_АРТИКУЛА not in (6, 8, 12, 13, 14)


def test_razobrat_vozvrashchaet_nomer():
    for номер in (10_000_000, 12_345_678, 50_000_000, 99_999_999):
        assert sku.разобрать(sku.собрать(номер)) == номер


def test_opechatka_v_odnoy_cifre_otsekaetsya():
    код = sku.собрать(12_345_678)
    поймано = 0
    for позиция in range(len(код)):
        for цифра in "0123456789":
            if цифра == код[позиция]:
                continue
            испорчен = код[:позиция] + цифра + код[позиция + 1:]
            if sku.разобрать(испорчен) is None:
                поймано += 1
    # Контрольный разряд GS1 ловит ВСЕ одиночные подмены.
    assert поймано == len(код) * 9


def test_chuzhoe_ne_priznayotsya_artikulom():
    assert sku.разобрать("") is None
    assert sku.разобрать("4607091380014") is None      # EAN-13
    assert sku.разобрать("46235046") is None           # EAN-8
    assert sku.разобрать("0124") is None               # старое внутреннее
    assert sku.разобрать("12345678") is None           # восемь знаков
    assert sku.разобрать("1234567890") is None         # десять знаков
    assert sku.разобрать("00000001") is None           # вне диапазона
    assert not sku.это_артикул("Вода 0,5")


def test_vnutrenniy_shtrihkod_chitaetsya_obratno():
    артикул = sku.собрать(50_000_123)
    шк = sku.внутренний_штрихкод(артикул)
    assert len(шк) == 13
    assert шк.startswith("240")
    assert sku.артикул_из_штрихкода(шк) == артикул


def test_vnutrenniy_shtrihkod_tolko_iz_artikula():
    with pytest.raises(ValueError):
        sku.внутренний_штрихкод("4607091380014")


def test_chuzhoy_rcn_ne_krepitsya_k_kartochke():
    # Реальные коды из справочника 208, снятые 30.08.2026.
    assert sku.чужой_ограниченного_обращения("2008000620011")
    assert sku.чужой_ограниченного_обращения("2200000090379")
    # Наш собственный внутренний код исключение — он рождается у нас.
    свой = sku.внутренний_штрихкод(sku.собрать(50_000_001))
    assert not sku.чужой_ограниченного_обращения(свой)
    # Обычные коды производителя правило не трогает.
    assert not sku.чужой_ограниченного_обращения("4607091380014")
    assert not sku.чужой_ограниченного_обращения("46235046")
    # Короткие внутренние обозначения — не RCN, у них своя история.
    assert not sku.чужой_ограниченного_обращения("2109")


def test_bloki_idut_vstyk_i_ne_peresekayutsya():
    край = None
    диапазоны = []
    for _ in range(4):
        от, до = sku.границы_блока(край)
        диапазоны.append((от, до))
        край = до
    # Каждый блок ровного размера, начинается сразу за предыдущим.
    for i, (от, до) in enumerate(диапазоны):
        assert до - от + 1 == sku.РАЗМЕР_БЛОКА
        assert от >= sku.СТАНЦИИ_ОТ and до <= sku.СТАНЦИИ_ДО
        if i:
            assert от == диапазоны[i - 1][1] + 1
    # И ни один не залезает в центральный пул.
    assert диапазоны[0][0] == sku.СТАНЦИИ_ОТ


def test_stancionnyy_pul_ischerpan_govorit_ob_etom():
    with pytest.raises(RuntimeError):
        sku.границы_блока(sku.СТАНЦИИ_ДО)
