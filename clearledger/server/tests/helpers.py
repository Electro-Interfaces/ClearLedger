"""Общие мелочи тестов.

Главная здесь — `seed_company_id`. Тесты годами брали «первую компанию из
каталога» (`me["companies"][0]`), а каталог отсортирован по имени: стоило тесту
завести компанию с именем на «Ж», и все следующие тесты начинали работать в
ней — со своими юрлицами, видами и номерами. Падало при этом не то, что
сломано, а то, что шло следом.

Якорь — slug компании сида, а не порядок в списке.
"""
from typing import Any

# Компании сида (`app/seed.py`): «ООО ГИГ» и «РусГидро». Первая — топливный
# профиль, на нём написано большинство проверок.
SEED_SLUGS = ("gig", "rushydro")


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
