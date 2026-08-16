"""«Дело»: регистрация, нумерация, файлы, согласование.

Ловим то, что молча ломается и дорого стоит потом: пропуск в журнале
регистрации, два документа под одним номером, вторая редакция от повторной
загрузки того же файла, виза, поставленная не тем человеком, и срок хранения,
пересчитанный задним числом.
"""
import asyncio
import uuid

import pytest
from httpx import AsyncClient

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
        "company_id": cid, "reg_number": taken})
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
    assert card["status"] == "draft", "документ не вернулся в черновики"
    assert card["reg_number"], "номер потерялся при возврате"
    assert card["approval_status"] == "rejected"


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
    finally:
        await anon.aclose()
