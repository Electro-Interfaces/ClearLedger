"""Карта нормализованной базы пространства держится на конфиге `_ENTITIES`.

Проверка нужна потому, что ошибка в конфиге не падает, а тихо врёт витрине: дубль
ключа схлопнет две сущности в одну строку, модель без `company_id` посчитает записи
чужой компании, а условие разрыва без подписи покажет жёлтое число без объяснения.

Запуск: cd server && py -3 -m pytest tests/test_space_data_model.py -v
"""
from app.services.space_data_model import _ENTITIES


def test_config_consistent():
    keys, domains = [], []
    for dkey, dlabel, items in _ENTITIES:
        domains.append(dkey)
        assert dlabel, f"домен {dkey} без названия"
        for key, label, model, sources, consumers, link, gap_cond, gap_label in items:
            keys.append(key)
            assert label and sources and consumers and link, f"сущность {key} описана не полностью"
            # Счёт всегда в пределах компании — иначе в пространство утекут чужие записи.
            assert hasattr(model, "company_id"), f"{key}: у модели нет company_id"
            assert getattr(model, "__tablename__", None), f"{key}: у модели нет таблицы"
            # Разрыв показывается числом с подписью: одно без другого бессмысленно.
            assert (gap_cond is None) == (gap_label is None), f"{key}: условие и подпись разрыва врозь"

    assert len(keys) == len(set(keys)), "ключи сущностей повторяются"
    assert len(domains) == len(set(domains)), "ключи доменов повторяются"
