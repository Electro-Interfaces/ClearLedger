import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import hash_password
from app.models import (
    Company, DocAccessGrant, DocArchiveEvent, DocCard, DocCase,
    DocDestructionAct, DocDestructionItem, DocExport, DocKind, DocShareLink,
    DocVersion, MailAttachment, MailMessage, User, UserCompany,
)
from app.routers import docs_router
from app.services import doc_archive, file_store

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_external_export_blocker_отделён_от_известных_копий():
    assert doc_archive.classify_external_export_status("placed") == "known_copy"
    assert doc_archive.classify_external_export_status("downloaded") == "known_copy"
    assert doc_archive.classify_external_export_status("failed") is None
    assert doc_archive.classify_external_export_status("pending") == "unresolved"
    assert doc_archive.classify_external_export_status("unknown") == "unresolved"
    frozen = {
        "known_external_copies": [{"status": "placed"}],
        "unresolved_external_exports": [],
        "has_unresolved_external_exports": False,
    }
    assert doc_archive.external_export_blocker(frozen) is None
    assert doc_archive.external_export_blocker({
        "known_external_copies": [],
        "unresolved_external_exports": [{"status": "pending"}],
        "has_unresolved_external_exports": True,
    })
    assert doc_archive.external_export_change_blocker(frozen, frozen) is None
    assert doc_archive.external_export_change_blocker(frozen, {
        **frozen,
        "known_external_copies": [
            *frozen["known_external_copies"], {"status": "downloaded"},
        ],
    })


async def test_mail_evidence_сохраняет_только_хеш_и_размер():
    evidence = doc_archive._content_evidence("секретный текст")
    assert evidence == {
        "present": True,
        "size_bytes": len("секретный текст".encode("utf-8")),
        "sha256": "370b7a8e0d27be7576d34af7cf339cb570b584874dde6211c92271b71b189afa",
    }
    assert doc_archive._content_evidence(None) == {
        "present": False, "size_bytes": 0, "sha256": None,
    }


async def test_mail_attestation_и_атомарность_акта_проверяются_строго():
    company_id = uuid.uuid4()
    export_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    attested_at = datetime.now(timezone.utc).isoformat()
    evidence_text = "Локальная копия письма не создавалась"
    export = SimpleNamespace(
        id=export_id, company_id=company_id,
        content={
            "channel": "mail",
            "no_local_copy_attestation": {
                "company_id": str(company_id), "export_id": str(export_id),
                "attested_by": str(actor_id),
                "attested_at": attested_at, "evidence": evidence_text,
            },
            "resolution": {
                "status": "placed", "resolved_by": str(actor_id),
                "resolved_at": attested_at, "evidence": evidence_text,
            },
        },
    )
    assert doc_archive.no_local_mail_copy_attested(export)
    export.content["no_local_copy_attestation"]["company_id"] = str(uuid.uuid4())
    assert not doc_archive.no_local_mail_copy_attested(export)

    current_id = uuid.uuid4()
    second_id = uuid.uuid4()
    linked = {current_id, second_id}
    retention = {current_id: "destruction_authorized",
                 second_id: "destruction_authorized"}
    assert doc_archive.mail_link_disposition(
        linked, current_doc_id=current_id,
        act_item_statuses={current_id: "pending", second_id: "pending"},
        retention_states=retention,
    ) == "defer"
    assert doc_archive.mail_link_disposition(
        linked, current_doc_id=current_id,
        act_item_statuses={current_id: "pending", second_id: "primary_purged"},
        retention_states=retention,
    ) == "clear"
    assert doc_archive.mail_link_disposition(
        linked, current_doc_id=current_id,
        act_item_statuses={current_id: "pending"},
        retention_states=retention,
    ) == "block"


