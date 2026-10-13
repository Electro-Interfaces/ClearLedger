"""Материалы к встрече для её участников: файл, ссылка, права и счётчик."""
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException, UploadFile
from sqlalchemy import select

from app.models import CalendarPaper, Company, User, UserCompany
from app.routers.work_router import (
    EventIn, PaperIn, calendar_create, paper_add, paper_file, paper_remove,
    paper_upload, papers_list,
)

pytestmark = pytest.mark.asyncio(loop_scope='session')


async def люди(db):
    company = await db.scalar(select(Company).limit(1))
    хозяин = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=хозяин.id, role='admin'))
    зван = User(email=f'paper-{uuid.uuid4()}@example.test', name='Приглашённый',
                password_hash='!test', company_id=company.id)
    чужой = User(email=f'paper-{uuid.uuid4()}@example.test', name='Посторонний',
                 password_hash='!test', company_id=company.id)
    db.add_all([зван, чужой])
    await db.flush()
    db.add(UserCompany(company_id=company.id, user_id=зван.id, role='user'))
    db.add(UserCompany(company_id=company.id, user_id=чужой.id, role='user'))
    await db.flush()
    начало = datetime.now(timezone.utc) + timedelta(days=1)
    встреча = await calendar_create(EventIn(
        company_id=str(company.id), title='Планёрка', starts_at=начало,
        ends_at=начало + timedelta(hours=1), visibility='private',
        attendee_ids=[str(зван.id)]), db=db, current_user=хозяин)
    return company, хозяин, зван, чужой, встреча


async def test_материалы_встречи(db, tmp_path, monkeypatch):
    monkeypatch.setenv('UPLOAD_DIR', str(tmp_path))
    company, хозяин, зван, чужой, встреча = await люди(db)
    cid, eid = str(company.id), встреча['id']

    # Участник прикладывает ссылку и файл — не только организатор.
    ссылка = await paper_add(eid, PaperIn(company_id=cid, url='https://example.test/agenda',
                                          title='Повестка'), db=db, current_user=зван)
    assert ссылка['kind'] == 'link' and ссылка['title'] == 'Повестка'
    # Организатору пришло личное сообщение о материале; приложившему — нет.
    from app.models import ChatMessage, ChatParticipant
    сказано = (await db.execute(select(ChatMessage).where(
        ChatMessage.content.like('%приложил к встрече «Планёрка»%Повестка')))).scalars().all()
    assert len(сказано) == 1
    читают = set((await db.execute(select(ChatParticipant.user_id).where(
        ChatParticipant.room_id == сказано[0].room_id))).scalars())
    assert хозяин.id in читают and зван.id not in читают
    файл = await paper_upload(
        eid, company_id=cid,
        file=UploadFile(file=io.BytesIO(b'%PDF-test'), filename='Смета.pdf'),
        db=db, current_user=хозяин)
    assert файл['kind'] == 'file' and файл['size'] == 9

    список = await papers_list(eid, company_id=cid, db=db, current_user=зван)
    assert [m['title'] for m in список['papers']] == ['Повестка', 'Смета.pdf']
    по_имени = {m['title']: m for m in список['papers']}
    assert по_имени['Повестка']['can_remove'], 'своё убрать можно'
    assert not по_имени['Смета.pdf']['can_remove'], 'чужое участник не убирает'
    assert по_имени['Смета.pdf']['added_by'] == хозяин.name

    ответ = await paper_file(eid, файл['id'], company_id=cid, db=db, current_user=зван)
    assert open(ответ.path, 'rb').read() == b'%PDF-test'

    # Не ссылка и не документ, либо оба сразу, либо не http — отказ.
    for плохо in (dict(), dict(url='ftp://x'), dict(url='https://x', target_ref=f'doc:{uuid.uuid4()}')):
        with pytest.raises(HTTPException) as отказ:
            await paper_add(eid, PaperIn(company_id=cid, **плохо), db=db, current_user=хозяин)
        assert отказ.value.status_code == 400

    # Посторонний закрытой встречи не видит ни списка, ни файла, и приложить не может.
    for вызов in (
        lambda: papers_list(eid, company_id=cid, db=db, current_user=чужой),
        lambda: paper_file(eid, файл['id'], company_id=cid, db=db, current_user=чужой),
        lambda: paper_add(eid, PaperIn(company_id=cid, url='https://x.test'),
                          db=db, current_user=чужой),
    ):
        with pytest.raises(HTTPException) as отказ:
            await вызов()
        assert отказ.value.status_code == 403

    # Чужой материал участник убрать не может, организатор — может.
    with pytest.raises(HTTPException) as отказ:
        await paper_remove(eid, файл['id'], company_id=cid, db=db, current_user=зван)
    assert отказ.value.status_code == 403
    await paper_remove(eid, ссылка['id'], company_id=cid, db=db, current_user=хозяин)
    осталось = (await db.execute(select(CalendarPaper).where(
        CalendarPaper.event_id == uuid.UUID(eid)))).scalars().all()
    assert [p.title for p in осталось] == ['Смета.pdf']


async def test_счётчик_материалов_в_строке_конференции(db, tmp_path, monkeypatch):
    """Строка конференции говорит, что повестка есть, до входа в карточку."""
    from app.routers.conf_router import _load
    from app.models import CalendarEvent

    monkeypatch.setenv('UPLOAD_DIR', str(tmp_path))
    company, хозяин, _, _, встреча = await люди(db)
    cid, eid = str(company.id), встреча['id']
    ev = await db.get(CalendarEvent, uuid.UUID(eid))
    assert (await _load(db, [ev], хозяин.id))[0]['papers'] == 0
    await paper_add(eid, PaperIn(company_id=cid, url='https://example.test/a'),
                    db=db, current_user=хозяин)
    await paper_add(eid, PaperIn(company_id=cid, url='https://example.test/b'),
                    db=db, current_user=хозяин)
    assert (await _load(db, [ev], хозяин.id))[0]['papers'] == 2
