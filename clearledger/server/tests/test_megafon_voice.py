"""Внешняя ВАТС: точная компания, права, одинаковые фильтры и честная история."""
import json
from datetime import datetime
import uuid
import pytest
from sqlalchemy import select, text
from app.models import App, AppCompanyLink, AuditEvent
from app.services import megafon_voice
from tests.test_voice_tokens import _h, _login, _user, _voice

pytestmark = pytest.mark.asyncio(loop_scope="session")
SCHEMA = "voice_provider_fixture"
RANGE = {"from": "2026-10-18T00:00:00Z", "to": "2026-10-19T00:00:00Z"}


@pytest.fixture
async def provider_db(db, monkeypatch):
    monkeypatch.setattr(megafon_voice, "_SCHEMA", SCHEMA)
    cid, other = await _voice(db, "rushydro"), await _voice(db, "gig")
    app = (await db.execute(select(App).where(App.code == "support"))).scalar_one()
    support_cid, other_support = uuid.uuid4(), uuid.uuid4()
    links = [AppCompanyLink(app_id=app.id, company_id=cid, external_company_id=str(support_cid)),
             AppCompanyLink(app_id=app.id, company_id=other, external_company_id=str(other_support))]
    db.add_all(links)
    await db.execute(text(f"CREATE SCHEMA {SCHEMA}"))
    await db.execute(text(f"""CREATE TABLE {SCHEMA}.call_records (
        id uuid PRIMARY KEY,company_id uuid,callid text,direction text,missed boolean,
        client_phone text,operator text,operator_login text,operator_user_id uuid,group_name text,
        via_number text,via_name text,started_at timestamptz,wait_sec int,duration_sec int,
        recording_url text,recording_external_id text,source text,thread_id uuid)"""))
    await db.execute(text(f"""CREATE TABLE {SCHEMA}.connectors (
        id uuid,company_id uuid,label text,endpoint text,status text,enabled boolean,
        last_sync_at timestamptz,last_error text,config jsonb,provider text,type text)"""))
    await db.execute(text(f"""INSERT INTO {SCHEMA}.connectors VALUES (
        :id,:cid,'Test VATs','https://example.invalid','active',true,now(),NULL,
        CAST(:config AS jsonb),'megafon','channel')"""), {"id": uuid.uuid4(), "cid": support_cid,
        "config": json.dumps({"line_context": {"public_number": "+78005550000", "forwarding_number": "+79990000001"}, "never_expose_secret": "private-config-value"})})
    ids = [uuid.uuid4() for _ in range(5)]
    for id_, company, direction, missed, name, group, at, source in [
        (ids[0], support_cid, "inbound", False, "Agent A", "Day", "2026-10-18T10:00:00Z", "megafon_api"),
        (ids[1], support_cid, "outbound", False, "Agent A", "Night", "2026-10-18T11:00:00Z", "megafon_api"),
        (ids[2], support_cid, "inbound", True, None, None, "2026-10-18T12:00:00Z", "megafon_api"),
        (ids[3], other_support, "inbound", False, "Foreign", "Day", "2026-10-18T10:00:00Z", "megafon_api"),
        (ids[4], support_cid, "inbound", False, "Other provider", "Day", "2026-10-18T10:00:00Z", "mango_api"),
    ]:
        await db.execute(text(f"""INSERT INTO {SCHEMA}.call_records VALUES (
            :id,:cid,:uid,:direction,:missed,'+79991234567',:name,'external-login',NULL,:group,
            '+79990000001','Test line',CAST(:at AS timestamptz),20,CASE WHEN :missed THEN 0 ELSE 60 END,
            'https://example.invalid/private-recording?secret=hidden',NULL,:source,NULL)"""),
            {"id": id_, "cid": company, "uid": str(id_), "direction": direction, "missed": missed,
             "name": name, "group": group, "at": datetime.fromisoformat(at.replace("Z", "+00:00")), "source": source})
    await db.commit()
    yield {"cid": cid, "support_cid": support_cid, "other": other, "ids": ids, "links": links}
    for link in links:
        await db.delete(link)
    await db.execute(text(f"DROP SCHEMA {SCHEMA} CASCADE"))
    await db.commit()


