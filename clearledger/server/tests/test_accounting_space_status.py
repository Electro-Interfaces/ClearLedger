"""Отметка сверки у карточек пространства: доказанное совпадение и необходимость уточнения.

Общий механизм один на все виды карточек, но ответ у них разный по смыслу:

* договор может быть «совпадает по сверенным реквизитам» — и только по тем полям,
  которые реально пришли из выгрузки (номер и дата). Снимок нашей же карточки
  (`target_values`) доказательством сверки не является, он отвечает за устаревание;
* контрагент и площадка своих реквизитов с бухгалтерией не сверяли НИКОГДА. Их
  отметка — сводка по договорам, и «сверено» ставится только если сверены все
  доступные договоры. Один договор без сведений делает сводку «требует сверки».

Проверяется и то, из-за чего отметка опасна: перенос зелёного признака договора на
контрагента или площадку, единая отметка вместо трёх осей, пропуск карточки в
batch-ответе (список прочитал бы его как «ещё грузится»), запрос на строку списка
вместо одного на страницу, и обход скоупа участника по юрлицу и по объектам.
"""
import contextlib
import json
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, event, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.database as dbmod
from app.auth import hash_password
from app.models import (
    Company,
    Contract,
    ContractLocation,
    Counterparty,
    DataEntry,
    Organization,
    ServiceLocation,
    User,
    UserCompany,
)
from app.services.accounting_space import _blocking_question, digest
# Строители строки источника и связи — те же, что в тесте среза: вторая копия
# сразу разошлась бы с формой данных, которую пишет применённая сверка.
from tests.test_accounting_space import FILE, SHA, _entry, _recon

pytestmark = pytest.mark.asyncio(loop_scope="session")

PASSWORD = "acct-status-123"
SUMMARY = "/api/accounting/space/link-summary"
SUMMARIES = "/api/accounting/space/link-summaries"


def _contract(company_id, party, org, number, date, type_code, type_name):
    return Contract(company_id=company_id, counterparty_id=party.id, organization_id=org.id,
                    number=number, date=date, type=type_name, type_code=type_code)


def _recheck_envelope(contract: Contract, party: Counterparty, *,
                      source_sha256=SHA, number_source=None, questions=None,
                      current_hash=None, relation="same_contract"):
    """Конверт независимой повторной сверки — ровно согласованная схема v1.

    Четыре сравниваемых поля и ничего больше: номер, дата, название стороны и
    вид договора. У названия `card` намеренно `null` — это совместимость
    значимых слов, а не юридическая проверка стороны: ИНН в выгрузке нет.
    """
    return {
        "schema_version": 1,
        "run_id": "rushydro-accounting-recheck-20261029",
        "checked_at": "2026-10-29T06:12:44+00:00",
        "source_as_of": "2026-09-30",
        "source_sha256": source_sha256,
        "source": {"file": FILE, "sheet": "Лист_1", "rows": [103]},
        "source_rows": [103],
        "overall": "confirmed_fields",
        "per_link": [{
            "contract_id": str(contract.id),
            "relation": relation,
            "compared_fields": [
                {"field": "number", "label": "Номер",
                 "source": number_source if number_source is not None else contract.number,
                 "card": contract.number, "result": "match",
                 "basis": "значимые знаки, как в accounting_space.compact"},
                {"field": "date", "label": "Дата", "source": contract.date,
                 "card": contract.date, "result": "match", "basis": "точное значение"},
                {"field": "counterparty_name", "label": "Сторона договора",
                 "source": party.name, "card": None, "result": "match",
                 "basis": "совместимость значимых слов названия, ИНН не сверялся"},
                {"field": "type_code", "label": "Вид договора", "source": "аренда",
                 "card": contract.type_code, "result": "unknown",
                 "basis": "вид в выгрузке не указан прямо"},
            ],
            "current_hash": current_hash if current_hash is not None else digest({
                "number": contract.number, "date": contract.date,
                "counterparty_id": str(contract.counterparty_id),
                "type_code": contract.type_code}),
            "unknowns": [{"field": "counterparty_inn", "label": "ИНН контрагента",
                          "reason": "в выгрузке отсутствует"}],
            "open_questions": questions if questions is not None else [
                {"code": "party_name_only", "label": "Сторона подтверждена только названием",
                 "reason": "ИНН не сверялся"}],
        }],
        "candidates_in_registry": [],
    }


