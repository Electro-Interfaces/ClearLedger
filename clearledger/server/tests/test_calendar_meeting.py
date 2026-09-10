"""Видеовстреча запланированной встречи: комната постоянная, вход — участнику."""
import base64
import uuid

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.models import Company, User, UserCompany
from app.routers.work_router import EventIn, calendar_create, calendar_meeting

pytestmark = pytest.mark.asyncio(loop_scope='session')


@pytest.fixture
def jitsi_key():
    """Ключ подписи на время теста: без него конференции выключены (503)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    s = get_settings()
    было = s.jitsi_signing_key
    s.jitsi_signing_key = base64.b64encode(pem).decode()
    yield
    s.jitsi_signing_key = было


async def people(db):
    from datetime import datetime, timedelta, timezone
    company = await db.scalar(select(Company).limit(1))
    owner = await db.scalar(select(User).where(User.email == 'admin@clearledger.ru'))
    await db.merge(UserCompany(company_id=company.id, user_id=owner.id, role='admin'))
    чужой = User(email=f'meet-{uuid.uuid4()}@example.test', name='Чужой',
                 password_hash='!test', company_id=company.id)
    db.add(чужой)
    await db.flush()
    db.add(UserCompany(company_id=company.id, user_id=чужой.id, role='user'))
    await db.flush()
    start = datetime.now(timezone.utc) + timedelta(days=1)
    event = await calendar_create(EventIn(
        company_id=str(company.id), title='Планёрка', starts_at=start,
        ends_at=start + timedelta(hours=1), visibility='private'), db=db, current_user=owner)
    return company, owner, чужой, event


async def test_комната_встречи_постоянна_и_ссылка_ложится_в_карточку(db, jitsi_key):
    company, owner, _, event = await people(db)
    первый = await calendar_meeting(event['id'], company_id=str(company.id),
                                    db=db, current_user=owner)
    второй = await calendar_meeting(event['id'], company_id=str(company.id),
                                    db=db, current_user=owner)
    assert первый['room'] == второй['room'], 'вход второй раз уводит в другую комнату'
    assert первый['moderator_url'] != первый['guest_url'], 'гостю ушёл токен ведущего'

    from app.routers.work_router import calendar_card
    карточка = await calendar_card(event['id'], company_id=str(company.id),
                                   db=db, current_user=owner)
    assert карточка['conference_url'] == первый['guest_url']


async def test_чужому_встречу_не_открыть(db, jitsi_key):
    company, _, чужой, event = await people(db)
    with pytest.raises(HTTPException) as отказ:
        await calendar_meeting(event['id'], company_id=str(company.id),
                               db=db, current_user=чужой)
    assert отказ.value.status_code == 403
