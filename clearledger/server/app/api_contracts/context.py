"""Immutable server-side access facts. No HTTP parsing, ORM or token issuance."""
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Iterable
from uuid import UUID


class PrincipalKind(str, Enum):
    USER = "user"
    PARTNER = "partner"
    SERVICE = "service"
    PUBLIC = "public"


class DatabaseAuthorityKind(str, Enum):
    PARTNER_CONTRACT_RECEIPT_V1 = "partner-contract-receipt-v1"


class PartnerContractReceiptEvidence(str, Enum):
    CURRENT_ELIGIBLE_RECEIPT_EXISTS = "current-eligible-receipt-exists"


class ScopeMode(str, Enum):
    ALL = "all"
    SET = "set"
    EMPTY = "empty"
    UNINITIALIZED = "uninitialized"


def _names(values: Iterable[str]) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError("Expected a collection of identifiers")
    result = frozenset(values)
    if any(not isinstance(value, str) or not value.strip() for value in result):
        raise ValueError("Identifiers must be nonempty strings")
    return result


@dataclass(frozen=True)
class ResourceScope:
    mode: ScopeMode = ScopeMode.UNINITIALIZED
    ids: frozenset[str] = frozenset()

    def __post_init__(self):
        if not isinstance(self.mode, ScopeMode):
            raise ValueError("Explicit ScopeMode required")
        object.__setattr__(self, "ids", _names(self.ids))
        if self.mode is ScopeMode.SET and not self.ids:
            object.__setattr__(self, "mode", ScopeMode.EMPTY)
        if self.mode is not ScopeMode.SET and self.ids:
            raise ValueError("Only SET can contain identifiers")

    @classmethod
    def all(cls):
        return cls(ScopeMode.ALL)

    @classmethod
    def selected(cls, ids: Iterable[str]):
        return cls(ScopeMode.SET, _names(ids))

    @classmethod
    def empty(cls):
        return cls(ScopeMode.EMPTY)

    def contains(self, ids: Iterable[str]) -> bool:
        requested = _names(ids)
        if self.mode in (ScopeMode.EMPTY, ScopeMode.UNINITIALIZED):
            return False
        return self.mode is ScopeMode.ALL or requested <= self.ids

    def intersect(self, other: "ResourceScope") -> "ResourceScope":
        if not isinstance(other, ResourceScope):
            raise TypeError("ResourceScope required")
        # Missing authority never becomes an initialized permission.
        if ScopeMode.UNINITIALIZED in (self.mode, other.mode):
            return ResourceScope()
        if ScopeMode.EMPTY in (self.mode, other.mode):
            return ResourceScope.empty()
        if self.mode is ScopeMode.ALL:
            return other
        if other.mode is ScopeMode.ALL:
            return self
        return ResourceScope.selected(self.ids & other.ids)


@dataclass(frozen=True)
class Principal:
    kind: PrincipalKind
    subject: str | None = None
    client_id: str | None = None
    installation_id: str | None = None
    grant_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.kind, PrincipalKind):
            raise ValueError("Explicit principal kind required")
        for value in (self.subject, self.client_id, self.installation_id, self.grant_id):
            if value is not None:
                _names([value])
        if self.kind is not PrincipalKind.PUBLIC and self.subject is None:
            raise ValueError("Authenticated principal requires a subject")
        if self.kind in (PrincipalKind.PARTNER, PrincipalKind.SERVICE):
            if not self.client_id or not self.grant_id:
                raise ValueError("Machine principal requires client and grant")
        if self.kind is PrincipalKind.PUBLIC and any(
            (self.subject, self.client_id, self.installation_id, self.grant_id)
        ):
            raise ValueError("Public principal cannot carry authenticated identity")


@dataclass(frozen=True)
class ResourcePermission:
    resource_type: str
    action: str
    resources: ResourceScope = ResourceScope()
    fields: ResourceScope = ResourceScope()

    def __post_init__(self):
        _names([self.resource_type, self.action])
        if type(self.resources) is not ResourceScope or type(self.fields) is not ResourceScope:
            raise ValueError("Explicit resource and field scopes required")

    def intersect(self, other: "ResourcePermission") -> "ResourcePermission":
        if (self.resource_type, self.action) != (other.resource_type, other.action):
            raise ValueError("Cannot intersect different resource actions")
        return replace(self, resources=self.resources.intersect(other.resources),
                       fields=self.fields.intersect(other.fields))


@dataclass(frozen=True)
class PartnerContractReceiptBinding:
    """Independent current server binding; never unverified HTTP authority input."""
    app_id: UUID
    create_profile_id: UUID
    policy_generation: int

    def __post_init__(self):
        if (type(self.app_id) is not UUID or type(self.create_profile_id) is not UUID
                or type(self.policy_generation) is not int or self.policy_generation <= 0):
            raise ValueError("Exact app/profile UUIDs and positive policy generation required")


