"""Public allowlists. No ORM/raw/secret objects are serialized implicitly."""
from datetime import date, datetime
import re
from typing import Annotated, Generic, Literal, TypeAliasType, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

Id = TypeAliasType("Id", Annotated[str, Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:\-]*$",
        description=(
            'Opaque non-Object identifier, 1..128 characters with the documented pattern. Preserve '
            'exact value; native UUID-backed lookups may return 404 for other syntactically valid '
            'strings.'
        ),
        examples=['30000000-0000-4000-8000-000000000001'])])
# Native ServiceLocation String(40), including exact Unicode/space identity.
# Path addressability is a separate transport limitation; never normalize IDs.
ObjectId = TypeAliasType("ObjectId", Annotated[str, Field(
        min_length=1,
        max_length=40,
        pattern=r"^[^\x00]+$",
        description=(
            'Exact opaque native service-point ID, 1..40 Unicode characters without NUL. Preserve '
            'case and whitespace, never UUID-parse or normalize; path transport addressability is '
            'separate.'
        ),
        examples=['20000000-0000-4000-8000-000000000001', 'Учебная точка 1'])])


class DTO(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True,
                              extra="forbid", allow_inf_nan=False)


class ListQuery(BaseModel):
    # Direct wire names avoid FastAPI 0.115/Pydantic alias metadata rebuilding.
    model_config = ConfigDict(extra="forbid")
    pageSize: int = Field(
        default=50,
        ge=1,
        le=200,
        description=(
            'Page size, default 50 (1..200). Keep unchanged across a cursor traversal; changing it '
            'requires a new traversal.'
        ),
        examples=[50])
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        description=(
            (
            'Opaque signed continuation from nextCursor. Bound to resource/parent, company, '
            'principal, client, installation, grant, live policy/scopes/resource grants and all '
            'filters including pageSize. URL-encode without decoding or editing; live pagination is '
            'not a snapshot. Omit cursor to start a new traversal; literal query cursor=null is not '
            'a valid continuation. Response nextCursor=null ends the traversal.'
        )
        ),
        examples=['<CURSOR_FROM_PREVIOUS_RESPONSE>'])
    q: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description=(
            'Case-insensitive SQL ILIKE substring: objects.name, equipment.serial_number, '
            'counterparties.name, contracts.number, documents.title. SQL % and _ remain wildcards; '
            'not full-text search or INN search.'
        ),
        examples=['DEMO'])
    dateFrom: date | None = Field(
        default=None,
        description=(
            'Inclusive UTC created_at lower bound at 00:00:00, ISO calendar date YYYY-MM-DD only; '
            'not the business date or registration date. Must be <= dateTo.'
        ),
        examples=['2026-10-01'])
    dateTo: date | None = Field(
        default=None,
        description=(
            'Inclusive UTC created_at upper bound at 23:59:59.999999, ISO calendar date YYYY-MM-DD '
            'only; not the business date or registration date.'
        ),
        examples=['2026-10-31'])

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
    typeCode: str | None = Field(
        default=None,
        min_length=1,
        max_length=256,
        pattern=r"^[^\x00]+$",
        description=(
            'Exact source classifier code; case and whitespace are significant. No global enum. '
            'Applied only to the contracts list; preserve unknown codes.'
        ),
        examples=['fictional-type'])


class ContractTypeMetadataQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    typeCode: str = Field(
        min_length=1,
        max_length=256,
        pattern=r"^[^\x00]+$",
        description=(
            'Exact code from an independently visible contract; not a global catalog selector. '
            'Preserve case and whitespace; unknown catalog codes have nullable metadata.'
        ),
        examples=['fictional-type'])