@pytest.fixture
async def space(db: AsyncSession):
    """Договоры во всех состояниях отметки плюс договор второго юрлица.

    Состав подобран так, чтобы каждое состояние бралось из данных, а не из
    подставленного статуса: сверенный, с расхождением, со связанным документом,
    без строк выгрузки, со снимком без значений источника, с вердиктом повторной
    сверки и чужого юрлица. Участник компании ограничен одним юрлицом и одной
    площадкой — на нём проверяется ACL.
    """
    company = (await db.execute(select(Company).where(Company.slug == "rushydro"))).scalar_one()
    org1 = Organization(company_id=company.id, name="ПАО «РусГидро»", inn="2460066195")
    org2 = Organization(company_id=company.id, name="АО «РусГидро Сбыт»", inn="7706107510")
    db.add_all([org1, org2])
    parties = {name: Counterparty(company_id=company.id, name=name,
                                  inn=f"78111111{i:02d}", kpp="781101001")
               for i, name in enumerate(("Чистый ООО", "Смешанный ООО",
                                         "Расхождение ООО", "Связанный ООО",
                                         "Повторная ООО", "Другая редакция ООО"))}
    db.add_all(parties.values())
    await db.flush()

    locs = {
        "clean": ServiceLocation(id="acct-st-loc-clean", company_id=company.id,
                                 code="НСП-0001", name="ЭЗС Чистая", type="ev_charging"),
        "mixed": ServiceLocation(id="acct-st-loc-mixed", company_id=company.id,
                                 code="НСП-0002", name="ЭЗС Смешанная", type="ev_charging"),
        # Площадка вне скоупа участника и без договоров: проверяет и ACL, и «нет данных».
        "far": ServiceLocation(id="acct-st-loc-far", company_id=company.id,
                               code="НСП-0003", name="ЭЗС Дальняя", type="ev_charging"),
    }
    db.add_all(locs.values())

    c = {
        "ok": _contract(company.id, parties["Чистый ООО"], org1,
                        "41-09/ЭЗС-23", "2023-09-25", "rent", "Аренда"),
        "mix_ok": _contract(company.id, parties["Смешанный ООО"], org1,
                            "77-01/ЭЗС-11", "2024-03-01", "energy_supply", "Энергоснабжение"),
        "mix_none": _contract(company.id, parties["Смешанный ООО"], org1,
                              "77-02/ЭЗС-12", "2024-04-02", "rent", "Аренда"),
        "diff": _contract(company.id, parties["Расхождение ООО"], org1,
                          "15082024", "2024-08-20", "energy_supply", "Энергоснабжение"),
        "rel": _contract(company.id, parties["Связанный ООО"], org1,
                         "55/2025", "2025-05-05", "rent", "Аренда"),
        # Сверка сказала «проверено», но сравнивать было нечем: в выгрузке ни
        # номера, ни даты. Снимок наших же полей доказательством не является.
        "blank": _contract(company.id, parties["Связанный ООО"], org1,
                           "66/2025", "2025-06-06", "rent", "Аренда"),
        # Договор с вердиктом независимой повторной сверки: номер и дата сошлись,
        # но вид договора с бухгалтерией не согласуется — открытый вопрос.
        "rech": _contract(company.id, parties["Повторная ООО"], org1,
                          "88-11/ЭЗС-7", "2025-11-11", "rent", "Аренда"),
        # Прогон по этому договору шёл по другой редакции файла выгрузки.
        "sha": _contract(company.id, parties["Другая редакция ООО"], org1,
                         "77-09/ЭЗС-9", "2025-09-09", "rent", "Аренда"),
        # Второе юрлицо того же клиента: участник, закреплённый за первым, его не видит.
        "other": _contract(company.id, parties["Чистый ООО"], org2,
                           "99-ORG2", "2026-01-01", "rent", "Аренда"),
    }
    db.add_all(c.values())
    await db.flush()
    db.add_all([
        ContractLocation(company_id=company.id, contract_id=c["ok"].id, location_id=locs["clean"].id),
        ContractLocation(company_id=company.id, contract_id=c["mix_ok"].id, location_id=locs["mixed"].id),
        ContractLocation(company_id=company.id, contract_id=c["mix_none"].id, location_id=locs["mixed"].id),
    ])

    def recs(**kw):
        return json.dumps([_recon(**kw)], ensure_ascii=False)

    entries = {
        # Две разные строки выгрузки на один договор: источников бывает несколько.
        "ok": _entry(company.id, status="matched", counterparty="Чистый ООО",
                     contract="41-09/ЭЗС-23 от 25.09.2023",
                     meta_extra={"_accountingReconciliations": recs(
                         contract=c["ok"], location_ids=[locs["clean"].id])}),
        "ok2": _entry(company.id, status="matched", counterparty="Чистый ООО",
                      contract="41-09/ЭЗС-23 (приложение)",
                      meta_extra={"Файл источника": "Договоры, лист 2.xlsx",
                                  "Строки источника": "19",
                                  "_accountingReconciliations": recs(
                                      contract=c["ok"], verification="verified")}),
        "mix": _entry(company.id, status="matched", counterparty="Смешанный ООО",
                      contract="77-01/ЭЗС-11 от 01.03.2024",
                      meta_extra={"_accountingReconciliations": recs(contract=c["mix_ok"])}),
        "diff": _entry(company.id, status="matched", counterparty="Расхождение ООО",
                       contract="15082024 от 15.08.2024",
                       meta_extra={"_accountingReconciliations": recs(
                           contract=c["diff"], verification="differences",
                           source_date="2024-08-15")}),
        # Связанный документ со СВОИМ номером и датой: паспорт договора они не
        # оспаривают, иначе соглашение вечно «расходится» с основным договором.
        "rel": _entry(company.id, status="related", counterparty="Связанный ООО",
                      contract="Соглашение № 1 от 01.02.2025",
                      meta_extra={"_accountingReconciliations": recs(
                          contract=c["rel"], status="related", verification="not_checked",
                          relation="annex_of", source_number="Соглашение № 1",
                          source_date="2025-02-01")}),
        "rech": _entry(company.id, status="matched", counterparty="Повторная ООО",
                       contract="88-11/ЭЗС-7 от 11.11.2025",
                       meta_extra={
                           # Прежний хеш устарел, повторная сверка пересчитала
                           # его заново: устаревшей проверку объявлять второй раз
                           # не за что — база устаревания у неё свежее.
                           "_accountingReconciliations": recs(
                               contract=c["rech"], hash_override="прежний-хеш-устарел"),
                           # Согласованный конверт: один стабильный ключ, дата
                           # прогона внутри, сравнения на уровне связи.
                           "_accountingRecheck": _recheck_envelope(
                               c["rech"], parties["Повторная ООО"]),
                           "Повторная сверка": "Номер и дата совпали · 29.10.2026",
                       }),
        # Прогон по ДРУГОЙ редакции файла: его свидетельство не принимается.
        "stale_sha": _entry(company.id, status="matched", counterparty="Другая редакция ООО",
                            contract="77-09/ЭЗС-9 от 09.09.2025",
                            meta_extra={
                                "_accountingReconciliations": recs(contract=c["sha"]),
                                "_accountingRecheck": _recheck_envelope(
                                    c["sha"], parties["Другая редакция ООО"],
                                    source_sha256="b" * 64,
                                    number_source="совсем другой номер"),
                            }),
        "blank": _entry(company.id, status="matched", counterparty="Связанный ООО",
                        contract="без номера и даты",
                        meta_extra={"_accountingReconciliations": recs(
                            contract=c["blank"], verification="verified",
                            source_number="", source_date="")}),
        "other": _entry(company.id, status="matched", counterparty="Чистый ООО",
                        contract="99-ORG2 от 01.01.2026",
                        meta_extra={"_accountingReconciliations": recs(contract=c["other"])}),
        "queue": _entry(company.id, status="unmatched", counterparty="Неизвестный ИП",
                        contract="03-10/2023", entry_status="new",
                        meta_extra={"Кандидаты в пространстве": "Не найдены"}),
    }
    db.add_all(entries.values())

    member = User(company_id=company.id, email=f"acct-st-{uuid.uuid4().hex}@example.org",
                  name="Менеджер одного юрлица", password_hash=hash_password(PASSWORD))
    db.add(member)
    await db.flush()
    db.add(UserCompany(user_id=member.id, company_id=company.id, role="company",
                       own_organization_id=org1.id, object_scope=[locs["clean"].id]))
    # Коммит, а не flush: ручки идут своей сессией и чужой транзакции не видят.
    await db.commit()

    yield {"company_id": str(company.id), "c": c, "locs": locs,
           "parties": parties, "entries": entries, "member": member,
           "org1": org1, "org2": org2}

    await db.execute(delete(DataEntry).where(DataEntry.id.in_([e.id for e in entries.values()])))
    await db.execute(delete(ContractLocation).where(
        ContractLocation.contract_id.in_([x.id for x in c.values()])))
    await db.execute(delete(Contract).where(Contract.id.in_([x.id for x in c.values()])))
    await db.execute(delete(Counterparty).where(
        Counterparty.id.in_([p.id for p in parties.values()])))
    await db.execute(delete(ServiceLocation).where(
        ServiceLocation.id.in_([x.id for x in locs.values()])))
    await db.execute(delete(UserCompany).where(UserCompany.user_id == member.id))
    await db.execute(delete(User).where(User.id == member.id))
    await db.execute(delete(Organization).where(Organization.id.in_([org1.id, org2.id])))
    await db.commit()


