import pytest
from sqlalchemy import select

from app.models import Company, InfoArticle, InfoBinding, User
from app.services.info_seed import seed_info
from app.services.info_seed_station import RETIRED_ARTICLE_TITLES


@pytest.mark.asyncio(loop_scope="session")
async def test_обновление_складской_помощи_сохраняет_ссылки_и_чужие_статьи(db):
    await seed_info(db)
    current = "Списание: причины и порядок работы"
    previous = "Списание: шесть причин и что каждая значит"
    article = (await db.execute(select(InfoArticle).where(
        InfoArticle.company_id.is_(None), InfoArticle.profile_id == "fuel",
        InfoArticle.title == current))).scalar_one()
    article_id = article.id
    article.title = previous
    company = (await db.execute(select(Company).limit(1))).scalar_one()
    user = (await db.execute(select(User).limit(1))).scalar_one()
    title = RETIRED_ARTICLE_TITLES[0]
    old = InfoArticle(title=title, profile_id="fuel", body_md="Старый текст")
    own = InfoArticle(title=title, company_id=company.id, profile_id="fuel",
                      body_md="Порядок компании")
    edited = InfoArticle(title=title, profile_id="fuel", updated_by=user.id,
                         body_md="Правка человека")
    other = InfoArticle(title=title, profile_id="office", body_md="Другой профиль")
    db.add_all([old, own, edited, other])
    await db.flush()

    await seed_info(db)
    first_ids = set((await db.execute(select(InfoArticle.id))).scalars())
    await seed_info(db)
    assert set((await db.execute(select(InfoArticle.id))).scalars()) == first_ids
    await db.refresh(article)
    assert article.id == article_id and article.title == current
    assert not (await db.execute(select(InfoArticle.id).where(
        InfoArticle.company_id.is_(None), InfoArticle.profile_id == "fuel",
        InfoArticle.title == previous))).scalars().all()
    assert (await db.execute(select(InfoBinding.id).where(
        InfoBinding.article_id == article_id))).scalars().all()
    await db.refresh(old)
    assert old.status == "draft" and old.body_md == "Старый текст"
    for protected, body in [(own, "Порядок компании"), (edited, "Правка человека"),
                            (other, "Другой профиль")]:
        await db.refresh(protected)
        assert protected.status == "published" and protected.body_md == body
