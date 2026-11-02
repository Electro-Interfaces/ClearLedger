"""«Документы» пространства — одно дерево из всех мест, где лежат бумаги.

Раньше раздел у пространств без смен и бухгалтерии показывал только прогоны каналов
загрузки: договоров было девятьсот, файлов договоров — десятки, а папки были пустыми.
Бумаги при этом есть, но живут у своих хозяев: документы договора — в «Треке»
(связь `contract:<id>`), документы площадок — в «Проектах», прочая переписка — в
«Треке». Здесь они собираются в одно дерево, путь листа задаёт его место:

  Договоры / <контрагент> / № <номер> от <даты> / …   документы договора + карточка
  Проекты  / <проект> / <вид документа> / …            документы площадок
  Трек     / <вид документа> / <год> / …               остальной документооборот

Своего хранилища у раздела нет: файл открывается обычной ручкой `/api/files/{id}`,
права на документ «Трека» — его же правилами (`_readable_doc_clause`).
"""
import uuid
from collections.abc import Iterable

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Contract, Counterparty, DocCard, DocKind, DocRelation, DocVersion, User


def _contract_folder(c: Contract, cp_name: str) -> str:
    cp = (cp_name or "Без контрагента").replace("/", "∕")
    num = (c.number or "б/н").replace("/", "∕")
    return f"Договоры/{cp}/№ {num} от {c.date or '—'}"


def _contract_owners(subject_ref: str | None, refs: Iterable[str],
                     allowed: set[uuid.UUID]) -> list[uuid.UUID]:
    """Предмет — первый владелец; прочие связи упорядочены по UUID, без дублей.

    Мягкие ссылки могут быть устаревшими, ошибочными или вести в другую компанию.
    Ни такую ссылку, ни порядок строк DocRelation наружу не переносим.
    """
    def owned(ref: str | None) -> uuid.UUID | None:
        if not ref or not ref.startswith("contract:"):
            return None
        try:
            ident = uuid.UUID(ref[9:])
        except ValueError:
            return None
        return ident if ident in allowed else None

    primary = owned(subject_ref)
    others = {ident for ref in refs if (ident := owned(ref)) is not None}
    others.discard(primary)
    return ([primary] if primary else []) + sorted(others, key=str)


def _file_priority(v: DocVersion) -> tuple:
    """Подписанный скан, тело, приложение, вложение; затем новая редакция.

    `is_current` задан отдельно для каждой роли, поэтому «последняя строка» не
    означает основной файл. Время загрузки и UUID разрешают равенство стабильно.
    Вызывается только для текущих неудалённых версий своей компании.
    """
    return ({"signed_scan": 0, "body": 1, "appendix": 2, "attachment": 3}.get(v.role, 4),
            -v.revision, -v.uploaded_at.timestamp() if v.uploaded_at else 0, str(v.id))


