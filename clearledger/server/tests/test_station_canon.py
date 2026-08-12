"""
Нормализация паспорта станции на входе: город без приставки типа, бренд в одном
написании, ключ сравнения владельцев, отбраковка координат вне России.

Из-за приставки «г./с./п.» 260 карточек пилота считались расходящимися с витриной,
из-за смеси латиницы и кириллицы 33 написания брендов жили как 33 разных бренда
(в том числе «StarСharge» с кириллической «С»), а три тест-станции стояли в Гренландии.

Запуск: cd server && py -3 -m pytest tests/test_station_canon.py -v
"""
from app.services.mapping import canon_brand, canon_city, geo_in_russia, owner_key


def test_gorod_bez_pristavki():
    assert canon_city("г.Красноярск") == "Красноярск"
    assert canon_city("с.Миасское") == "Миасское"
    assert canon_city("село Широкий Буерак") == "Широкий Буерак"
    assert canon_city("посёлок Усть-Ордынский") == "Усть-Ордынский"
    assert canon_city("Владивосток") == "Владивосток"      # уже канон
    assert canon_city("  Самара  ") == "Самара"
    assert canon_city(None) is None


def test_brend_v_odnom_napisanii():
    assert canon_brand("Фора") == canon_brand("FORA") == canon_brand("Fora") == "FORA"
    assert canon_brand("ПСС (Россия)") == canon_brand("ПСС") == "ПСС"
    assert canon_brand("Реватт") == canon_brand("REWATT") == "REWATT"
    # кириллическая «С» внутри латинского слова — тот же бренд
    assert canon_brand("StarСharge") == canon_brand("StarCharge") == "StarCharge"
    assert canon_brand("E-PROM") == canon_brand("EPROM") == "EPROM"
    assert canon_brand("Неизвестный бренд") == "Неизвестный бренд"   # чужое не портим
    assert canon_brand("") is None


def test_klyuch_vladeltsa_snimaet_pravovuyu_formu():
    assert owner_key("ООО СНК") == owner_key("СНК") == "снк"
    assert owner_key('АО "РусГидро"') == owner_key("РусГидро") == "русгидро"
    assert owner_key("ООО Доступная энергия") != owner_key("РусГидро")


def test_koordinaty_vne_rossii_otbrakovyvayutsya():
    assert geo_in_russia(55.75, 37.62)          # Москва
    assert geo_in_russia(43.11, 131.87)         # Владивосток
    assert not geo_in_russia(69.22, -51.10)     # Гренландия
    assert not geo_in_russia(81.0, -17.0)       # Арктика западнее РФ
    assert not geo_in_russia(None, None)
