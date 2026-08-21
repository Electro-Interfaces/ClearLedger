"""Послабление пункта чек-листа: обязательность снята, пункт остался.

Механизм легко сломать молча в обе стороны, поэтому проверки именно здесь:
  • снятая обязательность перестала открывать переход — люди снова упираются
    в пункт, который сознательно решили не ждать;
  • снятая обязательность стала считаться выполнением — в отчёте появится
    «собрано», хотя не собрано ничего.

Отдельно держим границу: три пункта не снимаются ничьей подписью, и если
кто-то уберёт их из `WAIVE_FORBIDDEN`, дата ввода в эксплуатацию (основание
перевода капвложений 08 → 01) станет предметом договорённости.
"""
import asyncio
import uuid
from types import SimpleNamespace

from app.models import EzsSite
from app.services.ezs_checklist import TASKS, WAIVE_FORBIDDEN
from app.services.ezs_site_work import gate_state, set_gate_item, set_gate_waiver


class _Result:
    """Пустой ответ базы: событий и связанных записей у тестового проекта нет."""
    def scalar_one_or_none(self): return None
    def scalars(self): return self
    def all(self): return []


class _FakeDb:
    def __init__(self): self.added = []
    async def execute(self, *a, **k): return _Result()
    def add(self, obj): self.added.append(obj)


def _site(stage: str) -> EzsSite:
    return EzsSite(id=uuid.uuid4(), company_id=uuid.uuid4(), stage=stage, gates=None)


_USER = SimpleNamespace(id=uuid.uuid4(), name="Илютина", email="ilyutina@example.ru")


def _run(coro):
    return asyncio.run(coro)


def test_снятая_обязательность_открывает_переход():
    site = _site("contracting")
    gate = gate_state(site)
    blocker = next(i for i in gate["items"] if i["required"] and not i["done"])
    assert blocker["label"] in gate["blocking"]
    assert gate["canAdvance"] is False

    res = _run(set_gate_waiver(_FakeDb(), site, blocker["key"], True,
                               "Собственник — муниципалитет, форма права одна", _USER))
    assert res["ok"] is True

    after = gate_state(site)
    it = next(i for i in after["items"] if i["key"] == blocker["key"])
    # Пункт не отменён и не выполнен — он просто не держит переход.
    assert it["done"] is False
    assert it["required"] is True
    assert it["waived"] is True
    assert it["waivedBy"] == "Илютина"
    assert it["waiveReason"].startswith("Собственник")
    assert blocker["label"] not in after["blocking"]
    assert [w["key"] for w in after["waived"]] == [blocker["key"]]


def test_возврат_обязательности_снимает_послабление():
    site = _site("contracting")
    key = next(i["key"] for i in gate_state(site)["items"] if i["required"] and not i["done"])
    _run(set_gate_waiver(_FakeDb(), site, key, True, "причина", _USER))
    _run(set_gate_waiver(_FakeDb(), site, key, False, "", _USER))
    it = next(i for i in gate_state(site)["items"] if i["key"] == key)
    assert it["waived"] is False
    assert it["label"] in gate_state(site)["blocking"]


def test_отметка_пункта_не_стирает_чужую_подпись():
    """Галочка и послабление живут в одной записи — раньше вторая затирала первую."""
    site = _site("negotiation")   # 3.1 «Переговоры с собственником» — глазами и обязателен
    manual = next(i for i in gate_state(site)["items"] if i["manual"] and i["required"])
    _run(set_gate_waiver(_FakeDb(), site, manual["key"], True, "проверено выездом", _USER))
    _run(set_gate_item(_FakeDb(), site, manual["key"], True, _USER))
    it = next(i for i in gate_state(site)["items"] if i["key"] == manual["key"])
    assert it["done"] is True
    assert it["waived"] is True, "отметка выполнения стёрла послабление"


def test_обоснование_обязательно():
    site = _site("contracting")
    key = next(i["key"] for i in gate_state(site)["items"] if i["required"] and not i["done"])
    res = _run(set_gate_waiver(_FakeDb(), site, key, True, "   ", _USER))
    assert res["ok"] is False
    assert "обоснование" in res["message"].lower()
    assert gate_state(site)["blocking"], "пункт перестал держать переход без обоснования"


def test_необязательный_пункт_снимать_нечего():
    site = _site("screening")
    key = next(i["key"] for i in gate_state(site)["items"] if not i["required"])
    res = _run(set_gate_waiver(_FakeDb(), site, key, True, "причина", _USER))
    assert res["ok"] is False


def test_неизвестный_пункт_отбивается():
    res = _run(set_gate_waiver(_FakeDb(), _site("lead"), "99.9", True, "причина", _USER))
    assert res["ok"] is False


def test_три_пункта_не_снимаются_ничьей_подписью():
    keys = {t["key"] for t in TASKS}
    for key in WAIVE_FORBIDDEN:
        # Защита должна что-то защищать: пункт существует и он обязателен.
        assert key in keys, f"{key} нет в чек-листе — запрет стережёт пустоту"
        task = next(t for t in TASKS if t["key"] == key)
        assert task.get("required"), f"{key} не обязателен — запрещать нечего"
        site = _site(task["stage"])
        res = _run(set_gate_waiver(_FakeDb(), site, key, True, "очень нужно", _USER))
        assert res["ok"] is False, f"с пункта {key} удалось снять обязательность"
        it = next(i for i in gate_state(site)["items"] if i["key"] == key)
        assert it["waivable"] is False
    # Дата ввода в эксплуатацию — основание перевода 08 → 01. Пункт назван явно,
    # чтобы удаление его из списка не прошло переименованием.
    assert "8.5" in WAIVE_FORBIDDEN
