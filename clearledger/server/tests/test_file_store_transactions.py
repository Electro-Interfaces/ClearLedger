"""Actual PostgreSQL transactions + tmpfiles, including SAVEPOINT and close."""
import asyncio
from contextlib import contextmanager
import hashlib
import io
import os
from pathlib import Path
import uuid
import zipfile
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Session

from tests.partner_test_safety import partner_test_safety_error

if os.environ.get("RUN_FILE_STORE_TESTS") != "1":
    pytest.skip("Opt in with RUN_FILE_STORE_TESTS=1", allow_module_level=True)
_safety_error = partner_test_safety_error(os.environ, flag="RUN_FILE_STORE_TESTS")
if _safety_error:
    raise pytest.UsageError("Refusing file-store test database: " + _safety_error)

from app.models import Company, SourceFile
from app.services import file_store


@pytest_asyncio.fixture
async def storage(db, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path.resolve()))
    cid = await db.scalar(select(Company.id).limit(1))
    return async_sessionmaker(db.bind, expire_on_commit=False), cid, tmp_path


def put(session, cid, **kwargs):
    return file_store.put(session, cid, b"new bytes", file_name="Скан.pdf", **kwargs)


@pytest.mark.parametrize("flush", [False, True])
async def test_successful_root_commit_keeps_row_and_bytes(storage, flush):
    factory, cid, root = storage
    async with factory() as session:
        row = put(session, cid)
        if flush:
            await session.flush()
        identifier, path = row.id, Path(row.storage_path)
        await session.commit()
    assert path.read_bytes() == b"new bytes"
    async with factory() as session:
        saved = await session.get(SourceFile, identifier)
        assert saved.fingerprint == hashlib.sha256(b"new bytes").hexdigest()
        assert saved.size == 9 and saved.file_name == "Скан.pdf"
        assert saved.purpose == "attachment"


@pytest.mark.parametrize("flush", [False, True])
async def test_rollback_or_close_without_commit_removes_only_owned_bytes(storage, flush):
    factory, cid, root = storage
    previous = root / "unrelated.pdf"
    previous.write_bytes(b"old")
    async with factory() as session:
        row = put(session, cid)
        if flush:
            await session.flush()
        path = Path(row.storage_path)
        await session.rollback()
        assert not path.exists()
    assert previous.read_bytes() == b"old"


@pytest.mark.parametrize("flush", [False, True])
async def test_close_without_explicit_rollback_cleans_pending_transaction(storage, flush):
    factory, cid, root = storage
    async with factory() as session:
        row = put(session, cid)
        path, identifier = Path(row.storage_path), row.id
        if flush:
            await session.flush()
    assert not path.exists()
    async with factory() as session:
        assert await session.get(SourceFile, identifier) is None


async def test_cancellation_after_successful_flush_cleans_on_transaction_exit(storage):
    factory, cid, root = storage
    ready = asyncio.Event()
    paths = []
    async def work():
        async with factory.begin() as session:
            row = put(session, cid)
            paths.append(Path(row.storage_path))
            await session.flush()
            ready.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(work())
    await ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not paths[0].exists()


@pytest.mark.parametrize("commit_root", [False, True])
async def test_nested_commit_stays_owned_by_root(storage, commit_root):
    factory, cid, root = storage
    async with factory() as session:
        async with session.begin_nested():
            row = put(session, cid)
            path = Path(row.storage_path)
            await session.flush()
        assert path.exists()
        if commit_root:
            await session.commit()
        else:
            await session.rollback()
    assert path.exists() is commit_root


async def test_inner_rollback_preserves_outer_file_then_root_commit(storage):
    factory, cid, root = storage
    async with factory() as session:
        outer = put(session, cid)
        outer_path = Path(outer.storage_path)
        savepoint = await session.begin_nested()
        inner = put(session, cid)
        inner_path = Path(inner.storage_path)
        await session.flush()
        await savepoint.rollback()
        assert not inner_path.exists() and outer_path.exists()
        await session.commit()
    assert outer_path.exists()


