"""Обращение между пространствами: одна ветка на обеих сторонах (docs/BRIDGE.md).

Проверяются три правила, поломка которых выглядит как работающая программа.

Первое: обращение с одним кодом заводится один раз. Разойдись коды — ответ
поддержки вернулся бы в новую ветку, и у клиента вопрос остался бы без ответа при
том, что ответ отправлен.

Второе: состояние приходит только по известному обращению. Иначе опечатка в коде
темы завела бы у клиента пустую строку в списке — обращение, которого он не
открывал.

Третье: лента обращения показывает только его реплики. Ошибка здесь показывает
человеку чужую переписку с поддержкой.

Запуск: cd server && py -3 -m pytest tests/test_partner_bridge_topics.py -v
"""
import base64
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, PartnerAttachment, PartnerSpace
from app.services import partner_bridge

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _партнёр(db: AsyncSession) -> tuple[uuid.UUID, PartnerSpace]:
    company = (await db.execute(select(Company).limit(1))).scalars().first()
    assert company is not None
    # Без адреса и ключа: доставка не уйдёт наружу, а записи у себя должны лечь
    # ровно так же — «связь ещё не включили» не повод терять переписку.
    partner = PartnerSpace(company_id=company.id, role="client",
                           code=f"test-{uuid.uuid4().hex[:8]}", name="Тестовое пространство")
    db.add(partner)
    await db.commit()
    await db.refresh(partner)
    return company.id, partner


async def test_обращение_с_тем_же_кодом_не_заводится_дважды(db: AsyncSession):
    cid, partner = await _партнёр(db)
    код = uuid.uuid4().hex

    первое = await partner_bridge.ensure_topic(db, cid, partner, код, title="Касса не печатает")
    await db.commit()
    второе = await partner_bridge.ensure_topic(db, cid, partner, код, title="Другое название")
    await db.commit()

    assert первое.id == второе.id
    # Заголовок остаётся тот, что дал открывший: реплики соседа несут его лишь
    # затем, чтобы новое обращение было чем назвать.
    assert второе.title == "Касса не печатает"


async def test_состояние_по_неизвестному_обращению_не_заводит_его(db: AsyncSession):
    cid, partner = await _партнёр(db)
    assert await partner_bridge.apply_state(
        db, partner, uuid.uuid4().hex, state="resolved", number="ЭЛСИ-1") is None
    assert await partner_bridge.topics(db, cid, partner) == []


async def test_состояние_и_номер_доезжают_до_обращения(db: AsyncSession):
    cid, partner = await _партнёр(db)
    тема = await partner_bridge.ensure_topic(db, cid, partner, uuid.uuid4().hex, title="Тариф")
    await db.commit()

    await partner_bridge.apply_state(db, partner, тема.code, state="in_progress", number="ЭЛСИ-318")
    (строка,) = await partner_bridge.topics(db, cid, partner)
    assert строка["state"] == "in_progress"
    assert строка["number"] == "ЭЛСИ-318"

    # Чужое значение состояния не применяется: словарь общий, и «почти такое же»
    # состояние у соседа показать нечем.
    await partner_bridge.apply_state(db, partner, тема.code, state="почти_решено", number=None)
    (строка,) = await partner_bridge.topics(db, cid, partner)
    assert строка["state"] == "in_progress"


async def test_лента_обращения_не_показывает_чужие_реплики(db: AsyncSession):
    cid, partner = await _партнёр(db)
    первое = uuid.uuid4().hex
    второе = uuid.uuid4().hex

    await partner_bridge.record_incoming(db, cid, partner, {
        "id": uuid.uuid4().hex, "body": "Касса не печатает чек",
        "topic": первое, "topicTitle": "Касса"})
    await partner_bridge.record_incoming(db, cid, partner, {
        "id": uuid.uuid4().hex, "body": "Не сходится тариф",
        "topic": второе, "topicTitle": "Тариф"})
    # Повтор доставки: отправитель ретраит по коду ответа, и дубль в ленте —
    # это то, что человек примет за наш второй вопрос.
    повтор = uuid.uuid4().hex
    _, новое = await partner_bridge.record_incoming(db, cid, partner, {
        "id": повтор, "body": "Ещё раз про кассу", "topic": первое, "topicTitle": "Касса"})
    assert новое is True
    _, снова = await partner_bridge.record_incoming(db, cid, partner, {
        "id": повтор, "body": "Ещё раз про кассу", "topic": первое, "topicTitle": "Касса"})
    assert снова is False

    тема = await partner_bridge.ensure_topic(db, cid, partner, первое)
    лента = await partner_bridge.feed(db, cid, partner, topic=тема)
    assert [m["body"] for m in лента] == ["Касса не печатает чек", "Ещё раз про кассу"]
    # Без темы — вся переписка с пространством: так читают историю.
    assert len(await partner_bridge.feed(db, cid, partner)) == 3


async def test_негодное_вложение_не_роняет_приём_сообщения(db: AsyncSession):
    """Текст важнее картинки.

    Отказать в приёме обращения из-за испорченного вложения значит потерять само
    обращение: отправитель получит ошибку и будет считать, что мы не ответили, —
    хотя ответить нам просто не на что.
    """
    cid, partner = await _партнёр(db)
    код = uuid.uuid4().hex
    row, новое = await partner_bridge.record_incoming(db, cid, partner, {
        "id": uuid.uuid4().hex, "body": "Скриншот ошибки", "topic": код,
        "topicTitle": "Касса",
        "files": [
            {"id": "1", "name": "screen.png", "contentBase64": "не base64 вовсе"},
            # Больше потолка: base64 честный, но такой файл мост не возит.
            {"id": "2", "name": "dump.sql",
             "contentBase64": base64.b64encode(b"x" * (partner_bridge.MAX_FILE_BYTES + 1)).decode()},
        ],
    })
    assert новое is True
    assert row.body == "Скриншот ошибки"
    сколько = await db.scalar(select(func.count()).select_from(PartnerAttachment).where(
        PartnerAttachment.message_id == row.id))
    assert сколько == 0
