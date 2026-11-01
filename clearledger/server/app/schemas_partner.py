"""Developer administration DTOs, camelCase on the HTTP boundary."""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PartnerDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterClient(PartnerDTO):
    companyId: UUID
    name: str = Field(min_length=1, max_length=120)
    redirectUris: list[str] = Field(min_length=1, max_length=10)
    scopes: list[str] = Field(default_factory=list, max_length=50)
    authMethod: Literal["none", "client_secret_basic"] = "none"


class ResourceSelection(PartnerDTO):
    mode: Literal["ALL", "SET", "EMPTY"] = "EMPTY"
    ids: list[str] = Field(default_factory=list, max_length=1000)


class ApproveInstallation(PartnerDTO):
    companyId: UUID
    scopes: list[str] = Field(max_length=50)
    # Null explicitly grants all locations; [] explicitly grants none.
    locationIds: list[str] | None = Field(default_factory=list, max_length=1000)
    resourceScopes: dict[Literal["objects", "equipment", "counterparties", "contracts", "documents"], ResourceSelection] = Field(default_factory=dict)


class ApproveConsent(PartnerDTO):
    companyId: UUID
    scopes: list[str] = Field(max_length=50)


class ApproveMachineGrant(PartnerDTO):
    scopes: list[str] = Field(max_length=50)


class SetEnabled(PartnerDTO):
    enabled: bool


# CREATE-профиль — настройка allowlists, а не допуск к внешней записи.
from typing import Annotated
from pydantic import BeforeValidator, model_validator


def _profile_uuid(value):
    if type(value) is UUID:
        return value
    if type(value) is not str:
        raise ValueError("Canonical UUID required")
    parsed = UUID(value)
    if str(parsed) != value.lower():
        raise ValueError("Canonical UUID required")
    return parsed


def _profile_text(value):
    if type(value) is not str or not value.strip() or "\x00" in value:
        raise ValueError("Exact nonblank text required")
    value.encode("utf-8", errors="strict")
    return value


def _profile_list(value):
    if type(value) not in (list, tuple) or len(value) > 100:
        raise ValueError("Bounded list required")
    try:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate identifiers")
    except TypeError:
        raise ValueError("Scalar identifiers required") from None
    return tuple(value)


_ProfileUUID = Annotated[UUID, BeforeValidator(_profile_uuid)]
_ProfileLocation = Annotated[str, Field(min_length=1, max_length=40), BeforeValidator(_profile_text)]
_ProfileType = Annotated[str, Field(min_length=1, max_length=256), BeforeValidator(_profile_text)]
_ProfileGeneration = Annotated[int, Field(strict=True, ge=1, le=9223372036854775807)]


class ReplaceContractCreateProfile(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    expectedGeneration: _ProfileGeneration | None = None
    revoked: bool = False
    userIds: Annotated[tuple[_ProfileUUID, ...], BeforeValidator(_profile_list)]
    machineGrantIds: Annotated[tuple[_ProfileUUID, ...], BeforeValidator(_profile_list)]
    organizationIds: Annotated[tuple[_ProfileUUID, ...], BeforeValidator(_profile_list)]
    counterpartyIds: Annotated[tuple[_ProfileUUID, ...], BeforeValidator(_profile_list)]
    locationIds: Annotated[tuple[_ProfileLocation, ...], BeforeValidator(_profile_list)]
    typeCodes: Annotated[tuple[_ProfileType, ...], BeforeValidator(_profile_list)]

    @model_validator(mode="after")
    def unique_typed_identifiers(self):
        # Upper/lower UUID spelling cannot smuggle duplicate logical IDs.
        for name in ("userIds", "machineGrantIds", "organizationIds", "counterpartyIds", "locationIds", "typeCodes"):
            items = getattr(self, name)
            if len(set(items)) != len(items):
                raise ValueError("Duplicate identifiers")
        return self


class ContractCreateProfileReadback(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")

    profileId: UUID
    installationId: UUID
    clientId: str
    companyId: UUID
    policyGeneration: _ProfileGeneration
    userEnabled: bool
    serviceEnabled: bool
    revoked: bool
    userIds: tuple[UUID, ...]
    machineGrantIds: tuple[UUID, ...]
    organizationIds: tuple[UUID, ...]
    counterpartyIds: tuple[UUID, ...]
    locationIds: tuple[str, ...]
    typeCodes: tuple[str, ...]
