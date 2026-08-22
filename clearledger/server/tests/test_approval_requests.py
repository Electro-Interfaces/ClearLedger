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

    def __init__(self, outcome="approved", on_approved="Согласовано", on_rejected="Отказано",
                 kind="approval"):
        self.kind = kind
        self.task_id = uuid.uuid4()
        self.company_id = uuid.uuid4()
        self.process_id = str(uuid.uuid4())
        self.branch_id = None
        self.doc_id = uuid.uuid4()
        self.round = 1
        self.outcome = outcome
        self.on_approved = on_approved
        self.on_rejected = on_rejected


class _Db:
    """Сессия-заглушка: доставка исхода поручения спрашивает у неё версию.

    Возвращает то, что положили: имя версии или None. Настоящая сессия здесь не
    нужна — проверяется, что уехало в след шага, а не как это прочитано.
    """

    def __init__(self, version: str | None = None):
        self._version = version

    async def execute(self, *_args, **_kwargs):
        version = self._version

        class _Result:
            def scalar_one_or_none(self):
                return version

        return _Result()


@pytest.fixture
def calls(monkeypatch):
    """Перехват вызовов фасада: важно и что послали, и чего НЕ читали.

    Патчим `_call`, а не алиас `call_process`: `send_verb` зовёт первый, и патч
    алиаса до него не доходил — тест был зелёным ровно до того дня, когда фасад
    перестал ходить через алиас, и с тех пор падал незамеченным (тесты с БД
    локально не гоняются). Поймано первым прогоном на стенде 23.08.2026.
    """
    seen = []

    async def fake_call(db, company_id, method, path, *, json=None, params=None):
        seen.append({"method": method, "path": path, "json": json})
        return {}

    from app.services import projects_process
    monkeypatch.setattr(projects_process, "_call", fake_call)
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


async def test_vypolnennoe_poruchenie_dvigaet_process(calls):
    """Поручение — такая же активность процесса, как круг виз.

    Исходов у любой активности два: работа сделана или не сделана. У круга это
    «согласовано / отказано», у поручения — «выполнено / отменено», и доезжают они
    одним и тем же путём: второй механизм доставки означал бы вторые ретраи и
    вторую историю о том, где потерялся исход.
    """
    row = _Row(outcome="done", on_approved="Работа принята", kind="errand")
    await approval_requests._deliver(_Db(), row)
    assert calls[0]["json"]["verb"] == "Работа принята"
    # В следе шага должно стоять само поручение, а не пустое место от документа.
    assert calls[0]["json"]["payload"] == {"task_id": str(row.task_id)}


async def test_versiya_ispravleniya_edet_zayavitelyu(calls):
    """Этап 10: закрыли поручение с версией — её ждёт заявитель в Поддержке.

    Имя версии, а не идентификатор: в ответе человеку стоит «1.4.2», и второй
    запрос за расшифровкой на той стороне был бы лишним.
    """
    row = _Row(outcome="done", on_approved="Работа принята", kind="errand")
    await approval_requests._deliver(_Db("1.4.2"), row)
    assert calls[0]["json"]["payload"] == {
        "task_id": str(row.task_id), "fixed_version": "1.4.2"}


async def test_otmenennoe_poruchenie_uhodit_svoim_glagolom(calls):
    row = _Row(outcome="cancelled", on_rejected="Работа отменена", kind="errand")
    # Отменённое поручение версию не везёт: чинить было нечего.
    await approval_requests._deliver(_Db("1.4.2"), row)
    assert calls[0]["json"]["verb"] == "Работа отменена"
    assert "fixed_version" not in calls[0]["json"]["payload"]
