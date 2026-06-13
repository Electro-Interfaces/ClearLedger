"""
Backend-исполнение разрезов сверки (corp/online) через ReconcileEngine.

§6.4 шаг 3 (КАНДИДАТ): тянет потоки и прогоняет ДЕКЛАРАТИВНЫЙ разрез единым
движком. НЕ заменяет golden (императивные frontend src/services/reconciliation,
mstoReconciliation) до сверки byte-for-byte (`/reconcile/diff`).

Потоки:
  • anchor  = TF (STS /v2/transactions) — sts_get_transactions
  • external= TradeCorp (corp_fuel) | MSTO (online_fuel) — reconciliation_proxy
  • control = смена (опц.)

⚠ Маппинг полей в формат движка (station/fuel/occurred_at/amount/volume/
card_last4) — defensive, уточняется на живых данных; нормализация топлива
(FUEL_NAME_MAP) для golden-парности — TODO.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.reconcile_catalog import list_reconcile_rules
from app.services import reconciliation_proxy
from app.services.reconcile.engine import run_reconcile
from app.services.sts_client import sts_get_transactions

_RULES = {r["id"]: r for r in list_reconcile_rules()}

# rule_id → source_type внешнего потока
_EXTERNAL = {"corp_fuel": "tradecorp", "online_fuel": "msto"}


def _last4(card: Any) -> str:
    s = str(card or "")
    return s[-4:] if len(s) >= 4 else s


def _fuel(name: Any) -> str:
    return str(name or "").strip().lower()


def _ts(val: Any) -> float | None:
    if val in (None, ""):
        return None
    s = str(val)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19], fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _tf_record(tx: dict) -> dict:
    """STS /v2/transactions item → запись движка (anchor)."""
    svc = tx.get("service") or {}
    card = tx.get("card") or {}
    return {
        "station": str(tx.get("station") or ""),
        "fuel": _fuel(svc.get("service_name") or svc.get("service_code") or tx.get("fuel")),
        "occurred_at": _ts(tx.get("dt") or tx.get("time") or tx.get("date")),
        "amount": float(tx.get("cost") or tx.get("amount") or 0),
        "volume": float(tx.get("volume") or tx.get("quantity") or 0),
        "card_last4": _last4(card.get("number") or tx.get("card")),
    }


def _corp_record(tx: dict) -> dict:
    """TradeCorp normalized tx → запись движка (external corp)."""
    cheque = (tx.get("cheque") or [{}])[0]
    return {
        "station": str(tx.get("stationNumber") or ""),
        "fuel": _fuel(cheque.get("productName") or tx.get("operationName")),
        "occurred_at": _ts(tx.get("date")),
        "amount": float(tx.get("cost") or 0),
        "volume": float(tx.get("quantity") or 0),
        "card_last4": _last4(tx.get("cardNumber")),
    }


def _msto_record(tx: dict) -> dict:
    """MSTO tx → запись движка (external online)."""
    return {
        "station": str(tx.get("stationNumber") or tx.get("servicePointId") or ""),
        "fuel": _fuel(tx.get("fuelName") or tx.get("productName")),
        "occurred_at": _ts(tx.get("date") or tx.get("orderDate")),
        "amount": float(tx.get("amount") or tx.get("cost") or 0),
        "volume": float(tx.get("volume") or tx.get("quantity") or 0),
    }


async def run_rule(
    rule_id: str,
    date_from: str,
    date_to: str,
    *,
    base_url: str,
    login: str,
    password: str,
    system: int,
    station_ids: list | None = None,
) -> dict[str, Any]:
    """Исполнить разрез corp_fuel/online_fuel движком на живых потоках (КАНДИДАТ)."""
    rule = _RULES.get(rule_id)
    if not rule:
        return {"status": "error", "message": f"разрез '{rule_id}' не найден"}
    ext_type = _EXTERNAL.get(rule_id)
    if ext_type is None:
        return {"status": "error", "message": f"для '{rule_id}' нет backend-фетча внешнего потока"}

    # anchor: TF (STS транзакции)
    tf = await sts_get_transactions(base_url, login, password, system, date_from, date_to)
    anchor = [_tf_record(t) for t in tf]

    # external: TradeCorp | MSTO
    if ext_type == "tradecorp":
        resp = await reconciliation_proxy.tradecorp_transactions(date_from, date_to, station_ids)
        external = [_corp_record(t) for t in (resp.get("transactions") or [])]
    else:
        resp = await reconciliation_proxy.msto_transactions(
            {"dt_beg": date_from, "dt_end": date_to})
        items = resp if isinstance(resp, list) else (resp.get("transactions") or resp.get("items") or [])
        external = [_msto_record(t) for t in items]

    result = run_reconcile(rule, {"anchor": anchor, "external": external})
    result["provenance"]["status"] = "candidate"
    result["provenance"]["note"] = (
        "§6.4: backend-кандидат, НЕ заменяет golden (frontend) до сверки "
        "byte-for-byte через /reconcile/diff"
    )
    return {"status": "success", "rule_id": rule_id, "period": [date_from, date_to], **result}
