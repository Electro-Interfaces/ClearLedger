"""Bounded contract-card input; no route, authority, persistence or app imports."""
from __future__ import annotations

from datetime import date as calendar_date
import hashlib
import json
import re
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator
from starlette.requests import Request

__all__ = [
    "ContractCreateBody", "ContractCreateLocations", "ContractCreateBodyError",
    "parse_contract_create_body", "canonical_contract_create_bytes", "contract_create_hash",
]

MAX_BODY_BYTES = 16384
_UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_MEDIA = re.compile(
    rb"[ \t]*application/json[ \t]*(?:;[ \t]*charset[ \t]*=[ \t]*utf-8[ \t]*)?",
    re.IGNORECASE,
)


class ContractCreateBodyError(ValueError):
    """Safe operation-local error. The transport owner maps status/code later."""

    def __init__(self, status: Literal[413, 415, 422], code: Literal[
        "request_too_large", "unsupported_media_type", "invalid_request"
    ]) -> None:
        self.status = status
        self.code = code
        super().__init__(code)


def _invalid() -> ContractCreateBodyError:
    return ContractCreateBodyError(422, "invalid_request")


def _text(value: object) -> str:
    if type(value) is not str or "\x00" in value:
        raise ValueError("Invalid text")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise ValueError("Invalid text") from None
    return value


def _nonblank(value: object) -> str:
    value = _text(value)
    if not value.strip():
        raise ValueError("Nonblank text required")
    return value


def _uuid(value: object) -> UUID:
    # Native exact UUID is permitted only in explicitly typed model validation.
    if type(value) is UUID:
        return value
    if type(value) is not str or _UUID.fullmatch(value) is None:
        raise ValueError("Canonical UUID required")
    return UUID(value)


def _date(value: object) -> str:
    value = _text(value)
    if _DATE.fullmatch(value) is None:
        raise ValueError("ISO calendar date required")
    try:
        calendar_date.fromisoformat(value)
    except ValueError:
        raise ValueError("ISO calendar date required") from None
    return value


def _literal(value: object) -> str:
    # Literal alone would also admit str subclasses in typed Python input.
    return _text(value)


def _locations(value: object) -> tuple[str, ...]:
    # Raw wire must be an array, never a string, tuple, set or iterable coercion.
    if type(value) is not list or not 1 <= len(value) <= 100:
        raise ValueError("Location array required")
    locations = tuple(_text(item) for item in value)
    if any(not 1 <= len(item) <= 40 for item in locations):
        raise ValueError("Invalid location identifier")
    if len(set(locations)) != len(locations):
        raise ValueError("Duplicate location identifier")
    return locations


_ExactUUID = Annotated[UUID, BeforeValidator(_uuid)]
_Nonblank100 = Annotated[str, Field(min_length=1, max_length=100), BeforeValidator(_nonblank)]
_TypeCode = Annotated[str, Field(min_length=1, max_length=256), BeforeValidator(_nonblank)]
_ValidUntil = Annotated[str, Field(max_length=20), BeforeValidator(_text)]
_Comment = Annotated[str, Field(max_length=2000), BeforeValidator(_text)]


class ContractCreateLocations(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    kind: Literal["locations"]
    locationIds: Annotated[tuple[str, ...], BeforeValidator(_locations)]

    @model_validator(mode="before")
    @classmethod
    def exact_discriminator(cls, value: object) -> object:
        # Pydantic forbids before field validators on an inferred discriminator.
        # Check raw kind at model level so typed str subclasses are still rejected.
        if isinstance(value, dict) and "kind" in value:
            _literal(value["kind"])
        return value


class ContractCreateBody(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid", hide_input_in_errors=True)

    kind: Annotated[Literal["contract-card"], BeforeValidator(_literal)]
    creationKey: _ExactUUID
    number: _Nonblank100
    date: Annotated[str, BeforeValidator(_date)]
    type: _Nonblank100
    typeCode: _TypeCode
    organizationId: _ExactUUID
    counterpartyId: _ExactUUID
    coverage: Annotated[ContractCreateLocations, Field(discriminator="kind")]
    validUntil: _ValidUntil | None
    comment: _Comment | None = None


def _check_media(request: Request) -> None:
    headers = request.scope.get("headers", [])
    types = [value for name, value in headers if name.lower() == b"content-type"]
    encodings = [value for name, value in headers if name.lower() == b"content-encoding"]
    if (len(types) != 1 or _MEDIA.fullmatch(types[0]) is None
            or len(encodings) > 1
            or (encodings and encodings[0].strip(b" \t").lower() != b"identity")):
        raise ContractCreateBodyError(415, "unsupported_media_type")


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON member")
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise ValueError("Invalid JSON constant")


async def parse_contract_create_body(request: Request) -> ContractCreateBody:
    """Read actual bytes up to 16 KiB inclusive, independent of Content-Length.

    Admission/auth/quota ordering belongs to the future caller. Stream disconnect,
    cancellation and upstream exceptions deliberately propagate unchanged.
    """
    _check_media(request)
    buffer = bytearray()
    async for chunk in request.stream():
        if len(chunk) > MAX_BODY_BYTES - len(buffer):
            # Do not copy even a slice of an oversized chunk or read another one.
            raise ContractCreateBodyError(413, "request_too_large")
        buffer.extend(chunk)
    try:
        payload = json.loads(
            buffer.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs, parse_constant=_constant,
        )
        if type(payload) is not dict:
            raise ValueError("JSON object required")
        return ContractCreateBody.model_validate(payload)
    except (ValueError, RecursionError):
        # Includes JSON/Unicode/Pydantic validation errors; never expose input.
        pass
    # Raise outside the handler: no raw validation exception retained as context.
    raise _invalid()


def _revalidate(body: ContractCreateBody) -> ContractCreateBody:
    """Build fresh raw fields, rather than trusting construct/copy or model_dump."""
    if type(body) is not ContractCreateBody:
        raise _invalid()
    data = vars(body)
    if set(data) != set(ContractCreateBody.model_fields) or body.__pydantic_extra__:
        raise _invalid()
    coverage = data["coverage"]
    if type(coverage) is not ContractCreateLocations:
        raise _invalid()
    nested = vars(coverage)
    if (set(nested) != set(ContractCreateLocations.model_fields)
            or coverage.__pydantic_extra__ or type(nested["locationIds"]) is not tuple):
        raise _invalid()
    # The list copy is bounded before allocating; tampered tuples can be huge.
    if not 1 <= len(nested["locationIds"]) <= 100:
        raise _invalid()
    raw = dict(data)
    raw["coverage"] = {"kind": nested["kind"], "locationIds": list(nested["locationIds"])}
    try:
        return ContractCreateBody.model_validate(raw)
    except ValidationError:
        pass
    raise _invalid()


def canonical_contract_create_bytes(body: ContractCreateBody) -> bytes:
    """Hash-v1 business payload; creationKey binds a separate intent namespace."""
    checked = _revalidate(body)
    payload = {
        "version": 1,
        "kind": checked.kind,
        "number": checked.number,
        "date": checked.date,
        "type": checked.type,
        "typeCode": checked.typeCode,
        "organizationId": str(checked.organizationId),
        "counterpartyId": str(checked.counterpartyId),
        "coverage": {"kind": checked.coverage.kind, "locationIds": sorted(checked.coverage.locationIds)},
        "validUntil": checked.validUntil,
        "comment": checked.comment,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def contract_create_hash(body: ContractCreateBody) -> str:
    return hashlib.sha256(canonical_contract_create_bytes(body)).hexdigest()
