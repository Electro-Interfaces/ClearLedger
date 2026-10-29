"""The remaining photo upload uses the shared transaction-owned SourceFile writer."""
import hashlib
from pathlib import Path
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.models import Company, ServiceLocation, SourceFile, StationCheck

pytestmark = pytest.mark.asyncio(loop_scope="session")


@pytest_asyncio.fixture(loop_scope="session")
async def station(db, tmp_path, monkeypatch):
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path))
    suffix = uuid.uuid4().hex
    company = Company(name="Synthetic photo company", slug="photo-" + suffix[:12], profile_id="energy")
    db.add(company); await db.flush()
    point = ServiceLocation(id="photo-" + suffix[:20], company_id=company.id,
        name="Synthetic station", code="PHOTO-1", type="ev_charging")
    db.add(point); await db.commit()
    return company, point, tmp_path


async def test_photo_check_commits_bytes_and_original_metadata(auth_client, db, station):
    company, point, directory = station
    response = await auth_client.post("/api/ops/station-check/" + point.id,
        params={"company_id": str(company.id), "item_key": "info.price"},
        files={"file": ("camera.jpg", b"synthetic photo bytes", "image/jpeg")})
    assert response.status_code == 201, response.text
    check = await db.get(StationCheck, uuid.UUID(response.json()["id"]))
    stored = await db.get(SourceFile, check.file_id)
    assert stored.company_id == company.id and stored.purpose == "attachment"
    assert stored.file_name == "camera.jpg" and stored.mime_type == "image/jpeg"
    assert stored.fingerprint == hashlib.sha256(b"synthetic photo bytes").hexdigest()
    assert Path(stored.storage_path).parent == directory
    assert Path(stored.storage_path).read_bytes() == b"synthetic photo bytes"


async def test_rejected_domain_check_rolls_back_photo_row_and_bytes(auth_client, db, station):
    company, point, directory = station
    response = await auth_client.post("/api/ops/station-check/" + point.id,
        params={"company_id": str(company.id), "item_key": "invalid.synthetic.item"},
        files={"file": ("camera.jpg", b"synthetic rejected photo", "image/jpeg")})
    assert response.status_code == 400, response.text
    assert not list(directory.iterdir())
    assert not (await db.scalars(select(SourceFile).where(SourceFile.company_id == company.id))).all()
    assert not (await db.scalars(select(StationCheck).where(StationCheck.company_id == company.id))).all()
