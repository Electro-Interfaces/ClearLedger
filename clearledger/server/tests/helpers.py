"""Общие мелочи тестов.

Главная здесь — `seed_company_id`. Тесты годами брали «первую компанию из
каталога» (`me["companies"][0]`), а каталог отсортирован по имени: стоило тесту
завести компанию с именем на «Ж», и все следующие тесты начинали работать в
ней — со своими юрлицами, видами и номерами. Падало при этом не то, что
сломано, а то, что шло следом.

Якорь — slug компании сида, а не порядок в списке.
"""
import asyncio
from pathlib import Path
from typing import Any

# Компании сида (`app/seed.py`): «ООО ГИГ» и «РусГидро». Первая — топливный
# профиль, на нём написано большинство проверок.
SEED_SLUGS = ("gig", "rushydro")


async def drain_application_tasks() -> None:
    """Дождаться работы API в фоне до удаления тестовых схем.

    ASGITransport не управляет lifespan и не ждёт create_task из аудита.
    Берём только корутины приложения, не служебные задачи pytest/asyncio.
    Доставка может породить следующую задачу (чат → push), поэтому ждём
    до опустошения набора. Таймаут означает ошибку lifecycle, а не retry.
    """
    app_dir = Path(__file__).resolve().parents[1] / "app"

    async def drain():
        while True:
            pending = [
                task for task in asyncio.all_tasks()
                if task is not asyncio.current_task()
                and (code := getattr(task.get_coro(), "cr_code", None))
                and Path(code.co_filename).resolve().is_relative_to(app_dir)
            ]
            if not pending:
                return
            await asyncio.gather(*pending)

    await asyncio.wait_for(drain(), timeout=10)


def seed_company_id(me: dict[str, Any], slug: str = "gig") -> str:
    """Идентификатор компании сида по slug — устойчиво к чужим компаниям."""
    companies = me.get("companies") or []
    assert companies, "сид-суперадмин не состоит ни в одной компании"
    for company in companies:
        if company.get("slug") == slug:
            return company["id"]
    # Профиль сида мог быть сужен переменной окружения стека — тогда берём любую
    # компанию сида, а не первую попавшуюся из каталога.
    for company in companies:
        if company.get("slug") in SEED_SLUGS:
            return company["id"]
    return companies[0]["id"]
