"""Регистрационный номер документа: область, счётчик, шаблон.

Три правила, ради которых это отдельный модуль.

Первое. Счётчик транзакционный, а не последовательность базы. Последовательность
не откатывается, поэтому отменённая регистрация оставляет пропуск, и журнал
регистрации перестаёт быть непрерывным. Пропуск в журнале - первое, что спросит
проверяющий, а объяснить его нечем.

Второе. Область нумерации задаёт вид документа: сквозная, по годам, по юрлицу или
по юрлицу и году. Одно юрлицо не должно двигать счётчик другого.

Третье. Шаблон подставляется своим разбором, а не `str.format`. Шаблон приходит
из формы, а `str.format` по чужой строке открывает доступ к внутренностям объектов
через `{0.__class__}`.
"""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# `{n}`, `{n:04d}`, `{yyyy}` — имя и необязательный формат.
_VAR = re.compile(r"\{(\w+)(?::([^}]+))?\}")

# ponytail: счётчик сериализует регистрации одной области на время транзакции.
# При человеческом темпе (десятки в день) это незаметно; если поток пойдёт на
# сотни в секунду — дробить область до месяца, а не менять механику.


def scope_key(kind_code: str, organization_id, on_date: date, scope: str) -> str:
    """Ключ области нумерации: `<вид>|<юрлицо или ->|<год или ->`."""
    org = str(organization_id) if (organization_id and "org" in scope) else "-"
    year = str(on_date.year) if "year" in scope else "-"
    return f"{kind_code}|{org}|{year}"


def render(template: str, *, prefix: str, number: int, on_date: date,
           org_code: str = "", kind_code: str = "") -> str:
    """Собрать номер по шаблону вида «{prefix}-{yyyy}-{n:04d}».

    Неизвестная переменная остаётся в тексте как есть: молча подставленная пустота
    даёт номер вроде «--0007», который потом никто не опознает.
    """
    values: dict[str, object] = {
        "prefix": prefix or "",
        "n": number,
        "yy": on_date.strftime("%y"),
        "yyyy": on_date.year,
        "org": org_code or "",
        "kind": kind_code or "",
    }

    def sub(m: re.Match[str]) -> str:
        name, fmt = m.group(1), m.group(2)
        if name not in values:
            return m.group(0)
        value = values[name]
        if not fmt:
            return str(value)
        try:
            return format(value, fmt)
        except (ValueError, TypeError):
            return str(value)

    return _VAR.sub(sub, template).strip()


async def next_number(db: AsyncSession, company_id, scope: str) -> int:
    """Выдать следующий номер в области.

    Одним оператором в той же транзакции, что и сама регистрация: строку счётчика
    блокирует база, поэтому два одновременных секретаря получают разные номера, а
    откат регистрации возвращает счётчик назад.
    """
    row = await db.execute(text("""
        INSERT INTO doc_counters (company_id, scope_key, next_value)
        VALUES (:cid, :scope, 1)
        ON CONFLICT (company_id, scope_key)
        DO UPDATE SET next_value = doc_counters.next_value + 1, updated_at = now()
        RETURNING next_value
    """), {"cid": str(company_id), "scope": scope})
    return int(row.scalar_one())
