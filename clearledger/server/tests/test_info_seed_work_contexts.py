import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Company, InfoArticle, InfoBinding, InfoCategory
from app.services import info_center
from app.services.info_seed import seed_info
from app.services.info_seed_projects import ARTICLES as PROJECTS, CATEGORY
from app.services.info_seed_track import ARTICLES as TRACK


@pytest.mark.asyncio(loop_scope="session")
async def test_help_migrates_to_common_profile_without_duplicates(db):
    company = Company(name="Учебный офис", slug="help-work-office", profile_id="office")
    db.add(company)
    old_category = InfoCategory(title=CATEGORY, profile_id="energy", sort_order=8)
    db.add(old_category)
    await db.flush()
    title = next(a["title"] for a in PROJECTS if a.get("common"))
    old = InfoArticle(title=title, kind="guide", profile_id="energy",
                      category_id=old_category.id, body_md="Прежняя инструкция")
    own = InfoArticle(title=title, kind="guide", company_id=company.id,
                      body_md="Порядок компании", status="draft")
    db.add_all([old, own])
    await db.flush()
    old_id = old.id

    await seed_info(db)
    first_ids = set((await db.execute(select(InfoArticle.id))).scalars())
    await seed_info(db)
    assert set((await db.execute(select(InfoArticle.id))).scalars()) == first_ids
    await db.refresh(old)
    await db.refresh(own)
    assert old.id == old_id and old.profile_id is None
    assert own.body_md == "Порядок компании" and own.status == "draft"
    assert (await db.execute(select(InfoArticle.id).where(
        InfoArticle.company_id.is_(None), InfoArticle.title == title))).scalars().all() == [old_id]

    common = [a for a in PROJECTS if a.get("common")]
    for article in common:
        rows = (await db.execute(select(InfoArticle).where(
            InfoArticle.title == article["title"], InfoArticle.company_id.is_(None)))).scalars().all()
        assert len(rows) == 1 and rows[0].profile_id is None
        bindings = (await db.execute(select(InfoBinding).where(
            InfoBinding.article_id == rows[0].id))).scalars().all()
        assert len(bindings) == len(article["bindings"])

    for app, section, expected in [
        ("projects", "pr_project:overview", "Вкладка «Обзор»: ближайший результат и ожидания"),
        ("projects", "pr_project:track", "Вкладка «Трек»: работа и бумаги по проекту"),
        ("projects", "pr_project:chats", "Вкладка «Чаты»: разговор по проекту"),
        ("chat", None, "Из сообщения в работу: контекст, поручение и процесс"),
        ("docs", "setup:templates", "Трек и приложения: контекст и настройки работы"),
    ]:
        result = await info_center.context(db, company.id, app_code=app, section_key=section)
        assert expected in {a["title"] for a in result["items"]}

    building = next(a for a in PROJECTS if not a.get("common"))
    building_row = (await db.execute(select(InfoArticle).where(
        InfoArticle.title == building["title"], InfoArticle.company_id.is_(None)))).scalar_one()
    assert await info_center.article(db, company.id, building_row.id) is None
    company.profile_id = "energy"
    await db.flush()
    assert await info_center.article(db, company.id, building_row.id) is not None


def test_help_images_and_context_bindings_match_frontend():
    front = Path(__file__).resolve().parents[2]
    if not (front / "src").exists():
        pytest.skip("Дерево фронта недоступно")
    tabs = (front / "src/components/sites/ProjectTabs.tsx").read_text(encoding="utf-8")
    tab_keys = set(re.findall(r"k: '([^']+)'", tabs))
    for article in PROJECTS + TRACK:
        for app, section, _ in article["bindings"]:
            if app == "projects" and section and section.startswith("pr_project:"):
                assert section.split(":", 1)[1] in tab_keys, article["title"]
        for line in article["body"].splitlines():
            if "![" not in line:
                continue
            match = re.fullmatch(r"!\[[^]]*\]\((/help/[^)]+)\)", line.strip())
            assert match, article["title"]
            assert (front / "public" / match[1].lstrip("/")).is_file(), match[1]