@dataclass(frozen=True)
class DatabaseResourcePermission:
    """Named server evidence, with no resource IDs, SQL callback or bearer encoding.

    This admits only an explicitly opted-in guard. It is not SQL authority:
    the query owner must revalidate current receipt eligibility in its transaction.
    """
    authority_kind: DatabaseAuthorityKind
    company_id: str
    principal: Principal
    policy_version: str
    binding: PartnerContractReceiptBinding
    evidence: PartnerContractReceiptEvidence
    resource_type: str = "contracts"
    action: str = "read"

    def __post_init__(self):
        if (type(self.authority_kind) is not DatabaseAuthorityKind
                or self.authority_kind is not DatabaseAuthorityKind.PARTNER_CONTRACT_RECEIPT_V1
                or type(self.evidence) is not PartnerContractReceiptEvidence
                or self.evidence is not PartnerContractReceiptEvidence.CURRENT_ELIGIBLE_RECEIPT_EXISTS
                or type(self.principal) is not Principal
                or type(self.principal.kind) is not PrincipalKind
                or self.principal.kind not in (PrincipalKind.PARTNER, PrincipalKind.SERVICE)
                or type(self.binding) is not PartnerContractReceiptBinding
                or type(self.resource_type) is not str or self.resource_type != "contracts"
                or type(self.action) is not str or self.action != "read"):
            raise ValueError("Exact named contracts-read receipt evidence required")
        self.binding.__post_init__()
        values = (self.company_id, self.policy_version, self.principal.subject,
                  self.principal.client_id, self.principal.installation_id, self.principal.grant_id)
        if any(type(value) is not str or not value.strip() for value in values):
            raise ValueError("Complete server identity and original grant binding required")

    def matches(self, context: "AccessContext", resource_type: str, action: str) -> bool:
        # Recheck shape as well as equality; string-enums/bools/subclasses cannot
        # masquerade as typed evidence, even in a malformed server-built object.
        try:
            if (type(self) is not DatabaseResourcePermission
                    or type(context.receipt_read_binding) is not PartnerContractReceiptBinding
                    or type(context.principal) is not Principal
                    or type(resource_type) is not str or type(action) is not str):
                return False
            current_values = (context.company_id, context.policy_version, context.principal.subject,
                              context.principal.client_id, context.principal.installation_id,
                              context.principal.grant_id)
            if any(type(value) is not str or not value.strip() for value in current_values):
                return False
            self.__post_init__()
            context.receipt_read_binding.__post_init__()
        except (ValueError, TypeError, AttributeError):
            return False
        return ((resource_type, action) == (self.resource_type, self.action)
                and self.company_id == context.company_id
                and type(context.principal) is Principal
                and type(context.principal.kind) is PrincipalKind and self.principal == context.principal
                and self.policy_version == context.policy_version
                and self.binding == context.receipt_read_binding)


# Server-only identity binding. This descriptor is admission metadata, never
# SQL evidence, a CREATE capability, a resource grant, or a read receipt.
CREATE_PREFLIGHT_KEY = "elsy.api_contracts.create_preflight"


@dataclass(frozen=True, eq=False)
class CreateNewbornPreflight:
    request: object = field(repr=False)
    company_id: str
    principal: Principal
    policy_version: str
    operation_id: str = "createContract"

    def matches(self, context: "AccessContext", request: object) -> bool:
        return (type(self) is CreateNewbornPreflight and request is self.request
                and request.scope.get(CREATE_PREFLIGHT_KEY) is self
                and type(context.principal) is Principal
                and context.principal == self.principal
                and self.principal.kind in (PrincipalKind.PARTNER, PrincipalKind.SERVICE)
                and bool(self.company_id) and self.company_id == context.company_id
                and self.policy_version == context.policy_version
                and self.operation_id == "createContract"
                and request.scope["route"].operation_id == self.operation_id
                and request.method == "POST" and "contracts:create" in context.scopes)


CREATE_OPTIONS_KEY = "elsy.api_contracts.create_options"


@dataclass(frozen=True, eq=False)
class CreateOptionsPreflight:
    """Exact request admission only; carries no SQL or resource authority."""
    request: object = field(repr=False)
    company_id: str
    principal: Principal
    policy_version: str
    operation_id: str = "getContractCreateOptions"

    def matches(self, context: "AccessContext", request: object) -> bool:
        return (type(self) is CreateOptionsPreflight and request is self.request
                and request.scope.get(CREATE_OPTIONS_KEY) is self
                and type(context.principal) is Principal and context.principal == self.principal
                and self.principal.kind in (PrincipalKind.PARTNER, PrincipalKind.SERVICE)
                and bool(self.company_id) and context.company_id == self.company_id
                and context.policy_version == self.policy_version
                and self.operation_id == "getContractCreateOptions"
                and request.scope["route"].operation_id == self.operation_id
                and request.scope["route"].path == "/contracts/create-options"
                and request.method == "GET" and "contracts:create" in context.scopes
                and context.permissions == () and context.database_permissions == ()
                and context.receipt_read_binding is None and context.create_preflight is None)


