"""Расшифровка записи конференции распознаванием речи пространства.

Запись конференции — час видео на две сотни мегабайт, а ASR (`<стек>-asr`,
faster-whisper на процессоре ВМ) распознаёт по одному файлу за раз и делит
очередь со звонками «Поддержки». Поэтому звук вынимается заранее и режется на
куски по десять минут: каждый кусок — короткий заход в ASR, между ними
успевают пройти звонки, а сбой одного куска не губит час работы.

Одновременно расшифровывается одна запись (`_очередь`): вторую ставим следом,
а не рядом — ASR всё равно обслуживает их по одной, только дольше держит обе.

Перезапуск бэкенда обрывает расшифровку на середине. Состояние в базе при этом
остаётся `running`; ручка карточки отличает такую запись по тому, что её нет в
`_в_работе`, и предлагает запустить снова.
"""
from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from pathlib import Path

import httpx

from app.config import settings

log = logging.getLogger(__name__)

КУСОК = 600  # секунд звука в одном заходе в ASR
_очередь = asyncio.Lock()
_в_работе: set[uuid.UUID] = set()
_задачи: set[asyncio.Task] = set()


def идёт(session_id: uuid.UUID) -> bool:
    return session_id in _в_работе


def поставить(session_id: uuid.UUID) -> bool:
    """Поставить запись в очередь расшифровки. False — она уже там."""
    if session_id in _в_работе:
        return False
    _в_работе.add(session_id)
    задача = asyncio.create_task(_выполнить(session_id))
    # Ссылку держим, иначе сборщик мусора может снять задачу на середине.
    _задачи.add(задача)
    задача.add_done_callback(_задачи.discard)
    return True


async def _выполнить(session_id: uuid.UUID) -> None:
    try:
        async with _очередь:
            await _расшифровать(session_id)
    except Exception:
        log.exception("Расшифровка записи %s упала", session_id)
    finally:
        _в_работе.discard(session_id)


async def _отметить(session_id: uuid.UUID, **поля) -> None:
    from app.database import async_session_factory
    from app.models import ConfSession

    async with async_session_factory() as db:
        s = await db.get(ConfSession, session_id)
        if s is None:
            return
        for k, v in поля.items():
            setattr(s, k, v)
        await db.commit()


async def _нарезать(путь: str, каталог: str) -> list[Path]:
    """Звук записи кусками по `КУСОК` секунд: 16 кГц, моно — как ждёт whisper."""
    процесс = await asyncio.create_subprocess_exec(
        "ffmpeg", "-nostdin", "-loglevel", "error", "-i", путь, "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        "-f", "segment", "-segment_time", str(КУСОК), f"{каталог}/part%04d.wav",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
    _, ошибка = await процесс.communicate()
    if процесс.returncode != 0:
        raise RuntimeError("Не удалось извлечь звук из записи: "
                           + (ошибка or b"").decode("utf-8", "replace")[-200:])
    куски = sorted(Path(каталог).glob("part*.wav"))
    if not куски:
        raise RuntimeError("В записи нет звука")
    return куски


async def _расшифровать(session_id: uuid.UUID) -> None:
    from app.database import async_session_factory
    from app.models import ConfSession, SourceFile

    async with async_session_factory() as db:
        s = await db.get(ConfSession, session_id)
        файл = await db.get(SourceFile, s.recording_file_id) if s and s.recording_file_id else None
        путь = файл.storage_path if файл else None
    if not путь or not Path(путь).exists():
        await _отметить(session_id, transcript_status="error",
                        transcript_error="Файла записи нет в хранилище")
        return
    await _отметить(session_id, transcript_status="running", transcript_error=None)
    try:
        отрезки: list[dict] = []
        адрес = settings.asr_url.rstrip("/") + "/file"
        with tempfile.TemporaryDirectory(prefix="conf-asr-") as каталог:
            куски = await _нарезать(путь, каталог)
            # ponytail: таймаут на кусок с запасом на очередь звонков; если ASR
            # будет стоять дольше, нужен повтор куска, а не всей записи.
            async with httpx.AsyncClient(timeout=1800) as клиент:
                for номер, кусок in enumerate(куски):
                    ответ = await клиент.post(
                        адрес, data={"language": "ru"},
                        files={"file": (кусок.name, кусок.read_bytes(), "audio/wav")})
                    ответ.raise_for_status()
                    данные = ответ.json()
                    if данные.get("status") != "ok":
                        raise RuntimeError(данные.get("note") or "Распознавание не справилось")
                    сдвиг = номер * КУСОК
                    for o in данные.get("segments") or []:
                        текст = (o.get("text") or "").strip()
                        if текст:
                            отрезки.append({"start": round(o["start"] + сдвиг, 1),
                                            "end": round(o["end"] + сдвиг, 1), "text": текст})
        await _отметить(session_id, transcript=отрезки, transcript_status="done",
                        transcript_error=None)
    except httpx.ConnectError:
        await _отметить(session_id, transcript_status="error",
                        transcript_error="Распознавание речи в пространстве недоступно")
    except Exception as e:
        await _отметить(session_id, transcript_status="error",
                        transcript_error=str(e)[:300] or "Расшифровка не удалась")