class ContractTypeMetadata(DTO):
    type_code: str = Field(
        description=(
            'Exact source code already present on an independently visible contract; open string, '
            'not a legal classification.'
        ),
        examples=['fictional-type'])
    label: str | None = Field(
        description=(
            'Nullable catalog label. Null when the code has no catalog metadata.'
        ),
        examples=[None])
    gk_basis: str | None = Field(
        description=(
            'Nullable source civil-code basis; no legal inference from a missing value.'
        ),
        examples=[None])
    direction: str | None = Field(
        description=(
            'Nullable source direction; open string.'
        ),
        examples=[None])
    is_active: bool | None = Field(
        description=(
            'Nullable catalog active flag; inactive historical metadata remains readable.'
        ),
        examples=[None])


class EmptyQuery(DTO):
    pass


class ContractObjectsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageSize: int = Field(
        default=50,
        ge=1,
        le=200,
        description=(
            'Page size, default 50 (1..200). Keep unchanged across a cursor traversal; changing it '
            'requires a new traversal.'
        ),
        examples=[50])
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        description=(
            (
            'Opaque signed continuation from nextCursor. Bound to resource/parent, company, '
            'principal, client, installation, grant, live policy/scopes/resource grants and all '
            'filters including pageSize. URL-encode without decoding or editing; live pagination is '
            'not a snapshot. Omit cursor to start a new traversal; literal query cursor=null is not '
            'a valid continuation. Response nextCursor=null ends the traversal.'
        )
        ),
        examples=['<CURSOR_FROM_PREVIOUS_RESPONSE>'])

    @property
    def page_size(self):
        return self.pageSize


class ContractObject(DTO):
    object_id: ObjectId = Field(
        description=(
            'Exact opaque ObjectId for an independently visible explicitly linked service point.'
        ),
        examples=['20000000-0000-4000-8000-000000000001'])


class ContractObjects(DTO):
    contract_id: Id = Field(
        description=(
            'Independently visible parent contract ID.'
        ),
        examples=['50000000-0000-4000-8000-000000000001'])
    scope_type: str = Field(
        description=(
            'Current native scope string, not a closed enum. Only locations yields explicit links; '
            'company/unassigned does not expand to all objects.'
        ),
        examples=['locations'])
    items: list[ContractObject] = Field(
        description=(
            'Current explicit links after independent object authorization; not historical legal '
            'coverage.'
        ),
        examples=[
            [
                {
                    'objectId': '20000000-0000-4000-8000-000000000001'
                }
            ]
        ])
    total: int = Field(
        ge=0,
        description=(
            'Live visible count before cursor, not a global inventory count.'
        ),
        examples=[1])
    next_cursor: str | None = Field(
        description=(
            'Opaque continuation; null ends this live traversal. Keep pageSize and the '
            'authorization/filter context unchanged.'
        ),
        examples=[None])


class ContractDocumentsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pageSize: int = Field(
        default=50,
        ge=1,
        le=200,
        description=(
            'Page size, default 50 (1..200). Keep unchanged across a cursor traversal; changing it '
            'requires a new traversal.'
        ),
        examples=[50])
    cursor: str | None = Field(
        default=None,
        min_length=1,
        max_length=4096,
        description=(
            (
            'Opaque signed continuation from nextCursor. Bound to resource/parent, company, '
            'principal, client, installation, grant, live policy/scopes/resource grants and all '
            'filters including pageSize. URL-encode without decoding or editing; live pagination is '
            'not a snapshot. Omit cursor to start a new traversal; literal query cursor=null is not '
            'a valid continuation. Response nextCursor=null ends the traversal.'
        )
        ),
        examples=['<CURSOR_FROM_PREVIOUS_RESPONSE>'])

    @property
    def page_size(self):
        return self.pageSize


class ContractDocument(DTO):
    document_id: Id = Field(
        description=(
            'Independently visible explicitly linked document ID; confers no file permission.'
        ),
        examples=['60000000-0000-4000-8000-000000000001'])