async def _summary(client: AsyncClient, cid: str, kind: str, entity_id, **kw):
    return await client.get(SUMMARY, params={"company_id": cid, "entity_type": kind,
                                             "entity_id": str(entity_id)}, **kw)


async def _batch(client: AsyncClient, cid: str, kind: str, ids, **kw):
    return await client.post(SUMMARIES, params={"company_id": cid},
                             json={"entity_type": kind,
                                   "entity_ids": [str(x) for x in ids]}, **kw)


async def _member_headers(client: AsyncClient, email: str) -> dict[str, str]:
    r = await client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@contextlib.contextmanager
def _count_sql():
    """Сколько запросов уходит в базу: защита от обхода по строке списка."""
    hits: list[str] = []

    def _on(conn, cursor, statement, params, context, executemany):  # noqa: ANN001
        hits.append(statement)

    event.listen(dbmod.engine.sync_engine, "before_cursor_execute", _on)
    try:
        yield hits
    finally:
        event.remove(dbmod.engine.sync_engine, "before_cursor_execute", _on)


async def test_отметка_договора_опирается_на_поля_источника(auth_client, space):
    """«Совпадает по сверенным реквизитам» — только при сошедшемся значении выгрузки."""
    r = await _summary(auth_client, space["company_id"], "contract", space["c"]["ok"].id)
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["state"] == "matched_checked"
    assert s["state_label"] == "Совпадает по сверенным реквизитам"
    assert "не полная проверка договора" in s["state_note"]
    # Карточка целиком не сверялась никогда — ни у договора, ни у остальных видов.
    assert s["entity_verified"] is False
    assert s["scope"] == "self" and s["aggregate"] is None

    v = s["verification"]
    # Сверено с источником — номер и дата, они и пришли из выгрузки.
    assert v["checked_fields"] == ["date", "number"]
    assert {f["field"]: f["equal"] for f in v["compared_fields"]} == {"number": True, "date": True}
    assert any(f["basis"] == "значимые знаки номера" for f in v["compared_fields"])
    # Снимок карточки — отдельное поле и отдельный смысл: он про устаревание.
    assert v["snapshot_fields"] == ["counterparty_id", "date", "number", "type_code"]
    assert "не сверка с источником" in v["snapshot_basis"]
    # Непроверенное перечисляется целиком, а не четырьмя константами: идентичность
    # стороны и вид договора выгрузка не подтверждала — они лежат только в снимке.
    unchecked = {u["field"]: u["reason"] for u in v["unchecked_fields"]}
    assert set(unchecked) == {"counterparty_id", "type_code", "inn_kpp",
                              "original_document", "posted_in_1c", "signing", "amounts"}
    assert "ИНН и КПП не сверялись" in unchecked["counterparty_id"]
    assert "number" not in unchecked and "date" not in unchecked, "эти два сошлись"

    # Источников у одной карточки бывает несколько — показываются все.
    assert s["records"] == 2
    assert {x["file"] for x in s["sources"]} == {
        "Контрагенты, Договоры за 9 месяцев 2026.xlsx", "Договоры, лист 2.xlsx"}
    assert s["freshness"]["stale"] is False
    assert s["freshness"]["checked_at"] == "2026-10-28T15:16:03+00:00"
    assert s["freshness"]["checked_at_basis"] == "snapshot_at применённой сверки"
    assert s["matching"]["by_status"] == {"matched": 2}


