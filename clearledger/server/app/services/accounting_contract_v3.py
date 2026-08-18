from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid
from typing import Any


ACCOUNTING_PACKET_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")
BUSINESS_PROJECTION_FIELDS = (
    "BusinessDate",
    "BusinessKeyHash",
    "BusinessShiftAliases",
    "BusinessShiftID",
    "CompanyID",
    "FactOrigin",
    "StationID",
    "Документы",
    "НСИ",
    "ПолнотаГруппы",
    "Смена",
    "ТТК",
)
ACCOUNTING_PACKET_FIELDS = frozenset({
    "ВерсияФормата", "ВерсияКонтракта", "ИдентификаторПакета",
    "BusinessShiftID", "BusinessShiftAliases", "BusinessDate", "CompanyID",
    "StationID", "BusinessKeyHash", "FactOrigin", "TransportProducer",
    "РевизияПакета", "ИдентификаторПолитики", "РевизияПолитики",
    "ХешПолитики", "ХешПакета", "ПолнотаГруппы", "Смена", "НСИ", "ТТК",
    "Документы", "UnicodeNormalization",
})
ACK_FIELDS = frozenset({
    "ТипСообщения", "ВерсияКонтракта", "ConsumerID", "ClaimRequestID",
    "AttemptID", "PacketID", "ИдентификаторПакета", "BusinessShiftID",
    "BusinessKeyHash", "РевизияПакета", "ХешПакета", "Результат",
    "КодОшибки", "ОписаниеОшибки", "Компоненты", "AckHash",
})
ACK_COMPONENT_FIELDS = frozenset({
    "Порядок", "Тип", "ИсточникUUID", "СсылкаБП", "SourceHash",
    "TargetHash", "Проведен", "Результат", "КодОшибки",
    "ОписаниеОшибки",
})


class AccountingContractError(ValueError):
    pass


def validate_top_level_v3(packet: dict) -> None:
    actual = set(packet)
    missing = sorted(ACCOUNTING_PACKET_FIELDS - actual)
    unknown = sorted(actual - ACCOUNTING_PACKET_FIELDS)
    if missing:
        raise AccountingContractError(
            "В пакете v3 отсутствуют поля: " + ", ".join(missing),
        )
    if unknown:
        raise AccountingContractError(
            "В пакете v3 запрещены поля: " + ", ".join(unknown),
        )
    if packet.get("UnicodeNormalization") != "NFC":
        raise AccountingContractError("UnicodeNormalization должен быть NFC")
    if normalize_nfc_json(packet) != packet:
        raise AccountingContractError("Пакет содержит строки не в NFC")