class ContractDocuments(DTO):
    contract_id: Id = Field(
        description=(
            'Independently visible parent contract ID.'
        ),
        examples=['50000000-0000-4000-8000-000000000001'])
    items: list[ContractDocument] = Field(
        description=(
            'Current subject/graph document links after independent document authorization. '
            'Delegated user only.'
        ),
        examples=[
            [
                {
                    'documentId': '60000000-0000-4000-8000-000000000001'
                }
            ]
        ])
    total: int = Field(
        ge=0,
        description=(
            'Live visible count before cursor, not the total number of all contract files.'
        ),
        examples=[1])
    next_cursor: str | None = Field(
        description=(
            'Opaque continuation; null ends this live traversal. Keep pageSize and the '
            'authorization/filter context unchanged.'
        ),
        examples=[None])


class MonitoringQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(
        default=90,
        ge=1,
        le=366,
        description=(
            'Lookback in days (default 90, 1..366); interval [endpoint minus days, endpoint] is '
            'inclusive in Europe/Moscow.'
        ),
        examples=[1])
    asOf: date | None = Field(
        default=None,
        description=(
            'Optional ISO calendar date. Caps endpoint at 23:59:59.999999 MSK or earlier '
            'object-observed data; absent uses the latest object boundary or current MSK time when '
            'unknown. Does not reconstruct catalog history.'
        ),
        examples=['2026-10-31'])

    @field_validator("asOf", mode="before")
    @classmethod
    def iso_date_only(cls, value):
        return ListQuery.iso_date_only(value)


class MonitoringWindow(DTO):
    days: int = Field(
        ge=1,
        le=366,
        description=(
            'Requested lookback in days.'
        ),
        examples=[1])
    start: datetime = Field(
        description=(
            'Inclusive interval start with explicit MSK UTC+03:00 offset.'
        ),
        examples=['2026-10-30T10:00:00+03:00'])
    end: datetime = Field(
        description=(
            'Inclusive interval endpoint with explicit MSK UTC+03:00 offset, capped by requested '
            'date and object-observed data.'
        ),
        examples=['2026-10-31T10:00:00+03:00'])
    time_zone: Literal["Europe/Moscow"] = Field(
        default="Europe/Moscow",
        description=(
            'Calendar/time-zone convention used by the monitoring interval.'
        ),
        examples=['Europe/Moscow'])
    interval: Literal["inclusive"] = Field(
        default="inclusive",
        description=(
            'Both interval boundaries are included.'
        ),
        examples=['inclusive'])


class MonitoringTotals(DTO):
    sessions: int = Field(
        ge=0,
        description=(
            'Count of charging session attempts in the selected object interval.'
        ),
        examples=[3])
    visits: int = Field(
        ge=0,
        description=(
            'Count of visits grouped by native visit key (session fallback), not a count of '
            'distinct people.'
        ),
        examples=[2])
    successful_visits: int = Field(
        ge=0,
        description=(
            'Visits with any attempt energy_kwh > 0.'
        ),
        examples=[1])
    unsuccessful_visits: int = Field(
        ge=0,
        description=(
            'Visits minus successfulVisits.'
        ),
        examples=[1])
    energy_kwh: float = Field(
        description=(
            'Non-financial energy in kWh, summed before rounding to one decimal place.'
        ),
        examples=[12.5])


class MonitoringProvenance(DTO):
    as_of: datetime = Field(
        description=(
            'Effective interval endpoint with MSK offset; not the HTTP response timestamp.'
        ),
        examples=['2026-10-31T10:00:00+03:00'])
    data_through: datetime | None = Field(
        description=(
            'Latest observed charging-session start for this authorized object, even if later than '
            'requestedDate. Null means unknown; never substitute zero or another object boundary.'
        ),
        examples=['2026-10-31T10:00:00+03:00'])
    data_lag_hours: float | None = Field(
        description=(
            'Non-negative hours from latest object observation to current MSK time, rounded to one '
            'decimal. Null means no observed boundary; zero is a known value.'
        ),
        examples=[0.0])
    requested_date: date | None = Field(
        description=(
            'Echoed asOf calendar date, or null when omitted.'
        ),
        examples=['2026-10-31'])
    catalog_mode: Literal["current"] = Field(
        description=(
            'Catalog/status are current even for an earlier requestedDate; no historical catalog '
            'snapshot.'
        ),
        examples=['current'])
    snapshot_note: str = Field(
        description=(
            'Source explanation of current catalog versus dated session aggregates.'
        ),
        examples=['Сессии — на выбранный день (МСК). Состав парка и паспортные статусы — текущие; история состава не восстановлена.'])
    boundary_scope: Literal["object"] = Field(
        default="object",
        description=(
            'Observed data watermark is limited to the authorized object.'
        ),
        examples=['object'])
    source: Literal["charge_sessions"] = Field(
        default="charge_sessions",
        description=(
            'Aggregate source; raw sessions and financial data are not published.'
        ),
        examples=['charge_sessions'])
    visit_success: Literal["any attempt energy_kwh > 0"] = Field(
        default="any attempt energy_kwh > 0",
        description=(
            'Native visit success rule, not a financial or ticket outcome.'
        ),
        examples=['any attempt energy_kwh > 0'])


