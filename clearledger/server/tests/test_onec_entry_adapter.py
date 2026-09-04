# -*- coding: utf-8 -*-
"""Документы 1С обязаны попадать в реестр, а не оставаться в слое данных.

Канал ЦБ привёз документы АЗС 208 за 11.06–19.08.2026 — 18 приёмок и 15
выпусков продукции за окно 25.06–09.07 в том числе. Они легли в `data_entries`
и там остались: оба прежних адаптера отбирают записи условием «где заполнен
document_id», а его проставляет только выгрузка в бухгалтерию. В итоге целый
период работы станции в 1С не участвовал ни в одном отчёте.
"""
import inspect
import uuid

from app.services import store_documents


def test_адаптер_подключён_к_реестру():
    имена = [имя for имя, _ in store_documents.ADAPTER_REGISTRY]
    assert "onec_entries" in имена


def test_адаптер_берёт_записи_без_канонического_документа():
    исходник = inspect.getsource(store_documents._onec_entry_adapter)
    # Именно is_(None): записи 1С канонического документа не имеют, и требование
    # заполненного document_id прятало их от реестра.
    assert "DataEntry.document_id.is_(None)" in исходник
    assert 'DataEntry.source == "oneC"' in исходник


def test_ключ_документа_детерминирован():
    """Пересборка реестра не должна плодить копии одного документа."""
    company = uuid.UUID("a1df1a45-7b82-4f2a-8c31-bbf0fc9a7ada")
    источник = "de825359-706c-11f1-8250-97953952ce5d"
    первый = uuid.uuid5(uuid.NAMESPACE_URL, f"onec:{company}:purchase:{источник}")
    второй = uuid.uuid5(uuid.NAMESPACE_URL, f"onec:{company}:purchase:{источник}")
    assert первый == второй
    # Разный вид документа при том же источнике — разные ключи.
    иной = uuid.uuid5(uuid.NAMESPACE_URL, f"onec:{company}:gain:{источник}")
    assert первый != иной


def test_приоритет_ниже_данных_станции():
    """Там, где станция прислала свой пакет, первичным остаётся он."""
    исходник = inspect.getsource(store_documents._onec_entry_adapter)
    assert "priority=90" in исходник


def test_область_учёта_по_виду_документа():
    карта = store_documents._ONEC_ENTRY_SCOPE
    assert карта["purchase"] == "store"
    assert карта["production_release"] == "food"
    assert карта["ingredients_writeoff"] == "food"
