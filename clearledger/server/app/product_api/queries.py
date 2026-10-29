"""Read projections with explicit tenant/resource/user conditions before limits."""
import base64
import hashlib
import hmac
import json
import uuid
from datetime import date, datetime, time, timezone

from fastapi import HTTPException
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.sql.sqltypes import Uuid

from app.api_contracts import ScopeMode
from app.models import Contract, ContractLocation, Counterparty, DocCard, EzsEquipmentUnit, ServiceLocation
from . import dto
from .access import READ_SCOPES

MODELS = {"objects": ServiceLocation, "equipment": EzsEquipmentUnit, "counterparties": Counterparty,
          "contracts": Contract, "documents": DocCard}
SEARCH = {"objects": ServiceLocation.name, "equipment": EzsEquipmentUnit.serial_number,
          "counterparties": Counterparty.name, "contracts": Contract.number, "documents": DocCard.title}


def native_id(column, value):
    if isinstance(column.type, Uuid):
        try:
            return uuid.UUID(value)
        except (ValueError, TypeError, AttributeError):
            return None
    return value


def scope_clause(column, scope):
    if scope.mode is ScopeMode.ALL:
        return column.is_not(None)
    if scope.mode is not ScopeMode.SET:
        return false()
    values = [native_id(column, value) for value in scope.ids]
    return column.in_([value for value in values if value is not None])