class Monitoring(DTO):
    point_id: ObjectId = Field(
        description=(
            'Exact opaque authorized service-point ObjectId.'
        ),
        examples=['20000000-0000-4000-8000-000000000001'])
    status: Literal["working", "no_link", "disabled", "decommissioned", "on_repair",
                    "maintenance", "not_working", "unknown"] = Field(
        description=(
            'Current operational status; unrecognized source status maps to unknown. This is not '
            'historical status.'
        ),
        examples=['working'])
    window: MonitoringWindow = Field(
        description=(
            'Inclusive MSK aggregate interval.'
        ),
        examples=[
            {
                'days': 1,
                'start': '2026-10-30T10:00:00+03:00',
                'end': '2026-10-31T10:00:00+03:00',
                'timeZone': 'Europe/Moscow',
                'interval': 'inclusive'
            }
        ])
    totals: MonitoringTotals = Field(
        description=(
            'Non-financial charging aggregate for the object interval.'
        ),
        examples=[
            {
                'sessions': 3,
                'visits': 2,
                'successfulVisits': 1,
                'unsuccessfulVisits': 1,
                'energyKwh': 12.5
            }
        ])
    last_seen_at: datetime | None = Field(
        description=(
            'Last observed object session at or before interval endpoint; null means unknown.'
        ),
        examples=['2026-10-31T10:00:00+03:00'])
    provenance: MonitoringProvenance = Field(
        description=(
            'Object boundary, observation lag and current-catalog limitations.'
        ),
        examples=[
            {
                'asOf': '2026-10-31T10:00:00+03:00',
                'dataThrough': '2026-10-31T10:00:00+03:00',
                'dataLagHours': 0.0,
                'requestedDate': '2026-10-31',
                'catalogMode': 'current',
                'snapshotNote': 'Сессии — на выбранный день (МСК). Состав парка и паспортные статусы — текущие; история состава не восстановлена.',
                'boundaryScope': 'object',
                'source': 'charge_sessions',
                'visitSuccess': 'any attempt energy_kwh > 0'
            }
        ])


class Object(DTO):
    id: ObjectId = Field(
        description=(
            'Exact opaque native service-point string, 1..40 Unicode characters without NUL; UUID '
            'examples do not imply a UUID type. Preserve spaces/case; URL-encode path segments. '
            'Transport addressability is separate.'
        ),
        examples=['20000000-0000-4000-8000-000000000001'])
    level: Literal["servicePoint"] = Field(
        default="servicePoint",
        description=(
            'Published hierarchy level; site/EVSE/connector are not exposed.'
        ),
        examples=['servicePoint'])
    code: str = Field(
        description=(
            'Native display code; not a resource identifier.'
        ),
        examples=['DEMO-001'])
    name: str = Field(
        description=(
            'Service-point display name.'
        ),
        examples=['Учебная ЭЗС'])
    type: str = Field(
        description=(
            'Native open type string; do not infer a closed enum.'
        ),
        examples=['ezs'])
    status: str = Field(
        description=(
            'Native open catalog status string, separate from monitoring operational status.'
        ),
        examples=['active'])
    address: str | None = Field(
        description=(
            'Nullable display address.'
        ),
        examples=['Учебный адрес, 1'])
    latitude: float | None = Field(
        description=(
            'Nullable latitude in degrees.'
        ),
        examples=[55.75])
    longitude: float | None = Field(
        description=(
            'Nullable longitude in degrees.'
        ),
        examples=[37.61])


