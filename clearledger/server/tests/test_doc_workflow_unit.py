from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.models import DocApproval, DocKind
from app.routers.docs_router import _STATUS_TRANSITIONS, _clean_fields, _validate_attrs
from app.services.doc_approvals import _activate, progress, step_passed


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
