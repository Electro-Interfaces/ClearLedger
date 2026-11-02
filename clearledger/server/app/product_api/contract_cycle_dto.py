"""Future V2 contract domain DTOs; deliberately disconnected from application IO.

Wire decimals are fixed-scale strings; Python values are exact Decimal objects.
Every full card validation needs context={"todayMSK": <exact datetime.date>}.
Partial patches do not establish a valid final card: use merge_contract_card.
No authority, concurrency, persistence, clock, or legacy inference lives here.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer,
    TypeAdapter, ValidationInfo, WithJsonSchema, model_validator,
)


def _date(value: object) -> date:
    if type(value) is date:
        return value
    if type(value) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
        raise ValueError("Expected YYYY-MM-DD or an exact Python date")
    return date.fromisoformat(value)


def _uuid(value: object) -> UUID:
    if type(value) is UUID:
        return value
    if type(value) is not str or re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value
    ) is None:
        raise ValueError("Expected hyphenated UUID36 or an exact Python UUID")
    return UUID(value)


def _text(value: object) -> str:
    if type(value) is not str:
        raise ValueError("Expected an exact string")
    # Reject invalid Unicode scalar encodings without trimming or case folding.
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Expected Unicode text") from None
    return value


def _object_id(value: object) -> str:
    text = _text(value)
    if not 1 <= len(text) <= 40 or "\x00" in text:
        raise ValueError("ObjectId requires 1..40 Unicode characters without NUL")
    return text


def _number(value: object) -> str:
    text = _text(value)
    if not text.strip():
        raise ValueError("Contract number must not be blank")
    return text


def _decimal(value: object, *, digits: int, scale: int, maximum: str) -> Decimal:
    # New V2 lexical convention: no plus/minus signs or leading integer zeros.
    if type(value) is not str or re.fullmatch(
        rf"(?:0|[1-9][0-9]{{0,{digits - scale - 1}}})\.[0-9]{{{scale}}}", value
    ) is None:
        raise ValueError("Expected unsigned canonical fixed-scale decimal string")
    result = Decimal(value)
    if result > Decimal(maximum):
        raise ValueError("Decimal exceeds domain maximum")
    return result


def _money(value: object) -> Decimal:
    return _decimal(value, digits=16, scale=2, maximum="99999999999999.99")


def _tariff(value: object) -> Decimal:
    return _decimal(value, digits=14, scale=6, maximum="99999999.999999")


def _rate(value: object) -> Decimal:
    return _decimal(value, digits=5, scale=2, maximum="100.00")


def _decimal_wire(value: Decimal, scale: int) -> str:
    # Do not round/format a float or silently repair malformed constructed state.
    if type(value) is not Decimal or not value.is_finite() or value.is_signed() or value.as_tuple().exponent != -scale:
        raise ValueError("Wire decimal requires an exact nonnegative fixed-scale Decimal")
    return format(value, "f")


DateV2 = Annotated[
    date, BeforeValidator(_date),
    WithJsonSchema({"type": "string", "format": "date", "pattern": r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$", "minLength": 10, "maxLength": 10}),
]
UUIDV2 = Annotated[
    UUID, BeforeValidator(_uuid),
    WithJsonSchema({"type": "string", "format": "uuid", "pattern": r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", "minLength": 36, "maxLength": 36}),
]
# Separate semantic alias: Site identifiers are never interpreted as ObjectIds.
SiteUUIDV2 = UUIDV2
ObjectIdV2 = Annotated[
    str, BeforeValidator(_object_id),
    WithJsonSchema({"type": "string", "minLength": 1, "maxLength": 40, "pattern": r"^[^\u0000]+$"}),
]
MoneyV2 = Annotated[
    Decimal, BeforeValidator(_money),
    PlainSerializer(lambda v: _decimal_wire(v, 2), return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^(?:0|[1-9][0-9]{0,13})\.[0-9]{2}$", "minLength": 4, "maxLength": 17}),
]
TariffV2 = Annotated[
    Decimal, BeforeValidator(_tariff),
    PlainSerializer(lambda v: _decimal_wire(v, 6), return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^(?:0|[1-9][0-9]{0,7})\.[0-9]{6}$", "minLength": 8, "maxLength": 15}),
]
RateV2 = Annotated[
    Decimal, BeforeValidator(_rate),
    PlainSerializer(lambda v: _decimal_wire(v, 2), return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": r"^(?:(?:0|[1-9][0-9]?)\.[0-9]{2}|100\.00)$", "minLength": 4, "maxLength": 6}),
]
VersionV2 = Annotated[str, BeforeValidator(_text), Field(pattern=r"^v1:[0-9a-f]{64}$", min_length=67, max_length=67)]
NumberV2 = Annotated[str, BeforeValidator(_number), Field(min_length=1, max_length=100)]
NoteV2 = Annotated[str, BeforeValidator(_text), Field(max_length=2000)]
BasisV2 = Literal["contract", "permission", "resolution", "order", "servitude"]
PeriodicityV2 = Literal["monthly", "quarterly", "annual", "one_time"]
ExpectedDocumentV2 = Literal["act", "upd", "invoice", "sf", "report"]
PaymentDaysV2 = Annotated[int, Field(strict=True, ge=0, le=366)]
DueDayV2 = Annotated[int, Field(strict=True, ge=1, le=31)]


class ContractDTOv2(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, hide_input_in_errors=True,
        revalidate_instances="always",
    )

    @model_validator(mode="before")
    @classmethod
    def instance_through_wire(cls, value: object) -> object:
        # Revalidation must keep fixed-scale strings and patch field presence.
        # Never trust an existing instance as proof of business-date validation.
        if isinstance(value, cls):
            return value.model_dump(mode="json", exclude_unset=True)
        return value


class SiteContextV2(ContractDTOv2):
    kind: Literal["site"]
    siteId: SiteUUIDV2


class LocationContextV2(ContractDTOv2):
    kind: Literal["location"]
    locationId: ObjectIdV2


ContextV2 = Annotated[SiteContextV2 | LocationContextV2, Field(discriminator="kind")]


class SiteCoverageV2(ContractDTOv2):
    kind: Literal["site"]
    siteId: SiteUUIDV2


class LocationsCoverageV2(ContractDTOv2):
    kind: Literal["locations"]
    locationIds: Annotated[list[ObjectIdV2], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def unique_locations(self) -> LocationsCoverageV2:
        if len(set(self.locationIds)) != len(self.locationIds):
            raise ValueError("Coverage locationIds must be unique")
        return self


CoverageV2 = Annotated[SiteCoverageV2 | LocationsCoverageV2, Field(discriminator="kind")]


class UnknownValidityV2(ContractDTOv2):
    kind: Literal["unknown"]


class OpenEndedValidityV2(ContractDTOv2):
    kind: Literal["openEnded"]


class UntilValidityV2(ContractDTOv2):
    kind: Literal["until"]
    date: DateV2


ValidityV2 = Annotated[UnknownValidityV2 | OpenEndedValidityV2 | UntilValidityV2, Field(discriminator="kind")]


def _today_msk(context: object) -> date:
    if type(context) is not dict or type(context.get("todayMSK")) is not date:
        raise ValueError("Full card validation requires explicit exact date context todayMSK")
    return context["todayMSK"]


class _CardV2(ContractDTOv2):
    number: NumberV2
    date: DateV2
    organizationId: UUIDV2
    counterpartyId: UUIDV2
    kind: Literal["supplier"]
    currency: Literal["RUB"]
    paymentTermDays: PaymentDaysV2
    vatPct: RateV2 | None
    amountInclVat: bool | None
    signed: bool
    signedAt: DateV2 | None
    comment: NoteV2 | None
    validity: ValidityV2

    @model_validator(mode="after")
    def business_dates(self, info: ValidationInfo) -> _CardV2:
        today = _today_msk(info.context)
        if self.signed:
            if self.signedAt is None or self.signedAt > today:
                raise ValueError("Signed card requires signedAt no later than todayMSK")
        elif self.signedAt is not None:
            raise ValueError("Unsigned card requires signedAt=null")
        if isinstance(self.validity, UntilValidityV2) and self.validity.date < self.date:
            raise ValueError("Validity must not end before the card date")
        return self


class LeaseCardV2(_CardV2):
    profile: Literal["Lease"]
    basis: BasisV2


class PowerSupplyCardV2(_CardV2):
    profile: Literal["PowerSupply"]
    basis: Literal["contract"]


CardV2 = Annotated[LeaseCardV2 | PowerSupplyCardV2, Field(discriminator="profile")]


class FixedConditionV2(ContractDTOv2):
    kind: Literal["fixed"]
    amountGross: MoneyV2
    vatPct: RateV2 | None

    @model_validator(mode="after")
    def positive_price(self) -> FixedConditionV2:
        if self.amountGross <= 0:
            raise ValueError("Fixed amountGross must be positive")
        return self


class MeteredConditionV2(ContractDTOv2):
    kind: Literal["metered_kwh"]
    tariffRub: TariffV2
    vatPct: RateV2 | None

    @model_validator(mode="after")
    def positive_price(self) -> MeteredConditionV2:
        if self.tariffRub <= 0:
            raise ValueError("Metered tariffRub must be positive")
        return self


class _TermV2(ContractDTOv2):
    context: ContextV2
    validFrom: DateV2
    validTo: DateV2 | None
    docDueDay: DueDayV2 | None
    payDueDay: DueDayV2 | None
    expectedDocs: Annotated[list[ExpectedDocumentV2], Field(max_length=5)]
    note: NoteV2 | None

    @model_validator(mode="after")
    def term_dates_and_documents(self) -> _TermV2:
        if self.validTo is not None and self.validTo < self.validFrom:
            raise ValueError("validTo must be no earlier than validFrom")
        if len(set(self.expectedDocs)) != len(self.expectedDocs):
            raise ValueError("expectedDocs must be unique")
        return self


class LeaseFixedTermV2(_TermV2):
    costItem: Literal["rent"]
    periodicity: PeriodicityV2
    condition: FixedConditionV2


class PowerMeteredTermV2(_TermV2):
    costItem: Literal["energy"]
    periodicity: Literal["monthly"]
    condition: MeteredConditionV2


TermV2 = Annotated[LeaseFixedTermV2 | PowerMeteredTermV2, Field(discriminator="costItem")]


class CardChangesV2(ContractDTOv2):
    """Presence, including explicit null, is tracked in model_fields_set.

    Factories supply internal omission placeholders for nonnullable fields,
    without advertising a null default in either wire schema. Only the four
    nullable business fields may explicitly contain null. Serialize patches
    with exclude_unset=True. Profile and organizationId are immutable.
    """

    number: NumberV2 = Field(default_factory=lambda: None, validate_default=False)
    date: DateV2 = Field(default_factory=lambda: None, validate_default=False)
    counterpartyId: UUIDV2 = Field(default_factory=lambda: None, validate_default=False)
    basis: BasisV2 = Field(default_factory=lambda: None, validate_default=False)
    kind: Literal["supplier"] = Field(default_factory=lambda: None, validate_default=False)
    currency: Literal["RUB"] = Field(default_factory=lambda: None, validate_default=False)
    paymentTermDays: PaymentDaysV2 = Field(default_factory=lambda: None, validate_default=False)
    vatPct: RateV2 | None = None
    amountInclVat: bool | None = None
    signed: bool = Field(default_factory=lambda: None, validate_default=False)
    signedAt: DateV2 | None = None
    comment: NoteV2 | None = None
    validity: ValidityV2 = Field(default_factory=lambda: None, validate_default=False)

    @model_validator(mode="after")
    def nonempty_and_required_nonnull(self) -> CardChangesV2:
        if not self.model_fields_set:
            raise ValueError("changes must not be empty")
        nullable = {"vatPct", "amountInclVat", "signedAt", "comment"}
        for field in self.model_fields_set:
            if getattr(self, field) is None and field not in nullable:
                raise ValueError("Required business fields cannot be cleared")
        return self


class ContractCreateCommandV2(ContractDTOv2):
    commandKey: UUIDV2
    card: CardV2
    coverage: CoverageV2


class _WriteCommandV2(ContractDTOv2):
    commandKey: UUIDV2
    expectedVersion: VersionV2


class ContractPatchCommandV2(_WriteCommandV2):
    changes: CardChangesV2


class TermCreateCommandV2(_WriteCommandV2):
    term: TermV2


class TermNewVersionCommandV2(_WriteCommandV2):
    replacement: TermV2


class MutationResultV2(ContractDTOv2):
    resourceId: UUIDV2
    editVersion: VersionV2
    replayed: bool


def _wire(value: object) -> object:
    # Revalidate model state through the same wire boundary, including nested
    # mutable collections. This does not trust model_construct/model_copy.
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def validate_contract_card(value: object, *, todayMSK: date) -> LeaseCardV2 | PowerSupplyCardV2:
    """Caller supplies the business date, already resolved in Moscow timezone."""
    return TypeAdapter(CardV2).validate_python(_wire(value), context={"todayMSK": todayMSK})


def merge_contract_card(
    currentCard: object, changes: object, *, todayMSK: date
) -> LeaseCardV2 | PowerSupplyCardV2:
    """Validate current state, preserve omission/null/value, validate final state."""
    current = validate_contract_card(currentCard, todayMSK=todayMSK)
    if isinstance(changes, CardChangesV2):
        changes = changes.model_dump(mode="json", exclude_unset=True)
    patch = CardChangesV2.model_validate(changes)
    merged = current.model_dump(mode="json")
    merged.update(patch.model_dump(mode="json", exclude_unset=True))
    return validate_contract_card(merged, todayMSK=todayMSK)


def validate_contract_term(
    term: object, *, finalCard: object, coverage: object, todayMSK: date
) -> LeaseFixedTermV2 | PowerMeteredTermV2:
    """Pure compatibility with explicit state; no resource existence/ACL lookup."""
    card = validate_contract_card(finalCard, todayMSK=todayMSK)
    covered = TypeAdapter(CoverageV2).validate_python(_wire(coverage))
    result = TypeAdapter(TermV2).validate_python(_wire(term))
    if (card.profile == "Lease") != (result.costItem == "rent"):
        raise ValueError("Term costItem/condition must match the final card profile")
    if isinstance(covered, SiteCoverageV2):
        if not isinstance(result.context, SiteContextV2) or result.context.siteId != covered.siteId:
            raise ValueError("Term context is outside explicit site coverage")
    elif not isinstance(result.context, LocationContextV2) or result.context.locationId not in covered.locationIds:
        raise ValueError("Term context is outside explicit location coverage")
    return result


def validate_term_replacement(
    replacement: object, *, previousTerm: object, finalCard: object,
    coverage: object, todayMSK: date,
) -> LeaseFixedTermV2 | PowerMeteredTermV2:
    """Pure stream identity/start check, not DB window/closed-period enforcement."""
    previous = TypeAdapter(TermV2).validate_python(_wire(previousTerm))
    result = validate_contract_term(
        replacement, finalCard=finalCard, coverage=coverage, todayMSK=todayMSK
    )
    if result.costItem != previous.costItem or result.context != previous.context:
        raise ValueError("Replacement must preserve costItem and exact context")
    if result.validFrom <= previous.validFrom:
        raise ValueError("Replacement validFrom must follow previous validFrom")
    return result