async def test_расхождение_и_устаревание_остаются_разными_осями(auth_client, db, space):
    """Расхождение источника и устаревание проверки считаются и показываются отдельно."""
    cid = space["company_id"]
    diff = (await _summary(auth_client, cid, "contract", space["c"]["diff"].id)).json()
    assert diff["state"] == "differences"
    assert [d["field"] for d in diff["differences"]] == ["date"]
    assert diff["freshness"]["stale"] is False, "карточку не правили — устаревания нет"
    assert diff["verification"]["status"] == "differences"

    # Правка поля ВНЕ состава сверки проверку не сбрасывает.
    space["c"]["ok"].title = "Аренда земельного участка (уточнили название)"
    await db.commit()
    assert (await _summary(auth_client, cid, "contract",
                           space["c"]["ok"].id)).json()["freshness"]["stale"] is False

    # Правка сверенного поля — устаревание, посчитанное из текущего значения карточки.
    space["c"]["ok"].type_code = "service"
    await db.commit()
    stale = (await _summary(auth_client, cid, "contract", space["c"]["ok"].id)).json()
    assert stale["state"] == "stale"
    assert stale["state_label"] == "Устарело, нужна повторная сверка"
    assert stale["freshness"]["stale"] is True and stale["freshness"]["stale_records"] == 2
    assert stale["freshness"]["checked_hash"] != stale["freshness"]["current_hash"]
    # Номер и дата при этом по-прежнему сходятся: оси независимы.
    assert stale["differences"] == []
    assert stale["verification"]["checked_fields"] == ["date", "number"]


async def test_контрагент_не_красится_отметкой_своего_договора(auth_client, space):
    """Отметка контрагента — только сводка по договорам, и всегда со своей областью."""
    cid = space["company_id"]
    states = {}
    for name, party in space["parties"].items():
        s = (await _summary(auth_client, cid, "counterparty", party.id)).json()
        states[name] = s["state"]
        assert s["state"] != "matched_checked", "зелёная отметка договора не переносится"
        assert s["entity_verified"] is False
        assert s["scope"] == "contracts_of_counterparty"
        assert s["scope_label"] == "Сводка по договорам контрагента"
        assert s["aggregate"] is not None

    assert states["Чистый ООО"] == "contracts_checked"
    assert states["Смешанный ООО"] == "needs_check"
    assert states["Расхождение ООО"] == "differences"
    assert states["Связанный ООО"] == "needs_check"
    # У «Повторной» номер и дата сошлись, а открытый вопрос прогона про название
    # стороны узкую отметку не снимает — это калибровка, а не дефект.
    assert states["Повторная ООО"] == "contracts_checked"

    clean = (await _summary(auth_client, cid, "counterparty",
                            space["parties"]["Чистый ООО"].id)).json()
    # У «чистого» два договора: свой сверенный и договор второго юрлица, тоже сверенный.
    assert "не к самой карточке" in clean["state_note"]
    assert clean["aggregate"]["contracts_total"] == clean["aggregate"]["with_source"]

    mixed = (await _summary(auth_client, cid, "counterparty",
                            space["parties"]["Смешанный ООО"].id)).json()
    agg = mixed["aggregate"]
    assert agg["contracts_total"] == 2 and agg["with_source"] == 1 and agg["without_source"] == 1
    assert agg["by_state"] == {"matched_checked": 1, "no_source": 1}
    # Порядок — по требующему работы. «Нет данных для сравнения» стоит последним
    # намеренно: это не дефект карточки, а граница периметра выгрузки.
    assert [row["state"] for row in agg["contracts"]] == ["matched_checked", "no_source"]
    assert agg["contracts"][-1]["number"] == "77-02/ЭЗС-12"


async def test_площадка_показывает_сводку_своих_оснований(auth_client, space):
    """Площадка не наследует проверку договора: у неё своя область и свой состав."""
    cid = space["company_id"]
    clean = (await _summary(auth_client, cid, "location", space["locs"]["clean"].id)).json()
    assert clean["state"] == "contracts_checked"
    assert clean["scope"] == "contracts_of_location" and clean["entity_verified"] is False
    assert clean["aggregate"]["contracts_total"] == 1

    mixed = (await _summary(auth_client, cid, "location", space["locs"]["mixed"].id)).json()
    assert mixed["state"] == "needs_check"
    assert mixed["aggregate"]["without_source"] == 1

    # Площадка без договоров существует, но сравнивать нечего — и это не «нет договора».
    far = (await _summary(auth_client, cid, "location", space["locs"]["far"].id)).json()
    assert far["exists"] is True and far["state"] == "no_source"
    assert far["aggregate"]["contracts_total"] == 0
    assert "не означает, что договора нет в учёте" in far["state_note"]
    assert "периметра выгрузки" in far["disclaimer"]


