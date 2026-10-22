"""Настоящие HTTP/SQL проверки на отдельной пустой PostgreSQL, без conftest/startup.

Запуск: TEST_DATABASE_URL=... PYTHONPATH=server python -m unittest discover
-s server/tests -p test_location_contacts_integration.py -v
Только локальная база contacts_test. Рабочие соединения запрещены.
"""
import asyncio
import os
import unittest
import uuid

import httpx
from fastapi import FastAPI
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.engine import make_url

from app.auth import get_current_user
from app.database import Base, get_db
from app.models import Company, Contract, ContractLocation, Counterparty, CounterpartyContact, LocationContact, Organization, ServiceLocation, User, UserCompany
from app.routers import location_contacts_router, references_router
from app.services.phone_e164 import PHONE_FUNCTION_DDL

URL = os.getenv("TEST_DATABASE_URL", "")


RUN = bool(URL and make_url(URL).database == "contacts_test" and make_url(URL).host in {"127.0.0.1", "localhost"})


@unittest.skipUnless(RUN, "Нужна отдельная локальная PostgreSQL contacts_test; общий pytest её не использует")
class LocationContactsIntegration(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        if not RUN:
            raise RuntimeError("Проверка удаляет тестовую схему: нужна отдельная локальная база contacts_test")
        cls.engine = create_async_engine(URL, poolclass=NullPool)
        cls.sessions = async_sessionmaker(cls.engine, expire_on_commit=False)
        tables = {m.__table__ for m in (Company, Contract, ContractLocation, Counterparty,
            CounterpartyContact, LocationContact, Organization, ServiceLocation, User, UserCompany)}
        while True:
            parents = {fk.column.table for table in tables for fk in table.foreign_keys}
            if parents <= tables:
                break
            tables |= parents
        async def create():
            async with cls.engine.begin() as conn:
                await conn.execute(text(PHONE_FUNCTION_DDL))
                await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=list(tables)))
        asyncio.run(create())

    @classmethod
    def tearDownClass(cls):
        async def cleanup():
            async with cls.engine.begin() as conn:
                await conn.execute(text("DROP SCHEMA public CASCADE"))
                await conn.execute(text("CREATE SCHEMA public"))
            await cls.engine.dispose()
        asyncio.run(cleanup())

    async def asyncSetUp(self):
        async with self.engine.begin() as conn:
            await conn.execute(text("TRUNCATE companies, users CASCADE"))
        async with self.sessions() as db:
            self.company = Company(name="Тест сеть", slug="contacts-test", profile_id="energy")
            self.foreign = Company(name="Другая сеть", slug="foreign-test", profile_id="energy")
            db.add_all([self.company, self.foreign]); await db.flush()
            self.member = User(email="member@example.invalid", name="Тест инженер", password_hash="fake")
            self.admin = User(email="admin@example.invalid", name="Тест админ", password_hash="fake", is_superadmin=True)
            db.add_all([self.member, self.admin]); await db.flush()
            db.add(UserCompany(user_id=self.member.id, company_id=self.company.id, role="user"))
            self.locations = [ServiceLocation(id="test-site-"+str(i), company_id=self.company.id,
                code=str(i), name="Тест площадка "+str(i)) for i in range(2)]
            self.other_location = ServiceLocation(id="foreign-site", company_id=self.foreign.id, code="1", name="Другой объект")
            db.add_all([*self.locations, self.other_location])
            self.cps = [Counterparty(company_id=self.company.id, name="Тест организация "+str(i), inn=str(i)) for i in range(2)]
            self.foreign_cp = Counterparty(company_id=self.foreign.id, name="Другая организация", inn="9")
            db.add_all([*self.cps, self.foreign_cp]); await db.flush()
            self.people = [CounterpartyContact(company_id=self.company.id, counterparty_id=self.cps[i//2].id,
                name="Тест контакт "+str(i), role="tech", phone="+7 000 000 0000") for i in range(4)]
            self.foreign_person = CounterpartyContact(company_id=self.foreign.id, counterparty_id=self.foreign_cp.id, name="Чужой человек")
            db.add_all([*self.people, self.foreign_person])
            org = Organization(company_id=self.company.id, name="Тест юрлицо", inn="1")
            db.add(org); await db.flush()
            contract = Contract(company_id=self.company.id, counterparty_id=self.cps[0].id,
                organization_id=org.id, number="test", date="2026-10-23", type="energy", scope_type="locations")
            db.add(contract); await db.flush()
            db.add_all([ContractLocation(company_id=self.company.id, contract_id=contract.id, location_id=l.id) for l in self.locations])
            await db.commit()
        self.actor = self.member
        self.app = FastAPI(); self.app.include_router(location_contacts_router.router, prefix="/api")
        self.app.include_router(references_router.router, prefix="/api")
        async def user(): return self.actor
        async def session():
            async with self.sessions() as db:
                try:
                    yield db
                    await db.commit()
                except Exception:
                    await db.rollback(); raise
        self.app.dependency_overrides[get_current_user] = user
        self.app.dependency_overrides[get_db] = session
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()

    def path(self, site=0, person=None):
        result = "/api/references/locations/"+self.locations[site].id+"/contacts"
        return result + ("/"+str(self.people[person].id) if person is not None else "")

    async def assign(self, site=0, person=0, responsibility="Энергоснабжение"):
        return await self.client.put(self.path(site, person), json={"responsibility": responsibility})

    async def test_save_reload_retry_and_independent_responsibilities(self):
        r = await self.assign(responsibility="  Энергоснабжение  "); self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["responsibility"], "Энергоснабжение")
        await self.assign(responsibility="Допуск"); await self.assign(site=1, responsibility="Технические вопросы")
        a = (await self.client.get(self.path())).json(); b = (await self.client.get(self.path(1))).json()
        self.assertEqual(len(a["assigned"]), 1); self.assertEqual(a["assigned"][0]["responsibility"], "Допуск")
        self.assertEqual(b["assigned"][0]["responsibility"], "Технические вопросы")
        async with self.sessions() as db:
            self.assertEqual((await db.scalar(select(func.count()).select_from(LocationContact))), 2)
            self.assertEqual((await db.scalar(select(func.count()).select_from(CounterpartyContact))), 5)

    async def test_master_edit_updates_both_sites_without_copies(self):
        await self.assign(); await self.assign(site=1)
        r = await self.client.put(f"/api/references/counterparties/{self.cps[0].id}/contacts/{self.people[0].id}",
            json=dict(name="Новое имя", role="tech", position="Энергетик", phone="+7 000 000 0001", email="test@example.invalid"))
        self.assertEqual(r.status_code, 200, r.text)
        for site in range(2):
            a = (await self.client.get(self.path(site))).json()["assigned"][0]
            self.assertEqual((a["name"],a["position"],a["phone"]), ("Новое имя","Энергетик","+7 000 000 0001"))

    async def test_unassign_is_idempotent_and_keeps_person_other_site(self):
        await self.assign(); await self.assign(site=1)
        for _ in range(2): self.assertEqual((await self.client.delete(self.path(person=0))).status_code, 204)
        self.assertEqual((await self.client.get(self.path())).json()["assigned"], [])
        self.assertEqual(len((await self.client.get(self.path(1))).json()["assigned"]), 1)
        async with self.sessions() as db: self.assertIsNotNone(await db.get(CounterpartyContact, self.people[0].id))

    async def test_general_contacts_never_autoassign(self):
        a = (await self.client.get(self.path())).json()
        self.assertEqual(a["assigned"], []); self.assertEqual(len(a["organizationContacts"]), 2)
        await self.assign()
        self.assertEqual(len((await self.client.get(self.path())).json()["organizationContacts"]), 1)
        self.assertEqual((await self.client.get(self.path(1))).json()["assigned"], [])

    async def test_company_member_cannot_read_or_write_foreign_site(self):
        path = "/api/references/locations/foreign-site/contacts"
        for method, suffix, data in [("GET","",None),("GET","-options",None),
                ("PUT","/"+str(self.people[0].id),{"responsibility":"Тест"}),("DELETE","/"+str(self.people[0].id),None)]:
            url = path.replace('/contacts','/contact-options') if suffix=='-options' else path+suffix
            self.assertEqual((await self.client.request(method, url, json=data)).status_code, 404)

    async def test_cross_company_contact_rejected_even_for_superadmin(self):
        self.actor = self.admin
        r = await self.client.put(self.path()+"/"+str(self.foreign_person.id),json={"responsibility":"Тест"})
        self.assertEqual(r.status_code, 404)
        self.assertEqual((await self.client.get(self.path())).json()["assigned"], [])

    async def restrict(self):
        async with self.sessions() as db:
            membership = await db.get(UserCompany,(self.member.id,self.company.id))
            membership.object_scope=[self.locations[0].id]; await db.commit()

    async def test_scoped_member_only_sees_related_or_explicit_people(self):
        # An admin explicitly assigns one person from a non-contractual organization.
        await self.assign(person=2); await self.restrict()
        r = await self.client.get(self.path().replace('/contacts','/contact-options'))
        self.assertEqual(r.status_code, 200, r.text); data=r.json()
        self.assertFalse(data["canEditContacts"])
        self.assertEqual({c["id"] for c in data["contacts"]},{str(p.id) for p in self.people[:3]})
        self.assertEqual((await self.assign(person=3)).status_code, 404)
        self.assertEqual((await self.assign(person=0)).status_code, 200)
        self.assertEqual((await self.client.get(self.path(1))).status_code, 404)
        self.assertEqual((await self.client.delete(self.path(1,0))).status_code, 404)

    async def test_scoped_member_cannot_use_site_as_master_directory_write(self):
        await self.restrict()
        r=await self.client.put(f"/api/references/counterparties/{self.cps[0].id}/contacts/{self.people[0].id}",json=dict(name="Тест", role="tech"))
        self.assertEqual(r.status_code,404)

    async def test_blank_long_and_invalid_responsibility_does_not_change_assignment(self):
        await self.assign()
        for value in ("", "   ", "x"*201, None):
            self.assertEqual((await self.assign(responsibility=value)).status_code,422)
        a=(await self.client.get(self.path())).json()["assigned"]
        self.assertEqual(len(a),1);self.assertEqual(a[0]["responsibility"],"Энергоснабжение")

    async def test_unknown_identifiers_fail_without_disclosing_foreign_data(self):
        for url in (self.path()+"/"+str(uuid.uuid4()),self.path().replace('test-site-0','not-found')+"/"+str(self.people[0].id)):
            self.assertEqual((await self.client.put(url,json={"responsibility":"Тест"})).status_code,404)
        self.assertEqual((await self.client.put(self.path()+"/bad-id",json={"responsibility":"Тест"})).status_code,422)

    async def test_concurrent_retry_creates_one_assignment(self):
        responses=await asyncio.gather(self.assign(),self.assign())
        self.assertEqual([r.status_code for r in responses],[200,200])
        self.assertEqual(len((await self.client.get(self.path())).json()["assigned"]),1)

    async def test_contact_and_location_deletion_cascade_only_assignments(self):
        await self.assign();await self.assign(site=1)
        async with self.sessions() as db:
            await db.execute(delete(ServiceLocation).where(ServiceLocation.id==self.locations[0].id));await db.commit()
            self.assertEqual(await db.scalar(select(func.count()).select_from(LocationContact)),1)
            self.assertIsNotNone(await db.get(CounterpartyContact,self.people[0].id))
            await db.execute(delete(CounterpartyContact).where(CounterpartyContact.id==self.people[0].id));await db.commit()
            self.assertEqual(await db.scalar(select(func.count()).select_from(LocationContact)),0)
