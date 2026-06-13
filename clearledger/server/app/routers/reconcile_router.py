"""
Роутер исполнения сверки (ReconcileEngine).

POST /reconcile/run  — исполнить разрез из справочника над переданными потоками.
POST /reconcile/diff — сверить результат движка с golden (примитив §6.4:
                       byte-for-byte против рабочих императивных движков).

⚠ Потоки (streams) на вход даёт канал (стадия fetch→normalize). Здесь —
движок над уже нормализованными записями. Golden capture (прогон императивных
TS-движков на боевых ГИГ) — операционный шаг, делается на живом стенде.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.reconcile_catalog import list_reconcile_rules
from app.services.reconcile.engine import run_reconcile
from app.services.recon_run import run_rule as run_rule_live

router = APIRouter(prefix="/reconcile", tags=["reconcile"])

_RULES = {r["id"]: r for r in list_reconcile_rules()}


class RunRequest(BaseModel):
    rule_id: str
    streams: dict[str, list[dict[str, Any]]]   # {anchor:[...], external:[...], control:[...]}


@router.post("/run")
async def run(req: RunRequest):
    """Исполнить разрез над потоками → ReconResult."""
    rule = _RULES.get(req.rule_id)
    if not rule:
        raise HTTPException(404, f"Разрез '{req.rule_id}' не найден в справочнике")
    return run_reconcile(rule, req.streams)


class DiffRequest(BaseModel):
    engine: dict[str, Any]   # результат ReconcileEngine
    golden: dict[str, Any]   # результат императивного движка (golden)


class RunRuleRequest(BaseModel):
    rule_id: str                 # corp_fuel | online_fuel
    date_from: str               # YYYY-MM-DD
    date_to: str
    base_url: str = "https://pos.autooplata.ru/tms"
    login: str
    password: str
    system: int = 65
    station_ids: list[Any] | None = None


@router.post("/run-rule")
async def run_rule_endpoint(req: RunRuleRequest):
    """Backend-исполнение разреза corp/online на живых потоках (КАНДИДАТ, §6.4).

    Тянет TF (STS) + внешний (TradeCorp/MSTO), прогоняет ReconcileEngine.
    Сверять с golden (frontend) через /reconcile/diff до замены.
    """
    return await run_rule_live(
        req.rule_id, req.date_from, req.date_to,
        base_url=req.base_url, login=req.login, password=req.password,
        system=req.system, station_ids=req.station_ids,
    )


@router.post("/diff")
async def diff(req: DiffRequest):
    """Сверка engine ↔ golden по summary (§6.4). identical=True → можно заменять."""
    e = req.engine.get("summary", {})
    g = req.golden.get("summary", {})
    keys = set(e) | set(g)
    mismatches = {
        k: {"engine": e.get(k), "golden": g.get(k)}
        for k in keys if e.get(k) != g.get(k)
    }
    return {"identical": not mismatches, "mismatches": mismatches}