async def test_batch_отвечает_на_каждый_запрошенный_id(auth_client, space):
    """Список получает отметку на каждую строку; пропуск читался бы как «грузится»."""
    cid = space["company_id"]
    unknown = str(uuid.uuid4())
    asked = [space["c"]["ok"].id, space["c"]["mix_none"].id, unknown, space["c"]["ok"].id]
    r = await _batch(auth_client, cid, "contract", asked)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requested"] == 3, "дубль свёрнут"
    assert [i["entity_id"] for i in body["items"]] == [
        str(space["c"]["ok"].id), str(space["c"]["mix_none"].id), unknown]
    by_id = {i["entity_id"]: i for i in body["items"]}
    assert by_id[str(space["c"]["ok"].id)]["state"] == "matched_checked"
    # Существующий договор без строк выгрузки: сведений нет, договор есть.
    none = by_id[str(space["c"]["mix_none"].id)]
    assert none["exists"] is True and none["state"] == "no_source"
    # Неизвестный id отвечает так же: отличать его от чужого наружу нельзя.
    assert by_id[unknown]["exists"] is False and by_id[unknown]["state"] == "no_source"

    assert (await _batch(auth_client, cid, "contract", [])).json()["items"] == []
    # Порция интерфейса — 500 карточек: в пространстве 901 договор, и при меньшем
    # лимите первая же страница списка получала бы 400.
    ok = await _batch(auth_client, cid, "contract", [uuid.uuid4() for _ in range(500)])
    assert ok.status_code == 200 and ok.json()["requested"] == 500
    too_many = await _batch(auth_client, cid, "contract", [uuid.uuid4() for _ in range(501)])
    assert too_many.status_code == 400 and "500" in too_many.json()["detail"]
    # Лимит считается по уникальным: повторённый id работы не добавляет.
    one = space["c"]["ok"].id
    dupes = await _batch(auth_client, cid, "contract", [one] * 600)
    assert dupes.status_code == 200 and dupes.json()["requested"] == 1
    bad = await _batch(auth_client, cid, "station", [space["c"]["ok"].id])
    assert bad.status_code == 400


async def test_batch_не_растёт_запросами_от_размера_списка(auth_client, space):
    """Отметки страницы берутся одним разбором среза, а не обходом по строке."""
    cid = space["company_id"]
    four = [space["c"]["ok"].id, space["c"]["mix_ok"].id,
            space["c"]["diff"].id, space["c"]["rel"].id]
    await _batch(auth_client, cid, "contract", [space["c"]["ok"].id])  # прогрев
    with _count_sql() as one:
        await _batch(auth_client, cid, "contract", [space["c"]["ok"].id])
    with _count_sql() as many:
        await _batch(auth_client, cid, "contract", four)
    assert len(many) == len(one), f"запрос на карточку: {len(one)} → {len(many)}"

    # Контрагенты и площадки считаются так же — через договоры, не по карточке.
    with _count_sql() as parties:
        await _batch(auth_client, cid, "counterparty",
                     [p.id for p in space["parties"].values()])
    with _count_sql() as sites:
        await _batch(auth_client, cid, "location", [x.id for x in space["locs"].values()])
    assert len(parties) == len(sites) == len(one) + 1, "существование карточек + их договоры"


async def test_страницы_списка_получают_отметки_одним_запросом(auth_client, space):
    """Пагинация и отметки согласованы: id каждой страницы доходят до batch без потерь."""
    cid = space["company_id"]
    seen: list[str] = []
    offset = 0
    while True:
        page = (await auth_client.get("/api/accounting/space/records", params={
            "company_id": cid, "limit": 2, "offset": offset})).json()
        for row in page["items"]:
            seen.extend(card["id"] for card in row["cards"] if card.get("exists"))
        offset += 2
        if offset >= page["total"]:
            break
    assert seen, "на страницах есть сопряжённые карточки"
    body = (await _batch(auth_client, cid, "contract", seen)).json()
    assert body["requested"] == len(set(seen))
    assert {i["entity_id"] for i in body["items"]} == set(seen)
    assert all(i["exists"] for i in body["items"])


async def test_закреплённое_юрлицо_и_скоуп_объектов_не_обходятся(client, space):
    """Участник одного юрлица и пяти станций не получает отметок чужого юрлица и объекта."""
    cid = space["company_id"]
    h = await _member_headers(client, space["member"].email)
    other, far = str(space["c"]["other"].id), space["locs"]["far"].id

    # Чужое юрлицо: ни одиночной отметкой, ни партией, ни через карточку строки.
    assert (await _summary(client, cid, "contract", other, headers=h)).status_code == 404
    mine = (await _batch(client, cid, "contract",
                         [space["c"]["ok"].id, other], headers=h)).json()
    by_id = {i["entity_id"]: i for i in mine["items"]}
    assert by_id[str(space["c"]["ok"].id)]["exists"] is True
    assert by_id[other]["exists"] is False and by_id[other]["state"] == "no_source"

    # Объект вне скоупа: 404 одиночным и нейтральный ответ в партии.
    assert (await _summary(client, cid, "location", far, headers=h)).status_code == 404
    sites = (await _batch(client, cid, "location",
                          [space["locs"]["clean"].id, far], headers=h)).json()
    states = {i["entity_id"]: i["exists"] for i in sites["items"]}
    assert states[space["locs"]["clean"].id] is True and states[far] is False

    # Сводка контрагента у участника считается только по его юрлицу.
    clean_party = space["parties"]["Чистый ООО"].id
    mine_party = (await _summary(client, cid, "counterparty", clean_party, headers=h)).json()
    assert mine_party["aggregate"]["contracts_total"] == 1
    assert str(space["c"]["other"].id) not in {
        row["id"] for row in mine_party["aggregate"]["contracts"]}