async def test_overview_filters_pagination_details_and_audit(client, db, provider_db):
    token = await _login(client, "admin@clearledger.ru", "admin123")
    headers = {**_h(token), "X-Company-Id": str(provider_db["cid"])}
    url = "/api/voice/megafon"
    r = await client.get(url, params={**RANGE, "page_size": 1}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["company_id"] == str(provider_db["cid"])
    assert body["summary"]["total"] == 3
    assert body["summary"]["answered"] == body["summary"]["missed"] == body["summary"]["outbound"] == 1
    assert body["connection"]["mode"] == "history"
    assert body["line"]["public_number"] == "+78005550000"
    assert body["line"]["origin_verified_per_call"] is False
    assert len(body["calls"]["items"]) == 1 and body["calls"]["total"] == 3
    assert r.headers["cache-control"] == "private, no-store"
    assert "private-recording" not in r.text and "private-config-value" not in r.text
    first = body["calls"]["items"][0]["id"]
    r = await client.get(url, params={**RANGE, "page_size": 1, "page": 2}, headers=headers)
    assert r.json()["calls"]["items"][0]["id"] != first
    for filters, count in [({"operator": "Agent A"}, 2), ({"group": "Day"}, 1),
                           ({"group": ""}, 1), ({"operator": ""}, 1),
                           ({"missed": "true"}, 1), ({"direction": "outbound"}, 1),
                           ({"search": "4567"}, 3), ({"operator": "' OR true --"}, 0),
                           ({"line": "+70000000000"}, 0)]:
        r = await client.get(url, params={**RANGE, **filters}, headers=headers)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["summary"]["total"] == data["calls"]["total"] == count
        assert sum(x["total"] for x in data["operators"]) == count
        assert sum(x["total"] for x in data["groups"]) == count
        assert len(data["filters"]["groups"]) == 3
    r = await client.get(url + "/calls/" + str(provider_db["ids"][0]), headers=headers)
    assert r.status_code == 200 and r.json()["call"]["operator_name"] == "Agent A"
    assert "recording_url" not in r.text
    for hidden in provider_db["ids"][3:]:
        assert (await client.get(url + "/calls/" + str(hidden), headers=headers)).status_code == 404
    audits = (await db.execute(select(AuditEvent).where(AuditEvent.action.like("voice.megafon.%")))).scalars().all()
    assert any(a.action == "voice.megafon.detail" for a in audits)
    assert all("4567" not in (a.details or "") for a in audits)


async def test_guards_and_input_validation(client, db, provider_db):
    tag = uuid.uuid4().hex[:6]
    reader = await _user(client, f"voice-reader-{tag}@test.ru", "rushydro", "user")
    admin = await _user(client, f"voice-admin-{tag}@test.ru", "rushydro", "admin")
    platform = await _login(client, "admin@clearledger.ru", "admin123")
    cid = provider_db["cid"]
    headers = {**_h(admin), "X-Company-Id": str(cid)}
    url = "/api/voice/megafon"
    assert (await client.get(url, params=RANGE)).status_code == 401
    assert (await client.get(url, params=RANGE, headers={**_h(reader), "X-Company-Id": str(cid)})).status_code == 403
    assert (await client.get(url, params=RANGE, headers={**_h(admin), "X-Company-Id": str(provider_db["other"])})).status_code == 403
    assert (await client.get(url, params=RANGE, headers=headers)).status_code == 200
    for bad in [{"search": "12"}, {"page": 0}, {"direction": "fake"},
                {"from": "2026-10-20T00:00:00Z"}, {"from": "2025-01-01T00:00:00Z"},
                {"from": "2026-10-18T00:00:00"}]:
        assert (await client.get(url, params={**RANGE, **bad}, headers=headers)).status_code == 422
    assert (await client.post(url, json={}, headers=headers)).status_code == 405
    r = await client.get(url, params={"from": "2026-10-18T10:00:00Z", "to": "2026-10-18T11:00:00Z"}, headers=headers)
    assert r.json()["summary"]["total"] == 1
    await _voice(db, "rushydro", False)
    assert (await client.get(url, params=RANGE, headers={**_h(platform), "X-Company-Id": str(cid)})).status_code == 403
    await _voice(db, "rushydro")
    await db.delete(provider_db["links"].pop(0))
    await db.commit()
    assert (await client.get(url, params=RANGE, headers=headers)).status_code == 404
