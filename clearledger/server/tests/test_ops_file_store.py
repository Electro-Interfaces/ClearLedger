"""Real temporary files; no app startup, network or database is required."""
import asyncio
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock
import uuid

import pytest

from app.services import file_store, ops_terms


class Session:
    def __init__(self, failure=None):
        self.rows = []
        self.flush = AsyncMock(side_effect=failure)

    def add(self, row):
        self.rows.append(row)


@pytest.mark.asyncio
async def test_ops_uses_shared_storage_and_preserves_identity_and_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    session = Session()
    company, identifier = uuid.uuid4(), uuid.uuid4()
    result = await ops_terms.store_file(session, company, "Скан.pdf", "application/pdf", b"document", identifier)
    assert result == identifier
    row, = session.rows
    assert row.id == identifier and row.company_id == company
    assert row.file_name == "Скан.pdf" and row.mime_type == "application/pdf"
    assert row.purpose == "data" and row.size == 8
    assert row.fingerprint == hashlib.sha256(b"document").hexdigest()
    assert Path(row.storage_path) == tmp_path / f"{identifier}.pdf"
    assert file_store.read(row) == b"document"
    session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_ops_default_name_and_mime_stay_compatible(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    session = Session()
    await ops_terms.store_file(session, uuid.uuid4(), None, None, b"scan")
    row, = session.rows
    assert row.file_name == "документ"
    assert row.mime_type == "application/octet-stream"
    assert row.purpose == "data"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [RuntimeError("synthetic flush error"), asyncio.CancelledError()])
async def test_failed_or_cancelled_flush_removes_only_new_file(tmp_path, monkeypatch, failure):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    previous = tmp_path / "previous.pdf"
    previous.write_bytes(b"old")
    session = Session(failure)
    with pytest.raises(type(failure)):
        await file_store.put_and_flush(session, uuid.uuid4(), b"new", file_name="new.pdf")
    assert previous.read_bytes() == b"old"
    assert list(tmp_path.iterdir()) == [previous]


@pytest.mark.asyncio
async def test_untrusted_filename_never_controls_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "storage"))
    session = Session()
    await ops_terms.store_file(session, uuid.uuid4(), "../../other.pdf", None, b"bytes")
    row, = session.rows
    assert Path(row.storage_path).parent == tmp_path / "storage"
    assert row.file_name == "../../other.pdf"
    assert file_store.read(row) == b"bytes"


def test_existing_put_remains_nonflushing_attachment_default(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    session = Session()
    row = file_store.put(session, uuid.uuid4(), b"attachment", file_name="a.pdf")
    assert row.purpose == "attachment"
    session.flush.assert_not_awaited()


@pytest.mark.asyncio
async def test_preallocated_id_collision_cannot_overwrite_or_delete_previous_file(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    identifier = uuid.uuid4()
    previous = tmp_path / f"{identifier}.pdf"
    previous.write_bytes(b"original")
    session = Session()
    with pytest.raises(FileExistsError):
        await file_store.put_and_flush(session, uuid.uuid4(), b"replacement",
                                       file_name="a.pdf", file_id=identifier)
    assert previous.read_bytes() == b"original"
    assert not session.rows
    session.flush.assert_not_awaited()


def test_invalid_preallocated_id_cannot_escape_storage(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        file_store.put(Session(), uuid.uuid4(), b"bytes", file_name="a.pdf", file_id="../escape")
    assert not list(tmp_path.iterdir())


def test_session_add_failure_removes_new_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    session = Session()
    def fail_add(row):
        raise RuntimeError("synthetic add failure")
    session.add = fail_add
    with pytest.raises(RuntimeError):
        file_store.put(session, uuid.uuid4(), b"bytes", file_name="a.pdf")
    assert not list(tmp_path.iterdir())
