"""Immutable server-side access facts. No HTTP parsing, ORM or token issuance."""
from dataclasses import dataclass, replace
from enum import Enum
from typing import Iterable


class PrincipalKind(str, Enum):
    USER = "user"
    PARTNER = "partner"
    SERVICE = "service"
    PUBLIC = "public"


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
class AccessContext:
    principal: Principal
    company_id: str | None
    policy_version: str
    scopes: frozenset[str] = frozenset()
    permissions: tuple[ResourcePermission, ...] = ()
    valid: bool = False

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

    def permission(self, resource_type: str, action: str) -> ResourcePermission:
        return next((item for item in self.permissions
                     if (item.resource_type, item.action) == (resource_type, action)),
                    ResourcePermission(resource_type, action))

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
        return replace(self, scopes=self.scopes & other.scopes, permissions=permissions,
                       valid=self.valid and other.valid)

    def select(self, resource_type: str, action: str, selection: ResourceScope) -> "AccessContext":
        permission = self.permission(resource_type, action)
        narrowed = replace(permission, resources=permission.resources.intersect(selection))
        return replace(self, permissions=tuple(
            narrowed if (item.resource_type, item.action) == (resource_type, action) else item
            for item in self.permissions))
