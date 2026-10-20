"""SQL leaf строгого выбора: без рекурсии и склейки однономерных клиентов."""
import uuid
from datetime import datetime, timedelta

import pytest
from app.models import ChargeSession, CorporateClient

from tests.test_voice_core import _company, _key, _seed_caller, _voice
from tests.test_voice_support_context import support_map

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def test_strict_source_candidates_selection_and_company_isolation(client, db):
    own = await _company(db, "gig")
    other = await _company(db, "rushydro")
    await _voice(db, own.id, True)
    key = await _key(db, own.id, ["voice.identify"])
    phone = f"+7900{uuid.uuid4().int % 10**7:07d}"
    caller = await _seed_caller(db, own, phone)
    foreign = await _seed_caller(db, other, phone)
    db.add(CorporateClient(company_id=own.id, name="Вымышленная организация", phone=phone))
    await db.commit()
    async with support_map(db, own.id) as (_app, support_id):
        body = {"supportCompanyId": support_id, "phone": phone, "detail": True,
                "limit": 1, "strictSelection": True}
        async def read():
            return await client.post("/api/eco/support/customer-context", json=body,
                                     headers={"X-Cloud-API-Key": key})
        r = await read()
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["identityState"] == "ambiguous" and len(data["candidates"]) > 1
        assert data["caller"] is None and data["corePartyRef"] is None and data["ezs"] is None
        assert data["historyIdentity"] == "phone"
        assert data["details"]["total"] == 3 and len(data["details"]["sessions"]) == 1
        count = data["counts"]["totalSessions"]
        assert count["value"] == 3 and count["identity"] == "phone" and count["complete"]
        assert count["period"]["timezone"] == "UTC" and count["period"]["from"] is None
        assert data["details"]["hasMore"] and data["details"]["nextCursor"]
        # Импорт старой сессии после начала обхода не меняет snapshot страниц.
        db.add(ChargeSession(company_id=own.id, session_ext_id="late-" + uuid.uuid4().hex,
                             started_at=datetime.now() - timedelta(days=20), user_id=phone,
                             result="Complete", energy_kwh=5))
        await db.commit()
        seen = [data["details"]["sessions"][0]["session_ext_id"]]
        cursor = data["details"]["nextCursor"]
        while cursor:
            body["cursor"] = cursor
            r = await read()
            assert r.status_code == 200, r.text
            page = r.json()["details"]
            assert page["total"] == 3
            seen.extend(s["session_ext_id"] for s in page["sessions"])
            cursor = page["nextCursor"]
        assert len(seen) == len(set(seen)) == 3
        body["cursor"] = data["details"]["nextCursor"]
        body["ref"] = "ezs:" + caller["ext"]
        r = await read()
        assert r.status_code == 409, r.text
        body.pop("cursor")
        assert foreign["ext"] not in {c["ref"].removeprefix("ezs:") for c in data["candidates"]}
        body["ref"] = "ezs:" + foreign["ext"]
        r = await read()
        assert r.status_code == 404, r.text
        body["ref"] = "ezs:" + caller["ext"]
        r = await read()
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["identityState"] == "operator_selected" and data["corePartyRef"] == body["ref"]
        assert data["historyIdentity"] == "core_person"
        assert data["counts"]["totalSessions"]["identity"] == "core_person"
        assert "support" not in data["counts"]["totalSessions"]["source"]
        body["supportCompanyId"] = str(uuid.uuid4())
        r = await read()
        assert r.status_code == 403
