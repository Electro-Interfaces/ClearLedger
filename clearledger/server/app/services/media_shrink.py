"""Сжатие видео-вложений: хранить запись экрана в исходном весе незачем.

Запись экрана macOS идёт в разрешении дисплея — 2704×1756, 20 МБ за сорок секунд,
63 МБ за две минуты. Сорок восемь процентов хранилища пространства занимали тринадцать
файлов (замер 13.09.2026). При этом смотрят в таком видео не пиксели, а интерфейс:
после пережатия до 1600 точек по ширине текст остаётся чётким, а файл худеет в
двадцать четыре раза — 19,6 МБ превращаются в 0,8 МБ.

Решение МАГа 13.09.2026: сжатое заменяет исходник сразу. Исходник записи экрана
не нужен никому — смотрят на интерфейс, а не на качество картинки.

Осторожности, без которых замена опасна:
  • результат проверяется ffprobe — совпадает длительность и файл читается;
  • пишем во временный файл и переставляем `os.replace`: кто в этот момент качает
    старый файл, спокойно дочитает его;
  • `fingerprint` НЕ меняется. Это отпечаток того, что принёс человек, по нему
    работает отбрасывание повторной загрузки того же файла;
  • сжатое больше исходника (уже сжатый ролик, короткое видео) — оставляем как было.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

log = logging.getLogger("clearledger.media")

# Ширина, на которой текст интерфейса ещё читается. Проверено на записи Safari с
# формой «Новая задача»: 1600 — читаются подписи полей и подсказки под ними.
ШИРИНА = 1600
CRF = 26
# Запись экрана идёт с частотой дисплея; для разбора хватает двадцати кадров.
КАДРОВ = 20
# Сжатие длинной записи не должно держать процесс вечно.
ТАЙМАУТ_СЕК = 900


def есть_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _длительность(path: Path) -> float | None:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=True).stdout
        return float(json.loads(out)["format"]["duration"])
    except Exception:
        return None


def сжать_видео(path: str | Path) -> dict[str, object] | None:
    """Пережать файл на месте. Возвращает {'before','after'} или None, если не вышло."""
    src = Path(path)
    if not src.exists() or not есть_ffmpeg():
        return None
    было = src.stat().st_size
    исходная_длительность = _длительность(src)
    if исходная_длительность is None:
        log.info("media: %s не похож на видео, не трогаем", src.name)
        return None

    # Контейнер сохраняем: имя файла уже лежит в сообщении, и .mov, ставший mp4,
    # скачивался бы с чужим расширением.
    tmp = src.with_name(f"{src.stem}.сжатие{src.suffix}")
    cmd = [
        "ffmpeg", "-v", "error", "-y", "-i", str(src),
        "-vf", f"scale='min({ШИРИНА},iw)':-2",
        "-c:v", "libx264", "-crf", str(CRF), "-preset", "veryfast", "-r", str(КАДРОВ),
        # Звук у записей экрана обычно отсутствует вовсе, но если он есть — это
        # голос автора, и терять его нельзя.
        "-c:a", "aac", "-b:a", "64k",
        "-movflags", "+faststart", str(tmp),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=ТАЙМАУТ_СЕК, check=True)
    except Exception as e:
        tmp.unlink(missing_ok=True)
        log.warning("media: не сжалось %s: %s", src.name, e)
        return None

    стало = tmp.stat().st_size if tmp.exists() else 0
    новая_длительность = _длительность(tmp)
    целое = (
        стало > 0
        and новая_длительность is not None
        and abs(новая_длительность - исходная_длительность) <= max(1.0, исходная_длительность * 0.02)
    )
    if not целое or стало >= было:
        tmp.unlink(missing_ok=True)
        log.info("media: оставили как было %s (%d → %d, целое=%s)",
                 src.name, было, стало, целое)
        return None

    os.replace(tmp, src)
    log.info("media: %s %.1f МБ → %.1f МБ", src.name, было / 1048576, стало / 1048576)
    return {"before": было, "after": стало}


def demo() -> None:
    """Самопроверка: без ffmpeg молчим, на не-видео не портим файл."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "не-видео.mov"
        p.write_bytes(b"\x00" * 2048)
        assert сжать_видео(p) is None, "мусорный файл не должен сжиматься"
        assert p.read_bytes() == b"\x00" * 2048, "исходник испорчен"
        assert сжать_видео(Path(d) / "нет-такого.mov") is None
    print(f"сжатие видео: ffmpeg {'есть' if есть_ffmpeg() else 'нет'}, проверки прошли")


if __name__ == "__main__":
    demo()
