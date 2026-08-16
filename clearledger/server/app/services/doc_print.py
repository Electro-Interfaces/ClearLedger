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

from app.models import DocApproval, DocCard, DocKind, Organization, User

_STATUS_RU = {
    "draft": "черновик", "registered": "зарегистрирован", "in_force": "действует",
    "executed": "исполнен", "archived": "в архиве", "cancelled": "отменён",
}
_APPROVAL_RU = {
    "pending": "ожидает", "approved": "согласовано",
    "rejected": "отказано", "skipped": "снято",
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
    ids = {a.assignee_id for a in rows if a.assignee_id}
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
        body = "".join(
            f"<tr><td>{a.round}</td><td>{_esc(a.step_name)}</td>"
            f"<td>{_esc(people.get(str(a.assignee_id), ''))}</td>"
            f"<td>{_APPROVAL_RU.get(a.status, a.status)}</td>"
            f"<td>{a.decided_at.strftime('%d.%m.%Y') if a.decided_at else ''}</td>"
            f"<td>{_esc(a.comment)}</td></tr>"
            for a in rows)
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
</body></html>"""