class Equipment(DTO):
    id: Id = Field(
        description=(
            'Opaque equipment ID, distinct from ObjectId.'
        ),
        examples=['30000000-0000-4000-8000-000000000001'])
    level: Literal["station"] = Field(
        default="station",
        description=(
            'Only station equipment is published.'
        ),
        examples=['station'])
    vendor: str | None = Field(
        description=(
            'Nullable manufacturer.'
        ),
        examples=['Учебный изготовитель'])
    model: str | None = Field(
        description=(
            'Nullable equipment model.'
        ),
        examples=['Пример 50'])
    serial_number: str | None = Field(
        description=(
            'Nullable serial number; q searches this field.'
        ),
        examples=['DEMO-0001'])
    power_kw: float | None = Field(
        description=(
            'Nullable rated power in kW; not energy in kWh.'
        ),
        examples=[50.0])
    state: str = Field(
        description=(
            'Native open equipment state string.'
        ),
        examples=['working'])
    object_id: ObjectId | None = Field(
        description=(
            'Nullable independently authorized link: null means absent or hidden, not proof that no '
            'relationship exists. Requires objects:read and an independent object resource grant to '
            'disclose.'
        ),
        examples=['20000000-0000-4000-8000-000000000001'])


class Counterparty(DTO):
    id: Id = Field(
        description=(
            'Opaque counterparty ID.'
        ),
        examples=['40000000-0000-4000-8000-000000000001'])
    name: str = Field(
        description=(
            'Counterparty display name; q searches this field.'
        ),
        examples=['Учебный контрагент'])
    inn: str | None = Field(
        description=(
            'Nullable native tax identifier; q does not search this field.'
        ),
        examples=[None])
    kpp: str | None = Field(
        description=(
            'Nullable native registration reason code.'
        ),
        examples=[None])


class Contract(DTO):
    type_code: str | None = Field(
        description=(
            'Source Contract.type_code, including unknown or empty codes. No legal inference or '
            'closed enum.'
        ),
        examples=['fictional-type'])
    valid_until: str | None = Field(
        max_length=20,
        description=(
            'Exact native validity value. Nullable source string up to 20 characters, not a '
            'validated ISO date; null is unknown, not perpetual.'
        ),
        examples=[None])
    id: Id = Field(
        description=(
            'Opaque contract ID.'
        ),
        examples=['50000000-0000-4000-8000-000000000001'])
    number: str = Field(
        description=(
            'Native contract number; q searches this field.'
        ),
        examples=['DEMO-001'])
    date: date | None = Field(
        description=(
            'Nullable parsed contract business date; dateFrom/dateTo filter created_at instead.'
        ),
        examples=['2026-10-01'])
    title: str | None = Field(
        description=(
            'Nullable native contract title.'
        ),
        examples=['Учебный договор'])
    is_closed: bool = Field(
        description=(
            'Native closed flag.'
        ),
        examples=[False])
    scope_type: str = Field(
        description=(
            'Native open scope string; company/unassigned implies no explicit object links.'
        ),
        examples=['locations'])
    counterparty_id: Id | None = Field(
        description=(
            'Nullable independently authorized link: null means absent or hidden, not proof that no '
            'relationship exists. Requires counterparties:read and an independent counterparty '
            'grant to disclose.'
        ),
        examples=['40000000-0000-4000-8000-000000000001'])


