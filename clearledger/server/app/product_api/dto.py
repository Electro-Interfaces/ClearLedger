"""Public allowlists. No ORM/raw/secret objects are serialized implicitly."""
from datetime import date, datetime
import re
from typing import Annotated, Generic, Literal, TypeAliasType, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

Id = TypeAliasType("Id", Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$")])
# Native ServiceLocation String(40), including exact Unicode/space identity.
# Path addressability is a separate transport limitation; never normalize IDs.
ObjectId = TypeAliasType("ObjectId", Annotated[str, Field(min_length=1, max_length=40, pattern=r"^[^\x00]+$")])


class DTO(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True,
                              extra="forbid", allow_inf_nan=False)


class ListQuery(BaseModel):
    # Direct wire names avoid FastAPI 0.115/Pydantic alias metadata rebuilding.
    model_config = ConfigDict(extra="forbid")
    pageSize: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)
    q: str | None = Field(default=None, min_length=1, max_length=100)
    dateFrom: date | None = None
    dateTo: date | None = None

    @field_validator("dateFrom", "dateTo", mode="before")
    @classmethod
    def iso_date_only(cls, value):
        if value is None or type(value) is date:
            return value
        if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
            raise ValueError("ISO calendar date required")
        return value

    @property
    def page_size(self):
        return self.pageSize

    @property
    def date_from(self):
        return self.dateFrom

    @property
    def date_to(self):
        return self.dateTo

    @model_validator(mode="after")
    def valid_window(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Invalid date window")
        return self


class ContractListQuery(ListQuery):
    typeCode: str | None = Field(default=None, min_length=1, max_length=256, pattern=r"^[^\x00]+$",
        description="Exact source classifier code; case and whitespace are significant. No global enum.")


class ContractTypeMetadataQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    typeCode: str = Field(min_length=1, max_length=256, pattern=r"^[^\x00]+$",
        description="Exact code from an independently visible contract; not a global catalog selector.")


class ContractTypeMetadata(DTO):
    type_code: str
    label: str | None
    gk_basis: str | None
    direction: str | None
    is_active: bool | None


class EmptyQuery(DTO):
    pass


class ContractObjectsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageSize: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)

    @property
    def page_size(self):
        return self.pageSize


class ContractObject(DTO):
    object_id: ObjectId


class ContractObjects(DTO):
    contract_id: Id
    scope_type: str
    items: list[ContractObject]
    total: int = Field(ge=0)
    next_cursor: str | None


class ContractDocumentsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageSize: int = Field(default=50, ge=1, le=200)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)

    @property
    def page_size(self):
        return self.pageSize


class ContractDocument(DTO):
    document_id: Id


class ContractDocuments(DTO):
    contract_id: Id
    items: list[ContractDocument]
    total: int = Field(ge=0)
    next_cursor: str | None


class MonitoringQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=90, ge=1, le=366)
    asOf: date | None = None

    @field_validator("asOf", mode="before")
    @classmethod
    def iso_date_only(cls, value):
        return ListQuery.iso_date_only(value)


class MonitoringWindow(DTO):
    days: int = Field(ge=1, le=366)
    start: datetime
    end: datetime
    time_zone: Literal["Europe/Moscow"] = "Europe/Moscow"
    interval: Literal["inclusive"] = "inclusive"


class MonitoringTotals(DTO):
    sessions: int = Field(ge=0)
    visits: int = Field(ge=0)
    successful_visits: int = Field(ge=0)
    unsuccessful_visits: int = Field(ge=0)
    energy_kwh: float


class MonitoringProvenance(DTO):
    as_of: datetime
    data_through: datetime | None
    data_lag_hours: float | None
    requested_date: date | None
    catalog_mode: Literal["current"]
    snapshot_note: str
    boundary_scope: Literal["object"] = "object"
    source: Literal["charge_sessions"] = "charge_sessions"
    visit_success: Literal["any attempt energy_kwh > 0"] = "any attempt energy_kwh > 0"


class Monitoring(DTO):
    point_id: ObjectId
    status: Literal["working", "no_link", "disabled", "decommissioned", "on_repair",
                    "maintenance", "not_working", "unknown"]
    window: MonitoringWindow
    totals: MonitoringTotals
    last_seen_at: datetime | None
    provenance: MonitoringProvenance


class Object(DTO):
    id: ObjectId
    level: Literal["servicePoint"] = "servicePoint"
    code: str
    name: str
    type: str
    status: str
    address: str | None
    latitude: float | None
    longitude: float | None


class Equipment(DTO):
    id: Id
    level: Literal["station"] = "station"
    vendor: str | None
    model: str | None
    serial_number: str | None
    power_kw: float | None
    state: str
    object_id: ObjectId | None


class Counterparty(DTO):
    id: Id
    name: str
    inn: str | None
    kpp: str | None


class Contract(DTO):
    type_code: str | None = Field(description="Source Contract.type_code, including unknown or empty codes. No legal inference.")
    valid_until: str | None = Field(max_length=20,
        description="Exact native validity value. Nullable source string, not a validated ISO date; null is unknown, not perpetual.")
    id: Id
    number: str
    date: date | None
    title: str | None
    is_closed: bool
    scope_type: str
    counterparty_id: Id | None


class Document(DTO):
    id: Id
    title: str
    status: str
    registration_number: str | None
    registration_date: date | None
    current_revision: int
    object_id: ObjectId | None
    counterparty_id: Id | None


class Version(DTO):
    id: Id
    revision: int
    role: str
    file_name: str
    mime_type: str | None
    size_bytes: int


class DocumentDetail(Document):
    versions: list[Version]
    versions_truncated: bool


T = TypeVar("T", bound=DTO)


class Page(DTO, Generic[T]):
    items: list[T]
    next_cursor: str | None
    total: int


class Problem(DTO):
    type: str = "about:blank"
    title: str
    status: int
    code: str
    request_id: str
    detail: str
