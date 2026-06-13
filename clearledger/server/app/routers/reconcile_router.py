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
