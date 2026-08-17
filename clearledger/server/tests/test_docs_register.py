"""«Дело»: регистрация, нумерация, файлы, согласование.

Ловим то, что молча ломается и дорого стоит потом: пропуск в журнале
регистрации, два документа под одним номером, вторая редакция от повторной
загрузки того же файла, виза, поставленная не тем человеком, и срок хранения,
пересчитанный задним числом.
"""
import asyncio
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DocCard, DocShareLink, User, UserCompany
from app.routers import docs_router

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _company(client: AsyncClient) -> str:
    me = (await client.get("/api/auth/me")).json()
    assert me["companies"], "сид-суперадмин не состоит ни в одной компании"
    return me["companies"][0]["id"]


async def _kinds(client: AsyncClient, cid: str) -> list[dict]:
    r = await client.post(f"/api/docs/kinds/starter?company_id={cid}")
    assert r.status_code in (200, 201), r.text
    r = await client.get("/api/docs/kinds", params={"company_id": cid})
    return r.json()["kinds"]


async def test_регистрация_выдаёт_номера_подряд(auth_client: AsyncClient):
    cid = await _company(auth_client)
    kinds = await _kinds(auth_client, cid)
    incoming = next(k for k in kinds if k["code"] == "doc_in")

    numbers = []
    for i in range(3):
        r = await auth_client.post("/api/docs", json={
            "company_id": cid, "kind_id": incoming["id"], "title": f"Письмо {i}"})
        assert r.status_code == 201, r.text
        doc = r.json()
        # У черновика номера нет: это и отличает его от зарегистрированного.
        assert doc["reg_number"] is None and doc["status"] == "draft"

        r = await auth_client.post(f"/api/docs/{doc['id']}/register",
                                   json={"company_id": cid})
        assert r.status_code == 200, r.text
        numbers.append(r.json()["reg_number"])

    tails = [int(n.rsplit("-", 1)[1]) for n in numbers]
    assert tails == list(range(tails[0], tails[0] + 3)), f"пропуск в нумерации: {numbers}"


async def test_повторная_регистрация_не_проходит(auth_client: AsyncClient):
    cid = await _company(auth_client)
    kinds = await _kinds(auth_client, cid)
    order = next(k for k in kinds if k["code"] == "order")

    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": order["id"], "title": "Приказ"})).json()
    r1 = await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    assert r1.status_code == 200
    r2 = await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    # Номер, однажды выданный, остаётся за документом навсегда.
    assert r2.status_code == 409, r2.text


async def test_занятый_номер_вручную_не_принимается(auth_client: AsyncClient):
    cid = await _company(auth_client)
    kinds = await _kinds(auth_client, cid)
    memo = next(k for k in kinds if k["code"] == "memo")

    first = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": memo["id"], "title": "Записка 1"})).json()
    taken = (await auth_client.post(f"/api/docs/{first['id']}/register",
                                    json={"company_id": cid})).json()["reg_number"]

    second = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": memo["id"], "title": "Записка 2"})).json()
    r = await auth_client.post(f"/api/docs/{second['id']}/register", json={
        "company_id": cid, "reg_number": taken,
        "manual_reason": "Перенос прежнего журнала"})
    assert r.status_code == 409, "два документа получили один номер"


async def test_параллельные_регистрации_не_дают_коллизии(auth_client: AsyncClient):
    cid = await _company(auth_client)
    kinds = await _kinds(auth_client, cid)
    out = next(k for k in kinds if k["code"] == "doc_out")

    docs = []
    for i in range(5):
        docs.append((await auth_client.post("/api/docs", json={
            "company_id": cid, "kind_id": out["id"], "title": f"Исходящее {i}"})).json())

    results = await asyncio.gather(*[
        auth_client.post(f"/api/docs/{d['id']}/register", json={"company_id": cid})
        for d in docs])
    numbers = [r.json()["reg_number"] for r in results if r.status_code == 200]
    assert len(numbers) == 5, [r.status_code for r in results]
    assert len(set(numbers)) == 5, f"номера совпали: {numbers}"