async def test_deep_nested_commit_then_middle_rollback_does_not_touch_root(storage):
    factory, cid, root = storage
    async with factory() as session:
        outer = put(session, cid)
        outer_path = Path(outer.storage_path)
        middle = await session.begin_nested()
        async with session.begin_nested():
            inner = put(session, cid)
            inner_path = Path(inner.storage_path)
        await middle.rollback()
        assert not inner_path.exists() and outer_path.exists()
        await session.commit()
    assert outer_path.exists()


async def test_failed_nested_flush_only_removes_inner_bytes(storage):
    factory, cid, root = storage
    async with factory() as session:
        outer = put(session, cid)
        outer_path = Path(outer.storage_path)
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                inner = put(session, uuid.uuid4())
                inner_path = Path(inner.storage_path)
                await session.flush()
        assert not inner_path.exists() and outer_path.exists()
        await session.commit()


async def test_failed_root_flush_cleans_new_bytes(storage):
    factory, cid, root = storage
    async with factory() as session:
        row = put(session, uuid.uuid4())
        path = Path(row.storage_path)
        with pytest.raises(IntegrityError):
            await session.flush()
        assert not path.exists()
        await session.rollback()


async def test_real_commit_failure_cleans_transaction_and_preserves_prior_commit(storage):
    factory, cid, root = storage
    async with factory() as session:
        previous = put(session, cid)
        previous_path = Path(previous.storage_path)
        await session.commit()
    def fail_commit(connection):
        raise RuntimeError("synthetic DBAPI commit failure")
    engine = factory.kw["bind"].sync_engine
    event.listen(engine, "commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="commit failure"):
            async with factory.begin() as session:
                row = put(session, cid)
                path = Path(row.storage_path)
                await session.flush()
    finally:
        event.remove(engine, "commit", fail_commit)
    assert not path.exists() and previous_path.read_bytes() == b"new bytes"


async def test_repeated_session_never_cleans_previous_committed_file(storage):
    factory, cid, root = storage
    async with factory() as session:
        old = put(session, cid)
        old_path = Path(old.storage_path)
        await session.commit()
        new = put(session, cid)
        new_path = Path(new.storage_path)
        await session.flush()
        await session.rollback()
        assert old_path.exists() and not new_path.exists()
        assert file_store._PENDING not in session.info


async def test_post_commit_observer_error_never_deletes_committed_bytes(storage):
    factory, cid, root = storage
    async with factory() as session:
        row = put(session, cid)
        identifier, path = row.id, Path(row.storage_path)
        def observer_error(value):
            raise RuntimeError("synthetic observer after durable commit")
        event.listen(session.sync_session, "after_commit", observer_error)
        with pytest.raises(RuntimeError, match="observer"):
            await session.commit()
    assert path.exists()
    async with factory() as session:
        assert await session.get(SourceFile, identifier) is not None


@contextmanager
def early_class_commit_observer(observer):
    # Model import order: an app-wide CLASS observer is registered before the
    # writer's CLASS listener. An instance listener runs too late to test this.
    event.remove(Session, "after_commit", file_store._file_commit)
    event.listen(Session, "after_commit", observer)
    event.listen(Session, "after_commit", file_store._file_commit)
    try:
        yield
    finally:
        event.remove(Session, "after_commit", observer)


@pytest.mark.parametrize("observer_raises", [False, True])
async def test_early_class_observer_preserves_durable_commit(storage, observer_raises):
    factory, cid, root = storage
    observed = []

    def observer(session):
        bucket = session.info[file_store._PENDING][file_store._current(session)]
        assert not bucket.committed  # Prove the observer runs before the writer.
        observed.append(True)
        if observer_raises:
            raise RuntimeError("early CLASS observer after durable commit")

    with early_class_commit_observer(observer):
        async with factory() as session:
            row = put(session, cid)
            identifier, path = row.id, Path(row.storage_path)
            await session.flush()
            if observer_raises:
                with pytest.raises(RuntimeError, match="early CLASS observer"):
                    await session.commit()
            else:
                await session.commit()
            # Verify durability through an independent PostgreSQL transaction,
            # before close can hide the distinction between commit and rollback.
            async with factory() as verification:
                assert await verification.get(SourceFile, identifier) is not None
            assert path.read_bytes() == b"new bytes"
        assert path.read_bytes() == b"new bytes"
        assert file_store._PENDING not in session.info
    assert observed == [True]


@pytest.mark.parametrize("parent_outcome", ["commit", "rollback", "close"])
async def test_early_class_observer_on_savepoint_keeps_parent_ownership(storage, parent_outcome):
    factory, cid, root = storage

    def observer(session):
        assert session.in_nested_transaction()
        bucket = session.info[file_store._PENDING][file_store._current(session)]
        assert not bucket.committed
        raise RuntimeError("early CLASS observer after RELEASE")

    async with factory() as session:
        outer = put(session, cid)
        outer_id, outer_path = outer.id, Path(outer.storage_path)
        await session.flush()
        nested = await session.begin_nested()
        inner = put(session, cid)
        inner_id, inner_path = inner.id, Path(inner.storage_path)
        await session.flush()
        with early_class_commit_observer(observer):
            with pytest.raises(RuntimeError, match="after RELEASE"):
                await nested.commit()
        # after_commit raised before SQLAlchemy could finish closing the nested
        # SessionTransaction. Close through its PUBLIC API, keeping the parent.
        await session.run_sync(lambda sync: sync.get_nested_transaction().close())
        assert outer_path.exists() and inner_path.exists()
        if parent_outcome == "commit":
            await session.commit()
        elif parent_outcome == "rollback":
            await session.rollback()
    for path in (outer_path, inner_path):
        assert path.exists() is (parent_outcome == "commit")
    async with factory() as verification:
        for identifier in (outer_id, inner_id):
            assert (await verification.get(SourceFile, identifier) is not None) is (parent_outcome == "commit")


@pytest.mark.parametrize("explicit_rollback", [False, True])
async def test_unconfirmed_commit_close_retains_bytes_but_rollback_cleans(storage, explicit_rollback, caplog):
    factory, cid, root = storage

    def fail_commit(connection):
        raise RuntimeError("synthetic commit failure with unknown outcome")

    engine = factory.kw["bind"].sync_engine
    async with factory() as session:
        row = put(session, cid)
        identifier, path = row.id, Path(row.storage_path)
        await session.flush()
        event.listen(engine, "commit", fail_commit)
        try:
            with pytest.raises(RuntimeError, match="unknown outcome"):
                await session.commit()
        finally:
            event.remove(engine, "commit", fail_commit)
        if explicit_rollback:
            await session.rollback()
    # A public commit-attempt event does not prove whether commit reached DB.
    # Without a rollback event, retention is intentional, even though this test
    # injected the error before DBAPI commit and can independently prove no row.
    assert path.exists() is not explicit_rollback
    if not explicit_rollback:
        assert "bytes сохранены" in caplog.text
    assert file_store._PENDING not in session.info
    async with factory() as verification:
        assert await verification.get(SourceFile, identifier) is None


async def test_collision_same_id_different_extension_preserves_original(storage):
    factory, cid, root = storage
    identifier = uuid.uuid4()
    async with factory() as session:
        old = put(session, cid, file_id=identifier)
        old_path = Path(old.storage_path)
        await session.commit()
    async with factory() as session:
        with pytest.raises(FileExistsError):
            put(session, cid, file_id=identifier)
        assert old_path.exists()
        row = file_store.put(session, cid, b"duplicate", file_name="other.txt", file_id=identifier)
        new_path = Path(row.storage_path)
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()
    assert old_path.read_bytes() == b"new bytes" and not new_path.exists()


async def test_generated_zip_has_exact_source_identity_and_rolls_back(storage):
    factory, cid, root = storage
    def archive(stream):
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as value:
            value.writestr("manifest.json", '{"synthetic":true}')
            value.writestr("scan.pdf", b"PDF bytes")
    async with factory() as session:
        row = file_store.put_generated(session, cid, archive, file_name="Комплект.zip", mime="application/zip")
        path = Path(row.storage_path)
        data = path.read_bytes()
        assert row.size == len(data) and row.fingerprint == hashlib.sha256(data).hexdigest()
        with zipfile.ZipFile(path) as value:
            assert value.read("scan.pdf") == b"PDF bytes"
        await session.flush()
        await session.rollback()
    assert not path.exists()


async def test_migrated_intake_keeps_data_purpose_dedup_and_commit_owner(storage, monkeypatch):
    from fastapi import BackgroundTasks, UploadFile
    from app.routers import intake_router
    factory, cid, root = storage
    monkeypatch.setattr(intake_router, "assert_company_member", AsyncMock(return_value=cid))
    user = SimpleNamespace(company_id=cid)
    async with factory() as session:
        response = await intake_router.upload_file(UploadFile(io.BytesIO(b"scan"), filename="Скан.pdf"),
            BackgroundTasks(), company_id=str(cid), purpose="data", db=session, current_user=user)
        identifier = uuid.UUID(response["source_id"])
        row = await session.get(SourceFile, identifier)
        path = Path(row.storage_path)
        assert row.purpose == "data" and path.parent == root and row.file_name == "Скан.pdf"
        duplicate = await intake_router.upload_file(UploadFile(io.BytesIO(b"scan"), filename="copy.pdf"),
            BackgroundTasks(), company_id=str(cid), purpose="data", db=session, current_user=user)
        assert duplicate == response
        # Intake still does not take over the enclosing commit.
        await session.rollback()
        assert not path.exists()


async def test_migrated_site_upload_preserves_data_and_late_failure_cleanup(storage, monkeypatch):
    from fastapi import UploadFile
    from app.routers import sites_router
    factory, cid, root = storage
    monkeypatch.setattr(sites_router, "assert_company_member", AsyncMock(return_value=cid))
    monkeypatch.setattr(sites_router, "_owned", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))
    operation = AsyncMock(return_value={"ok": True})
    monkeypatch.setattr(sites_router.ezs_project, "add_doc", operation)
    async with factory() as session:
        await sites_router.upload_site_doc(uuid.uuid4(), str(cid), kind="other", title=None, note=None,
            file=UploadFile(io.BytesIO(b"site"), filename="site.pdf"), user=SimpleNamespace(), db=session)
        row = await session.scalar(select(SourceFile).where(SourceFile.company_id == cid, SourceFile.fingerprint == hashlib.sha256(b"site").hexdigest()))
        assert row.purpose == "data" and Path(row.storage_path).read_bytes() == b"site"
        committed_path = Path(row.storage_path)
        operation.side_effect = RuntimeError("late domain failure")
        with pytest.raises(RuntimeError, match="late domain"):
            await sites_router.upload_site_doc(uuid.uuid4(), str(cid), kind="other", title=None, note=None,
                file=UploadFile(io.BytesIO(b"late"), filename="late.pdf"), user=SimpleNamespace(), db=session)
        await session.rollback()
        assert list(root.iterdir()) == [committed_path]


