"""Справка Телефонии: реальное меню, картинки и выдача общего API знаний."""
import re
from pathlib import Path

import pytest
from sqlalchemy import select

from app.models import Company, InfoArticle, InfoBinding, InfoCategory
from app.services import info_center
from app.services.info_seed import seed_info
from app.services.info_seed_voice import ARTICLES, CATEGORIES
from app.services.info_seed_cc import ARTICLES as CC_ARTICLES

FRONT = Path(__file__).resolve().parents[2]


def test_voice_help_covers_real_routes_and_images():
    """Добавленный экран без справки или переименованный ключ ломает проверку."""
    menu = FRONT / "src/pages/voice/views.ts"
    if not menu.exists():
        pytest.skip("Фронт недоступен в backend-only образе")
    keys = set(re.findall(r"\{ key: '([^']+)', path:", menu.read_text()))
    bindings = {section.split(":")[0] for a in ARTICLES for app, section, _ in a["bindings"] if app == "voice" and section}
    assert bindings == keys
    assert len({a["title"] for a in ARTICLES}) == len(ARTICLES)
    assert {a["category"] for a in ARTICLES} == {c["title"] for c in CATEGORIES}
    for a in ARTICLES:
        assert a["summary"] and len(a["body"]) > 400
        assert not re.search("[—–]", a["title"] + a["summary"] + a["body"])
        images = re.findall(r"(?m)^!\[[^]]+\]\((/help/voice/[^)]+\.png)\)$", a["body"])
        assert images, a["title"]
        for url in images:
            path = FRONT / "public" / url.lstrip("/")
            assert path.is_file(), url
            assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), url


@pytest.mark.asyncio(loop_scope="session")
async def test_voice_seed_is_repeatable_and_preserves_company_document(db):
    company = Company(name="Учебная сеть", slug="voice-help-seed", profile_id="energy")
    db.add(company)
    await db.flush()
    own = InfoArticle(company_id=company.id, title=ARTICLES[0]["title"], kind="lnd",
                      body_md="Собственный регламент организации", status="draft")
    db.add(own)
    await db.flush()
    await seed_info(db)
    seeded = (await db.execute(select(InfoArticle).where(
        InfoArticle.company_id.is_(None), InfoArticle.title.in_([a["title"] for a in ARTICLES])))).scalars().all()
    ids = {a.id for a in seeded}
    assert len(ids) == len(ARTICLES)
    assert all(a.profile_id is None and a.status == "published" for a in seeded)
    await seed_info(db)
    again = set((await db.execute(select(InfoArticle.id).where(
        InfoArticle.company_id.is_(None), InfoArticle.title.in_([a["title"] for a in ARTICLES])))).scalars())
    assert again == ids
    await db.refresh(own)
    assert own.body_md == "Собственный регламент организации" and own.status == "draft"
    root = (await db.execute(select(InfoCategory).where(
        InfoCategory.title == "Телефония", InfoCategory.company_id.is_(None)))).scalar_one()
    children = (await db.execute(select(InfoCategory).where(InfoCategory.parent_id == root.id))).scalars().all()
    assert {c.title for c in children} == {c["title"] for c in CATEGORIES}
    bindings = (await db.execute(select(InfoBinding).where(InfoBinding.article_id.in_(ids)))).scalars().all()
    assert len(bindings) == sum(len(a["bindings"]) for a in ARTICLES)


@pytest.mark.asyncio(loop_scope="session")
async def test_voice_help_is_available_by_context_and_is_company_scoped(db):
    energy = Company(name="Учебная энергетика", slug="voice-help-energy", profile_id="energy")
    office = Company(name="Учебный офис", slug="voice-help-office", profile_id="office")
    db.add_all([energy, office])
    await db.flush()
    own = InfoArticle(company_id=energy.id, title="Закрытый порядок работы линии", kind="lnd",
                      body_md="Правило только учебной энергетики", status="published")
    db.add(own)
    await db.flush()
    db.add(InfoBinding(article_id=own.id, app_code="voice", section_key="calls", weight=500))
    await seed_info(db)
    for company in [energy, office]:
        tree = await info_center.tree(db, company.id, app_code="voice")
        assert tree["total"] == len(ARTICLES) + len(CC_ARTICLES) + (1 if company == energy else 0)
        for section in ["now", "calls", "reception", "connections", "health", "extensions", "outbound"]:
            result = await info_center.context(db, company.id, app_code="voice", section_key=section)
            specific = [a for a in result["items"] if a.get("exact")]
            assert specific, section
            assert result["items"][0]["exact"]
            assert any(a["title"] == ARTICLES[0]["title"] for a in result["items"])
            if company == office:
                assert all(a["id"] != str(own.id) for a in result["items"])
    assert await info_center.article(db, office.id, own.id) is None


@pytest.mark.asyncio(loop_scope="session")
async def test_voice_help_ranks_current_source_and_tab_before_parent(db):
    company = Company(name="Учебная линия", slug="voice-help-context", profile_id="energy")
    db.add(company)
    await db.flush()
    await seed_info(db)
    for section, first, absent in [
        ("calls:node:card", "Карточка звонка: участки, запись и итог", "МегаФон ВАТС: история, операторы и группы"),
        ("calls:megafon:calls", "МегаФон ВАТС: история, операторы и группы", "Журнал звонков узла: поиск и отбор"),
        ("stats:megafon:operators", "МегаФон: показатели операторов", "Статистика: от показателя к звонкам"),
        ("stats:megafon:groups", "МегаФон: группы и полнота сведений", "МегаФон: показатели операторов"),
        ("report:megafon", "МегаФон: отчёт за месяц", "Отчёт за месяц: источник, версия и выгрузка"),
        ("report:node", "Отчёт за месяц: источник, версия и выгрузка", "МегаФон: отчёт за месяц"),
        ("passport:access", "Паспорт КЦ: допуск операторов", "Паспорт КЦ: приватность карточки"),
        ("webhooks:keys", "Ключи систем: выдать доступ к данным узла", "МегаФон: отчёт за месяц"),
    ]:
        result = await info_center.context(db, company.id, app_code="voice", section_key=section)
        titles = [a["title"] for a in result["items"]]
        assert titles[0] == first, (section, titles)
        assert absent not in titles
        assert len(titles) == len(set(titles))


@pytest.mark.asyncio(loop_scope="session")
async def test_context_limit_counts_unique_articles_not_bindings(db):
    company = Company(name="Учебная компания", slug="voice-help-dedup", profile_id="energy")
    db.add(company)
    await db.flush()
    for i in range(10):
        article = InfoArticle(company_id=company.id, title=f"Памятка {i}", kind="lnd",
                              body_md="Учебный документ", status="published")
        db.add(article)
        await db.flush()
        for section in ["calls:node:card", "calls:node", "calls", None]:
            db.add(InfoBinding(article_id=article.id, app_code="voice", section_key=section, weight=1000 - i))
    await db.flush()
    result = await info_center.context(db, company.id, app_code="voice", section_key="calls:node:card", limit=8)
    assert len(result["items"]) == 8
    assert len({a["id"] for a in result["items"]}) == 8
    assert [a["title"] for a in result["items"]] == [f"Памятка {i}" for i in range(8)]