async def test_суперадмин_видит_оба_юрлица(auth_client, space):
    """Контроль к предыдущему: ограничение участника, а не исчезновение данных."""
    cid = space["company_id"]
    s = (await _summary(auth_client, cid, "contract", space["c"]["other"].id)).json()
    assert s["exists"] is True and s["state"] == "matched_checked"
    party = (await _summary(auth_client, cid, "counterparty",
                            space["parties"]["Чистый ООО"].id)).json()
    assert party["aggregate"]["contracts_total"] == 2
    # Разрез по юрлицу параметром остаётся доступным и считает только своё.
    narrowed = await auth_client.get(SUMMARY, params={
        "company_id": cid, "entity_type": "counterparty",
        "entity_id": str(space["parties"]["Чистый ООО"].id),
        "organization_id": str(space["org2"].id)})
    assert narrowed.json()["aggregate"]["contracts_total"] == 1


async def test_состояние_считается_живым_сравнением_а_не_прежним_вердиктом(
        auth_client, db, space):
    """Исправленное расхождение исчезает, испорченный реквизит появляется."""
    cid = space["company_id"]
    before = (await _summary(auth_client, cid, "contract", space["c"]["diff"].id)).json()
    assert before["state"] == "differences"

    # Спорную дату исправили по выгрузке: расхождения больше нет, но сверенное
    # значение изменилось — проверку нужно повторить.
    space["c"]["diff"].date = "2024-08-15"
    await db.commit()
    fixed = (await _summary(auth_client, cid, "contract", space["c"]["diff"].id)).json()
    assert fixed["differences"] == [], "прежний вердикт «расхождение» не держится вечно"
    assert fixed["state"] == "stale" and fixed["freshness"]["stale"] is True

    # Обратный случай: испорченный номер становится расхождением, которого прежняя
    # сверка не видела, и устаревание остаётся выставленным параллельно.
    space["c"]["mix_ok"].number = "77-01/ЭЗС-11-испорчен"
    await db.commit()
    broken = (await _summary(auth_client, cid, "contract", space["c"]["mix_ok"].id)).json()
    assert broken["state"] == "differences"
    assert [d["field"] for d in broken["differences"]] == ["number"]
    assert broken["freshness"]["stale"] is True, "ось свежести не прячется за расхождением"


async def test_связанный_документ_не_оспаривает_паспорт_договора(auth_client, space):
    """Номер и дата соглашения — реквизиты ЕГО, а не договора, к которому оно идёт."""
    s = (await _summary(auth_client, space["company_id"], "contract",
                        space["c"]["rel"].id)).json()
    assert s["differences"] == [], "«Соглашение № 1» против «55/2025» — не расхождение"
    assert s["state"] == "needs_check"
    bases = {f["field"]: f["basis"] for f in s["verification"]["compared_fields"]}
    assert all("другой документ" in b for b in bases.values())
    assert s["verification"]["checked_fields"] == []


async def test_повторная_сверка_читается_и_показывается_отдельно(auth_client, db, space):
    """Независимый прогон: своё время, своя база устаревания, свои вопросы."""
    s = (await _summary(auth_client, space["company_id"], "contract",
                        space["c"]["rech"].id)).json()
    f = s["freshness"]
    # Время прогона — отдельное поле, дату прежнего применения не подменяет.
    assert f["rechecked_at"] == "2026-10-29T06:12:44+00:00"
    assert f["checked_at"] == "2026-10-28T15:16:03+00:00"
    # База устаревания — свежая: прежний хеш устарел, прогон пересчитал его сам.
    assert f["baseline"] == "повторная сверка" and f["stale"] is False

    r = s["verification"]["recheck"]
    assert r["schema_version"] == 1
    assert r["run_id"] == "rushydro-accounting-recheck-20261029"
    assert r["checked_at"] == "2026-10-29T06:12:44+00:00"
    assert r["applicable"] is True and r["not_applicable_reason"] is None
    assert [q["code"] for q in r["open_questions"]] == ["party_name_only"]
    # «Сторона подтверждена только названием» отметку номера и даты не снимает.
    assert r["blocking_questions"] == []
    assert s["state"] == "matched_checked"
    assert s["verification"]["checked_fields"] == ["date", "number"]

    # Название стороны прогон считает совпавшим — сервер это НЕ считает проверкой
    # идентичности: своего пересчёта у названия нет, ИНН в выгрузке нет.
    name = next(c for c in s["verification"]["compared_fields"]
                if c["field"] == "counterparty_name")
    assert name["result"] == "unknown" and name["claimed"] == "match"
    assert "не юридическая проверка" in name["basis"]
    assert name["evidence"]["file"] and name["evidence"]["sheet"]
    unchecked = {u["field"] for u in s["verification"]["unchecked_fields"]}
    assert "counterparty_id" in unchecked, "совместимость названий идентичность не доказывает"
    assert {"inn_kpp", "counterparty_inn", "type_code"} <= unchecked

    # Вид договора — подсказка, а не дефект: площадка законно заведена двумя
    # карточками (аренда и получение электроэнергии) с одним номером и датой.
    kind = next(c for c in s["verification"]["compared_fields"]
                if c["field"] == "type_code")
    assert kind["result"] == "unknown" and s["differences"] == []

    # Правка карточки ПОСЛЕ прогона устаревляет его результат: база сравнения —
    # хеш, который прогон записал, а не тот, что был у прежнего применения.
    space["c"]["rech"].type_code = "service"
    await db.commit()
    after = (await _summary(auth_client, space["company_id"], "contract",
                            space["c"]["rech"].id)).json()
    assert after["freshness"]["stale"] is True and after["state"] == "stale"