async def test_тот_же_файл_второй_редакции_не_создаёт(auth_client: AsyncClient):
    cid = await _company(auth_client)
    kinds = await _kinds(auth_client, cid)
    order = next(k for k in kinds if k["code"] == "order")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": order["id"], "title": "Приказ с файлом"})).json()

    files = {"file": ("prikaz.pdf", b"%PDF-1.4\ntext\n", "application/pdf")}
    r1 = await auth_client.post(f"/api/docs/{doc['id']}/versions",
                                params={"company_id": cid, "role": "body"}, files=files)
    assert r1.status_code == 201, r1.text
    r2 = await auth_client.post(f"/api/docs/{doc['id']}/versions",
                                params={"company_id": cid, "role": "body"}, files=files)
    assert r2.json().get("duplicate"), "повторная загрузка того же файла дала редакцию"

    bad = {"file": ("script.exe", b"MZ", "application/x-msdownload")}
    r3 = await auth_client.post(f"/api/docs/{doc['id']}/versions",
                                params={"company_id": cid}, files=bad)
    assert r3.status_code == 415, "принят недопустимый тип файла"


async def test_отказ_возвращает_документ_и_требует_причину(auth_client: AsyncClient):
    cid = await _company(auth_client)
    me = (await auth_client.get("/api/auth/me")).json()
    kinds = await _kinds(auth_client, cid)
    memo = next(k for k in kinds if k["code"] == "memo")

    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": memo["id"], "title": "Записка на согласование"})).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})

    route = [{"code": "chief", "name": "Руководитель", "mode": "serial", "quorum": "all",
              "actors": [{"by": "user", "ref": me["id"]}]}]
    r = await auth_client.post(f"/api/docs/{doc['id']}/approval/start",
                               json={"company_id": cid, "route": route})
    assert r.status_code == 201, r.text

    mine = (await auth_client.get("/api/docs/approvals/mine",
                                  params={"company_id": cid})).json()["approvals"]
    row = next(a for a in mine if a["doc_id"] == doc["id"])

    # Возврат без причины бессмыслен: автор не поймёт, что править.
    r = await auth_client.post(f"/api/docs/approvals/{row['id']}",
                               json={"company_id": cid, "approved": False})
    assert r.status_code == 400

    r = await auth_client.post(f"/api/docs/approvals/{row['id']}", json={
        "company_id": cid, "approved": False, "comment": "Нет обоснования суммы"})
    assert r.status_code == 200 and r.json()["returned"]

    card = (await auth_client.get(f"/api/docs/{doc['id']}",
                                  params={"company_id": cid})).json()
    assert card["status"] == "registered", "зарегистрированный документ потерял состояние"
    assert card["reg_number"], "номер потерялся при возврате"
    assert card["approval_status"] == "rejected"


async def test_последовательный_маршрут_не_открывает_будущий_шаг(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    me = (await auth_client.get("/api/auth/me")).json()
    memo = next(k for k in await _kinds(auth_client, cid) if k["code"] == "memo")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": memo["id"], "title": "Два шага",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    route = [
        {"code": "legal", "name": "Юрист", "mode": "serial", "quorum": "all",
         "actors": [{"by": "user", "ref": me["id"]}]},
        {"code": "director", "name": "Директор", "mode": "serial", "quorum": "all",
         "actors": [{"by": "user", "ref": me["id"]}]},
    ]
    started = await auth_client.post(f"/api/docs/{doc['id']}/approval/start", json={
        "company_id": cid, "route": route,
    })
    assert started.status_code == 201, started.text
    mine = (await auth_client.get("/api/docs/approvals/mine",
                                  params={"company_id": cid})).json()["approvals"]
    active = [item for item in mine if item["doc_id"] == doc["id"]]
    assert [item["step_name"] for item in active] == ["Юрист"]

    decided = await auth_client.post(f"/api/docs/approvals/{active[0]['id']}", json={
        "company_id": cid, "approved": True,
    })
    assert decided.status_code == 200, decided.text
    mine = (await auth_client.get("/api/docs/approvals/mine",
                                  params={"company_id": cid})).json()["approvals"]
    active = [item for item in mine if item["doc_id"] == doc["id"]]
    assert [item["step_name"] for item in active] == ["Директор"]