def validate_ack_v3(ack: dict) -> None:
    if not isinstance(ack, dict):
        raise AccountingContractError("ACK должен быть JSON-объектом")
    actual = set(ack)
    missing = sorted(ACK_FIELDS - actual)
    unknown = sorted(actual - ACK_FIELDS)
    if missing or unknown:
        details = []
        if missing:
            details.append("отсутствуют: " + ", ".join(missing))
        if unknown:
            details.append("запрещены: " + ", ".join(unknown))
        raise AccountingContractError("Некорректные поля ACK: " + "; ".join(details))
    if ack["ТипСообщения"] != "ack" or ack["ВерсияКонтракта"] != "3.0.0":
        raise AccountingContractError("ACK должен соответствовать контракту 3.0.0")
    if not isinstance(ack["ConsumerID"], str) or not ack["ConsumerID"].strip():
        raise AccountingContractError("ConsumerID ACK не может быть пустым")
    if ack["Результат"] not in {
        "accepted", "rejected", "blocked_mapping", "retry_wait", "needs_review",
    }:
        raise AccountingContractError("Недопустимый Результат ACK")
    for field in ("КодОшибки", "ОписаниеОшибки"):
        if ack[field] is not None and not isinstance(ack[field], str):
            raise AccountingContractError(f"{field} ACK должен быть строкой или null")
    components = ack["Компоненты"]
    if not isinstance(components, list):
        raise AccountingContractError("Компоненты ACK должны быть массивом")
    keys = []
    for index, component in enumerate(components):
        if not isinstance(component, dict) or set(component) != ACK_COMPONENT_FIELDS:
            raise AccountingContractError(
                f"Компонент ACK {index + 1} не соответствует exact schema",
            )
        order = component["Порядок"]
        if isinstance(order, bool) or not isinstance(order, int) or order != index + 1:
            raise AccountingContractError(
                "Порядок компонентов ACK должен быть непрерывным от 1",
            )
        kind = component["Тип"]
        source_id = component["ИсточникUUID"]
        if kind not in {"assembly", "retail", "disassembly"}:
            raise AccountingContractError("Неизвестный Тип компонента ACK")
        if not isinstance(source_id, str) or not source_id.strip():
            raise AccountingContractError("ИсточникUUID компонента ACK пуст")
        if not isinstance(component["Проведен"], bool):
            raise AccountingContractError("Проведен компонента ACK должен быть boolean")
        if component["Результат"] not in {"accepted", "rejected", "needs_review"}:
            raise AccountingContractError("Некорректный Результат компонента ACK")
        for field in ("СсылкаБП", "TargetHash", "КодОшибки", "ОписаниеОшибки"):
            if component[field] is not None and not isinstance(component[field], str):
                raise AccountingContractError(
                    f"{field} компонента ACK должен быть строкой или null",
                )
        keys.append((order, kind, source_id))
    if len(set(keys)) != len(keys) or keys != sorted(keys):
        raise AccountingContractError("Компоненты ACK дублируются или не канонически отсортированы")


def normalize_nfc_json(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [normalize_nfc_json(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise AccountingContractError("Ключ JSON должен быть строкой")
            key = unicodedata.normalize("NFC", raw_key)
            if key in result:
                raise AccountingContractError("Коллизия ключей JSON после NFC")
            result[key] = normalize_nfc_json(raw_value)
        return result
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        raise AccountingContractError("Binary float запрещён контрактом v3")
    raise AccountingContractError(f"Недопустимый тип JSON: {type(value).__name__}")


def canonical_bytes(value: Any) -> bytes:
    normalized = normalize_nfc_json(value)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def alias_hash(algorithm: str, attributes: dict) -> str:
    return canonical_hash({"algorithm": algorithm, **attributes})


def business_key_hash(
    business_shift_id: uuid.UUID | str,
    company_key: str,
    station_id: str,
) -> str:
    return canonical_hash({
        "BusinessShiftID": str(business_shift_id).lower(),
        "CompanyID": company_key,
        "StationID": station_id,
    })


def accounting_packet_uuid(business_shift_id: uuid.UUID | str) -> uuid.UUID:
    name = (
        "urn:elsyplus:ledger:accounting-packet:v1:"
        f"{str(business_shift_id).lower()}"
    )
    return uuid.uuid5(ACCOUNTING_PACKET_NAMESPACE, name)


def business_projection_hash(packet: dict) -> str:
    missing = [field for field in BUSINESS_PROJECTION_FIELDS if field not in packet]
    if missing:
        raise AccountingContractError(
            "В пакете отсутствуют поля бизнес-проекции: " + ", ".join(missing)
        )
    return canonical_hash({field: packet[field] for field in BUSINESS_PROJECTION_FIELDS})


def claim_request_hash(consumer_id: str, claim_request_id: uuid.UUID, lease_seconds: int) -> str:
    return canonical_hash({
        "ClaimRequestID": str(claim_request_id).lower(),
        "ConsumerID": consumer_id,
        "LeaseSeconds": lease_seconds,
        "ВерсияКонтракта": "3.0.0",
        "ТипСообщения": "claim_request",
    })


def ack_hash(ack: dict) -> str:
    projection = {
        key: value for key, value in ack.items()
        if key not in {"AckHash", "ПолученВ"}
    }
    return canonical_hash(projection)
