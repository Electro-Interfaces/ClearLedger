"""Выгрузка с ЖИВОЙ сводной таблицей Excel.

openpyxl не создаёт PivotTable с нуля — официально «it is not intended that
client code should be able to create pivot tables». Обходим шаблоном: сводная
нарисована один раз в Excel (см. scripts/build_pivot_template.py), сервер
заливает в неё свежие строки и просит Excel пересчитать кэш при открытии.

⚠ Пересчёт делает Excel, не мы. Это значит:
  • в LibreOffice/Google Sheets/веб-Excel сводная останется пустой;
  • при Защищённом просмотре (файл скачан из браузера — Windows ставит метку
    зоны) пересчёт откладывается до нажатия «Разрешить редактирование».
Поэтому лист с данными в файле полноценный: он читается везде и всегда, а
сводная — надстройка над ним, а не единственный носитель цифр.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChargeSession

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
SESSIONS_TEMPLATE = TEMPLATE_DIR / "pivot_charge_sessions.xlsx"

# Лист-источник сводной. Имя должно совпадать с worksheetSource в шаблоне —
# иначе сводная будет смотреть в пустоту.
DATA_SHEET = "Транзакции"

# Порядок колонок ЖЁСТКО задан шаблоном: сводная адресует поля по индексу,
# а не по названию. Переставить местами — значит показать энергию под видом
# выручки, молча и без ошибки. Менять только вместе с шаблоном.
COLUMNS = [
    "ID сессии", "Начало", "Станция", "Код станции", "Регион", "Коннектор",
    "Тип клиента", "Клиент (ЮЛ)", "Канал запуска", "Энергия кВтч",
    "Длительность мин", "Тариф ₽/кВтч", "Тариф договора ₽/кВтч", "Выручка ₽",
    "Исход", "Оплата",
]


def _f(value) -> float | None:
    """NUMERIC приходит Decimal — в Excel он уедет строкой, и сводная не сложит."""
    return float(value) if value is not None else None


def _row(s: ChargeSession) -> list:
    # Выручка: у ЮЛ session.amount = 0 (постоплата), реальная сумма считается по
    # договорному тарифу в client_amount. Брать amount «как есть» — занизить
    # корпоративную выручку до нуля.
    revenue = _f(s.client_amount) if s.client_amount is not None else _f(s.amount)
    return [
        s.session_ext_id,
        s.started_at,
        s.station_name,
        s.station_code,
        s.region,
        s.connector_type,
        s.user_type,
        s.client_name,
        s.charge_type,
        _f(s.energy_kwh),
        _f(s.duration_min),
        _f(s.tariff),
        _f(s.client_tariff),
        revenue,
        s.result,
        s.paid_at,
    ]


async def build_sessions_pivot(
    db: AsyncSession,
    company_id: uuid.UUID,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 200000,
):
    """Заполнить шаблон сессиями за период. Возвращает (Workbook, статистика)."""
    import openpyxl

    if not SESSIONS_TEMPLATE.exists():
        raise FileNotFoundError(
            f"Шаблон сводной не найден: {SESSIONS_TEMPLATE}. "
            f"Соберите его: py scripts/build_pivot_template.py <выгрузка.xlsx>"
        )

    S = ChargeSession
    where = [S.company_id == company_id, S.started_at.is_not(None)]
    if date_from:
        where.append(S.started_at >= datetime.fromisoformat(date_from[:10]))
    if date_to:
        # Верхняя граница включительно: started_at — DateTime, и сравнение с
        # «YYYY-MM-DD» отбросило бы весь последний день (Postgres приводит к
        # полуночи). См. правило в CLAUDE.md.
        where.append(S.started_at <= datetime.fromisoformat(f"{date_to[:10]}T23:59:59"))

    rows = (await db.execute(
        select(S).where(*where).order_by(S.started_at).limit(limit)
    )).scalars().all()

    wb = openpyxl.load_workbook(SESSIONS_TEMPLATE)
    ws = wb[DATA_SHEET]

    # Шапка в шаблоне уже есть; дописываем строго под неё.
    for s in rows:
        ws.append(_row(s))

    # Просим Excel пересобрать кэш при открытии — без этого сводная покажет
    # пустоту: в шаблоне pivotCacheRecords обнулён ради веса и скорости.
    for sheet in wb.worksheets:
        for pt in getattr(sheet, "_pivots", []):
            pt.cache.refreshOnLoad = True

    stats = {"rows": len(rows), "truncated": len(rows) >= limit}
    return wb, stats
