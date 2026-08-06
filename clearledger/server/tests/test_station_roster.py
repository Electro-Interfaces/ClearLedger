"""Ростер станции: проверка чистой логики доступа _covers.

Мост станция↔объект и SQL тривиальны; нетривиально — кого включать в ростер.
"""
from app.services.station_roster import _covers


def test_covers_доступ_к_станции():
    # NULL-скоуп — вся сеть: видит любую станцию.
    assert _covers(None, "ezs-208", False) is True
    # Станция явно в скоупе — видит.
    assert _covers(["ezs-208", "ezs-9"], "ezs-208", False) is True
    # Чужая станция в скоупе — не видит.
    assert _covers(["ezs-9"], "ezs-208", False) is False
    # Суперадмин — везде, даже с чужим скоупом.
    assert _covers(["ezs-9"], "ezs-208", True) is True
    # Станция не размечена (loc_id=None) и скоуп ограничен — не пускаем.
    assert _covers(["ezs-208"], None, False) is False
    # …но суперадмина пускаем и без разметки.
    assert _covers(["ezs-208"], None, True) is True