async def space_documents(db: AsyncSession, cid: uuid.UUID, user: User) -> list[dict]:
    from app.services.doc_access import _readable_doc_clause
    from app.services.ezs_project import DOC_LABELS

    out: list[dict] = []
    contracts = {c.id: c for c in (await db.execute(select(Contract).where(Contract.company_id == cid))).scalars()}
    cp_names = {cp.id: cp.name for cp in (await db.execute(
        select(Counterparty.id, Counterparty.name).where(Counterparty.company_id == cid))).all()}
    folder = {k: _contract_folder(c, cp_names.get(c.counterparty_id, "")) for k, c in contracts.items()}

    # Карточка договора — лист в его папке: договор виден в «Документах», даже пока к нему
    # не приложено ни одной бумаги (а таких сейчас почти все).
    for k, c in contracts.items():
        out.append({"id": f"contract-{k}", "docType": "contract_card", "title": f"Карточка договора № {c.number}",
                    "catalog": folder[k], "date": c.date or "", "contractId": str(k),
                    "status": "закрыт" if c.is_closed else None})

    # Документы «Трека»: по договору — в его папку, остальные — по виду и году.
    readable = await _readable_doc_clause(db, cid, user)
    cards = (await db.execute(select(DocCard, DocKind.name).join(DocKind, DocKind.id == DocCard.kind_id)
                              .where(DocCard.company_id == cid, DocKind.company_id == cid, readable))).all()
    ids = [d.id for d, _ in cards]
    rel: dict[uuid.UUID, list[str]] = {}
    if ids:
        for doc_id, ref in (await db.execute(select(DocRelation.doc_id, DocRelation.target_ref).where(
                DocRelation.company_id == cid, DocRelation.doc_id.in_(ids),
                DocRelation.target_ref.like("contract:%")))).all():
            rel.setdefault(doc_id, []).append(ref)
    files = {}
    if ids:
        for v in (await db.execute(select(DocVersion).where(
                DocVersion.company_id == cid, DocVersion.doc_id.in_(ids),
                DocVersion.is_current.is_(True), DocVersion.tombstoned_at.is_(None)))).scalars():
            if v.doc_id not in files or _file_priority(v) < _file_priority(files[v.doc_id]):
                files[v.doc_id] = v
    allowed_contracts = set(contracts)
    for d, kind_name in cards:
        owners = _contract_owners(d.subject_ref, rel.get(d.id, []), allowed_contracts)
        contract_id = owners[0] if owners else None
        date = str(d.external_date or d.reg_date or (d.created_at.date() if d.created_at else ""))
        if contract_id in folder:
            catalog = folder[contract_id]
        else:
            catalog = f"Трек/{kind_name}/{date[:4] or 'без даты'}"
        number = d.external_number or d.reg_number
        v = files.get(d.id)
        out.append({"id": f"doc-{d.id}", "docType": "space_file", "title": f"{kind_name}{f' № {number}' if number else ''} — {d.title}",
                    "catalog": catalog, "date": date, "docId": str(d.id), "contractId": str(contract_id) if contract_id in folder else None,
                    "contractIds": [str(owner) for owner in owners],
                    "fileId": str(v.file_id) if v else None, "fileName": v.file_name if v else None,
                    "size": v.size_bytes if v else None, "status": d.status})

    # Документы площадок «Проектов».
    rows = (await db.execute(text(
        "SELECT d.id, d.kind, d.title, s.id AS site_id, p.id AS project_id,"
        " p.title AS project_title, p.project_no AS project_no,"
        " f.id AS file_id, d.created_at, f.file_name, f.size,"
        " COALESCE(NULLIF(s.title, ''), NULLIF(s.address, ''), s.id::text)"
        "   || CASE WHEN s.project_no IS NOT NULL THEN ' · ' || s.project_no ELSE '' END AS site"
        " FROM ezs_site_docs d JOIN ezs_sites s ON s.id = d.site_id AND s.company_id = :co"
        " LEFT JOIN ezs_projects p ON p.id = d.project_id AND p.site_id = s.id AND p.company_id = :co"
        " LEFT JOIN source_files f ON f.id = d.file_id AND f.company_id = :co"
        " WHERE d.company_id = :co"), {"co": cid})).mappings().all()
    for r in rows:
        site = (r["site"] or "Проект").replace("/", "∕")
        # UUID — часть пути только у явно привязанных проектов: одинаковые
        # номера/названия и два проекта одной площадки не склеиваются. Старый
        # путь документов без project_id сохраняется; проект по имени не ищем.
        project = ""
        if r["project_id"]:
            label = (r["project_title"] or r["project_no"] or "Проект").replace("/", "∕")
            project = f"/{label} · {r['project_id']}"
        out.append({"id": f"site-{r['id']}", "docType": "space_file", "title": r["title"] or r["file_name"] or "Документ",
                    "catalog": f"Проекты/{site}{project}/{DOC_LABELS.get(r['kind'], r['kind'])}",
                    "date": r["created_at"].date().isoformat() if r["created_at"] else "",
                    "siteId": str(r["site_id"]), "projectId": str(r["project_id"]) if r["project_id"] else None,
                    "siteDocId": str(r["id"]),
                    "fileId": str(r["file_id"]) if r["file_id"] else None, "fileName": r["file_name"], "size": r["size"]})
    return out
