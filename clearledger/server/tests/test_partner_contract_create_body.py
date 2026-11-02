"""Authored NOTRUN. Standalone unittest; load source without product_api/__init__.

ROOT owns isolated execution with actual Pydantic/Starlette; no conftest/ORM/SQL.
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from uuid import UUID

from pydantic import ValidationError
from starlette.requests import ClientDisconnect, Request

_SOURCE = Path(__file__).resolve().parents[1] / "app/product_api/contract_create_body.py"
_SPEC = importlib.util.spec_from_file_location("_partner_contract_create_body_under_test", _SOURCE)
assert _SPEC is not None and _SPEC.loader is not None
body_module = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = body_module
_SPEC.loader.exec_module(body_module)
Body = body_module.ContractCreateBody
Locations = body_module.ContractCreateLocations
BodyError = body_module.ContractCreateBodyError
canonical = body_module.canonical_contract_create_bytes
body_hash = body_module.contract_create_hash
parse = body_module.parse_contract_create_body

# Independent literal oracle: no implementation encoder/model_dump produces this.
GOLDEN = (
    '{"comment":null,"counterpartyId":"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",'
    '"coverage":{"kind":"locations","locationIds":["A ","é","é","я","\uffff","😀"]},'
    '"date":"2024-02-29","kind":"contract-card","number":" Д-01 ",'
    '"organizationId":"aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",'
    '"type":" Lease ","typeCode":"Custom/А ","validUntil":null,"version":1}'
).encode("utf-8")
GOLDEN_SHA256 = "d11891751cc46939e67c4f41312af59d85dbe4b48a477bb7369ba3def36df3d8"


class StringSubclass(str):
    pass


class UUIDSubclass(UUID):
    pass


class ListSubclass(list):
    pass


def payload():
    return {
        "kind": "contract-card",
        "creationKey": "CCCCCCCC-CCCC-4CCC-8CCC-CCCCCCCCCCCC",
        "number": " Д-01 ", "date": "2024-02-29", "type": " Lease ",
        "typeCode": "Custom/А ",
        "organizationId": "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
        "counterpartyId": "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB",
        "coverage": {"kind": "locations", "locationIds": ["😀", "я", "é", "é", "A ", "\uffff"]},
        "validUntil": None,
    }


def wire(value=None):
    return json.dumps(payload() if value is None else value, ensure_ascii=False).encode("utf-8")


class Receiver:
    def __init__(self, events):
        self.events = list(events)
        self.calls = 0

    async def __call__(self):
        self.calls += 1
        if not self.events:
            raise AssertionError("Unexpected extra receive")
        event = self.events.pop(0)
        if isinstance(event, BaseException):
            raise event
        return event


def request(chunks, headers=None):
    events = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ]
    receiver = Receiver(events)
    scope = {"type": "http", "method": "POST", "path": "/api/v1/contracts",
             "headers": [(b"content-type", b"application/json")] if headers is None else headers}
    return Request(scope, receive=receiver), receiver


class ContractCreateModelTests(unittest.TestCase):
    def assert_invalid(self, value):
        with self.assertRaises(ValidationError):
            Body.model_validate(value)

    def test_valid_exact_frozen_models(self):
        body = Body.model_validate(payload())
        self.assertIs(type(body), Body)
        self.assertIs(type(body.coverage), Locations)
        self.assertIs(type(body.coverage.locationIds), tuple)
        self.assertEqual(body.number, " Д-01 ")
        self.assertEqual(body.typeCode, "Custom/А ")
        self.assertEqual(body.comment, None)
        self.assertEqual(str(body.organizationId), "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
        for model, field, value in [(body, "number", "changed"), (body.coverage, "kind", "x")]:
            with self.subTest(field=field), self.assertRaises(ValidationError):
                setattr(model, field, value)
        with self.assertRaises(TypeError):
            body.coverage.locationIds[0] = "changed"

    def test_all_required_fields(self):
        for field in payload():
            value = payload()
            del value[field]
            with self.subTest(field=field):
                self.assert_invalid(value)
        for field in ("kind", "locationIds"):
            value = payload()
            del value["coverage"][field]
            with self.subTest(nested=field):
                self.assert_invalid(value)

    def test_forbidden_fields_every_level_and_snake_aliases(self):
        forbidden = ("companyId", "company", "actor", "app", "install", "grant", "raw", "source",
                     "tax", "sign", "project", "budget", "amount", "credential", "token", "jti",
                     "approval", "responsible", "register", "creation_key", "organization_id",
                     "counterparty_id", "type_code", "valid_until", "location_ids")
        for level in ("body", "coverage"):
            for field in forbidden:
                value = payload()
                (value if level == "body" else value["coverage"])[field] = "private-value"
                with self.subTest(level=level, field=field):
                    self.assert_invalid(value)
        for camel, snake in (("creationKey", "creation_key"), ("typeCode", "type_code"),
                             ("organizationId", "organization_id"), ("counterpartyId", "counterparty_id"),
                             ("validUntil", "valid_until")):
            value = payload()
            value[snake] = value.pop(camel)
            with self.subTest(alias=snake):
                self.assert_invalid(value)

    def test_discriminators_and_coverage_shape(self):
        for field, bad in (("kind", "contract"), ("kind", StringSubclass("contract-card")),
                           ("kind", None), ("coverage", None), ("coverage", [])):
            value = payload()
            value[field] = bad
            with self.subTest(field=field, bad=bad):
                self.assert_invalid(value)
        for kind in ("company", "unassigned", "stations", "evse", "LOCATIONS", None, True,
                     StringSubclass("locations")):
            value = payload()
            value["coverage"]["kind"] = kind
            with self.subTest(kind=kind):
                self.assert_invalid(value)

    def test_uuid_strict_wire_and_exact_typed_uuid(self):
        identifier = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        invalid = [True, 1, 1.0, None, b"x", [], {}, " " + identifier, identifier + " ",
                   identifier.replace("-", ""), "{" + identifier + "}", "urn:uuid:" + identifier,
                   identifier.replace("a", "ａ"), "g" + identifier[1:], StringSubclass(identifier),
                   UUIDSubclass(identifier)]
        for field in ("creationKey", "organizationId", "counterpartyId"):
            for bad in invalid:
                value = payload()
                value[field] = bad
                with self.subTest(field=field, bad=bad):
                    self.assert_invalid(value)
            for good in (identifier, identifier.upper(), UUID(identifier)):
                value = payload()
                value[field] = good
                with self.subTest(field=field, good=good):
                    self.assertEqual(getattr(Body.model_validate(value), field), UUID(identifier))

    def test_strict_calendar_date(self):
        invalid = [None, True, 0, 20240229, 0.0, b"2024-02-29", date(2024, 2, 29),
                   datetime(2024, 2, 29), "2023-02-29", "2024-04-31", "0000-01-01", "10000-01-01",
                   "2024-00-10", "2024-13-01", "2024-01-00", "2024-2-29", "20240229", "2024-W09-4",
                   "２０２４-02-29", "2024-02-29T00:00:00Z", "2024-02-29 ", StringSubclass("2024-02-29")]
        for bad in invalid:
            value = payload()
            value["date"] = bad
            with self.subTest(bad=bad):
                self.assert_invalid(value)
        for good in ("0001-01-01", "9999-12-31", "2000-02-29"):
            value = payload()
            value["date"] = good
            self.assertEqual(Body.model_validate(value).date, good)

    def test_text_bounds_types_and_nonblank(self):
        for field, maximum, blank_allowed in (("number", 100, False), ("type", 100, False),
                                               ("typeCode", 256, False), ("validUntil", 20, True),
                                               ("comment", 2000, True)):
            for good in (("", " ", "я" * maximum) if blank_allowed else ("я", " x ", "я" * maximum)):
                value = payload()
                value[field] = good
                with self.subTest(field=field, good_len=len(good)):
                    self.assertEqual(getattr(Body.model_validate(value), field), good)
            bad_values = [True, 1, 1.0, b"x", [], {}, "я" * (maximum + 1), StringSubclass("x")]
            if not blank_allowed:
                bad_values += [None, "", " \t\r\n", "\u2003"]
            for bad in bad_values:
                value = payload()
                value[field] = bad
                with self.subTest(field=field, bad_type=type(bad), bad_len=len(bad) if type(bad) is str else None):
                    self.assert_invalid(value)

    def test_postgres_text_and_utf8_every_text_field(self):
        for field in ("number", "type", "typeCode", "validUntil", "comment"):
            for bad in ("a\x00b", "\ud800", "\udfff"):
                value = payload()
                value[field] = bad
                with self.subTest(field=field, bad=ascii(bad)):
                    self.assert_invalid(value)
        for bad in ("a\x00b", "\ud800", "\udfff"):
            value = payload()
            value["coverage"]["locationIds"] = [bad]
            self.assert_invalid(value)

    def test_location_bounds_raw_arrays_and_element_types(self):
        for bad in ([], ["x"] * 101, (), ("x",), {"x"}, "x", None, True,
                    [""], ["я" * 41], [True], [1], [1.0], [None], [b"x"], [["x"]],
                    [{}], [StringSubclass("x")], ListSubclass(["x"])):
            value = payload()
            value["coverage"]["locationIds"] = bad
            with self.subTest(bad=bad):
                self.assert_invalid(value)
        for good in (["я" * 40], [str(i) for i in range(100)], [" "]):
            value = payload()
            value["coverage"]["locationIds"] = good
            self.assertEqual(Body.model_validate(value).coverage.locationIds, tuple(good))

    def test_location_uniqueness_uses_exact_unicode_identity(self):
        value = payload()
        exact = ["A", "a", "A ", " A", "é", "é", "%2F", "/", "😀", "\uffff"]
        value["coverage"]["locationIds"] = exact
        self.assertEqual(Body.model_validate(value).coverage.locationIds, tuple(exact))
        for duplicate in ("A", "é", "é", "😀"):
            value["coverage"]["locationIds"] = [duplicate, duplicate]
            self.assert_invalid(value)

    def test_required_nullable_and_optional_nullable_distinctions(self):
        value = payload()
        self.assertIsNone(Body.model_validate(value).validUntil)
        del value["validUntil"]
        self.assert_invalid(value)
        value["validUntil"] = ""
        self.assertEqual(Body.model_validate(value).validUntil, "")
        value["validUntil"] = "not-a-date"
        self.assertEqual(Body.model_validate(value).validUntil, "not-a-date")
        self.assertIsNone(Body.model_validate(value).comment)
        value["comment"] = None
        self.assertIsNone(Body.model_validate(value).comment)
        value["comment"] = ""
        self.assertEqual(Body.model_validate(value).comment, "")

    def test_canonical_independent_literal_and_digest(self):
        body = Body.model_validate(payload())
        self.assertEqual(canonical(body), GOLDEN)
        self.assertEqual(len(GOLDEN), 343)
        self.assertEqual(body_hash(body), GOLDEN_SHA256)

    def test_canonical_order_uuid_spelling_comment_and_creation_key(self):
        value = payload()
        value["coverage"]["locationIds"].reverse()
        for field in ("creationKey", "organizationId", "counterpartyId"):
            value[field] = value[field].lower()
        value["creationKey"] = "00000000-0000-0000-0000-000000000000"
        value["comment"] = None
        value = dict(reversed(list(value.items())))
        self.assertEqual(canonical(Body.model_validate(value)), GOLDEN)
        self.assertEqual(body_hash(Body.model_validate(value)), GOLDEN_SHA256)

    def test_canonical_exact_differences(self):
        cases = [
            ("validUntil", "", GOLDEN.replace(b'"validUntil":null', b'"validUntil":""'),
             "ca612fc837888c422a0fad83280dc811cfe0da42f123f2f003308109f22cc77e"),
            ("number", "Д-01", GOLDEN.replace('" Д-01 "'.encode(), '"Д-01"'.encode()),
             "74b66c5002c9710fd1612920851aa1e67d0a9c0eba1df7c3caabc8acebc83b60"),
            ("type", " lease ", GOLDEN.replace(b'" Lease "', b'" lease "'),
             "233cbbf4fcf2184cb762010cf544082bb326b25210afe2a34d9047ee77a49579"),
        ]
        for field, changed, expected, digest in cases:
            value = payload()
            value[field] = changed
            with self.subTest(field=field):
                self.assertEqual(canonical(Body.model_validate(value)), expected)
                self.assertEqual(body_hash(Body.model_validate(value)), digest)
        for field, changed in (("comment", ""), ("typeCode", "custom/А ")):
            value = payload()
            value[field] = changed
            self.assertNotEqual(body_hash(Body.model_validate(value)), GOLDEN_SHA256)

    def test_canonical_rejects_non_exact_model(self):
        class BodySubclass(Body):
            pass

        from dataclasses import make_dataclass
        for bad in (payload(), None, object(), make_dataclass("Record", [])(),
                    BodySubclass.model_validate(payload())):
            for helper in (canonical, body_hash):
                with self.subTest(helper=helper.__name__, bad_type=type(bad)), self.assertRaises(BodyError):
                    helper(bad)

    def test_canonical_revalidates_model_construct_and_copy(self):
        good = Body.model_validate(payload())
        corrupt = [
            good.model_copy(update={"number": ""}),
            good.model_copy(update={"number": StringSubclass("x")}),
            good.model_copy(update={"number": "x" * 101}),
            good.model_copy(update={"organizationId": True}),
            good.model_copy(update={"date": date(2024, 2, 29)}),
            good.model_copy(update={"comment": "\ud800"}),
            good.model_copy(update={"validUntil": 1}),
            good.model_copy(update={"companyId": "private-value"}),
            good.model_copy(update={"coverage": {"kind": "locations", "locationIds": ["x"]}}),
            Body.model_construct(),
        ]
        for bad_ids in ((), ("x", "x"), ("x" * 41,), ("\x00",), ("\ud800",),
                        (True,), tuple(str(i) for i in range(101)), ["x"]):
            coverage = Locations.model_construct(kind="locations", locationIds=bad_ids)
            corrupt.append(good.model_copy(update={"coverage": coverage}))
        for update in ({"kind": "other"}, {"raw": "private-value"}):
            corrupt.append(good.model_copy(update={"coverage": good.coverage.model_copy(update=update)}))
        class LocationsSubclass(Locations):
            pass

        corrupt.append(good.model_copy(update={"coverage": LocationsSubclass.model_validate(payload()["coverage"])}))
        corrupt.append(good.model_copy(update={"coverage": Locations.model_construct()}))
        for missing in ("validUntil", "number", "coverage"):
            incomplete = dict(vars(good))
            del incomplete[missing]
            corrupt.append(Body.model_construct(**incomplete))
        constructed = dict(vars(good))
        constructed["creationKey"] = 42
        corrupt.append(Body.model_construct(**constructed))
        for i, bad in enumerate(corrupt):
            for helper in (canonical, body_hash):
                with self.subTest(case=i, helper=helper.__name__), self.assertRaises(BodyError) as caught:
                    helper(bad)
                self.assertEqual((caught.exception.status, caught.exception.code), (422, "invalid_request"))
                self.assertIsNone(caught.exception.__context__)
        # Valid bypass-created contents are revalidated, rather than categorically forbidden.
        self.assertEqual(canonical(Body.model_construct(**vars(good))), GOLDEN)


class ContractCreateParserTests(unittest.IsolatedAsyncioTestCase):
    async def assert_error(self, raw, status=422, code="invalid_request", headers=None):
        req, receiver = request([raw], headers)
        with self.assertRaises(BodyError) as caught:
            await parse(req)
        self.assertEqual((caught.exception.status, caught.exception.code), (status, code))
        self.assertEqual(str(caught.exception), code)
        self.assertIsNone(caught.exception.__context__)
        self.assertIsNone(caught.exception.__cause__)
        self.assertNotIn("private-value", repr(caught.exception))
        self.assertNotIn("private-value", vars(caught.exception).values())
        return receiver

    async def test_real_request_chunked_utf8_and_no_body_method(self):
        raw = wire()
        req, receiver = request([raw[:1], raw[1:10], b"", raw[10:]])
        async def forbidden_body():
            raise AssertionError("Unbounded Request.body call")
        req.body = forbidden_body
        body = await parse(req)
        self.assertEqual(canonical(body), GOLDEN)
        self.assertEqual(receiver.calls, 4)
        # Splitting inside a multibyte scalar must work: decode only after bounded read.
        req, _ = request([raw[i:i + 1] for i in range(len(raw))])
        self.assertEqual(canonical(await parse(req)), GOLDEN)

    async def test_content_length_missing_false_zero_large_and_invalid(self):
        for length in (None, b"0", b"1", b"999999999", b"invalid", b"-1"):
            headers = [(b"content-type", b"application/json")]
            if length is not None:
                headers.append((b"content-length", length))
            req, receiver = request([wire()], headers)
            with self.subTest(length=length):
                self.assertEqual(canonical(await parse(req)), GOLDEN)
                self.assertEqual(receiver.calls, 1)

    async def test_inclusive_actual_byte_boundary(self):
        raw = wire()
        for size in (16383, 16384):
            padded = raw + b" " * (size - len(raw))
            req, _ = request([padded[:111], padded[111:]])
            with self.subTest(size=size):
                self.assertEqual(canonical(await parse(req)), GOLDEN)
        await self.assert_error(raw + b" " * (16385 - len(raw)), 413, "request_too_large")

    async def test_oversized_chunk_stops_before_more_receive_and_before_json(self):
        for chunks in ([b"private-value" * 2000, b"never-read"],
                       [b"{" * 16384, b"x", b"never-read"]):
            req, receiver = request(chunks)
            with self.subTest(first_size=len(chunks[0])), self.assertRaises(BodyError) as caught:
                await parse(req)
            self.assertEqual((caught.exception.status, caught.exception.code), (413, "request_too_large"))
            self.assertEqual(receiver.calls, len(chunks) - 1)
            self.assertEqual(receiver.events[-1]["body"], b"never-read")

    async def test_media_accepts_only_json_optional_utf8_token(self):
        for media in (b"application/json", b"APPLICATION/JSON", b"application/json;charset=utf-8",
                      b" application/json ; CHARSET = UTF-8\t"):
            for encoding in (None, b"identity", b" Identity "):
                headers = [(b"content-type", media)]
                if encoding is not None:
                    headers.append((b"content-encoding", encoding))
                req, _ = request([wire()], headers)
                with self.subTest(media=media, encoding=encoding):
                    self.assertEqual(canonical(await parse(req)), GOLDEN)

    async def test_media_rejections_do_not_read_stream(self):
        invalid = [[], [(b"content-type", b"application/json"), (b"content-type", b"application/json")]]
        for media in (b"", b"text/json", b"application/problem+json", b"application/jsonx", b"application/json,application/json",
                      b"application/json;charset=ascii", b"application/json;charset=\"utf-8\"",
                      b"application/json;charset=utf-8; charset=utf-8", b"application/json;foo=bar",
                      b"application/json;", b"application/json; charset=utf8", b"application/json\n", b"\xff"):
            invalid.append([(b"content-type", media)])
        for encoding in (b"gzip", b"br", b"deflate", b"", b"identity,gzip", b"identity;foo=bar"):
            invalid.append([(b"content-type", b"application/json"), (b"content-encoding", encoding)])
        invalid.append([(b"content-type", b"application/json"), (b"content-encoding", b"identity"),
                        (b"content-encoding", b"identity")])
        for headers in invalid:
            with self.subTest(headers=headers):
                receiver = await self.assert_error(b"private-value", 415, "unsupported_media_type", headers)
                self.assertEqual(receiver.calls, 0)

    async def test_json_objects_only_malformed_trailing_and_constants(self):
        cases = [b"", b" ", b"null", b"[]", b'"private-value"', b"true", b"42", b"{} {}",
                 wire() + b"null", b'{"private-value":}', b"{", b"\xef\xbb\xbf{}", b"{\"x\":1,}",
                 b"NaN", b"Infinity", b"-Infinity", b'{"x":NaN}', b'{"x":[Infinity]}',
                 b'{"x":-Infinity}', b'/*comment*/{}', b'{"comment":"unescaped\nline"}']
        for raw in cases:
            with self.subTest(raw=raw):
                await self.assert_error(raw)
        for constant in (b"NaN", b"Infinity", b"-Infinity"):
            await self.assert_error(wire().replace(b'"validUntil": null', b'"validUntil": ' + constant))

    async def test_duplicate_keys_at_root_nested_and_escaped_spelling(self):
        raw = wire()
        cases = [b'{"kind":"private-value","kind":"contract-card"}',
                 raw.replace(b'"validUntil": null', b'"validUntil": null,"validUntil":""'),
                 raw.replace(b'"locationIds": [', b'"kind":"locations","locationIds": ['),
                 b'{"x":{"a":1,"a":2}}', b'{"x":[{"a":1,"a":2}]}',
                 b'{"comment":null,"\\u0063omment":null}']
        for duplicated in cases:
            with self.subTest(raw=duplicated):
                await self.assert_error(duplicated)

    async def test_invalid_utf8_escaped_surrogates_nul_and_deep_json(self):
        for raw in (b"\xff", b"\xc0\x80", b"\xed\xa0\x80", wire() + b"\xff",
                    wire().replace(b'"validUntil": null', b'"validUntil":"\\ud800"'),
                    wire().replace(b'"validUntil": null', b'"validUntil":"\\udfff"'),
                    wire().replace(b'"validUntil": null', b'"validUntil":"\\u0000"'),
                    b'{"x":' + b"[" * 1200 + b"0" + b"]" * 1200 + b"}"):
            with self.subTest(raw_prefix=raw[:10]):
                await self.assert_error(raw)
        # A valid escaped surrogate pair decodes to one scalar, which remains text.
        raw = wire().replace(b'"validUntil": null', b'"validUntil":"\\ud83d\\ude00"')
        req, _ = request([raw])
        self.assertEqual((await parse(req)).validUntil, "😀")

    async def test_parser_maps_dto_failure_without_raw_input(self):
        value = payload()
        value["companyId"] = "private-value"
        await self.assert_error(wire(value))
        value = payload()
        value["number"] = "private-value" * 100
        await self.assert_error(wire(value))

    async def test_cancellation_disconnect_and_upstream_errors_propagate(self):
        for error in (asyncio.CancelledError(), RuntimeError("upstream")):
            receiver = Receiver([{"type": "http.request", "body": b"{", "more_body": True}, error])
            req = Request({"type": "http", "headers": [(b"content-type", b"application/json")]}, receive=receiver)
            with self.subTest(error=type(error)), self.assertRaises(type(error)) as caught:
                await parse(req)
            self.assertIs(caught.exception, error)
            self.assertEqual(receiver.calls, 2)
        receiver = Receiver([{"type": "http.request", "body": b"{", "more_body": True},
                             {"type": "http.disconnect"}])
        req = Request({"type": "http", "headers": [(b"content-type", b"application/json")]}, receive=receiver)
        with self.assertRaises(ClientDisconnect):
            await parse(req)
        self.assertEqual(receiver.calls, 2)


if __name__ == "__main__":
    unittest.main()
