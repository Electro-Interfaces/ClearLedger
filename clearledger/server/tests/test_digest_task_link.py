import uuid
from types import SimpleNamespace

from app.services.task_scheduler import task_link


def test_ссылка_на_задачу_в_сводке():
    tid = uuid.uuid4()
    t = SimpleNamespace(id=tid, number=68, title="Схема [ЭЗС]", visibility="company")
    assert task_link(t) == f"[№68 «Схема [ЭЗС)»](/docs/company?view=errands&task={tid})"
    t.visibility = "personal"
    assert task_link(t).endswith(f"(/tasks/{tid})")