async def test_кворум_any_закрывает_параллельный_шаг(
        auth_client: AsyncClient, db: AsyncSession):
    cid = await _company(auth_client)
    me = (await auth_client.get("/api/auth/me")).json()
    other = User(
        company_id=uuid.UUID(cid), email=f"approval-{uuid.uuid4().hex}@example.org",
        name="Второй согласующий", password_hash="!",
    )
    db.add(other)
    await db.flush()
    db.add(UserCompany(user_id=other.id, company_id=uuid.UUID(cid),
                       role="user", modules=["docs"]))
    await db.commit()
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "doc_out")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Кворум один из двух",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    started = await auth_client.post(f"/api/docs/{doc['id']}/approval/start", json={
        "company_id": cid,
        "route": [{
            "code": "owners", "name": "Владельцы", "mode": "parallel", "quorum": "any",
            "actors": [{"by": "user", "ref": me["id"]},
                       {"by": "user", "ref": str(other.id)}],
        }],
    })
    assert started.status_code == 201, started.text
    mine = (await auth_client.get("/api/docs/approvals/mine",
                                  params={"company_id": cid})).json()["approvals"]
    own = next(item for item in mine if item["doc_id"] == doc["id"])
    decided = await auth_client.post(f"/api/docs/approvals/{own['id']}", json={
        "company_id": cid, "approved": True,
    })
    assert decided.status_code == 200 and decided.json()["status"] == "approved"
    card = (await auth_client.get(f"/api/docs/{doc['id']}",
                                  params={"company_id": cid})).json()
    statuses = {row["status"] for row in card["approval"]["rows"]
                if row["round"] == card["approval_round"]}
    assert statuses == {"approved", "skipped"}


async def test_пакет_согласования_фиксирует_файл_и_блокирует_новую_редакцию(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    me = (await auth_client.get("/api/auth/me")).json()
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "order")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Зафиксированный файл",
    })).json()
    body = b"%PDF-1.4\napproval-body\n"
    uploaded = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("body.pdf", body, "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    started = await auth_client.post(f"/api/docs/{doc['id']}/approval/start", json={
        "company_id": cid,
        "route": [{"code": "one", "name": "Один", "mode": "serial", "quorum": "all",
                   "actors": [{"by": "user", "ref": me["id"]}]}],
    })
    assert started.status_code == 201 and len(started.json()["snapshot_sha256"]) == 64
    card = (await auth_client.get(f"/api/docs/{doc['id']}",
                                  params={"company_id": cid})).json()
    assert card["approval"]["snapshot"]["files"][0]["sha256"] == hashlib.sha256(
        body).hexdigest()

    blocked = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("body-v2.pdf", b"%PDF-1.4\nchanged\n", "application/pdf")})
    assert blocked.status_code == 409
    cancelled = await auth_client.post(f"/api/docs/{doc['id']}/approval/cancel", json={
        "company_id": cid, "reason": "Нужна новая редакция",
    })
    assert cancelled.status_code == 200, cancelled.text


async def test_обязательный_реквизит_проверяется_при_регистрации(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    code = f"required_{uuid.uuid4().hex[:8]}"
    kind = await auth_client.post("/api/docs/kinds", json={
        "company_id": cid, "code": code, "name": "Документ с суммой",
        "fields": [{"code": "amount", "label": "Сумма", "type": "number",
                    "required": True}],
    })
    assert kind.status_code == 201, kind.text
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind.json()["id"], "title": "Без суммы",
    })).json()
    missing = await auth_client.post(f"/api/docs/{doc['id']}/register",
                                     json={"company_id": cid})
    assert missing.status_code == 409
    wrong = await auth_client.post(f"/api/docs/{doc['id']}/action", json={
        "company_id": cid, "attrs": {"amount": "сто"},
    })
    assert wrong.status_code == 400
    fixed = await auth_client.post(f"/api/docs/{doc['id']}/action", json={
        "company_id": cid, "attrs": {"amount": 100},
    })
    assert fixed.status_code == 200, fixed.text
    registered = await auth_client.post(f"/api/docs/{doc['id']}/register",
                                        json={"company_id": cid})
    assert registered.status_code == 200, registered.text


