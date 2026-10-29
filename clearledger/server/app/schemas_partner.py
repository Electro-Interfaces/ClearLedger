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
