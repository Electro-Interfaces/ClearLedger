"""Общая ось состояния: одна колонка на документ и на поручение.

Проверяется то, из-за чего доска соврала бы молча: закрытая задача, застрявшая на
середине маршрута; работа, отданная подрядчику, но показанная «в работе»; стадия,
исчезнувшая из маршрута после правки типа; документ на визах, который по статусу
ещё черновик.

Без БД: проекция — чистая функция, и проверять её через контейнер незачем.
"""
from types import SimpleNamespace

from app.services import work_state as ws


def _task(**kw):
    base = {"status": "open", "waiting_for": None, "stage_code": None}
    return SimpleNamespace(**{**base, **kw})


def _doc(**kw):
    return SimpleNamespace(**{"status": "draft", "approval_status": "none", **kw})


ROUTE = [
    {"code": "reg", "name": "Регистрация"},
    {"code": "diag", "name": "Диагностика"},
    {"code": "law", "name": "Согласование с юристом", "column": "approval"},
    {"code": "check", "name": "Проверка"},
]


def test_эвристика_читает_маршрут_по_месту_стадии():
    plain = [{"code": "new", "name": "Постановка"},
             {"code": "work", "name": "В работе"},
             {"code": "done", "name": "Готово"}]
    assert ws.task_state(_task(stage_code="new"), plain) == "new"
    assert ws.task_state(_task(stage_code="work"), plain) == "in_work"
    assert ws.task_state(_task(stage_code="done"), plain) == "done"
    # Маршрут из одной стадии: ни первой, ни последней в нём нет — есть работа.
    assert ws.task_state(_task(stage_code="only"), [{"code": "only", "name": "Дело"}]) == "in_work"


def test_стадия_называет_свою_колонку_сама():
    """Эвристика поставила бы «Согласование с юристом» в «В работе» — и доска
    показала бы идущую работу там, где на самом деле ждут подписи."""
    assert ws.task_state(_task(stage_code="law"), ROUTE) == "approval"
    assert ws.task_state(_task(stage_code="diag"), ROUTE) == "in_work"


def test_статус_и_внешняя_сторона_сильнее_маршрута():
    # Закрытая задача готова, даже если её стадия называется «Диагностика».
    assert ws.task_state(_task(status="done", stage_code="diag"), ROUTE) == "done"
    assert ws.task_state(_task(status="cancelled", stage_code="reg"), ROUTE) == "done"
    # Отданное наружу — «Ждём внешних»: иначе на доске работа выглядит идущей,
    # а мяч у подрядчика.
    assert ws.task_state(_task(waiting_for="external", stage_code="diag"), ROUTE) == "external"
    # Но закрытая задача не «ждёт» никого.
    assert ws.task_state(
        _task(status="done", waiting_for="external", stage_code="diag"), ROUTE) == "done"


def test_исчезнувшая_стадия_не_роняет_проекцию():
    """Тип переписали, задача осталась на прежнем шаге. Это работа в ходу, а не
    завершённая — иначе правка справочника молча «закрыла» бы чужие задачи."""
    assert ws.task_state(_task(stage_code="было_такое"), ROUTE) == "in_work"
    assert ws.task_state(_task(stage_code=None), []) == "in_work"


def test_у_документа_круг_виз_сильнее_статуса():
    assert ws.doc_state(_doc()) == "new"
    assert ws.doc_state(_doc(status="registered")) == "in_work"
    # Смотрящий на доску спрашивает «кого ждём», а не «зарегистрирован ли».
    assert ws.doc_state(_doc(status="draft", approval_status="pending")) == "approval"
    assert ws.doc_state(_doc(status="registered", approval_status="pending")) == "approval"
    for done in ("executed", "archived", "cancelled"):
        assert ws.doc_state(_doc(status=done, approval_status="pending")) == "done", done


def test_маршрут_чистится_а_не_падает_на_опечатке():
    """Незнакомая колонка отбрасывается: терять весь маршрут из-за одного слова
    в необязательном поле — цена, которой чистка не стоит."""
    clean = ws.normalize_route([
        {"code": "a", "name": "Первая", "column": "approval"},
        {"code": "b", "name": "Вторая", "column": "выдумка"},
        {"name": "без кода"},
        "мусор",
    ])
    assert clean == [{"code": "a", "name": "Первая", "column": "approval"},
                     {"code": "b", "name": "Вторая"}]
    # Имя необязательно: стадия без него называется своим кодом, а не пропадает.
    assert ws.normalize_route([{"code": "x"}]) == [{"code": "x", "name": "x"}]


def test_все_колонки_имеют_имя():
    """Колонка без имени доезжает до доски заголовком-кодом — это видно всем."""
    assert set(ws.COLUMNS) == set(ws.COLUMN_NAMES)
    assert ws.state_out("approval") == {"state": "approval", "state_name": "На согласовании"}


if __name__ == "__main__":  # ручной прогон без pytest
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ok")
