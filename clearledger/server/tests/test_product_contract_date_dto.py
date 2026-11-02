"""Production DTO regression tests; authored SOURCE-only, not run in this task.

Use the ordinary package import so eager package initialization and annotation
evaluation participate. No fake app/package, extracted DTO, or import patching.
"""
from datetime import date
import json
from typing import get_args
import unittest

from pydantic import ValidationError

from app.product_api.dto import Contract, ContractListQuery, ListQuery


class ContractDateDTOTests(unittest.TestCase):
    def payload(self, value):
        return {
            "id": "50000000-0000-4000-8000-000000000001",
            "number": "DEMO-001",
            "typeCode": "fictional-type",
            "validUntil": None,
            "date": value,
            "title": None,
            "isClosed": False,
            "scopeType": "company",
            "counterpartyId": None,
        }

    def test_date_annotation_and_nullable_iso_date_schema(self):
        self.assertEqual(set(get_args(Contract.model_fields["date"].annotation)),
                         {date, type(None)})
        for mode in ("validation", "serialization"):
            with self.subTest(mode=mode):
                schema = Contract.model_json_schema(mode=mode, by_alias=True)
                field = schema["properties"]["date"]
                self.assertEqual(field["anyOf"], [
                    {"format": "date", "type": "string"}, {"type": "null"}])
                self.assertNotIn('"enum"', json.dumps(field))
                self.assertIn("date", schema["required"])
                self.assertEqual(field["examples"], ["2026-10-01"])
                self.assertEqual(field["description"],
                                 "Nullable parsed contract business date; "
                                 "dateFrom/dateTo filter created_at instead.")

    def test_valid_date_and_null_validate_and_keep_wire_values(self):
        for raw, expected in (("2026-10-01", date(2026, 10, 1)),
                              ("2024-02-29", date(2024, 2, 29)),
                              (None, None)):
            with self.subTest(raw=raw):
                payload = self.payload(raw)
                model = Contract.model_validate(payload)
                self.assertEqual(model.date, expected)
                self.assertEqual(model.model_dump(mode="json", by_alias=True), payload)
                self.assertEqual(json.loads(model.model_dump_json(by_alias=True)), payload)

    def test_invalid_contract_dates_are_rejected(self):
        for raw in ("not-a-date", "2026-02-29", "2026-13-01", "2026-10-32", {}, []):
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError) as raised:
                    Contract.model_validate(self.payload(raw))
                self.assertIn(("date",), [error["loc"] for error in raised.exception.errors()])

    def test_existing_iso_date_and_window_validators(self):
        for model_type in (ListQuery, ContractListQuery):
            for payload in ({}, {"dateFrom": None, "dateTo": None},
                            {"dateFrom": "2026-10-01", "dateTo": "2026-10-31"},
                            {"dateFrom": "2026-10-01", "dateTo": "2026-10-01"},
                            {"dateFrom": date(2026, 10, 1)}):
                with self.subTest(model=model_type.__name__, payload=payload):
                    model = model_type.model_validate(payload)
                    self.assertEqual(model.date_from, model.dateFrom)
                    self.assertEqual(model.date_to, model.dateTo)
            with self.subTest(model=model_type.__name__, window="reversed"):
                with self.assertRaisesRegex(ValidationError, "Invalid date window"):
                    model_type.model_validate({"dateFrom": "2026-10-31",
                                               "dateTo": "2026-10-01"})
            for raw in ("2026-2-01", "2026-10-01T00:00:00", "2026-02-29", 1790812800):
                for field in ("dateFrom", "dateTo"):
                    with self.subTest(model=model_type.__name__, field=field, raw=raw):
                        with self.assertRaises(ValidationError):
                            model_type.model_validate({field: raw})
