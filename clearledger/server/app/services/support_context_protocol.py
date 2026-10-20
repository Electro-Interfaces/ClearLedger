"""Строгие DTO и криптография support-context/1. Ни legacy JWT, ни key fallback."""
from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime
from typing import Annotated, Literal
from urllib.parse import urlsplit

import jwt
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services import sso

VERSION = "support-context/1"
MAX_REQUEST = 64 * 1024
Text = Annotated[str, Field(min_length=1, max_length=200)]
ContextRef = Annotated[str, Field(pattern=r"^scx_[A-Za-z0-9_-]{43}$")]
Action = Literal["context.read", "context.details", "context.select", "context.clarify",
                 "ticket.create", "ticket.read", "ticket.append"]


def fail(status: int, code: str):
    raise HTTPException(status, {"code": code, "retryable": status in (503, 504)},
                        headers={"WWW-Authenticate": "DPoP"} if status == 401 else None)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(Strict):
    version: Literal["support-context/1"]
    schemaVersion: Literal[1]


class CallRef(Strict):
    nodeId: Text
    connectorId: Text
    nodeContactId: Text


class Prepare(Envelope):
    callRef: CallRef
    phone: Annotated[str, Field(pattern=r"^\+[1-9][0-9]{6,14}$")]
    startedAt: datetime
    direction: Literal["inbound", "outbound"]

    @field_validator("startedAt")
    @classmethod
    def aware(cls, v):
        if v.tzinfo is None:
            raise ValueError("timezone required")
        return v


def trusted_url(v: str, *, origin=False) -> str:
    u = urlsplit(v)
    if (u.scheme not in ("http", "https") or not u.hostname or u.username or u.password
            or u.query or u.fragment or (origin and u.path not in ("", "/"))):
        raise ValueError("trusted absolute URL required")
    return v.rstrip("/")


class NodeTrust(Strict):
    nodeId: Text
    connectorId: Text
    admissionBaseUrl: Annotated[str, Field(max_length=1000)]
    prepareKeyId: Text

    @field_validator("admissionBaseUrl")
    @classmethod
    def url(cls, v):
        return trusted_url(v)


class Trust(Strict):
    enabled: bool = False
    publicOrigin: Annotated[str, Field(max_length=1000)]
    nodes: Annotated[list[NodeTrust], Field(min_length=1, max_length=30)]
    introspectionKeyId: Text
    requireMfa: bool = True
    postcallMaxSec: Annotated[int, Field(strict=True, ge=0, le=86400)] = 3600

    @field_validator("publicOrigin")
    @classmethod
    def origin(cls, v):
        return trusted_url(v, origin=True)

    @field_validator("nodes")
    @classmethod
    def unique(cls, v):
        if len({(n.nodeId, n.connectorId) for n in v}) != len(v):
            raise ValueError("duplicate node/connector")
        return v


class Configure(Envelope):
    config: Trust


class Admit(Envelope):
    nodeId: Text
    admissionCode: Annotated[str, Field(min_length=16, max_length=512)]


class Renew(Envelope):
    grantId: Text
    nodeId: Text
    admissionCode: Annotated[str, Field(min_length=16, max_length=512)]


class Postcall(Envelope):
    grantId: Text
    ticketRef: Text


class Revoke(Envelope):
    grantId: Text


class Inspect(Envelope):
    token: Annotated[str, Field(min_length=20, max_length=16384)]
    contextRef: ContextRef
    callRef: CallRef


class ServiceTokenRequest(Envelope):
    pass


class Actor(Strict):
    iss: Text
    sub: Text


class Confirmation(Strict):
    jkt: Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{43}$")]


class Claims(Strict):
    model_config = ConfigDict(extra="forbid", strict=True)
    version: Literal["support-context/1"]
    iss: Text
    aud: Literal["support-context"]
    sub: Annotated[str, Field(pattern=r"^[0-9a-f-]{36}$")]
    act: Actor
    scp: Literal["support_context", "ticket_postcall"]
    coreCid: Text
    cid: Text
    callRef: CallRef
    connectionId: Text
    contextRef: ContextRef
    grantId: Text
    jti: Text
    assignmentVersion: Annotated[int, Field(strict=True, ge=1)]
    permissionsVersion: Annotated[int, Field(strict=True, ge=1)]
    bindingVersion: Annotated[int, Field(strict=True, ge=1)]
    phase: Literal["offering", "connected", "consult", "wrapup", "postcall"]
    actions: list[Action]
    ticketRefs: Annotated[list[Text], Field(max_length=1)] = []
    cnf: Confirmation
    amr: Annotated[list[Text], Field(max_length=10)]
    iat: int
    nbf: int
    exp: int


