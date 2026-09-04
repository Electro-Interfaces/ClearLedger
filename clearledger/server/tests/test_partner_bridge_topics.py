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
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Company, PartnerAttachment, PartnerSpace, Task, User
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


async def test_ответ_возвращает_мяч_заданию_клиента(db: AsyncSession):
    """Задание, переданное поддержке, не должно висеть в «ждём внешних» вечно.

    Связь здесь обратная той, что у поддержки: задание завёл клиент, а обращение
    выросло из его карточки — значит предмет хранит обращение, а не задание.
    Ищи мост только по `Task.subject_ref`, и мяч у клиента не вернётся никогда:
    человек будет ждать ответа, который уже пришёл.
    """
    from app.routers.space_bridge_router import _return_ball

    cid, partner = await _партнёр(db)
    task = Task(company_id=cid, title="Разобраться с кассой", waiting_for="external")
    db.add(task)
    await db.flush()

    тема = await partner_bridge.ensure_topic(
        db, cid, partner, uuid.uuid4().hex, title="Касса",
        subject_kind="task", subject_ref=str(task.id))
    await db.commit()

    await partner_bridge.record_incoming(db, cid, partner, {
        "id": uuid.uuid4().hex, "body": "Посмотрели, дело в драйвере",
        "topic": тема.code, "topicTitle": "Касса"})
    await _return_ball(db, cid, тема.id)

    await db.refresh(task)
    assert task.waiting_for is None


async def test_секретарь_говорит_про_обращение_один_раз(db: AsyncSession):
    """Повод «поддержка ждёт вас» человек должен получить и не получать снова.

    Сводка окна лечит поток числом сообщений: повторить один и тот же повод в
    каждом окне — тот же поток, только медленнее. И наоборот, промолчать про
    состояние «ждём вас» значит оставить мяч у человека, который об этом не
    знает: разговор идёт в панели, а панель открывают, когда вспомнят.
    """
    from app.services import digest
    from app.services.task_scheduler import run_partner_topics

    company = (await db.execute(select(Company).limit(1))).scalars().first()
    кто = (await db.execute(select(User).where(
        User.company_id == company.id).limit(1))).scalars().first()
    вендор = PartnerSpace(company_id=company.id, role="vendor",
                          code=f"desk-{uuid.uuid4().hex[:8]}", name="Техподдержка")
    db.add(вендор)
    await db.flush()
    тема = await partner_bridge.ensure_topic(
        db, company.id, вендор, uuid.uuid4().hex, title="Касса",
        opened_by_id=кто.id if кто else None)
    тема.state = "waiting"
    await db.commit()

    now = datetime.now(UTC)
    bucket = digest.Bucket()
    assert await run_partner_topics(db, now, bucket) >= 1
    поводы = [line for lines in bucket.lines.values() for line in lines
              if line.key == f"partner-topic:{тема.id}"]
    assert len(поводы) == 1
    assert "ждёт вашего ответа" in поводы[0].text

    # Доставка помечает сказанное — второе окно про то же молчит.
    поводы[0].mark()
    await db.commit()
    bucket2 = digest.Bucket()
    await run_partner_topics(db, now, bucket2)
    assert not [line for lines in bucket2.lines.values() for line in lines
                if line.key == f"partner-topic:{тема.id}"]


async def test_у_поддержки_свои_обращения_в_сводку_не_идут(db: AsyncSession):
    """У нас обращения живут в очереди Координатора со своими сроками.

    Позвать сводкой на ту же работу значит позвать дважды: оператор смотрит
    очередь, а не личную комнату.
    """
    from app.services import digest
    from app.services.task_scheduler import run_partner_topics

    cid, partner = await _партнёр(db)          # роль `client` — это наш клиент
    кто = (await db.execute(select(User).where(User.company_id == cid).limit(1))).scalars().first()
    тема = await partner_bridge.ensure_topic(
        db, cid, partner, uuid.uuid4().hex, title="Обращение клиента",
        opened_by_id=кто.id if кто else None)
    тема.state = "waiting"
    await db.commit()

    bucket = digest.Bucket()
    await run_partner_topics(db, datetime.now(UTC), bucket)
    assert not [line for lines in bucket.lines.values() for line in lines
                if line.key == f"partner-topic:{тема.id}"]
