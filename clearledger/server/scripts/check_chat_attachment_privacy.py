"""Проверка приватности вложения: файл разговора виден участнику и не виден чужому.

Создаёт временную комнату с одним участником, сообщение с вложением и пробует
скачать его тремя ролями. Всё созданное удаляет за собой.
"""
import asyncio, uuid
from fastapi import HTTPException
from sqlalchemy import select, delete
from app.database import async_session_factory
from app.models import User, ChatRoom, ChatParticipant, ChatMessage, SourceFile
from app.routers.intake_router import download_file


async def try_download(fid, user, db) -> str:
    try:
        await download_file(file_id=str(fid), db=db, current_user=user)
        return "отдан"
    except HTTPException as e:
        return f"{e.status_code}: {e.detail}"


async def main():
    async with async_session_factory() as db:
        users = (await db.execute(select(User).where(User.is_superadmin.is_(False)).limit(2))).scalars().all()
        assert len(users) == 2, "нужно два обычных пользователя"
        owner, stranger = users
        cid = owner.company_id or owner.default_company_id
        print("участник:", owner.name, "| чужой:", stranger.name)

        room = ChatRoom(id=uuid.uuid4(), company_id=cid, type="direct",
                        name="проверка вложения", created_by=owner.id)
        db.add(room); await db.flush()
        db.add(ChatParticipant(room_id=room.id, user_id=owner.id))
        src = SourceFile(id=uuid.uuid4(), company_id=cid, file_name="check.txt",
                         mime_type="text/plain", storage_path="/tmp/нет-такого-файла")
        db.add(src); await db.flush()
        msg = ChatMessage(id=uuid.uuid4(), room_id=room.id, user_id=owner.id, content="",
                          type="file", file_url=f"/api/files/{src.id}", file_name="check.txt")
        db.add(msg); await db.flush()

        print("участник       →", await try_download(src.id, owner, db))
        print("чужой          →", await try_download(src.id, stranger, db))
        msg.deleted_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        await db.flush()
        print("после удаления →", await try_download(src.id, owner, db))

        await db.execute(delete(ChatMessage).where(ChatMessage.id == msg.id))
        await db.execute(delete(ChatParticipant).where(ChatParticipant.room_id == room.id))
        await db.execute(delete(ChatRoom).where(ChatRoom.id == room.id))
        await db.execute(delete(SourceFile).where(SourceFile.id == src.id))
        await db.commit()
        print("прибрано")


asyncio.run(main())
