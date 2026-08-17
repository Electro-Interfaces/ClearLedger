"""
Intake: загрузка файлов + скачивание сохранённых файлов.
POST /api/intake — загрузка файла, возвращает source_id.
GET /api/files/{file_id} — скачивание файла по ID.
"""

import hashlib
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, get_current_user
from app.config import get_settings
from app.database import get_db
from app.deps import get_owned
from app.models import ChatMessage, ChatParticipant, SourceFile, User

router = APIRouter(tags=["Intake / Файлы"])

# Директория хранения загруженных файлов
UPLOAD_DIR = Path("uploads")


def _ensure_upload_dir() -> None:
    """Создаёт директорию для загрузок, если не существует."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


@router.post("/intake")
async def upload_file(
    file: UploadFile,
    company_id: str | None = None,
    purpose: str = "data",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Загрузить файл. Возвращает source_id.
    Файл сохраняется на диск, метаданные — в БД (source_files).
    """
    _ensure_upload_dir()

    content = await file.read()
    file_size = len(content)

    settings = get_settings()
    max_size = settings.ocr_max_file_size
    if file_size > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл слишком большой ({file_size} байт, максимум {max_size})",
        )

    # SHA-256 fingerprint
    fingerprint = hashlib.sha256(content).hexdigest()

    # Генерируем UUID, сохраняем файл
    file_id = uuid.uuid4()
    ext = Path(file.filename or "file").suffix
    storage_name = f"{file_id}{ext}"
    storage_path = UPLOAD_DIR / storage_name

    with open(storage_path, "wb") as f:
        f.write(content)

    # Определяем company_id (slug или UUID) с проверкой членства
    if company_id:
        cid = await assert_company_member(company_id, current_user, db)
    else:
        cid = current_user.company_id
        if cid is None:
            raise HTTPException(status_code=400, detail="Укажите company_id")

    # Запись в БД
    source = SourceFile(
        id=file_id,
        company_id=cid,
        file_name=file.filename or "unknown",
        mime_type=file.content_type or "application/octet-stream",
        size=file_size,
        storage_path=str(storage_path),
        fingerprint=fingerprint,
        purpose="attachment" if purpose == "attachment" else "data",
    )
    db.add(source)
    await db.flush()

    return {"source_id": str(file_id)}


@router.get("/files/{file_id}")
async def download_file(
    file_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Скачать файл по source_id."""
    try:
        uid = uuid.UUID(file_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Невалидный ID файла")

    # 404 и для несуществующего, и для файла чужой компании (не раскрываем факт).
    source = await get_owned(SourceFile, uid, current_user, db)

    # Файл проекции документов магазина повторно проверяет актуальный station grant.
    # Company-membership недостаточно: сохранённая старая ссылка не должна пережить
    # отзыв полномочий на АЗС или logical tombstone.
    from app.routers.store_documents_router import authorize_store_file_download
    await authorize_store_file_download(db, current_user, uid)

    # Файл документа «Дела»: закрытую карточку видят только автор, ответственный
    # и подписант, поэтому одной принадлежности компании здесь недостаточно.
    from app.routers.docs_router import authorize_docs_file_download
    await authorize_docs_file_download(db, current_user, uid)

    # Вложение чата принадлежит РАЗГОВОРУ, а не компании: членства мало. Иначе любой
    # сотрудник, которому попался адрес файла (переслали ссылку, увидел в логе), качает
    # снимок из чужой личной переписки. Тем же запросом закрывается и мягкое удаление:
    # сообщение убрали из ленты, а файл продолжал отдаваться по прямой ссылке.
    # Файлы вне чата (аватары комнат и людей, выгрузки, распознавание) сюда не попадают —
    # у них нет строки в chat_messages, и проверка их не касается.
    rows = (await db.execute(
        select(ChatMessage.room_id, ChatMessage.deleted_at)
        .where(ChatMessage.file_url == f"/api/files/{uid}")
    )).all()
    if rows:
        # Пересланное сообщение копирует адрес файла в другую комнату — достаточно
        # одного живого сообщения в комнате, где человек состоит.
        live_rooms = {r for r, deleted in rows if deleted is None}
        allowed = current_user.is_superadmin or bool(live_rooms and (await db.execute(
            select(ChatParticipant.id).where(
                ChatParticipant.user_id == current_user.id,
                ChatParticipant.room_id.in_(live_rooms),
            ).limit(1))).scalar_one_or_none())
        if not allowed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Не найдено")

    file_path = Path(source.storage_path)
    if not file_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Файл не найден на диске",
        )

    return FileResponse(
        path=str(file_path),
        media_type=source.mime_type,
        filename=source.file_name,
        headers={"Cache-Control": "private, no-store"},
    )
