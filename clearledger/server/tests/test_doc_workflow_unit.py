import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models import DocApproval, DocCard, DocKind
from app.routers.docs_router import (
    _STATUS_TRANSITIONS, _assert_ref, _clean_fields, _validate_attrs)
from app.services.process_templates import fill
from app.services.doc_approvals import (
    _activate, clean_route, progress, step_applies, step_passed)


def _row(status="waiting", mode="serial", quorum="all", required=True, sla_hours=None):
    return DocApproval(
        step_no=1, step_code="check", step_name="Проверка", mode=mode,
        quorum=quorum, actor_kind="user", required=required, status=status,
        sla_hours=sla_hours,
    )


def test_последовательный_шаг_активирует_одного_человека():
    rows = [_row(sla_hours=4), _row(sla_hours=4)]
    now = datetime(2026, 8, 16, 9, tzinfo=timezone.utc)
    assert _activate(rows, now) == 1
    assert [row.status for row in rows] == ["pending", "waiting"]
    assert rows[0].due_at.isoformat() == "2026-08-16T13:00:00+00:00"
    assert rows[1].due_at is None


def test_параллельный_шаг_активирует_всех_и_any_закрывает_его():
    rows = [_row(mode="parallel", quorum="any"),
            _row(mode="parallel", quorum="any")]
    assert _activate(rows, datetime.now(timezone.utc)) == 2
    rows[0].status = "approved"
    assert step_passed(rows) is True


def test_числовой_кворум_ждёт_заданное_число_виз():
    rows = [_row(status="approved", mode="parallel", quorum="2"),
            _row(status="pending", mode="parallel", quorum="2")]
    assert step_passed(rows) is False
    rows[1].status = "approved"
    assert step_passed(rows) is True


def test_прогресс_не_считает_будущий_шаг_решённым():
    rows = [_row(status="waiting"), _row(status="waiting")]
    state = progress(rows)[0]
    assert state["decided"] == 0
    assert state["active"] is False
    assert len(state["queued"]) == 2


def test_схема_реквизитов_нормализуется_и_проверяет_обязательное():
    fields = _clean_fields([
        {"code": "amount", "label": "Сумма", "type": "number", "required": True},
        {"code": "channel", "label": "Канал", "type": "select",
         "options": ["Почта", "ЭДО", "Почта"]},
    ])
    assert fields[1]["options"] == ["Почта", "ЭДО"]
    kind = DocKind(code="test", name="Тест", fields=fields)
    with pytest.raises(HTTPException) as missing:
        _validate_attrs(kind, {"channel": "Почта"}, required=True)
    assert missing.value.status_code == 409
    with pytest.raises(HTTPException) as wrong:
        _validate_attrs(kind, {"amount": "100", "channel": "Почта"}, required=True)
    assert wrong.value.status_code == 400
    assert _validate_attrs(
        kind, {"amount": 100, "channel": "ЭДО"}, required=True,
    )["amount"] == 100


def test_граф_состояний_не_позволяет_обратный_переход():
    assert "in_force" in _STATUS_TRANSITIONS["registered"]
    assert "draft" not in _STATUS_TRANSITIONS["registered"]
    assert not _STATUS_TRANSITIONS["archived"]
    assert not _STATUS_TRANSITIONS["cancelled"]


# ── Ссылки документа на сущности пространства ────────────────────────────────


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    """Сессия, которая считает обращения: важно не только что вернули, но и
    ходили ли в базу вообще — незнакомый вид ссылки не должен её трогать."""

    def __init__(self, value=None):
        self._value = value
        self.calls = 0

    async def execute(self, stmt):
        self.calls += 1
        return _FakeResult(self._value)


_CID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


async def test_незнакомый_вид_ссылки_пропускается_без_обращения_к_базе():
    db = _FakeDb()
    await _assert_ref(db, _CID, "ticket:42")
    await _assert_ref(db, _CID, "произвольная строка")
    await _assert_ref(db, _CID, None)
    await _assert_ref(db, _CID, "contract:")
    assert db.calls == 0


async def test_знакомый_вид_с_существующей_целью_проходит():
    db = _FakeDb(value=uuid.uuid4())
    await _assert_ref(db, _CID, f"contract:{uuid.uuid4()}")
    assert db.calls == 1


