"""
Правка объекта из интерфейса не должна сносить служебные ключи снимка:
по ним конвейеры находят карточку при следующей выгрузке (asuimStationId,
hubexAssetId, история номеров). До 12.08.2026 PATCH заменял снимок целиком —
карточка выпадала из индексов витрины и заводилась заново дублем.

Запуск: cd server && py -3 -m pytest tests/test_location_metadata_merge.py -v
"""
from app.routers.locations_router import _merge_metadata


def test_sluzhebnye_klyuchi_perezhivayut_pravku():
    current = {
        "asuimStationId": "03001365", "hubexAssetId": "223", "ext_id": "42919225",
        "numberHistory": [{"было": "580"}], "connectors": [{"type": "Type 2"}],
        "nameSource": "cpo_registry", "zoi1": "1780",
        "cityName": "г.Красноярск", "service": "true",
    }
    # форма присылает только то, что видит человек (и теряет структурные значения)
    incoming = {"cityName": "Красноярск", "comment": "проверено"}

    merged = _merge_metadata(current, incoming)

    for key in ("asuimStationId", "hubexAssetId", "ext_id", "numberHistory",
                "connectors", "nameSource", "zoi1"):
        assert merged[key] == current[key], f"служебный ключ {key} потерян"
    assert merged["cityName"] == "Красноярск"      # правка человека применилась
    assert merged["comment"] == "проверено"        # новое поле добавилось
    assert "service" not in merged                 # очистка поля в форме работает


def test_privyazka_k_aktivu_hubex_pravitsya_rukami():
    """Привязку к активу HubEx заводят вручную: присланное значение выигрывает,
    а отсутствие ключа в форме сохраняет прежнее (а не стирает его молча)."""
    current = {"asuimStationId": "X1", "hubexAssetId": "223", "linkStatus": "ok"}
    assert _merge_metadata(current, {"hubexAssetId": "999"})["hubexAssetId"] == "999"
    assert _merge_metadata(current, {"cityName": "Тула"})["hubexAssetId"] == "223"


def test_pustaya_pravka_ne_terjaet_snimok_i_pustoy_rezultat_eto_none():
    current = {"asuimStationId": "X1", "cityName": "Тула"}
    assert _merge_metadata(current, None) == {"asuimStationId": "X1"}
    assert _merge_metadata(None, None) is None
    assert _merge_metadata({}, {}) is None