async def test_ссылка_наружу_только_после_регистрации(auth_client: AsyncClient):
    cid = await _company(auth_client)
    kinds = await _kinds(auth_client, cid)
    out = next(k for k in kinds if k["code"] == "doc_out")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": out["id"], "title": "Акт сверки"})).json()

    r = await auth_client.post(f"/api/docs/{doc['id']}/share",
                               json={"company_id": cid, "days": 7})
    assert r.status_code == 409, "черновик ушёл наружу"

    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    r = await auth_client.post(f"/api/docs/{doc['id']}/share", json={
        "company_id": cid, "days": 7, "recipient_name": "Иванов И. И."})
    assert r.status_code == 201, r.text
    token = r.json()["token"]

    # Ссылка работает без авторизации — это её смысл.
    anon = AsyncClient(transport=auth_client._transport, base_url=str(auth_client.base_url))
    try:
        page = await anon.get(f"/api/doc-share/{token}")
        assert page.status_code == 200 and page.json()["reg_number"]
        assert page.headers["cache-control"] == "no-store"
        assert page.headers["x-robots-tag"] == "noindex, nofollow"

        ack = await anon.post(f"/api/doc-share/{token}/ack", json={"name": "Иванов И. И."})
        assert ack.status_code == 200
        again = await anon.post(f"/api/doc-share/{token}/ack", json={"name": "Другой"})
        assert again.json().get("repeated"), "повторное подтверждение переписало отметку"

        links = (await auth_client.get(f"/api/docs/{doc['id']}/share",
                                       params={"company_id": cid})).json()["links"]
        await auth_client.post(f"/api/docs/share/{links[0]['id']}/revoke",
                               params={"company_id": cid})
        gone = await anon.get(f"/api/doc-share/{token}")
        assert gone.status_code == 404, "отозванная ссылка продолжает открываться"
        assert gone.headers["cache-control"] == "no-store"
    finally:
        await anon.aclose()


async def test_юрлица_имеют_свои_журналы_и_чужое_юрлицо_не_принимается(
        auth_client: AsyncClient):
    me = (await auth_client.get("/api/auth/me")).json()
    cid = me["companies"][0]["id"]
    other_cid = me["companies"][1]["id"]
    suffix = uuid.uuid4().hex[:8]
    inn_tail = str(uuid.uuid4().int)[:7]

    async def make_org(company_id: str, index: int) -> dict:
        response = await auth_client.post("/api/references/organizations", json={
            "company_id": company_id, "name": f"Юрлицо {suffix}-{index}",
            "inn": f"77{index}{inn_tail}"[:10], "prefix": f"Ю{index}",
        })
        assert response.status_code == 201, response.text
        return response.json()

    first_org = await make_org(cid, 1)
    second_org = await make_org(cid, 2)
    foreign_org = await make_org(other_cid, 3)
    kind_response = await auth_client.post("/api/docs/kinds", json={
        "company_id": cid, "code": f"org_{suffix}", "name": "Журнал по юрлицам",
        "family": "internal", "direction": "none", "number_prefix": "ОРГ",
        "number_template": "{prefix}-{yyyy}-{n:04d}",
        "number_scope": "kind_org_year", "fields": [], "route": [],
    })
    assert kind_response.status_code == 201, kind_response.text
    kind = kind_response.json()

    numbers = []
    for organization in (first_org, second_org):
        created = await auth_client.post("/api/docs", json={
            "company_id": cid, "kind_id": kind["id"],
            "organization_id": organization["id"], "title": f"Документ {organization['name']}",
        })
        assert created.status_code == 201, created.text
        registered = await auth_client.post(
            f"/api/docs/{created.json()['id']}/register", json={"company_id": cid})
        assert registered.status_code == 200, registered.text
        numbers.append(registered.json()["reg_number"])
    assert numbers[0] == numbers[1], "независимые журналы юрлиц не начали с одного номера"

    without_org = await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Не выбран журнал",
    })
    blocked = await auth_client.post(
        f"/api/docs/{without_org.json()['id']}/register", json={"company_id": cid})
    assert blocked.status_code == 409

    rejected = await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"],
        "organization_id": foreign_org["id"], "title": "Чужое юрлицо",
    })
    assert rejected.status_code == 400


