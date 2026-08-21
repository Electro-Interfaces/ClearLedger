"""Документ как активность процесса: разбор просьбы маршрута.

Ловим то, из-за чего ключевая точка проекта осталась бы без бумаги или, наоборот,
встала бы навсегда: заготовка не та, процесс не назван, и главное — путаница в
том, ждёт ли маршрут исхода.
"""
import uuid

import pytest

from app.models import ApprovalRequest, TaskTemplate
from app.services import document_requests
from app.services.document_requests import DocumentRequestError, _uuid_or_none


class _FakeResult:
    def __init__(self, value=None):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    """Сессия, которой хватает для разбора просьбы: до записи дело не доходит."""

    def __init__(self, template=None):
        self._template = template
        self.added = []

    async def execute(self, stmt):
        return _FakeResult(self._template)

    async def get(self, model, ident):
        return self._template

    def add(self, obj):
        self.added.append(obj)


_CID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


async def test_просьба_без_процесса_отклоняется():
    # Без процесса некому вернуть исход: документ завёлся бы в никуда.
    with pytest.raises(DocumentRequestError):
        await document_requests.request(_FakeDb(), _CID, "req-1", {})


async def test_заготовка_поручения_не_годится_для_документа():
    # Иначе маршрут просил бы документ, а получал поручение — и вскрылось бы это
    # через неделю, когда подписывать оказалось бы нечего.
    task_template = TaskTemplate(company_id=_CID, name="Выезд", doc_kind_id=None)
    db = _FakeDb(template=task_template)
    with pytest.raises(DocumentRequestError):
        await document_requests.request(
            db, _CID, "req-2", {"process_id": "p-1", "template": "Выезд"})


async def test_заготовка_не_названа():
    with pytest.raises(DocumentRequestError):
        await document_requests.request(
            _FakeDb(), _CID, "req-3", {"process_id": "p-1"})


def test_обязательность_выражается_глаголом_возврата():
    """Задан глагол — маршрут ждёт исхода; не задан — идёт дальше сам.

    Отдельного флага «обязательно» нет намеренно: его пришлось бы держать
    согласованным с наличием ребра, по которому процесс двинется, и первое же
    расхождение дало бы либо вечное ожидание, либо молча пропущенное
    согласование.
    """
    waiting = ApprovalRequest(
        company_id=_CID, request_id="r", kind="document", process_id="p",
        on_approved="Согласовано", on_rejected="Отклонено")
    free = ApprovalRequest(
        company_id=_CID, request_id="r2", kind="document", process_id="p")

    assert bool(waiting.on_approved) is True
    assert bool(free.on_approved) is False


def test_идентификатор_разбирается_снисходительно():
    # Маршруты пишут люди: в графе может оказаться имя вместо идентификатора,
    # и падать на этом нельзя — просьба разберётся по имени заготовки.
    assert _uuid_or_none("не-uuid") is None
    assert _uuid_or_none(None) is None
    value = uuid.uuid4()
    assert _uuid_or_none(str(value)) == value


# ── Срез документооборота процесса ───────────────────────────────────────────


def test_держит_работу_только_незакрытая_обязательная_просьба():
    """Отличаем «ждём» от «ждали»: закрытая просьба уже никого не держит."""
    from app.services.process_documents import _state

    waiting = ApprovalRequest(company_id=_CID, request_id="a", kind="document",
                              process_id="p", on_approved="Согласовано")
    done = ApprovalRequest(company_id=_CID, request_id="b", kind="document",
                           process_id="p", on_approved="Согласовано",
                           outcome="approved")
    free = ApprovalRequest(company_id=_CID, request_id="c", kind="document",
                           process_id="p")

    holds = lambda row: bool(row.on_approved) and row.outcome is None  # noqa: E731
    assert holds(waiting) is True
    assert holds(done) is False      # исход пришёл — процесс пошёл дальше
    assert holds(free) is False      # заведён к сведению, хода не держит
    assert _state(None, done) == "согласован"


def test_исход_просьбы_важнее_состояния_карточки():
    """Отклонённый круг виз читается как отказ, даже если карточку успели тронуть.

    Иначе в срезе проекта отказ выглядел бы как «в работе», и человек ждал бы
    согласования, которого не будет.
    """
    from app.models import DocCard
    from app.services.process_documents import _state

    row = ApprovalRequest(company_id=_CID, request_id="d", kind="document",
                          process_id="p", outcome="rejected")
    doc = DocCard(company_id=_CID, title="Акт", approval_status="pending")
    assert _state(doc, row) == "отклонён"


def test_удалённый_документ_не_роняет_срез():
    from app.services.process_documents import _state

    row = ApprovalRequest(company_id=_CID, request_id="e", kind="document",
                          process_id="p")
    assert _state(None, row) == "документ удалён"