async def test_конверт_читается_и_строкой_json(auth_client, db, space):
    """`metadata` по контракту хранит строки: конверт приезжает сериализованным.

    Запись объектом в этом слое не принимается (служба правки записей приводит
    значения к строке), поэтому читатель обязан понимать обе формы одинаково.
    """
    cid = space["company_id"]
    entry = space["entries"]["rech"]
    envelope = _recheck_envelope(space["c"]["rech"], space["parties"]["Повторная ООО"])
    meta = dict(entry.meta)
    meta["_accountingRecheck"] = json.dumps(envelope, ensure_ascii=False)
    meta["_accountingRecheckHistory"] = json.dumps(
        [{"run_id": envelope["run_id"], "checked_at": envelope["checked_at"],
          "overall": envelope["overall"]}], ensure_ascii=False)
    entry.meta = meta
    await db.commit()

    s = (await _summary(auth_client, cid, "contract", space["c"]["rech"].id)).json()
    r = s["verification"]["recheck"]
    assert r["schema_version"] == 1, "строка разобрана, схема прочитана"
    assert r["checked_at"] == "2026-10-29T06:12:44+00:00"
    assert r["applicable"] is True
    assert s["freshness"]["rechecked_at"] == "2026-10-29T06:12:44+00:00"
    assert s["freshness"]["baseline"] == "повторная сверка"
    assert s["state"] == "matched_checked"
    # Значения стороны источника из строки тоже дошли — сравнение пересчитано.
    name = next(c for c in s["verification"]["compared_fields"]
                if c["field"] == "counterparty_name")
    assert name["claimed"] == "match" and name["result"] == "unknown"

    # Испорченная строка не должна ронять ручку: конверта просто нет.
    meta = dict(entry.meta)
    meta["_accountingRecheck"] = "{не json"
    entry.meta = meta
    await db.commit()
    broken = (await _summary(auth_client, cid, "contract", space["c"]["rech"].id)).json()
    assert broken["verification"]["recheck"] is None
    assert broken["freshness"]["rechecked_at"] is None


async def test_коды_открытых_вопросов_калиброваны():
    """Фактический набор кодов прогона: что снимает отметку, а что подсказка.

    Коды — контракт между прогоном и этой ручкой. Без проверки любой новый код
    молча попадал бы в «не блокирует», и неоднозначная привязка оставалась бы
    зелёной — или наоборот, подсказка о роли карточки гасила бы отметку.
    """
    blocking = {"party_ambiguous_identity", "party_contradiction",
                "link_ambiguous", "source_ambiguous"}
    hints = {"party_name_only", "role_card", "card_date_empty"}
    for code in blocking | hints:
        assert _blocking_question({"code": code}) is (code in blocking), code


async def test_конверт_дополнения_сравнивает_основной_договор(auth_client, db, space):
    """У дополнения номер строки — его собственный, а номер из конверта — основного.

    Поэтому значение строки сравнивать с паспортом нельзя, а значение конверта
    можно и нужно: иначе доказательство по дополнениям теряется целиком.
    """
    cid = space["company_id"]
    entry = space["entries"]["rel"]
    meta = dict(entry.meta)
    meta["_accountingRecheck"] = json.dumps(_recheck_envelope(
        space["c"]["rel"], space["parties"]["Связанный ООО"],
        relation="amendment_to_contract"), ensure_ascii=False)
    entry.meta = meta
    await db.commit()
    s = (await _summary(auth_client, cid, "contract", space["c"]["rel"].id)).json()
    by_origin = {(c["origin"], c["field"]): c for c in s["verification"]["compared_fields"]}
    # Своё значение строки осталось несравнимым...
    assert by_origin[("row", "number")]["result"] == "unknown"
    assert "другой документ" in by_origin[("row", "number")]["basis"]
    # ...а номер основного договора из конверта сошёлся.
    assert by_origin[("recheck", "number")]["result"] == "match"
    assert s["verification"]["checked_fields"] == ["date", "number"]


async def test_прогон_по_другой_редакции_файла_не_подтверждает_сверку(auth_client, space):
    """Свидетельство прогона принимается только если совпала редакция выгрузки."""
    s = (await _summary(auth_client, space["company_id"], "contract",
                        space["c"]["sha"].id)).json()
    r = s["verification"]["recheck"]
    assert r["applicable"] is False
    assert "другой редакции" in r["not_applicable_reason"]
    # Значения из непринятого конверта в сравнения не попали — иначе «совсем
    # другой номер» показался бы расхождением карточки.
    assert all(c["origin"] == "row" for c in s["verification"]["compared_fields"])
    assert s["differences"] == []
    # Собственное доказательство строки при этом осталось.
    assert s["verification"]["checked_fields"] == ["date", "number"]
    assert s["freshness"]["baseline"] == "прежнее применение"


