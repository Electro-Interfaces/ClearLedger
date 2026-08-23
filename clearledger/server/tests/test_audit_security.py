from httpx import AsyncClient
from tests.helpers import seed_company_id


async def test_client_audit_cannot_forge_actor_or_system_action(auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    company_id = seed_company_id(me)

    forged = await auth_client.post("/api/audit", json={
        "companyId": company_id,
        "action": "created",
        "userId": "00000000-0000-0000-0000-000000000001",
        "userName": "Чужой администратор",
    })
    assert forged.status_code == 201, forged.text
    row = forged.json()
    assert row["user_id"] == me["id"]
    assert row["user_name"] != "Чужой администратор"
    assert row["action"] == "client.created"

    system_action = await auth_client.post("/api/audit", json={
        "companyId": company_id,
        "action": "doc.register",
    })
    assert system_action.status_code == 422
