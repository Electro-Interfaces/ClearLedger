import uuid
from datetime import datetime, timezone
import httpx, pytest
from app.services.management_config import ManagementConfig, RemoteSource
from app.services import management_overview as service
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import base64

@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_original_links_policy_preserves_records_and_identity(monkeypatch, enabled):
    local, remote, company = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = base64.b64encode(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())).decode()
    config = ManagementConfig(code="desk", signing_private_key_b64=private)
    source = RemoteSource(code="office-rti", receiver_code="office", name="Аудит · РТИ", base_url="https://office.example.invalid", company_id=company, company_name="РТИ", original_links_enabled=enabled, grants=[{"id":"mag-rti","local_user_id":local,"local_company_id":uuid.uuid4(),"remote_user_id":remote,"kinds":["tasks"]}])
    record_id = str(uuid.uuid4())
    payload = {"fetched_at":datetime.now(timezone.utc).isoformat(),"items":[{"source_id":record_id,"kind":"tasks","title":"Разрешённая задача"}],"truncated":False}
    real = httpx.AsyncClient
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kw: real(**kw,transport=httpx.MockTransport(lambda req:httpx.Response(200,json=payload))))
    items,status = await service.fetch_remote(config,source,source.grants[0],"tasks",{"kind":"tasks"},100)
    assert status.state == "ok" and len(items) == 1
    assert items[0].title == "Разрешённая задача"
    assert items[0].source.company_id == str(company)
    assert items[0].id == f"office-rti:{company}:tasks:{record_id}"
    if enabled:
        assert items[0].href == f"https://office.example.invalid/docs/work?company={company}&view=errands&task={record_id}"
    else:
        assert items[0].href == ""

def test_original_links_enabled_by_default():
    source = RemoteSource(code="office",name="Аудит",base_url="https://office.example.invalid",company_id=uuid.uuid4(),company_name="РТИ")
    assert source.original_links_enabled is True
