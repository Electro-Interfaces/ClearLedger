"""
Построитель документов 1С:БП из разбивки смены (FuelShiftSale) и ТТН.

Воспроизводит TL_СозданиеДокументов расширения TradeLedger.cfe:
  СМЕНА → ОРП (retail_cash+retail_card) + ПКО (retail_cash) + Перемещения
          (cards/online/voucher/ledger) + Списание (writeoff_fuel)
  ТТН   → Перемещение тонн (41.01) + Комплектация тонны→литры (41.02)

Возвращает декларативные пакеты {kind, idem_key, payload} — материализуются
в ExportPacket. Натуральные ключи совпадают с .cfe (TL|СМЕНА / TL|ТТН) для
бесшовного cutover. Проводки делает 1С по своему механизму документа.
"""
from __future__ import annotations

# Время проведения документов (эталон ГИГ из TL_Настройки.ВремяДок_*)
T_SHIFT = "23:50"     # ОРП, ПКО, Перемещения каналов, Списание
T_TTN_TRANSFER = "11:00"
T_TTN_ASSEMBLY = "13:00"

RETAIL_CHANNELS = ("retail_cash", "retail_card")


def _nom(fuel_by_code: dict, code: int, unit: str) -> str:
    fm = fuel_by_code.get(code) or {}
    return (fm.get("nomenclature_liters") if unit == "л" else fm.get("nomenclature_tonnes")) or ""


def _fuel_name(fuel_by_code: dict, code: int) -> str:
    return (fuel_by_code.get(code) or {}).get("fuel_name") or str(code)


def build_shift_documents(
    *,
    system: int,
    station_code: int,
    shift_number: int,
    shift_date: str,
    warehouse_azs: str,
    sales: list[dict],
    fuel_by_code: dict,
    channels_by_code: dict,
) -> list[dict]:
    """sales: [{payment_channel, fuel_code, liters, amount, discount, warehouse_name}].

    channels_by_code: {code: {requires_transfer, warehouse_name, name}}.
    """
    base = f"TL|СМЕНА|{system}|{station_code}|{shift_number}"
    docs: list[dict] = []

    def line(s: dict, unit: str = "л") -> dict:
        code = int(s["fuel_code"])
        liters = float(s["liters"])
        amount = float(s["amount"])
        return {
            "fuel_code": code,
            "fuel_name": _fuel_name(fuel_by_code, code),
            "nomenclature": _nom(fuel_by_code, code, unit),
            "liters": round(liters, 3),
            "amount": round(amount, 2),
            "discount": round(float(s.get("discount") or 0), 2),
            "price": round(amount / liters, 2) if liters else 0,
        }

    # ── ОРП: розница (наличные + банковские карты) ──────────────────────────
    retail = [s for s in sales if s["payment_channel"] in RETAIL_CHANNELS]
    cash_amount = sum(float(s["amount"]) for s in sales if s["payment_channel"] == "retail_cash")
    card_amount = sum(float(s["amount"]) for s in sales if s["payment_channel"] == "retail_card")
    if retail:
        docs.append({
            "kind": "shift_orp",
            "idem_key": base,
            "payload": {
                "doc_type": "ОтчетОРозничныхПродажах",
                "operation": "ОтчетККМОПродажах",
                "warehouse": warehouse_azs,
                "date": shift_date, "time": T_SHIFT,
                "system": system, "station": station_code, "shift": shift_number,
                "lines": [line(s) for s in retail],
                "payment_cash": round(cash_amount, 2),
                "payment_card": round(card_amount, 2),
                "accounts": {"goods": "41.02", "revenue": "90.01.1",
                             "cost": "90.02.1", "vat": "90.03", "card": "57.03"},
            },
        })
    # ── ПКО: наличная выручка ───────────────────────────────────────────────
    if cash_amount > 0:
        docs.append({
            "kind": "cash_pko",
            "idem_key": f"{base}|ПКО",
            "payload": {
                "doc_type": "ПриходныйКассовыйОрдер",
                "operation": "РозничнаяВыручка",
                "date": shift_date, "time": T_SHIFT,
                "amount": round(cash_amount, 2),
                "basis": base,  # документ-основание = ОРП
                "accounts": {"dt": "50.01", "kt": "62.Р"},
            },
        })
    # ── Перемещения по каналам (cards/online/voucher/ledger) ────────────────
    transfer_groups: dict[tuple[str, str], list[dict]] = {}
    writeoff: list[dict] = []
    for s in sales:
        ch = s["payment_channel"]
        if ch in RETAIL_CHANNELS:
            continue
        if ch == "writeoff_fuel":
            writeoff.append(s)
            continue
        meta = channels_by_code.get(ch) or {}
        if not meta.get("requires_transfer"):
            continue
        wh = s.get("warehouse_name") or meta.get("warehouse_name") or ch
        transfer_groups.setdefault((ch, wh), []).append(s)

    for (ch, wh), rows in transfer_groups.items():
        docs.append({
            "kind": "fuel_transfer",
            "idem_key": f"{base}|{ch}",
            "payload": {
                "doc_type": "ПеремещениеТоваров",
                "channel": ch,
                "warehouse_from": warehouse_azs, "warehouse_to": wh,
                "date": shift_date, "time": T_SHIFT,
                "lines": [{**line(s), "amount": 0} for s in rows],  # литры, сумма 0
                "accounts": {"from": "41.02", "to": "41.01"},
            },
        })
    # ── Списание (writeoff_fuel, pay_type «Прочие») ─────────────────────────
    if writeoff:
        docs.append({
            "kind": "fuel_writeoff",
            "idem_key": f"{base}|СПИСАНИЕ",
            "payload": {
                "doc_type": "СписаниеТоваров",
                "operation": "СписаниеСоСклада",
                "warehouse": warehouse_azs,
                "date": shift_date, "time": T_SHIFT,
                "lines": [line(s) for s in writeoff],
                "accounts": {"kt": "41.02"},
            },
        })
    return docs