@dataclass(frozen=True)
class AccessContext:
    principal: Principal
    company_id: str | None
    policy_version: str
    scopes: frozenset[str] = frozenset()
    permissions: tuple[ResourcePermission, ...] = ()
    valid: bool = False
    database_permissions: tuple[DatabaseResourcePermission, ...] = ()
    receipt_read_binding: PartnerContractReceiptBinding | None = None
    create_preflight: CreateNewbornPreflight | None = None
    create_options: CreateOptionsPreflight | None = None

    def __post_init__(self):
        if type(self.principal) is not Principal or type(self.valid) is not bool:
            raise ValueError("Server Principal and validation verdict required")
        _names([self.policy_version])
        if self.company_id is not None:
            _names([self.company_id])
        object.__setattr__(self, "scopes", _names(self.scopes))
        object.__setattr__(self, "permissions", tuple(self.permissions))
        if any(type(item) is not ResourcePermission for item in self.permissions):
            raise ValueError("ResourcePermission required")
        keys = [(item.resource_type, item.action) for item in self.permissions]
        if len(keys) != len(set(keys)):
            raise ValueError("Ambiguous duplicate resource action")
        if self.create_preflight is not None and type(self.create_preflight) is not CreateNewbornPreflight:
            raise ValueError("Exact server CREATE preflight required")
        if self.create_options is not None and type(self.create_options) is not CreateOptionsPreflight:
            raise ValueError("Exact server CREATE_OPTIONS preflight required")
        if self.receipt_read_binding is not None:
            if type(self.receipt_read_binding) is not PartnerContractReceiptBinding:
                raise ValueError("Exact current receipt binding required")
            self.receipt_read_binding.__post_init__()
        object.__setattr__(self, "database_permissions", tuple(self.database_permissions))
        if any(type(item) is not DatabaseResourcePermission for item in self.database_permissions):
            raise ValueError("Exact DatabaseResourcePermission required")
        for item in self.database_permissions:
            item.__post_init__()
        database_keys = [(item.authority_kind, item.resource_type, item.action)
                         for item in self.database_permissions]
        if len(database_keys) != len(set(database_keys)):
            raise ValueError("Ambiguous duplicate database authority")

    def permission(self, resource_type: str, action: str) -> ResourcePermission:
        return next((item for item in self.permissions
                     if (item.resource_type, item.action) == (resource_type, action)),
                    ResourcePermission(resource_type, action))

    def permits_database_authority(self, accepted_kinds: frozenset[DatabaseAuthorityKind],
                                   resource_type: str, action: str) -> bool:
        if not accepted_kinds:
            return False
        return any(type(item) is DatabaseResourcePermission
                   and item.matches(self, resource_type, action)
                   and item.authority_kind in accepted_kinds for item in self.database_permissions)

    def intersect(self, other: "AccessContext") -> "AccessContext":
        # Identity/grant substitution needs an explicit delegation protocol.
        # An admin/user context cannot replace a narrower partner identity.
        if (type(other) is not AccessContext or self.principal != other.principal
                or self.company_id != other.company_id
                or self.policy_version != other.policy_version):
            raise ValueError("Different identity, tenant or policy version")
        own = {(item.resource_type, item.action): item for item in self.permissions}
        ceiling = {(item.resource_type, item.action): item for item in other.permissions}
        permissions = tuple(own[key].intersect(ceiling[key]) for key in sorted(own.keys() & ceiling.keys()))
        binding = self.receipt_read_binding if self.receipt_read_binding == other.receipt_read_binding else None
        database_permissions = tuple(item for item in self.database_permissions
                                     if binding is not None and item in other.database_permissions)
        return replace(self, scopes=self.scopes & other.scopes, permissions=permissions,
                       valid=self.valid and other.valid, database_permissions=database_permissions,
                       receipt_read_binding=binding, create_preflight=None, create_options=None)

    def select(self, resource_type: str, action: str, selection: ResourceScope) -> "AccessContext":
        permission = self.permission(resource_type, action)
        narrowed = replace(permission, resources=permission.resources.intersect(selection))
        return replace(self, permissions=tuple(
            narrowed if (item.resource_type, item.action) == (resource_type, action) else item
            for item in self.permissions), database_permissions=tuple(
                item for item in self.database_permissions
                if (item.resource_type, item.action) != (resource_type, action)))
