"""Internal birth-receipt grammar only; no authority or persistence effects.

The operation comes from the receipt owner, never from the stored JSON body.
SQL must still enforce unchanged 0005's whole-envelope JSONB text byte limit.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import (
    BaseModel, BeforeValidator, ConfigDict, Field, ValidationInfo,
    field_validator, model_validator,
)

from .contract_cycle_dto import DateV2, ObjectIdV2, UUIDV2, VersionV2


CONTRACT_CREATE = "v2.contract.create"
DOCUMENT_DRAFT_CREATE = "v2.document.draft.create"
BirthOperation = Literal["v2.contract.create", "v2.document.draft.create"]
DOCUMENT_ACTIONS = frozenset({
    "document.read", "document.edit", "document.download", "document.print",
    "document.export", "document.send", "document.approve", "document.sign",
    "document.archive", "document.manage_acl",
})


def _text(value: object) -> str:
    if type(value) is not str or "\x00" in value:
        raise ValueError("Expected exact text without NUL")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("Expected Unicode scalar text") from None
    return value


def _one(value: object) -> int:
    if type(value) is not int or value != 1:
        raise ValueError("Unsupported receipt format")
    return value


PositiveInt64 = Annotated[int, Field(strict=True, ge=1, le=9223372036854775807)]
PositiveInt32 = Annotated[int, Field(strict=True, ge=1, le=2147483647)]
NonnegativeInt = Annotated[int, Field(strict=True, ge=0)]
PositiveInt = Annotated[int, Field(strict=True, ge=1)]
SiteKind = Literal["site"]
LocationKind = Literal["location"]
BirthAction = Annotated[Literal[
    "contract.read", "document.read", "document.edit", "document.download",
    "document.print", "document.export", "document.send", "document.approve",
    "document.sign", "document.archive", "document.manage_acl",
], BeforeValidator(_text)]


class _ReceiptModel(BaseModel):
    model_config = ConfigDict(
        strict=True, extra="forbid", frozen=True, hide_input_in_errors=True,
        revalidate_instances="always",
    )

    @model_validator(mode="before")
    @classmethod
    def raw_instance_state(cls, value: object) -> object:
        # Never model_dump here: JSON mode can turn invalid constructed bytes,
        # UUID-like objects, dates, etc. into apparently valid wire values.
        # Nested models stay intact and each runs this same validation boundary.
        if isinstance(value, BaseModel):
            if type(value) is not cls:
                raise ValueError("Unexpected receipt model type")
            state = dict(object.__getattribute__(value, "__dict__"))
            extras = object.__getattribute__(value, "__pydantic_extra__")
            if extras is not None:
                if type(extras) is not dict or state.keys() & extras.keys():
                    raise ValueError("Invalid model extra state")
                state.update(extras)
            value = state
        # Tagged unions require literal discriminator fields without a field
        # BeforeValidator; enforce their exact text at the model boundary.
        if type(value) is dict and "kind" in value:
            _text(value["kind"])
        return value


class BirthGenerationRef(_ReceiptModel):
    id: UUIDV2
    generation: PositiveInt64


class BirthSiteContext(_ReceiptModel):
    kind: SiteKind
    siteId: UUIDV2
    organizationId: UUIDV2
    generation: PositiveInt32


class BirthLocationContext(_ReceiptModel):
    kind: LocationKind
    locationId: ObjectIdV2
    organizationId: UUIDV2


BindingContext = Annotated[
    BirthSiteContext | BirthLocationContext, Field(discriminator="kind"),
]


class BirthPolicyBinding(_ReceiptModel):
    birthPolicy: BirthGenerationRef
    context: BindingContext
    actions: Annotated[list[BirthAction], Field(min_length=1, max_length=10)]

    @field_validator("actions")
    @classmethod
    def canonical_actions(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("Duplicate receipt action")
        return sorted(value)


def _context_id(context: BirthSiteContext | BirthLocationContext) -> str:
    return str(context.siteId) if isinstance(context, BirthSiteContext) else context.locationId


class BirthAuthoritySnapshot(_ReceiptModel):
    profile: BirthGenerationRef
    principal: BirthGenerationRef
    bindings: Annotated[list[BirthPolicyBinding], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def complete_vector_grammar(self) -> BirthAuthoritySnapshot:
        contexts = {(b.context.kind, _context_id(b.context)) for b in self.bindings}
        policies = {b.birthPolicy.id for b in self.bindings}
        if len(contexts) != len(self.bindings) or len(policies) != len(self.bindings):
            raise ValueError("Duplicate receipt context or policy binding")
        if len({b.context.organizationId for b in self.bindings}) != 1:
            raise ValueError("Inconsistent binding organizations")
        kinds = {b.context.kind for b in self.bindings}
        if len(kinds) != 1 or ("site" in kinds and len(self.bindings) != 1):
            raise ValueError("Expected one Site or a location vector")
        self.bindings.sort(key=lambda b: (
            b.context.kind, _context_id(b.context), str(b.birthPolicy.id),
        ))
        return self


class ContractBirthResult(_ReceiptModel):
    resourceId: UUIDV2
    editVersion: VersionV2


class DocumentSiteContext(_ReceiptModel):
    kind: SiteKind
    siteId: UUIDV2


class DocumentLocationContext(_ReceiptModel):
    kind: LocationKind
    locationId: ObjectIdV2


DocumentContext = Annotated[
    DocumentSiteContext | DocumentLocationContext, Field(discriminator="kind"),
]


class DocumentBirthVersion(_ReceiptModel):
    versionId: UUIDV2
    role: Annotated[Literal["body", "signed_scan"], BeforeValidator(_text)]
    revision: PositiveInt
    sha256: Annotated[str, BeforeValidator(_text), Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64)]
    sizeBytes: Annotated[int, Field(strict=True, ge=1, le=26214400)]


class DocumentBirthResult(_ReceiptModel):
    docId: UUIDV2
    context: DocumentContext
    organizationId: UUIDV2
    kindCode: Annotated[Literal["contract_scan"], BeforeValidator(_text)]
    title: Annotated[str, BeforeValidator(_text), Field(min_length=1, max_length=500)]
    status: Annotated[Literal["draft", "registered"], BeforeValidator(_text)]
    editVersion: VersionV2
    currentRevision: NonnegativeInt
    registrationNumber: Annotated[str, BeforeValidator(_text), Field(min_length=1, max_length=60)] | None
    registrationDate: DateV2 | None
    versions: Annotated[list[DocumentBirthVersion], Field(max_length=200)]
    versionsTruncated: Annotated[bool, Field(strict=True)]


def _operation(value: object) -> BirthOperation:
    if type(value) is not str or value not in (CONTRACT_CREATE, DOCUMENT_DRAFT_CREATE):
        raise ValueError("Unsupported birth operation")
    return value


class BirthReceiptEnvelopeV1(_ReceiptModel):
    formatVersion: Annotated[int, BeforeValidator(_one)]
    authoritySnapshot: BirthAuthoritySnapshot
    result: ContractBirthResult | DocumentBirthResult

    @model_validator(mode="after")
    def operation_result(self, info: ValidationInfo) -> BirthReceiptEnvelopeV1:
        if type(info.context) is not dict:
            raise ValueError("Explicit birth operation required")
        operation = _operation(info.context.get("operation"))
        bindings = self.authoritySnapshot.bindings
        if operation == CONTRACT_CREATE:
            if type(self.result) is not ContractBirthResult:
                raise ValueError("Contract operation requires ContractBirthResult")
            allowed = {"contract.read"}
        else:
            if type(self.result) is not DocumentBirthResult or len(bindings) != 1:
                raise ValueError("Document operation requires one binding and DocState")
            allowed = DOCUMENT_ACTIONS
            binding = bindings[0].context
            result_context = self.result.context
            if (binding.kind != result_context.kind
                    or self.result.organizationId != binding.organizationId):
                raise ValueError("Document binding context or organization mismatch")
            if isinstance(binding, BirthSiteContext):
                if binding.siteId != result_context.siteId:
                    raise ValueError("Document Site mismatch")
            elif binding.locationId != result_context.locationId:
                raise ValueError("Document location mismatch")
        if any(action not in allowed for b in bindings for action in b.actions):
            raise ValueError("Action belongs to another operation")
        return self


def parse_birth_envelope(value: object, *, operation: BirthOperation) -> BirthReceiptEnvelopeV1:
    """Validate a stored JSON object or complete existing model, without I/O.

    Completeness against original coverage/receipt columns/current SQL is the
    command owner's separate proof. This function cannot establish that proof.
    """
    return BirthReceiptEnvelopeV1.model_validate(value, context={"operation": _operation(operation)})


def serialize_birth_envelope(value: object, *, operation: BirthOperation) -> str:
    """Revalidate all state then encode; this is NOT a PG JSONB byte predicate."""
    envelope = parse_birth_envelope(value, operation=operation)
    return json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def project_birth_result(value: object, *, operation: BirthOperation) -> dict[str, object]:
    """Public typed result only; replayed is a future adapter's computed field."""
    envelope = parse_birth_envelope(value, operation=operation)
    return envelope.result.model_dump(mode="json")
