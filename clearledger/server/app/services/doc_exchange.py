"""Обмен документами с корпоративными системами головной компании.

Как устроено. Наружу — папка: система кладёт туда пакет, корпоративная СЭД
(SEDO, Naumen) его забирает. Обратно так же: их система кладёт файлы в свою
папку, мы показываем находки человеку, и он решает, заводить ли карточку.

Почему папка, а не обращение к их системе напрямую. Доступа к API корпоративных
СЭД у нас нет и не предвидится, а каталог на диске есть всегда и переживает
смену версии на той стороне.

Про формат описи честно. Точных схем SEDO и Naumen нам не давали, поэтому опись
пишется своим форматом со всеми реквизитами карточки. Когда заказчик даст
спецификацию, меняется только `build_manifest`, а весь остальной контур —
сборка, журнал, приём — остаётся.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import os
import re
import stat
import time
import zipfile
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DocApproval, DocCard, DocExchangeTarget, DocInboxItem, DocKind, DocVersion,
    Organization, SourceFile, User,
)
from app.config import settings
from app.services import doc_print, file_store

# Что кладём в пакет: сам документ, приложения и подписанный экземпляр. Служебные
# вложения переписки наружу не отдаём — головной компании нужен документ, а не
# наша внутренняя кухня.
EXPORT_ROLES = ("body", "appendix", "signed_scan")
MAX_INBOX_FILES = 200
MAX_INBOX_ENTRIES = 1000
MAX_INBOX_FILE_BYTES = 50 * 1024 * 1024
MAX_INBOX_TOTAL_BYTES = 250 * 1024 * 1024
MAX_MANIFEST_BYTES = 2 * 1024 * 1024
MIN_STABLE_AGE_SECONDS = 5
SCAN_LOCK_NAMESPACE = 0x0ED012

# Имя пакета: по нему человек на той стороне опознаёт документ, не открывая.
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def exchange_roots() -> tuple[Path, ...]:
    roots = []
    for raw in settings.doc_exchange_roots.split(";"):
        value = raw.strip()
        if value:
            root = Path(value)
            if not root.is_absolute():
                raise ValueError("Корень обмена должен быть абсолютным путём")
            roots.append(root.resolve(strict=False))
    if not roots:
        raise ValueError("Не настроены разрешённые корни обмена с СЭД")
    return tuple(roots)


def exchange_path(value: str, company_id) -> Path:
    """Канонический путь внутри смонтированного корня обмена."""
    raw = (value or "").strip()
    if not raw:
        raise ValueError("Путь обмена не указан")
    path = Path(raw)
    if not path.is_absolute():
        raise ValueError("Путь обмена должен быть абсолютным")
    resolved = path.resolve(strict=False)
    if company_id is None:
        raise ValueError("У точки обмена не указана компания")
    tenant_roots = tuple((root / str(company_id)).resolve(strict=False)
                         for root in exchange_roots())
    if not any(resolved == root or resolved.is_relative_to(root)
               for root in tenant_roots):
        raise ValueError(
            f"Путь должен находиться в папке компании {tenant_roots[0]}")
    return resolved


def safe_name(value: str, limit: int = 80) -> str:
    """Имя файла, которое переживёт любую файловую систему."""
    cleaned = _BAD_CHARS.sub("_", (value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return (cleaned or "документ")[:limit]


def package_name(doc: DocCard) -> str:
    number = safe_name(doc.reg_number or "без-номера", 40)
    date = doc.reg_date.strftime("%Y-%m-%d") if doc.reg_date else "без-даты"
    return f"{date}_{number}_{safe_name(doc.title, 60)}"


async def build_manifest(db: AsyncSession, doc: DocCard,
                         versions: list[DocVersion]) -> bytes:
    """Опись пакета: реквизиты карточки машиночитаемо.

    Без описи принимающая сторона вбивает номер, дату и корреспондента руками —
    то есть обмен файлами не экономит ничего.
    """
    kind = await db.get(DocKind, doc.kind_id)
    org = await db.get(Organization, doc.organization_id) if doc.organization_id else None
    author = await db.get(User, doc.author_id) if doc.author_id else None

    root = ET.Element("Документ", {"версияОписи": "1.0"})
    ET.SubElement(root, "Вид").text = kind.name if kind else ""
    ET.SubElement(root, "КодВида").text = doc.kind_code or ""
    ET.SubElement(root, "Поток").text = doc.family
    ET.SubElement(root, "Направление").text = doc.direction
    ET.SubElement(root, "РегистрационныйНомер").text = doc.reg_number or ""
    ET.SubElement(root, "ДатаРегистрации").text = (
        doc.reg_date.isoformat() if doc.reg_date else "")
    ET.SubElement(root, "Заголовок").text = doc.title
    if doc.summary:
        ET.SubElement(root, "Содержание").text = doc.summary

    if org is not None:
        node = ET.SubElement(root, "Организация")
        ET.SubElement(node, "Наименование").text = org.name or ""
        ET.SubElement(node, "ИНН").text = org.inn or ""
        ET.SubElement(node, "КПП").text = org.kpp or ""

    if doc.counterparty_name or doc.external_number:
        node = ET.SubElement(root, "Корреспондент")
        ET.SubElement(node, "Наименование").text = doc.counterparty_name or ""
        ET.SubElement(node, "ИсходящийНомер").text = doc.external_number or ""
        ET.SubElement(node, "ДатаИсходящего").text = (
            doc.external_date.isoformat() if doc.external_date else "")

    if author is not None:
        ET.SubElement(root, "Автор").text = author.name or author.email or ""
    if doc.storage_until:
        ET.SubElement(root, "ХранитьДо").text = doc.storage_until.isoformat()

    approvals = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == doc.id).order_by(
        DocApproval.round, DocApproval.step_no))).scalars().all()
    if approvals:
        people = {str(u.id): (u.name or u.email) for u in (await db.execute(
            select(User).where(User.id.in_(
                {a.assignee_id for a in approvals if a.assignee_id})))).scalars().all()}
        node = ET.SubElement(root, "ЛистСогласования",
                             {"состояние": doc.approval_status})
        for a in approvals:
            row = ET.SubElement(node, "Виза", {"круг": str(a.round)})
            ET.SubElement(row, "Шаг").text = a.step_name
            ET.SubElement(row, "Согласующий").text = people.get(str(a.assignee_id), "")
            ET.SubElement(row, "Решение").text = a.status
            ET.SubElement(row, "Дата").text = (
                a.decided_at.isoformat() if a.decided_at else "")
            if a.comment:
                ET.SubElement(row, "Замечание").text = a.comment

    files_node = ET.SubElement(root, "Файлы")
    for v in versions:
        ET.SubElement(files_node, "Файл", {
            "роль": v.role, "редакция": str(v.revision), "хеш": v.sha256,
        }).text = v.file_name

    ET.SubElement(root, "СформированоСистемой").text = datetime.now(
        timezone.utc).isoformat(timespec="seconds")

    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


async def build_package(db: AsyncSession, doc: DocCard) -> tuple[bytes, dict[str, Any]]:
    """Собрать пакет: файлы документа, опись и лист согласования.

    Возвращает архив и состав. Состав пишется в журнал: через полгода вопрос
    «что именно мы отдали» решается им, а не памятью.
    """
    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id, DocVersion.is_current.is_(True),
        DocVersion.tombstoned_at.is_(None),
        DocVersion.role.in_(EXPORT_ROLES)).order_by(DocVersion.role))).scalars().all()

    manifest = await build_manifest(db, doc, versions)
    sheet = await doc_print.render_card(db, doc)

    buf = io.BytesIO()
    content: dict[str, Any] = {"files": [], "manifest": "опись.xml",
                               "sheet": "лист-согласования.html"}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("опись.xml", manifest)
        z.writestr("лист-согласования.html", sheet.encode("utf-8"))
        for v in versions:
            sf = await db.get(SourceFile, v.file_id)
            if sf is None:
                continue
            try:
                data = file_store.read(sf)
            except OSError:
                # Файл потерялся в хранилище — не тихо пропускаем, а называем в
                # составе: пакет без документа лучше, чем пакет, который врёт.
                content["files"].append({"name": v.file_name, "role": v.role,
                                         "error": "файл не читается"})
                continue
            name = f"{v.role}_{safe_name(v.file_name, 100)}"
            z.writestr(name, data)
            content["files"].append({"name": name, "role": v.role,
                                     "sha256": v.sha256, "size": len(data)})
    return buf.getvalue(), content


def place_package(target: DocExchangeTarget, name: str, data: bytes) -> str:
    """Положить пакет в папку обмена. Возвращает путь.

    Повторная выгрузка того же документа не затирает прежнюю: к имени
    добавляется отметка времени. Затирать — значит терять доказательство того,
    что и когда уходило.
    """
    folder = exchange_path(target.outbox_path, target.company_id)
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    path = folder / f"{name}_{stamp}.zip"
    with path.open("xb") as stream:
        stream.write(data)
    return str(path)


def parse_manifest(data: bytes) -> dict[str, Any]:
    """Вытащить реквизиты из описи, если она пришла вместе с файлом."""
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    out: dict[str, Any] = {}
    for tag, key in (("Вид", "kind"), ("РегистрационныйНомер", "reg_number"),
                     ("ДатаРегистрации", "reg_date"), ("Заголовок", "title"),
                     ("Содержание", "summary")):
        node = root.find(tag)
        if node is not None and node.text:
            out[key] = node.text.strip()
    cp = root.find("Корреспондент/Наименование")
    if cp is not None and cp.text:
        out["counterparty_name"] = cp.text.strip()
    return out


def _candidate_paths(target: DocExchangeTarget) -> list[Path]:
    folder = exchange_path(target.inbox_path, target.company_id)
    if not folder.exists():
        raise FileNotFoundError(f"Папка обмена не найдена: {folder}")
    if not folder.is_dir():
        raise NotADirectoryError(f"Путь обмена не является папкой: {folder}")
    entries = list(islice(folder.iterdir(), MAX_INBOX_ENTRIES + 1))
    if len(entries) > MAX_INBOX_ENTRIES:
        raise ValueError(
            f"В папке обмена больше {MAX_INBOX_ENTRIES} объектов; разберите её вручную")
    paths: list[Path] = []
    for path in entries:
        if path.name.startswith(".") or path.is_symlink() or not path.is_file():
            continue
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(folder):
            continue
        paths.append(resolved)
    ordered = sorted(paths, key=lambda item: item.name)
    if target.scan_cursor and ordered:
        split = next((index for index, item in enumerate(ordered)
                      if item.name > target.scan_cursor), 0)
        ordered = ordered[split:] + ordered[:split]
    return ordered


def _read_candidate(path: Path) -> dict[str, Any] | None:
    descriptor = None
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_INBOX_FILE_BYTES:
            return None
        if before.st_mtime > time.time() - MIN_STABLE_AGE_SECONDS:
            return None
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(MAX_INBOX_FILE_BYTES + 1)
        after = os.fstat(descriptor)
    except OSError:
        return None
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if (len(data) > MAX_INBOX_FILE_BYTES or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or len(data) != after.st_size):
        return None
    parsed: dict[str, Any] = {}
    if path.suffix.lower() == ".zip":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist()[:1000]:
                    if (info.filename.lower().endswith(".xml")
                            and info.file_size <= MAX_MANIFEST_BYTES):
                        parsed = parse_manifest(archive.read(info))
                        break
        except zipfile.BadZipFile:
            parsed = {}
    elif path.suffix.lower() == ".xml" and len(data) <= MAX_MANIFEST_BYTES:
        parsed = parse_manifest(data)
    return {
        "file_name": path.name, "source_path": str(path), "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(), "data": data,
        "parsed": parsed,
    }


def scan_inbox(target: DocExchangeTarget) -> list[dict[str, Any]]:
    """Посмотреть, что лежит во входящей папке.

    Читаем, но ничего не удаляем и не перекладываем: папка принадлежит той
    стороне, и хозяйничать в ней мы не вправе. Повтор ловится хешем.
    """
    found: list[dict[str, Any]] = []
    total = 0
    for path in _candidate_paths(target)[:MAX_INBOX_FILES]:
        item = _read_candidate(path)
        if item is None or total + item["size"] > MAX_INBOX_TOTAL_BYTES:
            continue
        found.append(item)
        total += item["size"]
    return found


async def collect_inbox(db: AsyncSession, target: DocExchangeTarget) -> int:
    """Перенести новые файлы папки в очередь разбора, не принимая их документами."""
    if target.id is not None:
        got = await db.scalar(text("SELECT pg_try_advisory_xact_lock(:ns, :key)"), {
            "ns": SCAN_LOCK_NAMESPACE, "key": target.id.int % (2 ** 31),
        })
        if not got:
            return 0
    paths = await asyncio.to_thread(_candidate_paths, target)
    target.last_scan_at = datetime.now(timezone.utc)
    target.last_error = None
    added = 0
    total = 0
    processed = 0
    for path in paths:
        if processed >= MAX_INBOX_FILES:
            break
        processed += 1
        item = await asyncio.to_thread(_read_candidate, path)
        target.scan_cursor = path.name
        if item is None:
            continue
        duplicate = (await db.execute(select(DocInboxItem.id).where(
            DocInboxItem.company_id == target.company_id,
            DocInboxItem.sha256 == item["sha256"]))).scalar_one_or_none()
        if duplicate is not None:
            continue
        if total + item["size"] > MAX_INBOX_TOTAL_BYTES:
            break
        total += item["size"]
        stored = file_store.put(
            db, target.company_id, item["data"], file_name=item["file_name"], mime=None)
        await db.flush()
        db.add(DocInboxItem(
            company_id=target.company_id, target_id=target.id,
            file_name=item["file_name"], source_path=item["source_path"],
            size_bytes=item["size"], sha256=item["sha256"], file_id=stored.id,
            parsed=item["parsed"] or None))
        added += 1
    return added
