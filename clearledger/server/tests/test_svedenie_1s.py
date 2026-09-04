# -*- coding: utf-8 -*-
"""Сведение записей 1С со станционными не зависит от прошлого состояния реестра.

02.09.2026 адаптер 1С читал станционные документы запросом к
`store_document_projections` — к уже существующему реестру. Адаптеры идут
последовательно, и на момент решения станционных кандидатов текущего прогона
там ещё нет: пересборка после удаления давала задвоение выпуска 208 за 12 дней
на 30 628,73 ₽, а лечилась повторным прогоном. Результат зависел от того,
сколько раз запустили пересборку.
"""
import inspect

from app.services import store_documents


def test_адаптер_не_читает_реестр():
    исходник = inspect.getsource(store_documents._onec_entry_adapter)
    assert "store_document_projections" not in исходник
    assert "закрыто_станцией" not in исходник


def test_сведение_идёт_после_сбора_всех_кандидатов():
    исходник = inspect.getsource(store_documents.rebuild_store_document_projection)
    сведение = исходник.index("_свести_записи_1с(candidates)")
    цикл = исходник.index("for name, adapter in ADAPTER_REGISTRY")
    assert цикл < сведение, "сведение обязано идти после цикла адаптеров"


def test_день_считается_по_москве():
    """Смена, закрытая после 21:00, обязана попасть в свой день, а не в UTC-день."""
    from datetime import datetime, timezone
    поздняя = datetime(2026, 8, 18, 22, 30, tzinfo=timezone.utc)  # 19.08 01:30 МСК
    assert store_documents._день(поздняя).isoformat() == "2026-08-19"
    наивная = datetime(2026, 8, 18, 22, 30)
    assert store_documents._день(наивная).isoformat() == "2026-08-18"
    assert store_documents._день(None) is None


def test_пустой_документ_станции_день_не_закрывает():
    исходник = inspect.getsource(store_documents._свести_записи_1с)
    assert "if c.amount and" in исходник


def test_ретранслированный_документ_день_не_закрывает():
    """Пока выпуск вёл 1С, агент возил её документы под ЕЁ номерами.

    18.06.2026 в 1С два выпуска — 598,18 и 3 424,80. Станция принесла только
    первый, под номером 1С «208000174», и правило «день закрыт станцией»
    вытесняло второй: минус 3 424,80 ₽.
    """
    исходник = inspect.getsource(store_documents._свести_записи_1с)
    assert "номера_1с" in исходник
    assert "not in номера_1с" in исходник


def test_склейка_пересчитывает_отпечаток():
    """Ключ документа входит в хеш: без пересчёта пересборка упрётся в конфликт."""
    исходник = inspect.getsource(store_documents._свести_записи_1с)
    assert "c.content_hash = _candidate_hash(c)" in исходник
