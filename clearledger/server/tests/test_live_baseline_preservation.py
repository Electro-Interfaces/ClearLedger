"""Literal controls against SHA-verified live functions and the candidate.

Only ROOT's frozen runner supplies LIVE_PRESERVATION_BASELINE_DIR. This is not
a second app: selected live function ASTs use the candidate's existing owners,
ORM and transactions; no startup, module imports or DDL from live is executed.
"""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import (
    CalendarAttendee, CalendarEvent, Channel, ChargeSession, Company, CorporateClient,
    EzsSite, EzsSiteEvent, ServiceLocation, User,
)
from app.scope import set_request_scope
from app.services import charge_sessions_normalize, email_service, ezs_site_work, jitsi, meeting_notice

pytestmark = pytest.mark.asyncio(loop_scope="session")


def live_functions(module, relative, names):
    root = os.environ.get("LIVE_PRESERVATION_BASELINE_DIR")
    if not root:
        pytest.skip("Requires ROOT's SHA-verified live baseline runner")
    tree = ast.parse((Path(root) / relative).read_text())
    nodes = [node for node in tree.body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert {node.name for node in nodes} == set(names)
    namespace = dict(vars(module))
    # Preserve deferred annotations without executing any live module imports.
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    selected = ast.fix_missing_locations(ast.Module(body=[future, *nodes], type_ignores=[]))
    exec(compile(selected, str(Path(root) / relative), "exec"), namespace)
    return SimpleNamespace(**{name: namespace[name] for name in names})


@pytest.fixture(params=["live", "candidate"])
def behavior(request):
    if request.param == "candidate":
        return SimpleNamespace(site=ezs_site_work, corporate=charge_sessions_normalize, notice=meeting_notice)
    return SimpleNamespace(
        site=live_functions(ezs_site_work, "services/ezs_site_work.py", ["_coerce", "update_site", "site_out_full"]),
        corporate=live_functions(charge_sessions_normalize, "services/charge_sessions_normalize.py", ["classify_corporate_sessions"]),
        notice=live_functions(meeting_notice, "services/meeting_notice.py", ["известить"]),
    )


@pytest.mark.parametrize("bad", ["2026-02-30", "20261030", "30.10.2026"])
async def test_invalid_date_is_atomic_before_any_write(db, behavior, bad):
    cid = (await db.execute(select(Company.id).limit(1))).scalar_one()
    site = EzsSite(company_id=cid, address="Прежний адрес", manual_fields=["city"])
    db.add(site)
    await db.flush()
    before = site.updated_at, site.last_touch_at, list(site.manual_fields)
    with pytest.raises(ValueError, match="корректную дату"):
        await behavior.site.update_site(db, site, {"address": "Не сохранять", "decommissioned_on": bad}, None)
    assert site.address == "Прежний адрес"
    assert (site.updated_at, site.last_touch_at, site.manual_fields) == before
    assert not db.dirty and not db.new
    assert not (await db.scalars(select(EzsSiteEvent).where(EzsSiteEvent.site_id == site.id))).all()
    await db.rollback()


@pytest.mark.parametrize("kind", ["hidden", "foreign", "warehouse"])
async def test_unavailable_station_rejects_whole_payload(db, behavior, kind):
    companies = (await db.scalars(select(Company).limit(2))).all()
    cid, other = companies[0].id, companies[1].id
    station = ServiceLocation(id=str(uuid4()), company_id=other if kind == "foreign" else cid,
                              code="GOLD-01", name="Станция", status="active",
                              type="warehouse" if kind == "warehouse" else "ev_charging")
    site = EzsSite(company_id=cid, address="Прежний адрес")
    db.add_all([station, site])
    await db.flush()
    set_request_scope(["unrelated-location"] if kind == "hidden" else None)
    try:
        with pytest.raises(ValueError, match="недоступна"):
            await behavior.site.update_site(db, site, {"address": "Не сохранять", "dismantle_location_ids": [station.id]}, None)
        assert site.address == "Прежний адрес" and site.dismantle_location_ids is None
        assert not db.new and not db.dirty
    finally:
        set_request_scope(None)
        await db.rollback()


@pytest.mark.parametrize("clear", [None, "", []])
async def test_nullable_clear_and_literal_audit_output(db, behavior, clear):
    cid = (await db.execute(select(Company.id).limit(1))).scalar_one()
    station = ServiceLocation(id=str(uuid4()), company_id=cid, code="GOLD-02", name="Станция",
                              type="ev_charging", status="active", operational_status="working")
    site = EzsSite(company_id=cid, address="СМР", kind="decommission",
                   dismantle_location_ids=["no-longer-visible"], decommissioned_on="2026-10-30")
    db.add_all([station, site])
    await db.flush()
    result = await behavior.site.update_site(db, site, {
        "dismantle_location_ids": [station.id, station.id], "decommissioned_on": "2026-11-12"}, None)
    assert result == {"changed": ["dismantle_location_ids", "decommissioned_on"]}
    await db.flush()
    event = (await db.scalars(select(EzsSiteEvent).where(EzsSiteEvent.site_id == site.id))).one()
    change = event.changes[0]
    assert change == {"field": "dismantle_location_ids", "label": "ЭЗС к демонтажу", "category": "technical",
                      "old": ["no-longer-visible"], "new": [station.id],
                      "oldDisplay": "Недоступная ЭЗС", "newDisplay": "GOLD-02 · Станция"}
    assert event.changes[1]["label"] == "Дата вывода ЭЗС из эксплуатации"
    output = behavior.site.site_out_full(site)
    assert output["dismantleLocationIds"] == [station.id] and output["decommissionedOn"] == "2026-11-12"
    await behavior.site.update_site(db, site, {"dismantle_location_ids": clear, "decommissioned_on": None}, None)
    await db.flush()
    output = behavior.site.site_out_full(site)
    assert output["dismantleLocationIds"] == [] and output["decommissionedOn"] is None
    assert {"dismantle_location_ids", "decommissioned_on"} <= set(site.manual_fields)
    await db.refresh(station)
    assert (station.status, station.operational_status, station.decommissioned_on) == ("active", "working", None)
    assert site.dismantle_location_ids == ([] if clear == [] else None)
    await db.rollback()


async def test_corporate_identity_channel_admin_and_explicit_type(db, behavior):
    companies = (await db.scalars(select(Company).limit(2))).all()
    cid, foreign = companies[0].id, companies[1].id
    name, phone, channel, other_channel = "Golden corporate", uuid4().hex[:20], uuid4(), uuid4()
    db.add_all([Channel(id=channel, company_id=cid, name="Golden channel"),
                Channel(id=other_channel, company_id=cid, name="Other golden channel")])
    await db.flush()
    db.add(CorporateClient(company_id=cid, name=name, phone=phone, mode="flat", rate=99))
    # Literal expected type/cut; amount=0 is deliberately identical in all rows.
    rows = [
        (cid, name, phone, None, "RFID", channel, "ЮЛ", "ezs_corp"),
        (cid, name, phone, " ", " admin ", channel, "ЮЛ", "ezs_admin"),
        (cid, name, phone, "ФЛ", "RFID", channel, "ФЛ", "ezs_unpaid"),
        (cid, name, phone, "ЮЛ", "RFID", channel, "ЮЛ", "ezs_unpaid"),
        (foreign, name, phone, None, "RFID", channel, None, "ezs_unpaid"),
        (cid, "Other name", phone, None, "RFID", channel, None, "ezs_unpaid"),
        (cid, name, "other-phone", None, "RFID", channel, None, "ezs_unpaid"),
        (cid, name, phone, None, "RFID", other_channel, None, "ezs_unpaid"),
    ]
    sessions = [ChargeSession(company_id=c, session_ext_id=str(uuid4()), client_name=n, user_id=p,
                user_type=t, charge_type=charge, channel_id=ch, cut_key="ezs_unpaid", amount=0,
                client_amount=Decimal("123.40"), client_tariff=Decimal("12.34"), tariff=30, energy_kwh=10)
                for c, n, p, t, charge, ch, _, _ in rows]
    db.add_all(sessions)
    await db.flush()
    assert await behavior.corporate.classify_corporate_sessions(db, cid, channel) == 2
    assert await behavior.corporate.classify_corporate_sessions(db, cid, channel) == 0
    for session, expected in zip(sessions, rows):
        await db.refresh(session)
        assert (session.user_type, session.cut_key) == expected[-2:]
        assert (session.amount, session.client_amount, session.client_tariff, session.tariff) == (
            0, Decimal("123.40"), Decimal("12.34"), Decimal("30"))
    await db.rollback()


@pytest.mark.parametrize("hosts", [False, True], ids=["organizer-fallback", "shared-hosts"])
@pytest.mark.parametrize("preference", [["meeting"], []], ids=["mail-enabled", "mail-disabled"])
async def test_actor_email_chat_and_common_hosts(db, behavior, monkeypatch, hosts, preference):
    cid = (await db.execute(select(Company.id).limit(1))).scalar_one()
    people = [User(company_id=cid, name=n, email=f"{uuid4().hex}@example.test", password_hash="!synthetic",
                   email_notify=["meeting"]) for n in ["Организатор", "Анна", "Борис"]]
    db.add_all(people)
    await db.flush()
    owner, alpha, bravo = people
    owner.email_notify = preference
    start = datetime(2030, 1, 1, 10, tzinfo=timezone.utc)
    ev = CalendarEvent(company_id=cid, organizer_id=owner.id, title="Golden hosts", starts_at=start,
                       ends_at=start + timedelta(hours=1), tz="UTC", conference_url="https://meet.example.test/room")
    db.add(ev)
    await db.flush()
    db.add_all(CalendarAttendee(event_id=ev.id, user_id=p.id, is_host=hosts and p != owner) for p in people)
    await db.flush()
    mails, chats = [], []

    async def mail(to, **fields):
        mails.append({"to": to, **fields})
        return True

    async def chat(db, company, actor, recipient, text, title):
        chats.append((actor.id, recipient.id, text))
        return True

    monkeypatch.setattr(email_service, "send_meeting_invite", mail)
    # Live's function globals are an isolated dict; patch its own sender too.
    monkeypatch.setitem(behavior.notice.известить.__globals__, "в_личку", chat)
    result = await behavior.notice.известить(db, ev, owner, "invite")
    expected_mails = {alpha.email, bravo.email} | ({owner.email} if preference else set())
    assert result == {"mailed": len(expected_mails), "chatted": 2}
    assert {m["to"] for m in mails} == expected_mails
    assert {recipient for _, recipient, _ in chats} == {alpha.id, bravo.id}
    assert all(sender != recipient for sender, recipient, _ in chats)
    golden = ("Организатор зовёт на встречу «Golden hosts» 01.01.2030 в 10:00.\n"
              "Ссылка на видеовстречу: https://meet.example.test/room\nВедущие: "
              + ("Анна, Борис" if hosts else "Организатор"))
    assert await jitsi.meeting_hosts(db, ev) == ({alpha.id, bravo.id} if hosts else {owner.id})
    assert all(m["text"] == golden and m["method"] == "REQUEST" for m in mails)
    assert all(text == "📅 " + golden for _, _, text in chats)
    # /room is an external calendar link; only /ledger-<hex> has @conf.elsyplus.
    assert all(f"UID:{ev.id}@trek" in m["ics"] for m in mails)
    await db.rollback()
