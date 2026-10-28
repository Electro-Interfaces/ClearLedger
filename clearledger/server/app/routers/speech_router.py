"""Речь в текст для полей пространства: тема встречи, позже — любые формы.

Считает распознаватель СВОЕГО стека (`<стек>-asr`, faster-whisper), тот же, что
расшифровывает звонки и записи конференций: запись не покидает контейнер
компании. Раньше диктовка жила только у Аудитора (`/auditor/dictate`), и там, где
Аудитора в стеке нет, микрофон в карточке встречи стоял неактивным, хотя
распознаватель работал (МАГ, 28.10.2026).
"""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.auth import get_current_user
from app.config import settings
from app.models import User

router = APIRouter(prefix="/speech", tags=["Речь"])

# Диктовка — фраза, а не совещание: минута речи в webm/opus — сотни килобайт.
ПРЕДЕЛ_БАЙТ = 10 * 1024 * 1024


@router.get("/health")
async def speech_health(current_user: User = Depends(get_current_user)):
    """Поднят ли распознаватель стека. Нет — микрофон стоит неактивным с объяснением."""
    try:
        async with httpx.AsyncClient(timeout=3) as клиент:
            ответ = await клиент.get(settings.asr_url.rstrip("/") + "/health")
        return {"ready": ответ.status_code == 200}
    except httpx.HTTPError:
        return {"ready": False}


@router.post("/dictate")
async def speech_dictate(file: UploadFile = File(...), current_user: User = Depends(get_current_user)):
    """Запись голоса → текст. Ошибки распознавателя — внятным словом, не кодом."""
    данные = await file.read(ПРЕДЕЛ_БАЙТ + 1)
    if len(данные) > ПРЕДЕЛ_БАЙТ:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Запись слишком длинная — диктуйте короче")
    if not данные:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Запись пустая")
    try:
        # ponytail: распознаватель один на стек и держит очередь сам; таймаут с запасом
        # на занятость звонками. Отдельная очередь — если диктовок станут десятки разом.
        async with httpx.AsyncClient(timeout=120) as клиент:
            ответ = await клиент.post(settings.asr_url.rstrip("/") + "/file", data={"language": "ru"},
                                      files={"file": (file.filename or "voice.webm", данные,
                                                      file.content_type or "audio/webm")})
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Распознавание речи сейчас недоступно — повторите через минуту") from e
    if ответ.status_code != 200:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Распознавание речи не ответило")
    тело = ответ.json()
    if тело.get("status") != "ok":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, тело.get("note") or "Не удалось распознать речь")
    return {"text": (тело.get("text") or "").strip()}