async def test_регистрация_проверяет_дату_состояние_и_ручной_перенос(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "memo")

    future = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Будущая дата",
    })).json()
    response = await auth_client.post(f"/api/docs/{future['id']}/register", json={
        "company_id": cid, "reg_date": "2999-01-01",
    })
    assert response.status_code == 400

    blank = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Пустой номер",
    })).json()
    response = await auth_client.post(f"/api/docs/{blank['id']}/register", json={
        "company_id": cid, "reg_number": "   ", "manual_reason": "Перенос",
    })
    assert response.status_code == 400

    cancelled = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Отменён до регистрации",
    })).json()
    await auth_client.post(f"/api/docs/{cancelled['id']}/action", json={
        "company_id": cid, "status": "cancelled", "note": "Создан ошибочно",
    })
    response = await auth_client.post(f"/api/docs/{cancelled['id']}/register",
                                      json={"company_id": cid})
    assert response.status_code == 409


async def test_публичная_проверка_не_раскрывает_карточку_и_видит_отмену(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "doc_out")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Секретный заголовок",
        "summary": "Секретное содержание", "counterparty_name": "Секретный получатель",
    })).json()
    content = b"%PDF-1.4\nverified-version\n"
    uploaded = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("secret-name.pdf", content, "application/pdf")})
    assert uploaded.status_code == 201, uploaded.text
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    link = await auth_client.post(f"/api/docs/{doc['id']}/verification",
                                  params={"company_id": cid})
    assert link.status_code == 200, link.text
    token = link.json()["code"]

    anon = AsyncClient(transport=auth_client._transport, base_url=str(auth_client.base_url))
    try:
        checked = await anon.get(f"/api/doc-share/verify/{token}")
        assert checked.status_code == 200, checked.text
        data = checked.json()
        assert data["record_status"] == "registered"
        assert data["files"][0]["sha256"] == hashlib.sha256(content).hexdigest()
        forbidden = {"id", "title", "summary", "counterparty_name", "file_name"}
        assert not forbidden.intersection(data)
        assert all("file_name" not in item for item in data["files"])
        assert checked.headers["cache-control"] == "no-store"

        printed = await auth_client.get(f"/api/docs/{doc['id']}/print",
                                        params={"company_id": cid})
        assert printed.status_code == 200
        assert f"/doc-verify/{token}" in printed.text
        assert hashlib.sha256(content).hexdigest() in printed.text

        cancelled = await auth_client.post(f"/api/docs/{doc['id']}/action", json={
            "company_id": cid, "status": "cancelled", "note": "Документ отозван",
        })
        assert cancelled.status_code == 200, cancelled.text
        checked = await anon.get(f"/api/doc-share/verify/{token}")
        assert checked.json()["record_status"] == "cancelled"
    finally:
        await anon.aclose()


async def test_ссылка_получателя_фиксирует_редакцию(auth_client: AsyncClient):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "doc_out")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Фиксация редакции",
    })).json()
    first = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("first.pdf", b"%PDF-1.4\nfirst\n", "application/pdf")})
    assert first.status_code == 201, first.text
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    share = await auth_client.post(f"/api/docs/{doc['id']}/share", json={
        "company_id": cid, "days": 7,
    })
    token = share.json()["token"]
    second = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("second.pdf", b"%PDF-1.4\nsecond\n", "application/pdf")})
    assert second.status_code == 201, second.text
    changed = await auth_client.post(f"/api/docs/{doc['id']}/action", json={
        "company_id": cid, "title": "Заголовок после отправки",
        "summary": "Содержание после отправки",
    })
    assert changed.status_code == 200, changed.text

    anon = AsyncClient(transport=auth_client._transport, base_url=str(auth_client.base_url))
    try:
        shared = await anon.get(f"/api/doc-share/{token}")
        assert [item["id"] for item in shared.json()["files"]] == [first.json()["id"]]
        assert shared.json()["title"] == "Фиксация редакции"
        assert shared.json()["summary"] is None
        blocked = await anon.get(f"/api/doc-share/{token}/file/{second.json()['id']}")
        assert blocked.status_code == 404
        downloaded = await anon.get(f"/api/doc-share/{token}/file/{first.json()['id']}")
        assert downloaded.status_code == 200
        assert downloaded.headers["cache-control"] == "no-store"
    finally:
        await anon.aclose()