async def test_migrated_shared_pdf_keeps_pdf_storage_suffix_and_attachment(storage, monkeypatch):
    from fastapi import UploadFile
    from app.models import Organization
    from app.routers import sites_router
    from app.services.ezs_tp_workflow import SHARED_KINDS
    factory, cid, root = storage
    monkeypatch.setattr(sites_router, "assert_company_member", AsyncMock(return_value=cid))
    monkeypatch.setattr(sites_router, "_owned", AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4())))
    monkeypatch.setattr(sites_router.ezs_site_work, "log_event", AsyncMock())
    async with factory() as session:
        org = Organization(company_id=cid, name="Synthetic applicant", inn="9999999999")
        session.add(org)
        await session.commit()
        await sites_router.upload_tp_shared_document(uuid.uuid4(), org.id, next(iter(SHARED_KINDS)),
            company_id=str(cid), file=UploadFile(io.BytesIO(b"%PDF-test"), filename="original.bin"),
            user=SimpleNamespace(is_superadmin=True, id=uuid.uuid4()), db=session)
        row = await session.scalar(select(SourceFile).where(SourceFile.company_id == cid,
            SourceFile.fingerprint == hashlib.sha256(b"%PDF-test").hexdigest()))
        assert row.file_name == "original.bin" and row.mime_type == "application/pdf"
        assert row.purpose == "attachment" and Path(row.storage_path).suffix == ".pdf"