async def test_purge_preflight_проверяет_все_пути_до_изменений(tmp_path):
    first_id = uuid.uuid4()
    second_id = uuid.uuid4()
    first_path = tmp_path / "first.bin"
    first_path.write_bytes(b"first")
    versions = [
        SimpleNamespace(
            id=uuid.uuid4(), file_id=first_id,
            archive_purged_at=None, purge_result=None,
        ),
        SimpleNamespace(
            id=uuid.uuid4(), file_id=second_id,
            archive_purged_at=None, purge_result=None,
        ),
    ]
    sources = {
        first_id: SimpleNamespace(storage_path=str(first_path)),
        second_id: SimpleNamespace(
            storage_path=str(tmp_path.parent / "outside.bin"),
        ),
    }

    class FakeDb:
        async def scalar(self, _query):
            return None

        async def get(self, _model, file_id):
            return sources[file_id]

    with pytest.raises(ValueError, match="вне управляемого хранилища"):
        await doc_archive._purge_plans(
            FakeDb(), versions, uuid.uuid4(), uuid.uuid4(), tmp_path.resolve(),
        )
    assert first_path.read_bytes() == b"first"
    assert not (tmp_path / ".archive-quarantine").exists()


async def _headers(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/auth/login", json={
        "email": email, "password": password,
    })
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def test_акт_уничтожения_требует_четырёх_раздельных_решений(
    client: AsyncClient, db: AsyncSession, tmp_path, monkeypatch,
):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    company = (await db.execute(select(Company).order_by(Company.created_at))).scalars().first()
    assert company is not None
    password = "archive-test-123"
    users = [User(
        company_id=company.id,
        email=f"archive-{index}-{uuid.uuid4().hex}@example.org",
        name=f"Архивист {index}", password_hash=hash_password(password),
    ) for index in range(1, 5)]
    db.add_all(users)
    await db.flush()
    db.add_all([
        UserCompany(user_id=user.id, company_id=company.id, role="admin",
                    modules=["docs"])
        for user in users
    ])
    kind = DocKind(
        company_id=company.id, code=f"archive_{uuid.uuid4().hex[:8]}",
        name="Архивный тест", family="internal", direction="none",
        number_scope="kind_year", fields=[], route=[],
    )
    case = DocCase(
        company_id=company.id, year=2020, index=f"А-{uuid.uuid4().hex[:6]}",
        title="Дело с истёкшим сроком", storage_term="1 год",
        storage_years=1, retention_class="temporary",
        retention_basis="Тестовое основание", status="closed",
    )
    db.add_all([kind, case])
    await db.flush()
    incoming = MailMessage(
        company_id=company.id, direction="in",
        message_id=f"<archive-{uuid.uuid4().hex}@example.org>",
        subject="Исходное письмо архивного документа",
        body_text="Текст входящего письма", body_html="<p>Текст входящего письма</p>",
        raw_eml=b"From: sender@example.org\r\n\r\nincoming body",
        has_attachments=True, routed_to="doc",
    )
    db.add(incoming)
    await db.flush()
    search_token = f"archive-content-{uuid.uuid4().hex}"
    doc = DocCard(
        company_id=company.id, kind_id=kind.id, kind_code=kind.code,
        family=kind.family, direction=kind.direction,
        title="Документ к уничтожению", summary="Содержательное резюме",
        attrs={"subject": "Содержательный реквизит"}, status="archived",
        reg_number=f"АРХ-{uuid.uuid4().hex[:8]}", reg_date=date(2020, 2, 1),
        author_id=users[0].id, responsible_id=users[0].id,
        case_id=case.id, storage_until=date(2021, 12, 31),
        retention_state="archived", retention_class="temporary",
        retention_snapshot={"case_id": str(case.id), "storage_term": "1 год"},
        confidentiality="company", current_revision=1, has_files=True,
        source="mail", source_ref=doc_archive._mail_source_ref(incoming),
    )
    db.add(doc)
    await db.flush()
    source = file_store.put(
        db, company.id, b"archive evidence", file_name="document.txt",
        mime="text/plain",
    )
    await db.flush()
    version = DocVersion(
        company_id=company.id, doc_id=doc.id, revision=1, role="body",
        file_id=source.id, file_name=source.file_name, mime=source.mime_type,
        size_bytes=source.size, sha256=source.fingerprint,
        author_id=users[0].id, content_text=search_token,
    )
    second_source = file_store.put(
        db, company.id, b"archive appendix", file_name="appendix.txt",
        mime="text/plain",
    )
    await db.flush()
    second_version = DocVersion(
        company_id=company.id, doc_id=doc.id, revision=1, role="appendix",
        file_id=second_source.id, file_name=second_source.file_name,
        mime=second_source.mime_type, size_bytes=second_source.size,
        sha256=second_source.fingerprint, author_id=users[0].id,
    )
    outgoing = MailMessage(
        company_id=company.id, direction="out",
        message_id=f"<archive-out-{uuid.uuid4().hex}@example.org>",
        subject="Исходящая выгрузка архивного документа",
        body_text="Текст исходящего письма",
        body_html="<p>Текст исходящего письма</p>",
        raw_eml=b"To: recipient@example.org\r\n\r\noutgoing body",
        has_attachments=True,
    )
    db.add_all([version, second_version, outgoing])
    await db.flush()
    incoming_attachment = MailAttachment(
        company_id=company.id, message_id=incoming.id,
        file_name=source.file_name, content_type=source.mime_type,
        size=source.size, sha256=source.fingerprint, content=b"archive evidence",
    )
    outgoing_attachment = MailAttachment(
        company_id=company.id, message_id=outgoing.id,
        file_name=source.file_name, content_type=source.mime_type,
        size=source.size, sha256=source.fingerprint, content=b"archive evidence",
    )
    downloaded_export = DocExport(
        company_id=company.id, doc_id=doc.id, status="downloaded",
        package_name="archive-export.zip", package_sha256="a" * 64,
        size_bytes=100, created_by=users[0].id,
        content={
            "channel": "mail", "to": "recipient@example.org",
            "file_ids": [str(source.id)],
            "mail_message_id": str(outgoing.id),
            "rfc_message_id": outgoing.message_id,
        },
    )
    share = DocShareLink(
        company_id=company.id, doc_id=doc.id, token=uuid.uuid4().hex,
        recipient_name="Получатель", recipient_email="recipient@example.org",
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        version_snapshot=[{"id": str(version.id), "sha256": version.sha256}],
        card_snapshot={"title": doc.title, "reg_number": doc.reg_number},
        ack_evidence={"text": "Подтверждаю получение", "ip": "192.0.2.1"},
        created_by=users[0].id,
    )
    db.add_all([
        incoming_attachment, outgoing_attachment, downloaded_export, share,
    ])
    await db.commit()

    export_rows = [
        DocExport(
            company_id=company.id, doc_id=doc.id, status=status,
            package_name=f"{status}.zip", size_bytes=1,
            error=(f"{status}-error" if status in {"pending", "unknown"} else None),
            created_by=users[0].id,
        )
        for status in ("placed", "failed", "pending", "unknown")
    ]
    next(row for row in export_rows if row.status == "unknown").content = {
        "channel": "mail", "to": ["recipient@example.org"],
        "file_ids": [str(source.id)],
    }
    db.add_all(export_rows)
    await db.commit()
    export_snapshot = await doc_archive.document_snapshot(db, doc)
    assert {row["status"] for row in export_snapshot["known_external_copies"]} == {
        "placed", "downloaded",
    }
    assert {row["status"] for row in export_snapshot["unresolved_external_exports"]} == {
        "pending", "unknown",
    }
    downloaded_snapshot = next(
        row for row in export_snapshot["known_external_copies"]
        if row["status"] == "downloaded"
    )
    assert downloaded_snapshot["size_bytes"] == 100
    assert downloaded_snapshot["content"]["file_ids"] == [str(source.id)]
    assert downloaded_snapshot["content"]["mail_message_id"] == str(outgoing.id)
    assert all(
        row["size_bytes"] == 1 and row["error"] == f"{row['status']}-error"
        for row in export_snapshot["unresolved_external_exports"]
    )
    assert export_snapshot["card"]["summary"] == "Содержательное резюме"
    assert export_snapshot["card"]["attrs"] == {
        "subject": "Содержательный реквизит",
    }
    assert export_snapshot["known_share_links"][0]["version_snapshot"]
    assert export_snapshot["known_share_links"][0]["card_snapshot"]["title"] == doc.title
    assert export_snapshot["known_share_links"][0]["ack_evidence"]["text"] == (
        "Подтверждаю получение"
    )
    assert doc_archive.external_export_blocker(export_snapshot)
    assert "failed" not in {
        row["status"] for row in export_snapshot["known_external_copies"]
    }
    first, second, third, fourth = [
        await _headers(client, user.email, password) for user in users
    ]
    company_id = str(company.id)
    doc_id = str(doc.id)
    unresolved = {row.status: row for row in export_rows
                  if row.status in {"pending", "unknown"}}
    resolved_failed = await client.post(
        f"/api/docs/archive/exports/{unresolved['pending'].id}/resolve",
        headers=first,
        json={
            "company_id": company_id, "resolution": "failed",
            "evidence": "Процесс остановился до передачи пакета наружу",
        },
    )
    assert resolved_failed.status_code == 200, resolved_failed.text
    missing_attestation = await client.post(
        f"/api/docs/archive/exports/{unresolved['unknown'].id}/resolve",
        headers=first,
        json={
            "company_id": company_id, "resolution": "placed",
            "evidence": "Получатель подтвердил пакет письмом от 17.08.2026",
        },
    )
    assert missing_attestation.status_code == 409
    resolved_placed = await client.post(
        f"/api/docs/archive/exports/{unresolved['unknown'].id}/resolve",
        headers=first,
        json={
            "company_id": company_id, "resolution": "placed",
            "evidence": (
                "Получатель подтвердил пакет; локальная копия письма не создавалась"
            ),
            "no_local_copy": True,
        },
    )
    assert resolved_placed.status_code == 200, resolved_placed.text
    assert resolved_placed.json()["no_local_copy_attested"] is True
    await db.refresh(unresolved["unknown"])
    assert doc_archive.no_local_mail_copy_attested(unresolved["unknown"])
    assert (
        unresolved["unknown"].content["no_local_copy_attestation"]["company_id"]
        == company_id
    )
    assert doc_archive.external_export_blocker(
        await doc_archive.document_snapshot(db, doc),
    ) is None
    hold = await client.post(
        f"/api/docs/{doc_id}/archive/holds", headers=first,
        json={
            "company_id": company_id, "authority": "Судебный запрос",
            "reference": "Дело 42", "reason": "Сохранить до завершения спора",
        },
    )
    assert hold.status_code == 201, hold.text
    blocked = await client.post(
        f"/api/docs/{doc_id}/archive/decisions", headers=first,
        json={
            "company_id": company_id, "decision": "destroy",
            "reason": "Попытка уничтожения при действующем запрете",
        },
    )
    assert blocked.status_code == 409
    released = await client.post(
        f"/api/docs/archive/holds/{hold.json()['id']}/release", headers=first,
        json={"company_id": company_id,
              "reason": "Судебный спор завершён, запрет снят"},
    )
    assert released.status_code == 200, released.text
    decision = await client.post(
        f"/api/docs/{doc_id}/archive/decisions", headers=first,
        json={
            "company_id": company_id, "decision": "destroy",
            "reason": "Срок хранения истёк, ценность не подтверждена",
        },
    )
    assert decision.status_code == 201, decision.text
    act = await client.post("/api/docs/archive/acts", headers=first, json={
        "company_id": company_id, "act_number": f"АКТ-{uuid.uuid4().hex[:8]}",
        "act_date": date.today().isoformat(),
        "basis": "Экспертиза ценности и истечение срока хранения",
        "committee": [users[0].name, users[1].name], "doc_ids": [doc_id],
    })
    assert act.status_code == 201, act.text
    act_id = act.json()["id"]
    stored_item = await db.scalar(select(DocDestructionItem).where(
        DocDestructionItem.act_id == uuid.UUID(act_id),
        DocDestructionItem.doc_id == doc.id,
    ))
    assert stored_item.snapshot["card"]["summary"] == "Содержательное резюме"
    assert stored_item.snapshot["card"]["attrs"] == {
        "subject": "Содержательный реквизит",
    }
    assert any(
        row["content"] and row["content"].get("mail_message_id") == str(outgoing.id)
        for row in stored_item.snapshot["known_external_copies"]
    )
    assert stored_item.snapshot["known_share_links"][0]["version_snapshot"]

    own_approval = await client.post(
        f"/api/docs/archive/acts/{act_id}/approve", headers=first,
        json={"company_id": company_id},
    )
    assert own_approval.status_code == 409
    approved = await client.post(
        f"/api/docs/archive/acts/{act_id}/approve", headers=second,
        json={"company_id": company_id},
    )
    assert approved.status_code == 200, approved.text
    assert (await client.get(
        f"/api/files/{source.id}", headers=third,
    )).status_code == 404

    own_execution = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=second,
        json={"company_id": company_id},
    )
    assert own_execution.status_code == 409
    shared_doc = DocCard(
        company_id=company.id, kind_id=kind.id, kind_code=kind.code,
        family=kind.family, direction=kind.direction,
        title="Независимая ссылка на общий файл", status="draft",
        author_id=users[0].id, responsible_id=users[0].id,
        confidentiality="company", current_revision=1, has_files=True,
    )
    db.add(shared_doc)
    await db.flush()
    shared_version = DocVersion(
        company_id=company.id, doc_id=shared_doc.id, revision=1, role="body",
        file_id=source.id, file_name=source.file_name, mime=source.mime_type,
        size_bytes=source.size, sha256=source.fingerprint,
        author_id=users[0].id,
    )
    shared_mail_export = DocExport(
        company_id=company.id, doc_id=shared_doc.id, status="downloaded",
        package_name="shared-mail-export.eml", size_bytes=source.size,
        content={
            "channel": "mail", "file_ids": [str(source.id)],
            "mail_message_id": str(outgoing.id),
            "rfc_message_id": outgoing.message_id,
        }, created_by=users[0].id,
    )
    db.add_all([shared_version, shared_mail_export])
    await db.commit()
    real_purge_item_files = doc_archive.purge_item_files
    purge_entered = asyncio.Event()
    release_purge = asyncio.Event()

    async def paused_purge(*args, **kwargs):
        purge_entered.set()
        await release_purge.wait()
        return await real_purge_item_files(*args, **kwargs)

    monkeypatch.setattr(doc_archive, "purge_item_files", paused_purge)
    first_execution = asyncio.create_task(client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=third,
        json={"company_id": company_id},
    ))
    await asyncio.wait_for(purge_entered.wait(), timeout=5)
    concurrent_execution = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=fourth,
        json={"company_id": company_id},
    )
    assert concurrent_execution.status_code == 409
    release_purge.set()
    first_execution_result = await asyncio.wait_for(first_execution, timeout=10)
    assert first_execution_result.status_code == 409
    monkeypatch.setattr(doc_archive, "purge_item_files", real_purge_item_files)
    stored_act = await db.get(DocDestructionAct, uuid.UUID(act_id))
    await db.refresh(stored_act)
    assert stored_act.status == "failed"
    assert stored_act.executed_by == users[2].id
    shared_block = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=third,
        json={"company_id": company_id},
    )
    assert shared_block.status_code == 409
    assert (tmp_path / f"{source.id}.txt").exists()
    assert (tmp_path / f"{second_source.id}.txt").exists()
    await db.refresh(incoming)
    await db.refresh(outgoing)
    await db.refresh(incoming_attachment)
    await db.refresh(outgoing_attachment)
    assert incoming.raw_eml is not None
    assert outgoing.raw_eml is not None
    assert incoming_attachment.content is not None
    assert outgoing_attachment.content is not None
    await db.delete(shared_mail_export)
    await db.delete(shared_version)
    await db.delete(shared_doc)
    await db.commit()
    mail_shared_doc = DocCard(
        company_id=company.id, kind_id=kind.id, kind_code=kind.code,
        family=kind.family, direction=kind.direction,
        title="Другой документ в общем исходящем письме", status="draft",
        author_id=users[0].id, responsible_id=users[0].id,
        confidentiality="company", current_revision=0, has_files=False,
    )
    db.add(mail_shared_doc)
    await db.flush()
    mail_shared_export = DocExport(
        company_id=company.id, doc_id=mail_shared_doc.id, status="downloaded",
        package_name="same-outgoing-message.eml", size_bytes=1,
        content={
            "channel": "mail", "file_ids": [],
            "mail_message_id": str(outgoing.id),
            "rfc_message_id": outgoing.message_id,
        }, created_by=users[0].id,
    )
    db.add(mail_shared_export)
    await db.commit()
    shared_mail_block = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=third,
        json={"company_id": company_id},
    )
    assert shared_mail_block.status_code == 409
    await db.refresh(outgoing)
    await db.refresh(outgoing_attachment)
    assert outgoing.raw_eml is not None
    assert outgoing_attachment.content is not None
    await db.delete(mail_shared_export)
    await db.delete(mail_shared_doc)
    await db.commit()
    unrelated_attachment = MailAttachment(
        company_id=company.id, message_id=outgoing.id,
        file_name="unrelated.bin", content_type="application/octet-stream",
        size=17, sha256="b" * 64, content=b"unrelated payload",
    )
    db.add(unrelated_attachment)
    await db.commit()
    unrelated_block = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=third,
        json={"company_id": company_id},
    )
    assert unrelated_block.status_code == 409
    await db.refresh(outgoing)
    await db.refresh(outgoing_attachment)
    await db.refresh(unrelated_attachment)
    assert outgoing.raw_eml is not None
    assert outgoing_attachment.content is not None
    assert unrelated_attachment.content == b"unrelated payload"
    assert (tmp_path / f"{source.id}.txt").exists()
    await db.delete(unrelated_attachment)
    await db.commit()
    second_path = Path(second_source.storage_path)
    second_source.storage_path = str(
        tmp_path.parent / f"outside-{second_source.id}.txt",
    )
    await db.commit()
    invalid_path = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=third,
        json={"company_id": company_id},
    )
    assert invalid_path.status_code == 409
    assert (tmp_path / f"{source.id}.txt").exists()
    assert second_path.exists()
    second_source.storage_path = str(second_path)
    await db.commit()

    real_unlink = Path.unlink

    def fail_second_quarantine(path: Path, *args, **kwargs):
        if path.name == str(second_source.id):
            raise OSError("simulated second-file purge failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_second_quarantine)
    partial = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=third,
        json={"company_id": company_id},
    )
    assert partial.status_code == 409
    await db.refresh(version)
    await db.refresh(second_version)
    assert version.archive_purged_at is None
    assert second_version.archive_purged_at is None
    assert version.purge_result in {"quarantined", "removed_after_intent"}
    assert second_version.purge_result == "quarantined"
    intent = await db.scalar(select(DocArchiveEvent.id).where(
        DocArchiveEvent.act_id == uuid.UUID(act_id),
        DocArchiveEvent.kind == "purge_intent",
    ).limit(1))
    assert intent is not None
    monkeypatch.setattr(Path, "unlink", real_unlink)
    executed = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=third,
        json={"company_id": company_id},
    )
    assert executed.status_code == 200, executed.text
    assert executed.json()["status"] == "primary_purged"
    assert not (tmp_path / f"{source.id}.txt").exists()
    assert not second_path.exists()
    assert not (
        tmp_path / ".archive-quarantine" / act_id / str(second_source.id)
    ).exists()
    await db.refresh(doc)
    await db.refresh(version)
    await db.refresh(incoming)
    await db.refresh(outgoing)
    await db.refresh(incoming_attachment)
    await db.refresh(outgoing_attachment)
    assert version.content_text is None
    assert doc.summary is None
    assert doc.attrs is None
    assert incoming.raw_eml is None
    assert incoming.body_text is None
    assert incoming.body_html is None
    assert outgoing.raw_eml is None
    assert outgoing.body_text is None
    assert outgoing.body_html is None
    assert incoming_attachment.content is None
    assert outgoing_attachment.content is None
    latest_intent = await db.scalar(select(DocArchiveEvent).where(
        DocArchiveEvent.act_id == uuid.UUID(act_id),
        DocArchiveEvent.kind == "purge_intent",
    ).order_by(DocArchiveEvent.created_at.desc(), DocArchiveEvent.id.desc()).limit(1))
    assert latest_intent.payload["mail_evidence_sha256"]
    assert len(latest_intent.payload["mail_copies"]) == 2
    assert all(
        row["raw_eml"]["sha256"] for row in latest_intent.payload["mail_copies"]
    )
    assert all(
        row["attachments"][0]["content"]["sha256"]
        for row in latest_intent.payload["mail_copies"]
    )

    terminal_replay = await client.post(
        f"/api/docs/archive/acts/{act_id}/execute", headers=fourth,
        json={"company_id": company_id},
    )
    assert terminal_replay.status_code == 409
    await db.refresh(stored_act)
    assert stored_act.status == "primary_purged"
    assert stored_act.executed_by == users[2].id

    version.content_text = search_token
    await db.commit()
    stale_search = await client.get(
        "/api/docs", headers=third,
        params={"company_id": company_id, "q": search_token},
    )
    assert stale_search.status_code == 200, stale_search.text
    assert doc_id not in {row["id"] for row in stale_search.json()["docs"]}
    version.content_text = None
    await db.commit()

    late_hold = await client.post(
        f"/api/docs/{doc_id}/archive/holds", headers=first,
        json={
            "company_id": company_id, "authority": "Служба безопасности",
            "reference": "Проверка 17", "reason": "Остановить финализацию акта",
        },
    )
    assert late_hold.status_code == 201, late_hold.text
    blocked_final = await client.post(
        f"/api/docs/archive/acts/{act_id}/confirm-backup-purge", headers=fourth,
        json={"company_id": company_id,
              "evidence": "Манифест backup-test-001, срок поколения завершён",
              "external_copies_evidence": "Внешняя выгрузка удалена получателем"},
    )
    assert blocked_final.status_code == 409
    late_release = await client.post(
        f"/api/docs/archive/holds/{late_hold.json()['id']}/release", headers=first,
        json={"company_id": company_id,
              "reason": "Проверка завершена, финализация разрешена"},
    )
    assert late_release.status_code == 200, late_release.text

    own_attestation = await client.post(
        f"/api/docs/archive/acts/{act_id}/confirm-backup-purge", headers=third,
        json={"company_id": company_id,
              "evidence": "Поколения резервных копий удалены по регламенту"},
    )
    assert own_attestation.status_code == 409
    missing_external = await client.post(
        f"/api/docs/archive/acts/{act_id}/confirm-backup-purge", headers=fourth,
        json={"company_id": company_id,
              "evidence": "Манифест backup-test-001, срок поколения завершён"},
    )
    assert missing_external.status_code == 409
    finished = await client.post(
        f"/api/docs/archive/acts/{act_id}/confirm-backup-purge", headers=fourth,
        json={"company_id": company_id,
              "evidence": "Манифест backup-test-001, срок поколения завершён",
              "external_copies_evidence": (
                  "Выгрузка archive-export.zip отозвана и удалена получателем")},
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "destroyed"

    await db.refresh(doc)
    await db.refresh(version)
    stored_act = await db.get(DocDestructionAct, uuid.UUID(act_id))
    assert doc.retention_state == "destroyed"
    assert version.archive_purged_at is not None
    assert version.content_text is None
    assert doc.summary is None
    assert doc.attrs is None
    assert stored_act.sealed_sha256
    history = await client.get(
        f"/api/docs/{doc_id}/archive", headers=fourth,
        params={"company_id": company_id},
    )
    assert history.status_code == 200, history.text
    events = history.json()["events"]
    assert events and events[0]["prev_hash"] is None
    assert all(
        current["prev_hash"] == previous["event_hash"]
        for previous, current in zip(events, events[1:])
    )
    assert all(event["doc_id"] == doc_id for event in events)


async def test_strict_deny_и_break_glass_закрывают_прямой_файл(
    auth_client: AsyncClient, db: AsyncSession, tmp_path, monkeypatch,
):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    me = (await auth_client.get("/api/auth/me")).json()
    company_id = uuid.UUID(me["companies"][0]["id"])
    superadmin = await db.get(User, uuid.UUID(me["id"]))
    kind = DocKind(
        company_id=company_id, code=f"strict_{uuid.uuid4().hex[:8]}",
        name="Строгий тест", family="internal", direction="none",
        number_scope="kind_year", fields=[], route=[],
    )
    employee_password = "strict-user-123"
    employee = User(
        company_id=company_id,
        email=f"strict-{uuid.uuid4().hex}@example.org",
        name="Сотрудник строгого документа",
        password_hash=hash_password(employee_password),
    )
    db.add_all([kind, employee])
    await db.flush()
    db.add(UserCompany(
        user_id=employee.id, company_id=company_id, role="user",
        modules=["docs", "connections"],
    ))
    doc = DocCard(
        company_id=company_id, kind_id=kind.id, kind_code=kind.code,
        family=kind.family, direction=kind.direction, title="Секретный документ",
        status="registered", reg_number=f"СТР-{uuid.uuid4().hex[:8]}",
        reg_date=date.today(), confidentiality="company",
        author_id=employee.id, responsible_id=employee.id,
        verify_token=uuid.uuid4().hex,
        current_revision=1, has_files=True,
    )
    db.add(doc)
    await db.flush()
    source = file_store.put(
        db, company_id, b"strict content", file_name="strict.txt", mime="text/plain",
    )
    await db.flush()
    db.add(DocVersion(
        company_id=company_id, doc_id=doc.id, revision=1, role="body",
        file_id=source.id, file_name=source.file_name, mime=source.mime_type,
        size_bytes=source.size, sha256=source.fingerprint, author_id=employee.id,
    ))
    grant = DocAccessGrant(
        company_id=company_id, scope_type="doc", scope_id=doc.id,
        subject_type="user", subject_id=employee.id,
        permissions=["read"], denied_permissions=["download"],
        created_by=employee.id,
    )
    db.add(grant)
    await db.commit()
    employee_headers = await _headers(
        auth_client, employee.email, employee_password,
    )

    link = await auth_client.post(
        f"/api/docs/{doc.id}/share", headers=employee_headers,
        json={"company_id": str(company_id), "days": 1},
    )
    assert link.status_code == 201, link.text
    token = link.json()["token"]
    assert (await auth_client.get(f"/api/doc-share/{token}")).status_code == 200
    strict_policy = await auth_client.put(
        f"/api/docs/{doc.id}/access-policy", headers=employee_headers,
        json={
            "company_id": str(company_id), "inherit_kind_acl": True,
            "confidentiality": "strict", "expected_acl_revision": 0,
        },
    )
    assert strict_policy.status_code == 200, strict_policy.text
    assert (await auth_client.get(f"/api/doc-share/{token}")).status_code == 404
    assert (await auth_client.get(
        f"/api/doc-share/{token}/file/{version.id}",
    )).status_code == 404
    assert (await auth_client.post(
        f"/api/doc-share/{token}/ack", json={"name": "Контрагент"},
    )).status_code == 404
    await db.refresh(doc)

    assert await docs_router._can_doc(db, company_id, doc, employee, "read")
    assert not await docs_router._can_doc(db, company_id, doc, employee, "download")
    assert not await docs_router._can_doc(db, company_id, doc, superadmin, "read")
    mail_bypass = await auth_client.post(
        "/api/mail/send",
        params={"company_id": str(company_id)},
        headers=employee_headers,
        json={
            "account_id": str(uuid.uuid4()), "to": ["outside@example.org"],
            "subject": "Попытка обхода", "body": "Закрытый документ",
            "attachments": [str(source.id)],
        },
    )
    assert mail_bypass.status_code == 404

    closed = await auth_client.get(
        f"/api/docs/{doc.id}", params={"company_id": str(company_id)},
    )
    assert closed.status_code == 403
    direct = await auth_client.get(f"/api/files/{source.id}")
    assert direct.status_code == 404
    public_check = await auth_client.get(
        f"/api/doc-share/verify/{doc.verify_token}",
    )
    assert public_check.status_code == 200
    assert public_check.json()["record_status"] == "restricted"

    activated = await auth_client.post(
        f"/api/docs/{doc.id}/break-glass",
        json={
            "company_id": str(company_id), "password": "admin123",
            "reason": "Аварийное чтение для проверки инцидента безопасности",
            "ttl_minutes": 5,
        },
    )
    assert activated.status_code == 201, activated.text
    opened = await auth_client.get(
        f"/api/docs/{doc.id}", params={"company_id": str(company_id)},
    )
    assert opened.status_code == 200
    assert opened.json()["capabilities"]["download"] is True
    assert opened.json()["capabilities"]["print"] is True
    assert opened.json()["capabilities"]["send"] is False
    assert opened.json()["capabilities"]["export"] is False
    downloaded = await auth_client.get(f"/api/files/{source.id}")
    assert downloaded.status_code == 200
    assert downloaded.headers["cache-control"] == "private, no-store"
    forbidden_share = await auth_client.post(
        f"/api/docs/{doc.id}/share",
        json={"company_id": str(company_id), "days": 1},
    )
    assert forbidden_share.status_code == 403

    revoked = await auth_client.post(
        f"/api/docs/break-glass/{activated.json()['id']}/revoke",
        params={"company_id": str(company_id)},
    )
    assert revoked.status_code == 200, revoked.text
    assert (await auth_client.get(f"/api/files/{source.id}")).status_code == 404