async def test_параллельный_выпуск_оставляет_один_код_проверки(
        auth_client: AsyncClient, db: AsyncSession):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "memo")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Один код проверки",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    stored = await db.get(DocCard, uuid.UUID(doc["id"]))
    stored.verify_token = None
    await db.commit()

    responses = await asyncio.gather(*[
        auth_client.post(f"/api/docs/{doc['id']}/verification", params={"company_id": cid})
        for _ in range(2)
    ])
    assert all(response.status_code == 200 for response in responses)
    assert len({response.json()["code"] for response in responses}) == 1


async def test_параллельное_подтверждение_не_переписывает_получателя(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "doc_out")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Одно подтверждение",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    share = (await auth_client.post(f"/api/docs/{doc['id']}/share", json={
        "company_id": cid, "days": 7,
    })).json()

    first = AsyncClient(transport=auth_client._transport, base_url=str(auth_client.base_url))
    second = AsyncClient(transport=auth_client._transport, base_url=str(auth_client.base_url))
    try:
        responses = await asyncio.gather(
            first.post(f"/api/doc-share/{share['token']}/ack", json={"name": "Первый"}),
            second.post(f"/api/doc-share/{share['token']}/ack", json={"name": "Второй"}),
        )
        assert all(response.status_code == 200 for response in responses)
        assert sum(not response.json().get("repeated", False) for response in responses) == 1
        links = (await auth_client.get(f"/api/docs/{doc['id']}/share",
                                       params={"company_id": cid})).json()["links"]
        saved = next(link for link in links if link["id"] == share["id"])
        assert saved["acknowledged_by"] in {"Первый", "Второй"}
    finally:
        await first.aclose()
        await second.aclose()


async def test_закрытая_проверка_и_ошибки_не_раскрывают_реквизиты(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "memo")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Закрытая запись",
        "confidentiality": "private",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    issued = await auth_client.post(f"/api/docs/{doc['id']}/verification",
                                    params={"company_id": cid})

    anon = AsyncClient(transport=auth_client._transport, base_url=str(auth_client.base_url))
    try:
        checked = await anon.get(f"/api/doc-share/verify/{issued.json()['code']}")
        assert checked.status_code == 200
        assert checked.json()["record_status"] == "restricted"
        assert not {"organization", "kind", "reg_number", "files"}.intersection(checked.json())
        missing = await anon.get("/api/doc-share/verify/unknown-token")
        assert missing.status_code == 404
        assert missing.headers["cache-control"] == "no-store"
        assert missing.headers["x-robots-tag"] == "noindex, nofollow"
    finally:
        await anon.aclose()


async def test_старая_ссылка_без_снимка_не_открывается(
        auth_client: AsyncClient, db: AsyncSession):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "doc_out")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Старая ссылка",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid})
    token = f"legacy-{uuid.uuid4().hex}"
    db.add(DocShareLink(
        company_id=uuid.UUID(cid), doc_id=uuid.UUID(doc["id"]), token=token,
        expires_at=datetime.now(timezone.utc) + timedelta(days=1),
    ))
    await db.commit()

    anon = AsyncClient(transport=auth_client._transport, base_url=str(auth_client.base_url))
    try:
        response = await anon.get(f"/api/doc-share/{token}")
        assert response.status_code == 404
    finally:
        await anon.aclose()