async def test_migrated_task_attachment_keeps_source_data_default(storage, monkeypatch):
    from fastapi import UploadFile
    from app.models import Task, TaskAttachment, User
    from app.routers import tasks_router
    factory, cid, root = storage
    monkeypatch.setattr(tasks_router, "_assert_work", AsyncMock(return_value=cid))
    monkeypatch.setattr(tasks_router, "_can_view_task", AsyncMock(return_value=True))
    async with factory() as session:
        user = await session.scalar(select(User).limit(1))
        task = Task(company_id=cid, title="Synthetic attachment")
        session.add(task)
        await session.commit()
        monkeypatch.setattr(tasks_router, "_task_or_404", AsyncMock(return_value=task))
        result = await tasks_router.upload_attachment(str(task.id), str(cid), event_id=None,
            file=UploadFile(io.BytesIO(b"task"), filename="task.txt"), db=session, current_user=user)
        attachment = await session.get(TaskAttachment, uuid.UUID(result["id"]))
        source = await session.get(SourceFile, attachment.file_id)
        assert source.purpose == "data" and source.mime_type == "application/octet-stream"
        assert source.file_name == "task.txt" and Path(source.storage_path).read_bytes() == b"task"


@pytest.mark.parametrize("commit", [False, True])
async def test_migrated_tp_handover_preserves_archive_version_identity(storage, monkeypatch, commit):
    from app.models import DocVersion, EzsSite, User
    from app.services import doc_access, ezs_tp_method, ezs_tp_workflow, notify
    factory, cid, root = storage
    async with factory() as session:
        user = await session.scalar(select(User).limit(1))
        site = EzsSite(company_id=cid, project_no="synthetic-" + uuid.uuid4().hex[:10], title="Synthetic TP")
        session.add(site)
        original = file_store.put(session, cid, b"input", file_name="Вход.pdf")
        await session.commit()
        original_path = Path(original.storage_path)
        tc = SimpleNamespace(id=uuid.uuid4(), company_id=cid, site_id=site.id, workflow={})
        w = SimpleNamespace(archived=True, responsibilities={"owner": SimpleNamespace(controller=user.id)},
                            organization_id=None, supply_contract_id=None)
        monkeypatch.setattr(ezs_tp_workflow, "data_of", lambda value: w)
        monkeypatch.setattr(ezs_tp_workflow, "evidence", AsyncMock(return_value=(set(), {}, {"tu": [str(original.id)]})))
        monkeypatch.setattr(ezs_tp_workflow, "final_missing", lambda *args: [])
        monkeypatch.setattr(ezs_tp_workflow, "required_kinds", lambda *args: [])
        monkeypatch.setattr(ezs_tp_workflow, "supply_kinds", lambda *args: [])
        monkeypatch.setattr(doc_access, "_docs_members", AsyncMock(return_value={user.id: user}))
        monkeypatch.setattr(notify, "notify_person", AsyncMock())
        await ezs_tp_method.create_handover(session, tc)
        version = await session.scalar(select(DocVersion).where(DocVersion.company_id == cid,
            DocVersion.doc_id == uuid.UUID(tc.workflow["_handover"]["docId"])))
        source = await session.get(SourceFile, version.file_id)
        path = Path(source.storage_path)
        assert source.purpose == "attachment" and source.mime_type == "application/zip"
        assert version.sha256 == source.fingerprint == hashlib.sha256(path.read_bytes()).hexdigest()
        assert version.size_bytes == source.size == path.stat().st_size
        with zipfile.ZipFile(path) as archive:
            assert archive.read("001_Вход.pdf") == b"input" and "manifest.json" in archive.namelist()
        if commit:
            await session.commit()
        else:
            await session.rollback()
    assert original_path.exists() and path.exists() is commit