async def test_конфликтные_отношения_остаются_тем_же_договором(auth_client, db, space):
    """`number_conflict` и соседи — тот же договор: его номер сравнивать обязательно."""
    cid = space["company_id"]
    entry = space["entries"]["rel"]
    for relation, expect in (("number_conflict", "differences"),
                             ("joint_party", "differences"),
                             ("same_contract_payee_label", "differences"),
                             ("annex_of", "needs_check")):
        meta = dict(entry.meta)
        meta["_accountingReconciliations"] = json.dumps(
            [_recon(space["c"]["rel"], status="related", verification="not_checked",
                    relation=relation, source_number="55/2025-другой",
                    source_date="2025-05-05")], ensure_ascii=False)
        entry.meta = meta
        await db.commit()
        s = (await _summary(auth_client, cid, "contract", space["c"]["rel"].id)).json()
        assert s["state"] == expect, f"{relation}: ожидалось {expect}"
        if expect == "differences":
            assert [d["field"] for d in s["differences"]] == ["number"]
        else:
            assert s["differences"] == [], "у дополнения свой номер, это не расхождение"


async def test_противоречие_стороны_снимает_отметку(auth_client, db, space):
    """Доказанное противоречие стороны и неоднозначная привязка блокируют зелёное."""
    cid = space["company_id"]
    entry = space["entries"]["rech"]
    meta = dict(entry.meta)
    meta["_accountingRecheck"] = _recheck_envelope(
        space["c"]["rech"], space["parties"]["Повторная ООО"],
        questions=[{"code": "party_contradiction", "label": "Сторона не та",
                    "reason": "в выгрузке другая организация"}])
    entry.meta = meta
    await db.commit()
    s = (await _summary(auth_client, cid, "contract", space["c"]["rech"].id)).json()
    assert s["state"] == "needs_check"
    assert [q["code"] for q in s["verification"]["recheck"]["blocking_questions"]] == [
        "party_contradiction"]

    # Неоднозначная привязка к нескольким карточкам — тоже блокирует.
    meta = dict(entry.meta)
    meta["_accountingReconciliations"] = json.dumps(
        [_recon(space["c"]["rech"], relation="multiple_cards")], ensure_ascii=False)
    meta.pop("_accountingRecheck")
    entry.meta = meta
    await db.commit()
    s = (await _summary(auth_client, cid, "contract", space["c"]["rech"].id)).json()
    assert s["state"] == "needs_check"
    # При этом номер и дату она сравнить не мешает: это тот же договор.
    assert s["verification"]["checked_fields"] == ["date", "number"]


async def test_строки_чужого_юрлица_не_видны_целиком(client, auth_client, space):
    """Фильтрация договоров недостаточна: названия из строк чужого юрлица тоже уходят."""
    cid = space["company_id"]
    h = await _member_headers(client, space["member"].email)
    mine = await client.get("/api/accounting/space/records",
                            params={"company_id": cid, "search": "99-ORG2"}, headers=h)
    assert mine.json()["total"] == 0, "строка источника чужого юрлица скрыта целиком"
    full = await auth_client.get("/api/accounting/space/records",
                                 params={"company_id": cid, "search": "99-ORG2"})
    assert full.json()["total"] == 1, "у суперадмина она на месте"
    # Итог пространства считается в том же разрезе, что и срез.
    member_total = (await client.get("/api/accounting/space/summary",
                                     params={"company_id": cid}, headers=h)).json()
    admin_total = (await auth_client.get("/api/accounting/space/summary",
                                         params={"company_id": cid})).json()
    assert member_total["source_rows"] < admin_total["source_rows"]
    assert member_total["space"]["contracts"] < admin_total["space"]["contracts"]
    assert member_total["space"]["locations"] < admin_total["space"]["locations"]


async def test_снимок_своих_полей_не_считается_сверкой(auth_client, space):
    """«Проверено» без значения в выгрузке — это не доказанное совпадение.

    `target_values` — снимок НАШЕЙ карточки на момент сверки. Если источник не дал
    ни номера, ни даты, сравнивать было нечего, и отметка обязана просить сверку,
    даже когда сама сверка записала себе `verified`.
    """
    s = (await _summary(auth_client, space["company_id"], "contract",
                        space["c"]["blank"].id)).json()
    assert s["state"] == "needs_check"
    assert s["verification"]["checked_fields"] == []
    # Нечего сравнивать — это «неизвестно», а не расхождение.
    assert all(f["result"] == "unknown" and f["equal"] is None
               for f in s["verification"]["compared_fields"])
    assert {f["field"]: f["basis"] for f in s["verification"]["compared_fields"]} == {
        "number": "номер источника без значимых знаков — сравнивать нечего",
        "date": "в выгрузке даты нет"}
    # Снимок при этом есть — он отвечает за устаревание, а не за сверку.
    assert s["verification"]["snapshot_fields"] == [
        "counterparty_id", "date", "number", "type_code"]
    assert s["freshness"]["checked_hash"] == s["freshness"]["current_hash"]


async def test_связанный_документ_требует_сверки(auth_client, space):
    """Сопряжение без сверки реквизитов зелёным не показывается."""
    s = (await _summary(auth_client, space["company_id"], "contract",
                        space["c"]["rel"].id)).json()
    assert s["state"] == "needs_check"
    assert s["matching"]["by_status"] == {"related": 1}
    assert s["matching"]["labels"]["related"] == "Связанный документ"
    assert s["verification"]["status"] == "not_checked"
