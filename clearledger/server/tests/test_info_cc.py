"""Один источник инструкций, повторный сид и границы внешнего чтения КЦ."""
import re

import pytest
from sqlalchemy import select

from app.models import Company, InfoArticle
from app.services.info_cc import instructions
from app.services.info_seed import seed_info
from app.services.info_seed_cc import ARTICLES


def test_cc_instructions_have_unique_keys_and_readable_steps():
    assert len(ARTICLES) == len({a["title"] for a in ARTICLES}) == len({a["cc_key"] for a in ARTICLES})
    for a in ARTICLES:
        assert len(a["body"]) > 500 and a["summary"]
        assert not re.search('[—–]', a["body"] + a["title"] + a["summary"])
        assert a["bindings"] == [("voice", "cc", 50)]


@pytest.mark.asyncio(loop_scope="session")
async def test_cc_public_pack_is_same_published_platform_content_and_excludes_company(db, client):
    await seed_info(db)
    first = await instructions(db)
    assert len(first["items"]) == len(ARTICLES)
    await seed_info(db)
    assert await instructions(db) == first
    company = Company(name="Учебное пространство КЦ", slug="cc-info-test", profile_id="energy")
    db.add(company); await db.flush()
    db.add(InfoArticle(company_id=company.id, title=ARTICLES[0]["title"], kind="guide", status="published", body_md="Закрытая инструкция компании"))
    db.add(InfoArticle(company_id=None, profile_id="energy", title=ARTICLES[1]["title"], kind="guide", status="published", body_md="Отраслевой документ"))
    db.add(InfoArticle(company_id=None, title="Другая опубликованная статья", kind="guide", status="published", body_md="Не относится к КЦ"))
    row = (await db.execute(select(InfoArticle).where(InfoArticle.company_id.is_(None),
        InfoArticle.profile_id.is_(None), InfoArticle.title == ARTICLES[0]["title"]))).scalars().first()
    row.body_md = "Обновлённый текст из общего Инфо"
    await db.flush()
    pack = await instructions(db)
    assert pack["items"][0]["bodyMd"] == row.body_md
    assert len(pack["items"]) == len(ARTICLES)
    assert set(pack["items"][0]) == {"key", "title", "summary", "bodyMd", "category", "sections", "audience"}
    row.status = "draft"; await db.flush()
    assert len((await instructions(db))["items"]) == len(ARTICLES) - 1
    await db.commit()
    # HTTP-выдача не требует сессии компании и не принимает её контекст.
    response = await client.get('/api/info/cc?company_id=other&article_id=other')
    assert response.status_code == 200
    assert response.json() == await instructions(db)
