"""Заявка по объекту, заведённому после последней проекции, всё равно создаётся.

Проекция объектов запускается руками из Центра управления, поэтому свежий объект
приложение не знает и отвечает 404 «не спроецирован». `create_object_ticket` в этом
случае досылает справочник и повторяет — проверяем именно это.

Запуск на стенде: exec-py.sh <стек> server/scripts/check_object_ticket_autoprojection.py
Заведённую заявку скрипт не удаляет — у Ядра нет прав на public.tickets; номер печатает,
прибрать можно SQL-ом под владельцем базы.
"""
import asyncio
import uuid

from sqlalchemy import delete, select, text

from app.database import async_session_factory
from app.models import Company, ServiceLocation, User
from app.services import space_projection as sp


async def main() -> None:
    async with async_session_factory() as db:
        company = (await db.execute(select(Company))).scalars().first()
        actor = (await db.execute(select(User).where(User.is_superadmin.is_(True)))).scalars().first()

        obj = ServiceLocation(
            id=uuid.uuid4().hex[:24], company_id=company.id, code=f"chk-{uuid.uuid4().hex[:6]}",
            name="Проверка досыла проекции", type="fuel_station", status="active")
        db.add(obj)
        await db.commit()

        known = (await db.execute(text(
            "select 1 from public.service_objects where eco_object_id = :o"), {"o": obj.id})).first()
        assert known is None, "объект уже спроецирован — проверка ничего не покажет"

        try:
            res = await sp.create_object_ticket(
                db, company.id, obj.id,
                description="Проверка: заявка по свежему объекту без ручной проекции",
                title="Проверка досыла проекции", priority="low", author_email=actor.email)
            print("заявка заведена:", res.get("display_number"), res.get("id"))
        finally:
            await db.execute(delete(ServiceLocation).where(ServiceLocation.id == obj.id))
            await db.commit()

        assert res.get("id"), "заявка не создалась"
        print("проверка пройдена: свежий объект доехал сам")


asyncio.run(main())
