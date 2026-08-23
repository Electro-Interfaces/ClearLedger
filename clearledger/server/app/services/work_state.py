"""Общая ось состояния работы: одна колонка на документ и на поручение.

Этап 13а трекерного контура (`ecosystem-deploy/docs/TRACK-ROADMAP.md`). Внутри
«Трека» два движка: у поручения стадии своего маршрута («Диагностика → Правка →
Проверка»), у документа — состояние согласования («Черновик → На визах →
Подписан → В деле»). Пока они несравнимы, ни общего списка, ни общей доски не
собрать: колонок нет, сравнивать нечего.

Пять колонок, одинаковых для всего. Их немного намеренно: человек читает доску
глазами, а не считает; десять колонок — это уже таблица, которую всё равно
фильтруют.

Проекция считается ЗДЕСЬ и больше нигде. Второй источник правды о состоянии
разошёлся бы с первым на первой же правке маршрута — и доска показывала бы одно,
список другое.

Стадия маршрута может назвать свою колонку сама (поле `column` у стадии). Это
решение делопроизводителя: только он знает, что «Согласование с юристом» — это
согласование, а не работа. Поле необязательное: пусто — работает эвристика по
месту стадии в маршруте.
"""
from __future__ import annotations

from typing import Any

# Порядок колонок = порядок движения работы. Он же порядок слева направо на доске.
COLUMNS: tuple[str, ...] = ("new", "in_work", "approval", "external", "done")

COLUMN_NAMES: dict[str, str] = {
    "new": "Заведено",
    "in_work": "В работе",
    "approval": "На согласовании",
    "external": "Ждём внешних",
    "done": "Готово",
}

# Состояния документа, из которых работа уже не выйдет. `cancelled` тоже здесь:
# отменённый документ — законченная история, а не работа, которую кто-то ведёт.
_DOC_DONE = ("executed", "archived", "cancelled")


def stage_column(stage: dict[str, Any] | None, index: int, total: int) -> str:
    """Колонка стадии маршрута: что сказал делопроизводитель, иначе — по месту.

    Эвристика намеренно грубая: первая стадия — «Заведено», последняя —
    «Готово», всё между ними — «В работе». Она угадывает простой маршрут и врёт
    на маршруте с согласованием — для этого у стадии и есть своё поле.
    """
    named = (stage or {}).get("column")
    if named in COLUMNS:
        return str(named)
    if total <= 1:
        return "in_work"
    if index <= 0:
        return "new"
    if index >= total - 1:
        return "done"
    return "in_work"


def task_state(task: Any, route: list[dict[str, Any]]) -> str:
    """Колонка поручения.

    Порядок проверок — не косметика. Закрытая задача «Готова», даже если её
    стадия называется «Диагностика»: статус сильнее маршрута. Отданное наружу
    показывается в «Ждём внешних», даже когда стадия говорит «В работе», — иначе
    на доске работа выглядит идущей, а на деле мяч у подрядчика.
    """
    if getattr(task, "status", "open") != "open":
        return "done"
    if getattr(task, "waiting_for", None) == "external":
        return "external"
    code = getattr(task, "stage_code", None)
    stages = [s for s in (route or []) if isinstance(s, dict)]
    if not stages:
        return "in_work"
    index = next((i for i, s in enumerate(stages) if s.get("code") == code), -1)
    if index < 0:
        # Стадии нет в маршруте: тип переписали, а задача осталась на прежнем
        # шаге. Это работа в ходу, а не завершённая и не новая.
        return "in_work"
    return stage_column(stages[index], index, len(stages))


def doc_state(doc: Any) -> str:
    """Колонка документа.

    Круг виз сильнее статуса: документ на согласовании — это «На согласовании»,
    в каком бы состоянии он ни был зарегистрирован. Именно этого ждёт тот, кто
    смотрит на доску: не «зарегистрирован ли», а «кого ждём».
    """
    status = getattr(doc, "status", "draft")
    if status in _DOC_DONE:
        return "done"
    if getattr(doc, "approval_status", "none") == "pending":
        return "approval"
    if status == "draft":
        return "new"
    return "in_work"


def state_out(code: str) -> dict[str, str]:
    """Состояние для выдачи: код для отбора, имя для глаз."""
    return {"state": code, "state_name": COLUMN_NAMES.get(code, code)}


def normalize_route(route: list[Any] | None) -> list[dict[str, Any]]:
    """Оставить в маршруте только то, что мы понимаем.

    Незнакомое имя колонки не роняет сохранение типа, а отбрасывается: маршрут
    приходит и из заготовок, и из чужих выгрузок, и падать на опечатке в
    необязательном поле значит потерять весь маршрут из-за одного слова.
    """
    clean: list[dict[str, Any]] = []
    for stage in route or []:
        if not isinstance(stage, dict) or not stage.get("code"):
            continue
        item: dict[str, Any] = {"code": str(stage["code"])[:40],
                                "name": str(stage.get("name") or stage["code"])[:120]}
        if stage.get("column") in COLUMNS:
            item["column"] = str(stage["column"])
        clean.append(item)
    return clean