def digest(v: str | dict) -> str:
    raw = v if isinstance(v, str) else json.dumps(v, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def thumbprint(jwk: dict) -> str:
    try:
        if set(jwk) - {"kty", "crv", "x", "y", "alg", "use", "key_ops", "kid"}:
            raise ValueError("private or unknown key field")
        if jwk["kty"] != "EC" or jwk["crv"] != "P-256":
            raise ValueError("P-256 required")
        if jwk.get("alg", "ES256") != "ES256" or jwk.get("use", "sig") != "sig":
            raise ValueError("signing key required")
        jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(jwk))
        raw = json.dumps({k: jwk[k] for k in ("crv", "kty", "x", "y")},
                         sort_keys=True, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
    except (ValueError, KeyError, TypeError):
        fail(401, "invalid_dpop_key")


def sign(payload: dict) -> str:
    key = sso._private_key()
    if not key:
        fail(503, "sso_unavailable")
    return jwt.encode(payload, key, algorithm="RS256",
                      headers={"kid": sso.settings.sso_kid, "typ": "at+jwt"})


def verify(token: str, audience: str) -> dict:
    try:
        h = jwt.get_unverified_header(token)
        if (h.get("alg") != "RS256" or h.get("typ") != "at+jwt"
                or set(h) - {"alg", "typ", "kid"}):
            raise ValueError("header")
        key = next((k for k in sso.public_jwks()["keys"] if k["kid"] == h.get("kid")), None)
        if key is None:
            raise ValueError("kid")
        c = jwt.decode(token, jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key)),
                       algorithms=["RS256"], audience=audience, issuer=sso.settings.sso_issuer,
                       options={"strict_aud": True,
                                "require": ["sub", "aud", "iss", "version", "iat", "nbf", "exp", "jti"]})
        if (c["version"] != VERSION or any(type(c[k]) is not int for k in ("iat", "nbf", "exp"))
                or not 0 < c["exp"] - c["iat"] <= 120 or c["nbf"] != c["iat"]
                or not isinstance(c["jti"], str) or not c["jti"]):
            raise ValueError("claims")
        if audience == "support-context":
            Claims.model_validate(c)
            if c["scp"] == "ticket_postcall":
                if (c["phase"] != "postcall" or len(c["ticketRefs"]) != 1
                        or not set(c["actions"]) <= {"ticket.read", "ticket.append"}):
                    raise ValueError("postcall scope")
            elif c["phase"] == "postcall" or c["ticketRefs"] or "ticket.read" in c["actions"]:
                raise ValueError("live scope")
        return c
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        fail(401, "invalid_token")


def proof(proof_token: str, *, jkt: str, htu: str, access_token: str | None) -> str:
    try:
        h = jwt.get_unverified_header(proof_token)
        if (h.get("typ") != "dpop+jwt" or h.get("alg") != "ES256"
                or set(h) != {"typ", "alg", "jwk"} or thumbprint(h["jwk"]) != jkt):
            raise ValueError("header")
        c = jwt.decode(proof_token, jwt.algorithms.ECAlgorithm.from_jwk(json.dumps(h["jwk"])),
                       algorithms=["ES256"], options={"require": ["htm", "htu", "iat", "jti"]})
        if (set(c) - {"htm", "htu", "iat", "jti", "ath"}
                or c["htm"] != "POST" or c["htu"] != htu
                or type(c["iat"]) is not int or abs(time.time() - c["iat"]) > 30
                or not isinstance(c["jti"], str) or not 1 <= len(c["jti"]) <= 200):
            raise ValueError("binding")
        expected = (base64.urlsafe_b64encode(hashlib.sha256(access_token.encode()).digest()).decode().rstrip("=")
                    if access_token else None)
        if c.get("ath") != expected:
            raise ValueError("ath")
        return digest(jkt + ":" + c["jti"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        fail(401, "invalid_dpop")
