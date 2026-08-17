"""Стендовая проверка очереди «Трека»; все строки откатываются, файлы удаляются."""
from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, literal_column, select, text

from app.database import async_session_factory
from app.models import (
    Company, Counterparty, DocAccessGrant, DocAcquaint, DocApproval, DocCard,
    DocExchangeTarget, DocInboxItem, DocKind, DocVersion, MailAttachment,
    MailMessage, User, UserCompany,
)
from app.routers import docs_router
from app.services import (
    doc_approvals, doc_exchange, file_store, mail_routing, task_scheduler,
)


async def main() -> None:
    slug = os.environ.get("COMPANY_SLUG")
    if not slug:
        raise RuntimeError("Нужен COMPANY_SLUG")
    marker = f"ПРОВЕРКА-ТРЕК-{uuid.uuid4().hex}"
    now = datetime.now(timezone.utc)
    written: set[Path] = set()
    notices: list[str] = []
    original_put = file_store.put
    original_notice = task_scheduler.task_mail.send_notice_checked

    def tracked_put(*args, **kwargs):
        row = original_put(*args, **kwargs)
        written.add(Path(row.storage_path))
        return row

    async def checked_notice(emails, subject, _body):
        notices.append(f"{','.join(emails)}:{subject}")
        return True, None

    file_store.put = tracked_put
    task_scheduler.task_mail.send_notice_checked = checked_notice
    try:
        async with async_session_factory() as db:
            company = (await db.execute(select(Company).where(
                Company.slug == slug))).scalar_one_or_none()
            if company is None:
                available = (await db.execute(select(Company.slug))).scalars().all()
                raise AssertionError(
                    f"Компания {slug!r} не найдена; доступны: {', '.join(available)}")
            cid = company.id

            assert await db.scalar(text(
                "SELECT to_regclass('doc_access_grants') IS NOT NULL"))
            required_indexes = {
                "idx_doc_versions_text", "uq_doc_versions_current_role",
                "uq_doc_acquaints_snapshot", "uq_doc_cases_index",
                "uq_doc_cards_mail_source",
                "uq_mail_messages_company_msgid",
            }
            index_rows = (await db.execute(text(
                "SELECT c.relname, i.indisunique, i.indisvalid, pg_get_indexdef(i.indexrelid) "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "JOIN pg_index i ON i.indexrelid = c.oid "
                "WHERE n.nspname = current_schema() "
                "AND c.relname IN ('idx_doc_versions_text','uq_doc_versions_current_role',"
                "'uq_doc_acquaints_snapshot','uq_doc_cases_index',"
                "'uq_doc_cards_mail_source','uq_mail_messages_company_msgid')"
            ))).all()
            indexes = {row[0] for row in index_rows}
            assert indexes == required_indexes
            by_name = {row[0]: row for row in index_rows}
            for name in required_indexes:
                assert by_name[name][2], f"Индекс {name} невалиден"
            for name in required_indexes:
                if name.startswith("uq_"):
                    assert by_name[name][1], f"Индекс {name} не уникальный"
            assert "COALESCE(organization_id" in by_name["uq_doc_cases_index"][3]
            columns = set((await db.execute(text(
                "SELECT table_name || '.' || column_name FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name IN "
                "('doc_versions','doc_acquaints','doc_exchange_targets','doc_approvals',"
                "'mail_messages') AND column_name IN "
                "('content_text','reminded_at','reminder_attempted_at','reminder_error',"
                "'scan_enabled','scan_interval_min','scan_cursor','sla_hours','activated_at',"
                "'activation_estimated','document_snapshot','snapshot_sha256','reason_ref',"
                "'reason_name','route_error','route_attempts','route_attempted_at')"
            ))).scalars().all())
            assert columns == {
                "doc_versions.content_text",
                "doc_acquaints.reminded_at", "doc_acquaints.reminder_attempted_at",
                "doc_acquaints.reminder_error", "doc_acquaints.document_snapshot",
                "doc_acquaints.snapshot_sha256", "doc_acquaints.reason_ref",
                "doc_acquaints.reason_name",
                "doc_exchange_targets.scan_enabled",
                "doc_exchange_targets.scan_interval_min",
                "doc_exchange_targets.scan_cursor",
                "doc_approvals.sla_hours", "doc_approvals.activated_at",
                "doc_approvals.activation_estimated", "doc_approvals.document_snapshot",
                "doc_approvals.snapshot_sha256",
                "mail_messages.route_error", "mail_messages.route_attempts",
                "mail_messages.route_attempted_at",
            }

            owner = User(
                company_id=cid, email=f"{uuid.uuid4().hex}@check.invalid",
                name=marker, password_hash="!", is_superadmin=True,
            )
            person = User(
                company_id=cid, email=f"{uuid.uuid4().hex}@check.invalid",
                name=f"{marker}-получатель", password_hash="!",
            )
            kind = DocKind(
                company_id=cid, code=f"check_{uuid.uuid4().hex[:12]}",
                name=marker, family="incoming", direction="in", number_prefix="ЧЕК",
            )
            db.add_all([owner, person, kind])
            await db.flush()
            db.add_all([
                UserCompany(user_id=owner.id, company_id=cid, role="admin", modules=["docs"]),
                UserCompany(user_id=person.id, company_id=cid, role="user", modules=["docs"]),
            ])

            private_doc = DocCard(
                company_id=cid, kind_id=kind.id, kind_code=kind.code,
                family=kind.family, direction=kind.direction,
                title=f"{marker}-доступ", confidentiality="private", author_id=owner.id,
            )
            report_doc = DocCard(
                company_id=cid, kind_id=kind.id, kind_code=kind.code,
                family=kind.family, direction=kind.direction,
                title=f"{marker}-отчёт", approval_status="approved", approval_round=1,
                author_id=owner.id,
            )
            company_doc = DocCard(
                company_id=cid, kind_id=kind.id, kind_code=kind.code,
                family=kind.family, direction=kind.direction,
                title=f"{marker}-чужой", author_id=person.id,
            )
            db.add_all([private_doc, report_doc, company_doc])
            await db.flush()

            workflow_doc = DocCard(
                company_id=cid, kind_id=kind.id, kind_code=kind.code,
                family=kind.family, direction=kind.direction,
                title=f"{marker}-маршрут", status="registered",
                reg_number=f"ЧЕК-{uuid.uuid4().hex[:12]}", reg_date=now.date(),
                author_id=owner.id, signatory_id=owner.id,
            )
            db.add(workflow_doc)
            await db.flush()
            workflow_body = marker.encode()
            db.add(DocVersion(
                company_id=cid, doc_id=workflow_doc.id, revision=1, role="body",
                file_id=uuid.uuid4(), file_name="маршрут.txt", mime="text/plain",
                size_bytes=len(workflow_body), sha256=hashlib.sha256(workflow_body).hexdigest(),
                content_text=marker,
            ))
            await db.flush()
            route = [
                {"code": "first", "name": "Первый", "mode": "serial", "quorum": "all",
                 "actors": [{"by": "user", "ref": str(owner.id)}]},
                {"code": "second", "name": "Второй", "mode": "serial", "quorum": "all",
                 "actors": [{"by": "user", "ref": str(owner.id)}]},
            ]
            started = await doc_approvals.start(db, cid, workflow_doc, route, owner)
            assert len(started["snapshot_sha256"]) == 64
            await db.flush()
            workflow_rows = (await db.execute(select(DocApproval).where(
                DocApproval.doc_id == workflow_doc.id,
            ).order_by(DocApproval.step_no))).scalars().all()
            assert [row.status for row in workflow_rows] == ["pending", "waiting"]
            card = await docs_router.get_doc(
                str(workflow_doc.id), str(cid), db, owner)
            assert card["approval"]["rows"][0]["assignee_name"] == owner.name
            assert workflow_rows[0].document_snapshot["files"][0]["sha256"] == hashlib.sha256(
                workflow_body).hexdigest()
            await doc_approvals.decide(
                db, cid, workflow_doc, workflow_rows[0], owner, True, None,
            )
            assert workflow_rows[1].status == "pending"
            await doc_approvals.decide(
                db, cid, workflow_doc, workflow_rows[1], owner, True, None,
            )
            assert workflow_doc.approval_status == "approved"

            extracted = await mail_routing.doc_text.extract(
                f"содержимое {marker}".encode(), "text/plain", "проверка.txt")
            version = DocVersion(
                company_id=cid, doc_id=private_doc.id, revision=1, role="body",
                file_id=uuid.uuid4(), file_name="проверка.txt", mime="text/plain",
                size_bytes=len(extracted or ""),
                sha256=hashlib.sha256(marker.encode()).hexdigest(),
                content_text=extracted,
            )
            db.add(version)
            await db.flush()
            ru = literal_column("'russian'::regconfig")
            found = await db.scalar(select(DocVersion.id).where(
                DocVersion.doc_id == private_doc.id,
                func.to_tsvector(
                    ru, func.coalesce(DocVersion.content_text, literal_column("''")),
                ).op("@@")(func.plainto_tsquery(ru, marker)),
            ))
            assert found == version.id

            mine = await docs_router.list_docs(
                company_id=str(cid), family=None, direction=None, status_=None,
                kind_id=None, counterparty_id=None, responsible_id=None,
                date_from=None, date_to=None, q=None, mine=True, limit=200, offset=0,
                db=db, current_user=owner,
            )
            mine_ids = {row["id"] for row in mine["docs"]}
            assert str(private_doc.id) in mine_ids
            assert str(company_doc.id) not in mine_ids
            search = await docs_router.list_docs(
                company_id=str(cid), family=None, direction=None, status_=None,
                kind_id=None, counterparty_id=None, responsible_id=None,
                date_from=None, date_to=None, q=marker, mine=False, limit=200, offset=0,
                db=db, current_user=owner,
            )
            assert str(private_doc.id) in {row["id"] for row in search["docs"]}

            assert not await docs_router._can_doc(db, cid, private_doc, person, "read")
            assert await docs_router._can_doc(db, cid, workflow_doc, person, "read")
            assert not await docs_router._can_doc(db, cid, workflow_doc, person, "edit")
            db.add(DocAccessGrant(
                company_id=cid, scope_type="doc", scope_id=private_doc.id,
                subject_type="user", subject_id=person.id, permissions=["read", "edit"],
                created_by=owner.id,
            ))
            await db.flush()
            assert await docs_router._can_doc(db, cid, private_doc, person, "read")
            assert await docs_router._can_doc(db, cid, private_doc, person, "edit")

            approval = DocApproval(
                company_id=cid, doc_id=report_doc.id, round=1, step_no=1,
                step_code="check", step_name="Проверка", assignee_id=person.id,
                status="approved", decided_by=person.id,
                created_at=now - timedelta(hours=2), decided_at=now,
            )
            db.add(approval)
            await db.flush()
            report = await docs_router.approval_discipline(
                company_id=str(cid), date_from=now.date(), date_to=now.date(),
                db=db, current_user=owner,
            )
            assert report["summary"]["completed"] >= 1
            assert any(row["user_id"] == str(person.id) for row in report["people"])

            acquaint = DocAcquaint(
                company_id=cid, doc_id=private_doc.id, user_id=person.id,
                reason="manual", due_at=now + timedelta(hours=12), created_by=owner.id,
            )
            db.add(acquaint)
            await db.flush()
            assert await task_scheduler.run_acquaint_reminders(db, now) >= 1
            assert acquaint.reminded_at is not None
            assert any(marker in notice for notice in notices)

            counterparty = Counterparty(
                company_id=cid, inn=str(uuid.uuid4().int)[:12], name=f"{marker}-контрагент",
            )
            db.add(counterparty)
            await db.flush()
            message = MailMessage(
                company_id=cid, direction="in", message_id=f"<{uuid.uuid4()}@check.invalid>",
                subject=f"{marker}-письмо", from_email="check@invalid.local",
                body_text=marker, has_attachments=True, counterparty_id=counterparty.id,
            )
            db.add(message)
            await db.flush()
            attachment = f"вложение {marker}".encode()
            db.add(MailAttachment(
                company_id=cid, message_id=message.id, file_name=f"{marker}.txt",
                content_type="text/plain", size=len(attachment),
                sha256=hashlib.sha256(attachment).hexdigest(), content=attachment,
            ))
            await db.flush()
            assert await mail_routing.to_doc(db, cid, message)
            await db.flush()
            assert await mail_routing.to_doc(db, cid, message)
            await db.flush()
            mail_docs = await db.scalar(select(func.count()).select_from(DocCard).where(
                DocCard.company_id == cid, DocCard.source == "mail",
                DocCard.source_ref == f"mail:{message.message_id}",
            ))
            assert mail_docs == 1

            exchange_root = doc_exchange.exchange_roots()[0]
            tenant_root = (exchange_root / str(cid)).resolve(strict=False)
            if not tenant_root.is_relative_to(exchange_root):
                raise AssertionError("Корень стендовой проверки вышел за tenant-папку")
            tenant_root_existed = tenant_root.exists()
            tenant_root.mkdir(parents=True, exist_ok=True)
            try:
                with tempfile.TemporaryDirectory(
                        prefix="trek-check-", dir=tenant_root) as folder:
                    inbox = Path(folder).resolve(strict=True)
                    if not inbox.is_relative_to(tenant_root):
                        raise AssertionError("Временная папка вышла за tenant-корень")
                    first_path = inbox / f"{marker}-1.txt"
                    first_path.write_text(marker, encoding="utf-8")
                    stable_at = now.timestamp() - doc_exchange.MIN_STABLE_AGE_SECONDS - 1
                    os.utime(first_path, (stable_at, stable_at))
                    target = DocExchangeTarget(
                        company_id=cid, code=f"check-{uuid.uuid4().hex[:8]}", name=marker,
                        system="other", inbox_path=str(inbox), outbox_path="",
                        scan_enabled=False, scan_interval_min=5,
                    )
                    db.add(target)
                    await db.flush()
                    assert await doc_exchange.collect_inbox(db, target) == 1
                    target.scan_enabled = True
                    target.last_scan_at = now - timedelta(minutes=10)
                    second_path = inbox / f"{marker}-2.txt"
                    second_path.write_text(marker + "2", encoding="utf-8")
                    os.utime(second_path, (stable_at, stable_at))
                    assert await task_scheduler.run_exchange_scans(db, now) >= 1
                    inbox_count = await db.scalar(select(func.count()).select_from(
                        DocInboxItem).where(DocInboxItem.target_id == target.id))
                    assert inbox_count == 2
            finally:
                if not tenant_root_existed:
                    try:
                        tenant_root.rmdir()
                    except OSError:
                        pass

            print("OK: schema workflow snapshot workspace search access discipline acquaint mail exchange")
            await db.rollback()
    finally:
        file_store.put = original_put
        task_scheduler.task_mail.send_notice_checked = original_notice
        root = file_store.upload_dir().resolve()
        for path in written:
            resolved = path.resolve()
            if resolved.is_relative_to(root) and resolved.is_file():
                resolved.unlink()


if __name__ == "__main__":
    asyncio.run(main())