class Document(DTO):
    id: Id = Field(
        description=(
            'Opaque document ID; all document operations require a delegated user.'
        ),
        examples=['60000000-0000-4000-8000-000000000001'])
    title: str = Field(
        description=(
            'Document title; q searches this field.'
        ),
        examples=['Учебный документ'])
    status: str = Field(
        description=(
            'Native open document status string.'
        ),
        examples=['draft'])
    registration_number: str | None = Field(
        description=(
            'Nullable native registration number.'
        ),
        examples=[None])
    registration_date: date | None = Field(
        description=(
            'Nullable registration business date; dateFrom/dateTo filter created_at instead.'
        ),
        examples=[None])
    current_revision: int = Field(
        description=(
            'Native current revision number.'
        ),
        examples=[1])
    object_id: ObjectId | None = Field(
        description=(
            'Nullable independently authorized link: null means absent or hidden, not proof that no '
            'relationship exists. Requires independent object authorization.'
        ),
        examples=[None])
    counterparty_id: Id | None = Field(
        description=(
            'Nullable independently authorized link: null means absent or hidden, not proof that no '
            'relationship exists. Requires independent counterparty authorization.'
        ),
        examples=[None])


class Version(DTO):
    id: Id = Field(
        description=(
            'Opaque document version ID. Metadata never grants download permission.'
        ),
        examples=['70000000-0000-4000-8000-000000000001'])
    revision: int = Field(
        description=(
            'Native version revision.'
        ),
        examples=[1])
    role: str = Field(
        description=(
            'Native open file role string.'
        ),
        examples=['main'])
    file_name: str = Field(
        description=(
            'Version filename metadata; download uses a confined attachment basename.'
        ),
        examples=['example.txt'])
    mime_type: str | None = Field(
        description=(
            'Nullable metadata MIME type; download wire type remains application/octet-stream.'
        ),
        examples=['text/plain'])
    size_bytes: int = Field(
        description=(
            'File size metadata in bytes; fictional examples are not generated files.'
        ),
        examples=[15])


class DocumentDetail(Document):
    versions: list[Version] = Field(
        description=(
            'At most 200 current, non-tombstoned, non-purged versions ordered by revision then id. '
            'Not a historical archive.'
        ),
        examples=[
            [
                {
                    'id': '70000000-0000-4000-8000-000000000001',
                    'revision': 1,
                    'role': 'main',
                    'fileName': 'example.txt',
                    'mimeType': 'text/plain',
                    'sizeBytes': 15
                }
            ]
        ])
    versions_truncated: bool = Field(
        description=(
            'True when more than 200 eligible current versions exist. No endpoint for complete '
            'historical version listing is published.'
        ),
        examples=[False])


T = TypeVar("T", bound=DTO)


class Page(DTO, Generic[T]):
    items: list[T] = Field(
        description=(
            'Visible resource items, fixed ascending created_at then id. Pagination is live, not a '
            'snapshot; custom sort/offset are unsupported.'
        ),
        examples=[
            []
        ])
    next_cursor: str | None = Field(
        description=(
            'Opaque continuation, null at traversal end. Bound to pageSize, filters and current '
            'authorization context; never edit or reuse across contexts.'
        ),
        examples=[None])
    total: int = Field(
        description=(
            'Current authorized filtered count before cursor; may change between pages. Not a '
            'global inventory count.'
        ),
        examples=[1])


class Problem(DTO):
    type: str = Field(
        default="about:blank",
        description=(
            'Problem type identifier.'
        ),
        examples=['about:blank'])
    title: str = Field(
        description=(
            'HTTP status phrase; classify errors by status/code, not free text.'
        ),
        examples=['Not Found'])
    status: int = Field(
        description=(
            'HTTP response status.'
        ),
        examples=[404])
    code: str = Field(
        description=(
            'Application error code; the product profile does not cover proxy errors.'
        ),
        examples=['not_found'])
    request_id: str = Field(
        description=(
            'Server-generated correlation ID, equal to X-Request-Id; not a resource selector.'
        ),
        examples=['80000000-0000-4000-8000-000000000001'])
    detail: str = Field(
        description=(
            'Safe human-readable detail; not a stable discriminator.'
        ),
        examples=['Resource was not found'])
