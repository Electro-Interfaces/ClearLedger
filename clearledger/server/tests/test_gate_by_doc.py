"""Пункт чек-листа проекта закрывается документом «Трека».

Ловим разрыв, из-за которого акт ввода, прошедший круг виз и подписание, гейт не
закрывал: для гейта требовалось, чтобы кто-то отдельно приложил тот же файл в
карточку проекта. Два источника правды об одном факте — и человек выбирал,
какому верить.
"""
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocCard, DocKind, EzsSite
from app.services import ezs_checklist, ezs_site_work

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_согласованный_документ_закрывает_пункт(db: AsyncSession):
    from sqlalchemy import select

    from app.models import Company

    company = (await db.execute(select(Company).limit(1))).scalars().first()
    cid = company.id
    site = EzsSite(company_id=cid, title=f"Гейт {uuid.uuid4().hex[:6]}",
                   kind="new_build", stage="contracting")
    kind = DocKind(company_id=cid, code=f"lease{uuid.uuid4().hex[:6]}",
                   name="Договор аренды ЗУ", family="internal", direction="none",
                   gate_key="contract")
    db.add_all([site, kind])
    await db.flush()

    # Связь, а не предмет: предмет карточки уникален на компанию, а по проекту
    # бумаг десяток — договор аренды, договор ТП, акт ввода.
    from app.models import DocRelation

    draft = DocCard(company_id=cid, kind_id=kind.id, kind_code=kind.code,
                    family="internal", direction="none",
                    title="Договор аренды (черновик)", status="draft")
    db.add(draft)
    await db.flush()
    db.add(DocRelation(company_id=cid, doc_id=draft.id, kind="basis",
                       target_ref=f"site:{site.id}"))
    await db.flush()
    # Черновик не подтверждает ничего: иначе гейт закрывался бы намерением.
    assert "contract" not in await ezs_site_work.site_doc_kinds(db, site.id)

    draft.approval_status = "approved"
    await db.flush()
    assert "contract" in await ezs_site_work.site_doc_kinds(db, site.id)

    # Документ без объявленного пункта гейт не двигает, даже согласованный.
    other = DocKind(company_id=cid, code=f"memo{uuid.uuid4().hex[:6]}",
                    name="Служебная записка", family="internal", direction="none")
    db.add(other)
    await db.flush()
    note = DocCard(company_id=cid, kind_id=other.id, kind_code=other.code,
                   family="internal", direction="none", title="Записка",
                   status="draft", approval_status="approved")
    db.add(note)
    await db.flush()
    db.add(DocRelation(company_id=cid, doc_id=note.id, kind="basis",
                       target_ref=f"site:{site.id}"))
    await db.flush()
    assert await ezs_site_work.site_doc_kinds(db, site.id) == {"contract"}

    await db.rollback()


async def test_перечень_пунктов_собирается_из_чеклиста():
    """Второй список, разойдясь с чек-листом, дал бы вид, закрывающий
    несуществующий пункт: человек искал бы, почему документ не двигает гейт."""
    keys = ezs_checklist.doc_gate_keys()
    assert keys, "чек-лист обязан содержать пункты, закрываемые документом"
    from_tasks = {i["doc"] for i in ezs_checklist.TASKS if i.get("doc")}
    assert {k["key"] for k in keys} == from_tasks
    assert all(k["label"] for k in keys)
