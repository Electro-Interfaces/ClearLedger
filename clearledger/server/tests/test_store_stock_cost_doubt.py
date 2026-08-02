"""Партийной себестоимости остатка верить можно не всегда.

На складе 208 из 573 позиций с партийной себестоимостью 48 имели её выше розничной цены
(маржа −15%), а 66 — вдвое ниже реальной закупки (маржа 65% вместо 23%). Такие цифры
не должны попадать в сводную «потенц. маржу», иначе плитка живёт своей жизнью.
"""
from app.services.goods_dashboard import _cost_doubt


def test_partiya_vyshe_ceny_ne_verim():
    # Kent Nano mix: партия 277,05 при цене 240 — маржа ушла бы в минус
    assert _cost_doubt(277.05, 240.0, 186.84) == "выше розничной цены"


def test_partiya_vdvoe_nizhe_zakupki_ne_verim():
    # Winston XS Silver: партия 93,96 при закупке 206,10 — «маржа 64,9%» фальшивая
    assert _cost_doubt(93.96, 268.0, 206.10) is not None


def test_normalnaya_partiya_prohodit():
    # Camel Compact: партия 196,60 при цене 210 — сигаретная маржа 6%, это правда
    assert _cost_doubt(196.60, 210.0, 161.15) is None


def test_bez_zakupok_sudim_tolko_po_cene():
    assert _cost_doubt(120.0, 200.0, None) is None
    assert _cost_doubt(220.0, 200.0, None) == "выше розничной цены"


def test_bez_partii_nechego_proveryat():
    assert _cost_doubt(None, 200.0, 150.0) is None