def build_ttn_documents(
    *,
    system: int,
    station_code: int,
    ttn: str,
    fuel_code: int,
    nomenclature_t: str,
    nomenclature_l: str,
    tonnes: float,
    liters: float,
    ttn_date: str,
    warehouse_azs: str,
    main_warehouse: str = "Основной склад",
) -> list[dict]:
    """ТТН → Перемещение тонн (ОснСклад→АЗС, 41.01) + Комплектация (тонны→литры)."""
    base = f"TL|ТТН|{system}|{station_code}|{ttn}|{fuel_code}"
    docs: list[dict] = []
    if tonnes and tonnes > 0:
        docs.append({
            "kind": "ttn_transfer",
            "idem_key": f"{base}|ПЕРЕМ",
            "payload": {
                "doc_type": "ПеремещениеТоваров",
                "warehouse_from": main_warehouse, "warehouse_to": warehouse_azs,
                "date": ttn_date, "time": T_TTN_TRANSFER, "ttn": ttn,
                "lines": [{"fuel_code": fuel_code, "nomenclature": nomenclature_t,
                           "tonnes": round(float(tonnes), 3)}],
                "accounts": {"from": "41.01", "to": "41.01"},
            },
        })
        if liters and liters > 0:
            docs.append({
                "kind": "ttn_assembly",
                "idem_key": f"{base}|КОМПЛ",
                "payload": {
                    "doc_type": "КомплектацияНоменклатуры",
                    "operation": "Комплектация",
                    "warehouse": warehouse_azs,
                    "date": ttn_date, "time": T_TTN_ASSEMBLY, "ttn": ttn,
                    "product": {"nomenclature": nomenclature_l, "liters": round(float(liters), 3)},
                    "components": [{"nomenclature": nomenclature_t, "tonnes": round(float(tonnes), 3)}],
                    "accounts": {"component": "41.01", "product": "41.02"},
                },
            })
    return docs