async def test_цель_из_другой_компании_не_принимается():
    db = _FakeDb(value=None)
    with pytest.raises(HTTPException) as err:
        await _assert_ref(db, _CID, f"counterparty:{uuid.uuid4()}")
    assert err.value.status_code == 404


async def test_ключ_объекта_сети_остаётся_строкой():
    db = _FakeDb(value="ezs-208")
    await _assert_ref(db, _CID, "object:ezs-208")
    assert db.calls == 1


# ── Условия на шаге маршрута ─────────────────────────────────────────────────


def _card(**kw):
    return DocCard(company_id=_CID, title="Договор", **kw)


def test_шаг_без_условия_нужен_всегда():
    assert step_applies({"code": "check"}, _card()) is True


def test_условие_по_реквизиту_вида_сравнивает_числа():
    step = {"code": "fin", "when": {"field": "amount", "op": "gt", "value": 100000}}
    assert step_applies(step, _card(attrs={"amount": 150000})) is True
    assert step_applies(step, _card(attrs={"amount": 50000})) is False


def test_условие_по_свойству_карточки():
    step = {"code": "law", "when": {"field": "family", "op": "eq", "value": "contract"}}
    assert step_applies(step, _card(family="contract")) is True
    assert step_applies(step, _card(family="internal")) is False


def test_условие_на_заполненность_реквизита():
    step = {"code": "obj", "when": {"field": "object_id", "op": "set"}}
    assert step_applies(step, _card(object_id="ezs-208")) is True
    assert step_applies(step, _card()) is False


def test_нечисловое_значение_не_роняет_маршрут_а_гасит_шаг():
    step = {"code": "fin", "when": {"field": "amount", "op": "gte", "value": 10}}
    assert step_applies(step, _card(attrs={"amount": "не указана"})) is False
    assert step_applies(step, _card()) is False


def test_мусорное_условие_отбрасывается_но_шаг_остаётся():
    route = [{"code": "check", "name": "Проверка",
              "actors": [{"by": "user", "ref": str(uuid.uuid4())}],
              "when": {"field": "amount", "op": "магия", "value": 1}}]
    cleaned = clean_route(route)
    assert len(cleaned) == 1
    assert "when" not in cleaned[0]


# ── Подстановка в шаблон документа ───────────────────────────────────────────


def test_подстановка_заполняет_известные_места():
    values = {"контрагент": "ООО «Ромашка»", "договор": "12/2026",
              "дата": "20.08.2026"}
    assert fill("Акт по договору {договор} с {контрагент} от {дата}", values) == (
        "Акт по договору 12/2026 с ООО «Ромашка» от 20.08.2026")


def test_незаполненное_место_остаётся_видимым():
    # Пустота вместо имени доезжает до контрагента; оставшаяся скобка видна
    # своему человеку до отправки.
    assert fill("Акт по договору {договор}", {}) == "Акт по договору {договор}"
    assert fill("Акт с {контрагент}", {"контрагент": ""}) == "Акт с {контрагент}"


def test_подстановка_не_трогает_обычный_текст_и_пустое():
    assert fill(None, {"дата": "20.08.2026"}) is None
    assert fill("Смета 100 {} руб.", {"дата": "x"}) == "Смета 100 {} руб."


# ── Партнёр как участник маршрута ────────────────────────────────────────────


def test_маршрут_принимает_партнёра_как_участника():
    key_id = str(uuid.uuid4())
    cleaned = clean_route([{"code": "cp", "name": "Согласование контрагента",
                            "actors": [{"by": "partner", "ref": key_id}]}])
    assert len(cleaned) == 1
    assert cleaned[0]["actors"] == [{"by": "partner", "ref": key_id}]


def test_имя_партнёра_в_листе_называет_систему_и_человека():
    from app.models import SpaceInboundKey
    from app.routers.partner_router import PartnerActor

    key = SpaceInboundKey(consumer="СБИС контрагента", key_hash="x",
                          key_prefix="ab12")
    # Учётки за партнёром нет — идентификатор обязан остаться пустым, иначе он
    # уедет в события и в лист согласования строкой «None».
    assert PartnerActor(key).id is None
    assert PartnerActor(key).name == "СБИС контрагента (партнёр)"
    assert PartnerActor(key, "Орлова А. В.").name == (
        "СБИС контрагента — Орлова А. В.")