async def test_удаление_текущей_редакции_возвращает_предыдущую(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "memo")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Возврат редакции",
    })).json()
    first = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("first.pdf", b"%PDF-1.4\nfirst\n", "application/pdf")})
    second = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("second.pdf", b"%PDF-1.4\nsecond\n", "application/pdf")})
    removed = await auth_client.post(
        f"/api/docs/versions/{second.json()['id']}/tombstone",
        json={"company_id": cid, "reason": "Ошибочная редакция"})
    assert removed.status_code == 200, removed.text
    repeated = await auth_client.post(
        f"/api/docs/versions/{second.json()['id']}/tombstone",
        json={"company_id": cid, "reason": "Другая причина"})
    assert repeated.status_code == 409
    card = (await auth_client.get(f"/api/docs/{doc['id']}",
                                  params={"company_id": cid})).json()
    assert card["current_revision"] == first.json()["revision"]
    assert next(v for v in card["versions"] if v["id"] == first.json()["id"])["is_current"]

    third = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("third.pdf", b"%PDF-1.4\nthird\n", "application/pdf")})
    assert third.status_code == 201 and third.json()["revision"] == 3
    removed = await auth_client.post(
        f"/api/docs/versions/{third.json()['id']}/tombstone",
        json={"company_id": cid, "reason": "Новая редакция не нужна"})
    assert removed.status_code == 200, removed.text
    removed = await auth_client.post(
        f"/api/docs/versions/{first.json()['id']}/tombstone",
        json={"company_id": cid, "reason": "Основной файл не нужен"})
    assert removed.status_code == 200, removed.text
    card = (await auth_client.get(f"/api/docs/{doc['id']}",
                                  params={"company_id": cid})).json()
    assert card["current_revision"] == 0 and not card["has_files"]


async def test_загрузка_и_вывод_редакции_не_дают_две_текущие(
        auth_client: AsyncClient):
    cid = await _company(auth_client)
    kind = next(k for k in await _kinds(auth_client, cid) if k["code"] == "memo")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid, "kind_id": kind["id"], "title": "Гонка редакций",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("first.pdf", b"%PDF-1.4\nrace-first\n", "application/pdf")})
    second = await auth_client.post(f"/api/docs/{doc['id']}/versions",
        params={"company_id": cid, "role": "body"},
        files={"file": ("second.pdf", b"%PDF-1.4\nrace-second\n", "application/pdf")})

    uploaded, removed = await asyncio.gather(
        auth_client.post(f"/api/docs/{doc['id']}/versions",
            params={"company_id": cid, "role": "body"},
            files={"file": ("third.pdf", b"%PDF-1.4\nrace-third\n", "application/pdf")}),
        auth_client.post(f"/api/docs/versions/{second.json()['id']}/tombstone",
            json={"company_id": cid, "reason": "Параллельный вывод"}),
    )
    assert uploaded.status_code == 201 and removed.status_code == 200
    card = (await auth_client.get(f"/api/docs/{doc['id']}",
                                  params={"company_id": cid})).json()
    current = [version for version in card["versions"]
               if version["role"] == "body" and version["is_current"]]
    assert len(current) == 1 and current[0]["revision"] == 3
    assert card["current_revision"] == 3


async def test_читатель_не_выпускает_публичный_код(
        auth_client: AsyncClient, db: AsyncSession):
    cid_raw = await _company(auth_client)
    cid = uuid.UUID(cid_raw)
    kind = next(k for k in await _kinds(auth_client, cid_raw) if k["code"] == "memo")
    doc = (await auth_client.post("/api/docs", json={
        "company_id": cid_raw, "kind_id": kind["id"], "title": "Только чтение",
    })).json()
    await auth_client.post(f"/api/docs/{doc['id']}/register", json={"company_id": cid_raw})
    reader = User(
        company_id=cid, email=f"reader-{uuid.uuid4().hex}@example.org",
        name="Читатель", password_hash="!",
    )
    db.add(reader)
    await db.flush()
    db.add(UserCompany(user_id=reader.id, company_id=cid, role="user", modules=["docs"]))
    await db.commit()
    stored = await db.get(DocCard, uuid.UUID(doc["id"]))
    assert await docs_router._can_doc(db, cid, stored, reader, "read")
    assert not await docs_router._can_doc(db, cid, stored, reader, "edit")
    with pytest.raises(HTTPException) as error:
        await docs_router.verification_link(doc["id"], cid_raw, db, reader)
    assert getattr(error.value, "status_code", None) == 403
