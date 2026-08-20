"""Возврат исхода круга виз в процесс: действие называется глаголом.

Ошибка здесь молчалива и дорога: круг виз закрыт, действие в процессе не найдено —
и стройка стоит, пока кто-нибудь не заметит.

Раньше Ядро читало карточку процесса и искало нужный глагол в списке кнопок. Список
этот считается для ЧЕЛОВЕКА: на ролевом переходе все кнопки приходят закрытыми,
потому что ответственности по договору у машины нет. Доставка работала только
потому, что не смотрела на признак доступности, — и держалась бы ровно до первого,
кто добавит фильтр `allowed`. Теперь Ядро называет действие словом, а ребро по
глаголу ищет сам фасад, где у него под рукой текущий шаг процесса.

Сравнение с «кодом ребра» вместе с этим ушло: колонки `code` у перехода нет вовсе
(есть только `verb`), то есть та ветка никогда и не срабатывала на живых данных.
"""
import uuid

import pytest

from app.services import approval_requests


class _Row:
    """Запись исхода: круг закрыт, осталось доставить его процессу."""

    def __init__(self, outcome="approved", on_approved="Согласовано", on_rejected="Отказано"):
        self.company_id = uuid.uuid4()
        self.process_id = str(uuid.uuid4())
        self.branch_id = None
        self.doc_id = uuid.uuid4()
        self.round = 1
        self.outcome = outcome
        self.on_approved = on_approved
        self.on_rejected = on_rejected


@pytest.fixture
def calls(monkeypatch):
    """Перехват вызовов фасада: важно и что послали, и чего НЕ читали."""
    seen = []

    async def fake_call(db, company_id, method, path, *, json=None, params=None):
        seen.append({"method": method, "path": path, "json": json})
        return {}

    from app.services import projects_process
    monkeypatch.setattr(projects_process, "call_process", fake_call)
    return seen


async def test_ishod_dostavlyaetsya_glagolom(calls):
    await approval_requests._deliver(None, _Row())
    assert len(calls) == 1, "карточку читать незачем — довольно одного действия"
    (call,) = calls
    assert call["method"] == "POST" and call["path"].endswith("/actions")
    assert call["json"]["verb"] == "Согласовано"
    assert "actionId" not in call["json"], "идентификатор кнопки машине взять неоткуда"


async def test_otkaz_uhodit_svoim_glagolom(calls):
    await approval_requests._deliver(None, _Row(outcome="rejected"))
    assert calls[0]["json"]["verb"] == "Отказано"


async def test_krug_bez_glagola_processa_ne_dvigaet(calls):
    """Маршрут просил только собрать визы. Это законный случай, а не недоставка."""
    await approval_requests._deliver(None, _Row(on_approved=None))
    assert calls == []


async def test_v_dejstvie_edet_krug_i_dokument(calls):
    """Процесс должен знать, чем именно его двинули: круг и документ — часть следа."""
    row = _Row()
    await approval_requests._deliver(None, row)
    payload = calls[0]["json"]["payload"]
    assert payload["approval_round"] == row.round
    assert payload["doc_id"] == str(row.doc_id)