class Query:
    def __init__(self, db, facts, context, cursor_key):
        self.db, self.facts, self.context, self.cursor_key = db, facts, context, cursor_key

    def contract_domain(self):
        f = self.facts
        conditions = [Contract.company_id == f.company_id]
        if f.organization_id is not None:
            conditions.append(Contract.organization_id == f.organization_id)
        if f.objects.mode is not ScopeMode.ALL:
            conditions += [Contract.scope_type == "locations", select(ContractLocation.id).where(
                ContractLocation.company_id == f.company_id,
                ContractLocation.contract_id == Contract.id,
                scope_clause(ContractLocation.location_id, f.objects),
            ).correlate(Contract).exists()]
        return conditions

    def organization_location(self, column):
        return select(ContractLocation.id).join(Contract, and_(
            Contract.id == ContractLocation.contract_id, Contract.company_id == self.facts.company_id,
        )).where(ContractLocation.company_id == self.facts.company_id,
                 ContractLocation.location_id == column,
                 Contract.scope_type == "locations",
                 Contract.organization_id == self.facts.organization_id).correlate(column.table).exists()

    async def conditions(self, resource):
        f, model = self.facts, MODELS[resource]
        conditions = [model.company_id == f.company_id, scope_clause(model.id, f.grants[resource])]
        if resource == "objects":
            conditions.append(scope_clause(model.id, f.objects))
            if f.organization_id is not None:
                conditions.append(self.organization_location(model.id))
        elif resource == "equipment":
            conditions.append(model.kind == "station")
            if f.objects.mode is not ScopeMode.ALL:
                conditions.append(scope_clause(model.current_location_id, f.objects))
            if f.organization_id is not None:
                conditions.append(self.organization_location(model.current_location_id))
        elif resource == "contracts":
            conditions.extend(self.contract_domain())
        elif resource == "counterparties":
            conditions.append(model.is_group.is_(False))
            if f.organization_id is not None or f.objects.mode is not ScopeMode.ALL:
                conditions.append(select(Contract.id).where(
                    *self.contract_domain(), Contract.counterparty_id == model.id,
                ).correlate(model).exists())
        elif resource == "documents":
            if f.user is None:
                conditions.append(false())
            else:
                from app.services.doc_access import _readable_doc_clause
                conditions.append(await _readable_doc_clause(self.db, f.company_id, f.user))
            if f.objects.mode is not ScopeMode.ALL:
                conditions.append(scope_clause(model.object_id, f.objects))
            if f.organization_id is not None:
                conditions.append(model.organization_id == f.organization_id)
        return conditions

    def binding(self, resource, params):
        def scope(value):
            return [value.mode.value, sorted(value.ids)]
        principal = self.context.principal
        value = {"resource": resource, "company": self.context.company_id,
                 "subject": principal.subject, "client": principal.client_id,
                 "installation": principal.installation_id, "grant": principal.grant_id,
                 "policy": self.context.policy_version, "scopes": sorted(self.context.scopes),
                 "objects": scope(self.facts.objects), "organization": str(self.facts.organization_id),
                 "grants": {key: scope(value) for key, value in self.facts.grants.items()},
                 "filter": params.model_dump(mode="json", exclude={"cursor"})}
        return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

    def encode_cursor(self, row, binding):
        payload = json.dumps({"v": 1, "at": row.created_at.isoformat(), "id": str(row.id),
                              "binding": binding}, sort_keys=True).encode()
        signature = hmac.digest(self.cursor_key, payload, "sha256")
        return base64.urlsafe_b64encode(signature + payload).decode().rstrip("=")

    def decode_cursor(self, raw, binding):
        try:
            data = base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True)
            signature, payload = data[:32], data[32:]
            if not hmac.compare_digest(signature, hmac.digest(self.cursor_key, payload, "sha256")):
                raise ValueError()
            value = json.loads(payload)
            if value["v"] != 1 or value["binding"] != binding:
                raise ValueError()
            timestamp = datetime.fromisoformat(value["at"])
            if timestamp.tzinfo is None:
                raise ValueError()
            return timestamp, value["id"]
        except (ValueError, TypeError, KeyError, UnicodeError):
            raise HTTPException(400, "Invalid cursor") from None

    async def listing(self, resource, params):
        model = MODELS[resource]
        conditions = await self.conditions(resource)
        if params.q is not None:
            conditions.append(SEARCH[resource].ilike("%" + params.q + "%"))
        if params.date_from is not None:
            conditions.append(model.created_at >= datetime.combine(params.date_from, time(), timezone.utc))
        if params.date_to is not None:
            conditions.append(model.created_at <= datetime.combine(params.date_to, time.max, timezone.utc))
        binding = self.binding(resource, params)
        cursor = self.decode_cursor(params.cursor, binding) if params.cursor else None
        total = await self.db.scalar(select(func.count()).select_from(model).where(*conditions))
        if cursor:
            at, last_id = cursor
            last_id = native_id(model.id, last_id)
            if last_id is None:
                raise HTTPException(400, "Invalid cursor")
            conditions.append(or_(model.created_at > at, and_(model.created_at == at, model.id > last_id)))
        rows = list((await self.db.scalars(select(model).where(*conditions).order_by(
            model.created_at, model.id).limit(params.page_size + 1))).all())
        has_more = len(rows) > params.page_size
        rows = rows[:params.page_size]
        return {"items": await self.project(resource, rows), "total": total,
                "next_cursor": self.encode_cursor(rows[-1], binding) if has_more else None}

    async def detail(self, resource, identifier):
        model = MODELS[resource]
        value = native_id(model.id, identifier)
        if value is None:
            raise HTTPException(404, "Not found")
        row = await self.db.scalar(select(model).where(*await self.conditions(resource), model.id == value))
        if row is None:
            raise HTTPException(404, "Not found")
        return row

    async def visible_links(self, resource, ids):
        ids = {value for value in ids if value is not None}
        if (not ids or READ_SCOPES[resource] not in self.context.scopes
                or not self.facts.grants[resource].contains([])):
            return set()
        model = MODELS[resource]
        return set((await self.db.scalars(select(model.id).where(
            *await self.conditions(resource), model.id.in_(ids)))).all())

    async def project(self, resource, rows):
        objects, parties = set(), set()
        if resource in ("equipment", "documents"):
            objects = await self.visible_links("objects", [getattr(row, "current_location_id", None)
                        if resource == "equipment" else row.object_id for row in rows])
        if resource in ("contracts", "documents"):
            parties = await self.visible_links("counterparties", [row.counterparty_id for row in rows])
        output = []
        for row in rows:
            if resource == "objects":
                value = dto.Object(id=str(row.id), code=row.code, name=row.name, type=row.type,
                                   status=row.status, address=row.address, latitude=row.latitude, longitude=row.longitude)
            elif resource == "equipment":
                value = dto.Equipment(id=str(row.id), vendor=row.vendor, model=row.model,
                    serial_number=row.serial_number, power_kw=row.power_kwt, state=row.state,
                    object_id=row.current_location_id if row.current_location_id in objects else None)
            elif resource == "counterparties":
                value = dto.Counterparty(id=str(row.id), name=row.name, inn=row.inn, kpp=row.kpp)
            elif resource == "contracts":
                try:
                    contract_date = date.fromisoformat(row.date)
                except (ValueError, TypeError):
                    contract_date = None
                value = dto.Contract(id=str(row.id), number=row.number, date=contract_date, title=row.title,
                    is_closed=row.is_closed, scope_type=row.scope_type,
                    counterparty_id=str(row.counterparty_id) if row.counterparty_id in parties else None)
            else:
                value = dto.Document(id=str(row.id), title=row.title, status=row.status,
                    registration_number=row.reg_number, registration_date=row.reg_date, current_revision=row.current_revision,
                    object_id=row.object_id if row.object_id in objects else None,
                    counterparty_id=str(row.counterparty_id) if row.counterparty_id in parties else None)
            output.append(value)
        return output
