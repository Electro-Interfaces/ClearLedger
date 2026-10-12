"""Находки по снимку остатков: касса сравнивается только с залом (вымышленные данные)."""
from app.services.edge_service import analyze_stock, build_alerts


def _книга(uid, qty, место="208", шк="1", имя="Товар"):
    return {"Номенклатура": uid, "Остаток": qty, "Место": место, "ШтрихКод": шк, "Наименование": имя}


def _касса(uid, qty, код=500, шк="1", **kw):
    return {"Номенклатура": uid, "Остаток": qty, "КодНС": код, "ШтрихКод": шк,
            "Наименование": "Товар", "Цена": 10, "СтавкаНДСПроцент": 22, **kw}


def test_ostatok_tolko_na_sklade_ne_trevoga():
    doc = {"Касса": [_касса("a", 0)], "Учет": [_книга("a", 30, место="20800002")]}
    assert analyze_stock(doc, hall="208")["totals"]["cannot_sell"] == 0
    assert analyze_stock(doc)["totals"]["cannot_sell"] == 1          # без зала — прежнее поведение


def test_ostatok_v_zale_pri_nule_kassy_trevoga():
    doc = {"Касса": [_касса("a", 0)], "Учет": [_книга("a", 1), _книга("a", 5, место="20800002")]}
    out = analyze_stock(doc, hall="208")
    assert out["totals"]["cannot_sell"] == 1 and out["cannot_sell"][0]["book_qty"] == 1


def test_syryo_bez_stroki_kassy_ne_propazha():
    doc = {"Касса": [], "Учет": [_книга("raw", 700), _книга("tovar", 2)]}
    out = analyze_stock(doc, hall="208", raw={"raw"})
    assert [r["item"] for r in out["missing_in_cash"]] == ["tovar"]


def test_minus_po_kartochke_a_ne_po_stroke():
    doc = {"Касса": [], "Учет": [
        _книга("a", 5, шк=""), _книга("a", -5, шк="1"),              # в сумме ноль — не минус
        _книга("b", -2), _книга("b", 10, место="20800002"),           # минус в зале не гасится складом
        _книга("", 100, шк="9"), _книга("c", -40, шк="9")]}           # строка без карточки карточку не гасит
    out = analyze_stock(doc, hall="208")
    assert sorted((r["item"], r["qty"]) for r in out["negative_book"]) == [("b", -2.0), ("c", -40.0)]


def test_tekst_bez_knopki_1s():
    doc = {"Касса": [], "Учет": [_книга("tovar", 2)]}
    out = analyze_stock(doc, hall="208")
    out["available"] = True
    тексты = " ".join(a["text"] for a in build_alerts(out))
    assert "нет строки кассы" in тексты and "ККМ" not in тексты
