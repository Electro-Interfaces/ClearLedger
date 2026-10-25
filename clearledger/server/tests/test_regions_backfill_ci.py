"""Заполнение регионов не спотыкается о регистр (инцидент 25.10.2026).

У `regions` уникальность регистронезависимая (`uq_regions_company_name_ci`:
btrim+lower), а миграция заполняла таблицу из `service_locations`, группируя по
точному тексту. Два объекта с «Тест» и «тест» давали две строки на вставку —
и Ядро не стартовало вовсе: UniqueViolation в startup, воркеры падали по кругу,
пространство отвечало 502.
"""
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, ServiceLocation

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_разный_регистр_федерального_субъекта_даёт_один_регион(db: AsyncSession):
    company = (await db.execute(select(Company).order_by(Company.created_at))).scalars().first()
    assert company is not None
    метка = uuid.uuid4().hex[:6]
    for n, значение in enumerate((f"Тест{метка}", f"тест{метка}", f" Тест{метка} ")):
        db.add(ServiceLocation(
            id=f"ci-{метка}-{n}", company_id=company.id, code=f"ci-{метка}-{n}",
            name=f"Точка {значение}", type="other",
            extra_metadata={"federalSubject": значение}))
    await db.commit()

    # Тот же запрос, что и в миграции (database.py, набор «regions»).
    await db.execute(text(
        "INSERT INTO regions (id, company_id, name, federal_subject) "
        "SELECT gen_random_uuid(), company_id, имя, имя FROM ("
        "  SELECT DISTINCT ON (company_id, btrim(lower(extra_metadata->>'federalSubject'))) "
        "         company_id, extra_metadata->>'federalSubject' AS имя "
        "  FROM service_locations "
        "  WHERE extra_metadata->>'federalSubject' IS NOT NULL "
        "    AND extra_metadata->>'federalSubject' <> '' "
        "  ORDER BY company_id, btrim(lower(extra_metadata->>'federalSubject')), "
        "           extra_metadata->>'federalSubject'"
        ") AS источник "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM regions r WHERE r.company_id = источник.company_id "
        "    AND btrim(lower(r.name)) = btrim(lower(источник.имя))"
        ") ON CONFLICT DO NOTHING"))
    await db.commit()

    сколько = (await db.execute(text(
        "SELECT count(*) FROM regions WHERE company_id = :c "
        "AND btrim(lower(name)) = :n"), {"c": company.id, "n": f"тест{метка}"})).scalar()
    assert сколько == 1, f"ожидали один регион на три написания, получили {сколько}"

    # Повторный прогон миграции ничего не добавляет и не падает.
    await db.execute(text(
        "INSERT INTO regions (id, company_id, name, federal_subject) "
        "SELECT gen_random_uuid(), company_id, имя, имя FROM ("
        "  SELECT DISTINCT ON (company_id, btrim(lower(extra_metadata->>'federalSubject'))) "
        "         company_id, extra_metadata->>'federalSubject' AS имя "
        "  FROM service_locations "
        "  WHERE extra_metadata->>'federalSubject' IS NOT NULL "
        "    AND extra_metadata->>'federalSubject' <> '' "
        "  ORDER BY company_id, btrim(lower(extra_metadata->>'federalSubject')), "
        "           extra_metadata->>'federalSubject'"
        ") AS источник "
        "WHERE NOT EXISTS ("
        "  SELECT 1 FROM regions r WHERE r.company_id = источник.company_id "
        "    AND btrim(lower(r.name)) = btrim(lower(источник.имя))"
        ") ON CONFLICT DO NOTHING"))
    await db.commit()
    снова = (await db.execute(text(
        "SELECT count(*) FROM regions WHERE company_id = :c "
        "AND btrim(lower(name)) = :n"), {"c": company.id, "n": f"тест{метка}"})).scalar()
    assert снова == 1


async def test_миграция_регионов_сверяет_нормализованное_имя():
    """Страж на исходник: вернётся `ON CONFLICT (company_id, name)` — вернётся и падение.

    Сам набор DDL выполняется на старте приложения, в тестовую базу его не позвать
    отдельно, поэтому проверяем текст миграции: сверка должна идти по
    `btrim(lower(...))`, как в индексе `uq_regions_company_name_ci`.
    """
    from pathlib import Path
    текст = Path(__file__).resolve().parents[1].joinpath("app/database.py").read_text(encoding="utf-8")
    начало = текст.index("INSERT INTO regions (id, company_id, name, federal_subject)")
    кусок = текст[начало:начало + 1500]
    assert "ON CONFLICT (company_id, name) DO NOTHING" not in кусок, (
        "сверка вернулась к точному имени — «Тест» и «тест» снова разъедутся")
    assert "btrim(lower(" in кусок, "нет нормализации имени при сверке с regions"
