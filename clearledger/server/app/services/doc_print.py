"""Печатная форма документа и лист согласования.

Отдаём HTML, печатает браузер. PDF-движка в системе нет, и заводить его ради
двух бланков дороже, чем печать через «Сохранить как PDF»: то же самое делает
генератор складских форм.

Шапка собирается из карточки нашего юрлица: наименование, ИНН и КПП, директор с
должностью — всё это там уже есть и второй раз не заводится.
"""
from __future__ import annotations

import html
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocApproval, DocCard, DocKind, DocVersion, Organization, User
from app.services import doc_verify

_STATUS_RU = {
    "draft": "черновик", "registered": "зарегистрирован", "in_force": "действует",
    "executed": "исполнен", "archived": "в архиве", "cancelled": "отменён",
}
_APPROVAL_RU = {
    "pending": "ожидает", "approved": "согласовано",
    "rejected": "отказано", "skipped": "снято", "waiting": "ещё не начато",
}
_ROLE_RU = {
    "body": "основной документ", "appendix": "приложение",
    "signed_scan": "подписанный экземпляр", "attachment": "вложение",
}

_CSS = """
@page { size: A4; margin: 20mm 15mm; }
body { font-family: Arial, sans-serif; font-size: 12pt; color: #000; }
.head { text-align: center; margin-bottom: 18pt; }
.org { font-weight: bold; }
.meta { color: #444; font-size: 10pt; }
h1 { font-size: 14pt; margin: 16pt 0 8pt; }
table { width: 100%; border-collapse: collapse; margin-top: 10pt; }
th, td { border: 1px solid #999; padding: 4pt 6pt; font-size: 10pt; text-align: left; }
th { background: #eee; }
.sign { margin-top: 28pt; }
.sign td { border: none; padding: 10pt 6pt 0; }
.rule { border-bottom: 1px solid #000; width: 60mm; display: inline-block; }
.note { color: #555; font-size: 9pt; margin-top: 14pt; }
.verify { margin-top: 18pt; border-top: 1px solid #bbb; padding-top: 8pt; }
.verify-url { font-family: Consolas, monospace; font-size: 8pt; overflow-wrap: anywhere; }
.hash { font-family: Consolas, monospace; font-size: 7.5pt; word-break: break-all; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value or ""))


async def render_card(db: AsyncSession, doc: DocCard) -> str:
    """Бланк документа: шапка организации, реквизиты и лист согласования."""
    kind = await db.get(DocKind, doc.kind_id)
    org = await db.get(Organization, doc.organization_id) if doc.organization_id else None

    rows = (await db.execute(select(DocApproval).where(
        DocApproval.doc_id == doc.id).order_by(
        DocApproval.round, DocApproval.step_no))).scalars().all()
    people: dict[str, str] = {}
    ids = {user_id for row in rows for user_id in (row.assignee_id, row.decided_by)
           if user_id}
    if ids:
        people = {str(u.id): (u.name or u.email) for u in (await db.execute(
            select(User).where(User.id.in_(ids)))).scalars().all()}

    org_line = _esc(org.name) if org else ""
    org_meta = ""
    if org:
        bits = [b for b in (f"ИНН {org.inn}" if org.inn else "",
                            f"КПП {org.kpp}" if org.kpp else "") if b]
        org_meta = " · ".join(bits)

    approvals_html = ""
    if rows:
        body = ""
        for approval in rows:
            assigned = people.get(str(approval.assignee_id), "")
            decided = people.get(str(approval.decided_by), "")
            participant = assigned
            if decided and approval.decided_by != approval.assignee_id:
                participant = f"{decided} (замещает {assigned})"
            body += (
                f"<tr><td>{approval.round}</td><td>{_esc(approval.step_name)}</td>"
                f"<td>{_esc(participant)}</td>"
                f"<td>{_APPROVAL_RU.get(approval.status, approval.status)}</td>"
                f"<td>{approval.decided_at.strftime('%d.%m.%Y') if approval.decided_at else ''}</td>"
                f"<td>{_esc(approval.comment)}</td></tr>")
        approvals_html = (
            "<h1>Лист согласования</h1>"
            "<table><tr><th>Круг</th><th>Шаг</th><th>Согласующий</th>"
            "<th>Решение</th><th>Дата</th><th>Замечание</th></tr>"
            f"{body}</table>")

    reg = ""
    if doc.reg_number:
        reg = f"№ {_esc(doc.reg_number)}"
        if doc.reg_date:
            reg += f" от {doc.reg_date.strftime('%d.%m.%Y')}"

    external = ""
    if doc.external_number or doc.external_date:
        ext_date = doc.external_date.strftime('%d.%m.%Y') if doc.external_date else ""
        external = (f"<tr><td>Исходящий корреспондента</td>"
                    f"<td>{_esc(doc.external_number)} {ext_date}</td></tr>")

    storage = ""
    if doc.storage_until:
        storage = (f"<tr><td>Хранить до</td>"
                   f"<td>{doc.storage_until.strftime('%d.%m.%Y')}</td></tr>")

    versions = (await db.execute(select(DocVersion).where(
        DocVersion.doc_id == doc.id, DocVersion.is_current.is_(True),
        DocVersion.tombstoned_at.is_(None)).order_by(
        DocVersion.role, DocVersion.revision))).scalars().all()
    hashes = ""
    if versions:
        hash_rows = "".join(
            f"<tr><td>{_esc(_ROLE_RU.get(version.role, version.role))}</td>"
            f"<td>{version.revision}</td>"
            f"<td class=\"hash\">SHA-256: {_esc(version.sha256)}</td></tr>"
            for version in versions)
        hashes = ("<h1>Редакции файлов</h1><table><tr><th>Роль</th>"
                  "<th>Редакция</th><th>Контрольная сумма</th></tr>"
                  f"{hash_rows}</table>")

    verification_url = await doc_verify.public_url(db, doc) if doc.reg_number else ""
    verification = ""
    if verification_url:
        verification = (
            "<div class=\"verify\"><strong>Проверка записи в реестре</strong>"
            f"<div class=\"verify-url\">{_esc(verification_url)}</div>"
            "<div class=\"note\">Ссылка подтверждает наличие записи с указанными "
            "реквизитами. Она не проверяет электронную подпись и не подтверждает "
            "юридическую силу бумажной копии.</div></div>")

    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<title>{_esc(doc.reg_number or doc.title)}</title>
<style>{_CSS}</style></head>
<body onload="window.print()">
  <div class="head">
    <div class="org">{org_line}</div>
    <div class="meta">{_esc(org_meta)}</div>
  </div>

  <h1>{_esc(kind.name if kind else 'Документ')} {reg}</h1>
  <div>{_esc(doc.title)}</div>

  <table>
    <tr><td style="width:45mm">Вид документа</td><td>{_esc(kind.name if kind else '')}</td></tr>
    <tr><td>Состояние</td><td>{_STATUS_RU.get(doc.status, doc.status)}</td></tr>
    <tr><td>{'Отправитель' if doc.direction == 'in' else 'Получатель'}</td>
        <td>{_esc(doc.counterparty_name)}</td></tr>
    {external}
    {storage}
  </table>

  {f'<p>{_esc(doc.summary)}</p>' if doc.summary else ''}

  {approvals_html}

  {hashes}

  <table class="sign">
    <tr>
      <td>{_esc(org.director_position if org and org.director_position else 'Руководитель')}</td>
      <td><span class="rule"></span></td>
      <td>{_esc(org.director_name if org else '')}</td>
    </tr>
  </table>

  <p class="note">Отпечатано из системы {date.today().strftime('%d.%m.%Y')}.
  Документ подписывается собственноручно либо электронной подписью вне системы:
  своей криптографии система не имеет и подпись не создаёт.</p>
  {verification}
</body></html>"""
