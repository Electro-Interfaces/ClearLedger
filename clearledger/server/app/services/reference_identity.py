"""Общие правила тождества НСИ: строки/UUID, однозначность и ручной повтор.

Имена сохраняют организационно-правовую форму. Неполные реквизиты не доказывают
тождество; существующие дубли требуют решения человека, а не выбора первой строки.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import date, datetime


class IdentityConflict(ValueError):
    pass


def id_key(value) -> str:
    if value is None:
        return ""
    value = str(value).strip()
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return value


def json_ids(value):
    """JSONB не умеет UUID, в том числе внутри вложенного снимка источника."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_ids(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ids(v) for v in value]
    return value


def name_key(value) -> str:
    # ООО и АО с одинаковым именем остаются разными лицами.
    return re.sub(r"\s+", " ", str(value or "").casefold().translate(
        str.maketrans("", "", '"«»'))).strip()


def unique_candidate(candidates, label):
    found = {id_key(c.id): c for c in candidates}
    if len(found) > 1:
        raise IdentityConflict(f"Неоднозначное сопоставление {label}: "
                               + ", ".join(sorted(found)))
    return next(iter(found.values()), None)


class CounterpartyIndex:
    def __init__(self, rows=()):
        self.by_name = {}
        self.by_inn = {}
        for cp in rows:
            self.add(cp)

    def add(self, cp):
        source = (cp.raw or {}).get("referenceIdentity") or {}
        manual = set(getattr(cp, "manual_overrides", None) or [])
        names = [cp.name, *((cp.raw or {}).get("mergedNames") or [])]
        if "name" in manual and source.get("name"):
            names.append(source["name"])
        for name in names:
            if key := name_key(name):
                self.by_name.setdefault(key, {})[id_key(cp.id)] = cp
        for inn, _ in self.tax_versions(cp):
            if inn:
                self.by_inn.setdefault(inn, {})[id_key(cp.id)] = cp

    @staticmethod
    def tax_versions(cp):
        fields = ("inn", "kpp")
        current = tuple(str(getattr(cp, f) or "").strip() for f in fields)
        yield current
        source = (cp.raw or {}).get("referenceIdentity") or {}
        manual = set(getattr(cp, "manual_overrides", None) or [])
        if source and manual.intersection(fields):
            yield tuple(str(source.get(f, v) or "").strip() if f in manual else v
                        for f, v in zip(fields, current))

    def resolve(self, name, inn=None, kpp=None):
        inn = str(inn or "").strip()
        if inn:
            candidates = list(self.by_inn.get(inn, {}).values())
            if kpp:
                by_inn = candidates
                candidates = [c for c in candidates
                              if (inn, str(kpp).strip()) in self.tax_versions(c)]
                if not candidates and any((inn, "") in self.tax_versions(c) for c in by_inn):
                    raise IdentityConflict(f"Нужно сверить КПП контрагента «{name}»: "
                                           "есть карточка с тем же ИНН без КПП")
            # С известным ИНН нельзя выбирать только по имени и дописывать ИНН
            # неизвестному лицу: совпадение имени не доказывает тождество.
            if not candidates and any(not str(c.inn or "").strip() for c in
                                      self.by_name.get(name_key(name), {}).values()):
                raise IdentityConflict(f"Нужно сверить ИНН контрагента «{name}»: "
                                       "есть одноимённая карточка без ИНН")
        else:
            candidates = list(self.by_name.get(name_key(name), {}).values())
        return unique_candidate(candidates, f"контрагента «{name}»")


class ContractIndex:
    def __init__(self, rows=()):
        self.by_cp_type = {}
        for contract in rows:
            self.add(contract)

    def add(self, contract):
        for party, ctype, _, _ in self.versions(contract):
            key = (id_key(party), ctype)
            self.by_cp_type.setdefault(key, {})[id_key(contract.id)] = contract

    @staticmethod
    def versions(contract):
        fields = ("counterparty_id", "type", "number", "date")
        current = tuple(getattr(contract, f) for f in fields)
        yield current
        source = (getattr(contract, "raw", None) or {}).get("referenceIdentity") or {}
        manual = set(getattr(contract, "manual_overrides", None) or [])
        if source and manual.intersection(fields):
            yield tuple(source.get(f, v) if f in manual else v for f, v in zip(fields, current))

    def resolve(self, cp, ctype, number=None, cdate=None, organization_id=None):
        candidates = []
        party_keys = {id_key(cp.id), id_key(cp.external_ref)} - {""}
        for key in party_keys:
            if ctype is None:
                for (party, _), matches in self.by_cp_type.items():
                    if party == key:
                        candidates.extend(matches.values())
            else:
                candidates.extend(self.by_cp_type.get((key, ctype), {}).values())
        if organization_id is not None:
            candidates = [c for c in candidates if id_key(c.organization_id) == id_key(organization_id)]
        candidates = [c for c in candidates if any(
            id_key(party) in party_keys and (ctype is None or kind == ctype)
            and (not number or str(num).strip() == str(number).strip())
            and (not cdate or str(dt or "").strip() == str(cdate).strip())
            for party, kind, num, dt in self.versions(c))]
        return unique_candidate(candidates, f"договора «{number or 'без номера'}»")


def organization_for_import(organizations, contracts=()):
    """Только существующая Organization этой компании; выбор без догадок."""
    ids = {id_key(o.id) for o in organizations}
    used = {id_key(c.organization_id) for c in contracts} & ids
    candidates = used if len(used) == 1 else ids
    return next(iter(candidates)) if len(candidates) == 1 else None


def require_organization(org_id):
    if not org_id:
        raise IdentityConflict("Для создания договора нужна однозначная организация "
                               "в справочнике пространства (Organization)")
    return org_id


def counterparty_identity(inn, kpp):
    inn, kpp = str(inn or "").strip(), str(kpp or "").strip()
    if not inn.isascii() or not inn.isdigit():
        return None
    if len(inn) == 12 and not kpp:
        return inn, ""
    if len(inn) == 10 and (not kpp or (len(kpp) == 9 and kpp.isascii() and kpp.isdigit())):
        return inn, kpp
    return None


def contract_identity(number, cdate, ctype):
    number, cdate, ctype = (str(v or "").strip() for v in (number, cdate, ctype))
    # Без номера/даты/вида нельзя отличить самостоятельные обязательства.
    if not number or not ctype or not cdate:
        return None
    try:
        cdate = date.fromisoformat(cdate).isoformat()
    except ValueError:
        return None
    return number, cdate, ctype


async def lock_manual_creation(db, company_id, entity):
    """Блокировка ручного и импортного создания до COMMIT/ROLLBACK.

    Проверка и INSERT находятся в одной транзакции.

    На компанию/вид НСИ, чтобы эквивалентные представления реквизитов не могли
    взять разные блокировки. Не является ограничением UNIQUE для старых данных.
    """
    from sqlalchemy import text
    payload = json.dumps(["reference-create-v1", id_key(company_id), entity])
    lock_id = int.from_bytes(hashlib.sha256(payload.encode()).digest()[:8], "big", signed=True)
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_id})
