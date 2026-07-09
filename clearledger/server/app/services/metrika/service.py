"""Сервис коннектора Яндекс.Метрики: хранение подключения (счётчик + шифрованный
OAuth-токен) и отчёты (сводка / динамика / источники). Токен наружу не отдаётся."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MetrikaConnection
from app.services.metrika import client as mc
from app.services.onec.crypto import decrypt_password, encrypt_password


class MetrikaService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _row(self, company_id) -> MetrikaConnection | None:
        return (await self.db.execute(select(MetrikaConnection).where(
            MetrikaConnection.company_id == company_id))).scalar_one_or_none()

    async def status(self, company_id) -> dict[str, Any]:
        row = await self._row(company_id)
        if not row:
            return {"configured": False}
        return {"configured": True, "counter_id": row.counter_id, "counter_name": row.counter_name,
                "enabled": row.enabled, "status": row.status, "last_error": row.last_error,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None}

    async def save(self, company_id, counter_id: str, token: str) -> dict[str, Any]:
        """Сохранить подключение + сразу провалидировать токен и наличие счётчика."""
        counter_name: str | None = None
        st, err = "ok", None
        try:
            counters = await mc.list_counters(token)
            found = next((c for c in counters if str(c.get("id")) == str(counter_id)), None)
            if found:
                counter_name = found.get("name")
            else:
                st, err = "error", f"Счётчик {counter_id} не найден среди доступных ({len(counters)})"
        except mc.MetrikaError as e:
            st, err = "error", str(e)
        row = await self._row(company_id)
        if row is None:
            row = MetrikaConnection(company_id=company_id, counter_id=str(counter_id),
                                    token_encrypted=encrypt_password(token))
            self.db.add(row)
        else:
            row.counter_id = str(counter_id)
            row.token_encrypted = encrypt_password(token)
        row.counter_name, row.status, row.last_error = counter_name, st, err
        await self.db.commit()
        return await self.status(company_id)

    async def delete(self, company_id) -> None:
        row = await self._row(company_id)
        if row:
            await self.db.delete(row)
            await self.db.commit()

    async def test(self, company_id) -> dict[str, Any]:
        row = await self._row(company_id)
        if not row:
            return {"ok": False, "error": "не подключено"}
        try:
            counters = await mc.list_counters(decrypt_password(row.token_encrypted))
            found = next((c for c in counters if str(c.get("id")) == str(row.counter_id)), None)
            row.status = "ok" if found else "error"
            row.last_error = None if found else f"счётчик {row.counter_id} недоступен токену"
            if found:
                row.counter_name = found.get("name")
            await self.db.commit()
            return {"ok": bool(found), "counter_name": row.counter_name, "error": row.last_error}
        except mc.MetrikaError as e:
            row.status, row.last_error = "error", str(e)
            await self.db.commit()
            return {"ok": False, "error": str(e)}

    async def _creds(self, company_id) -> tuple[str, str]:
        row = await self._row(company_id)
        if not row:
            raise mc.MetrikaError("Яндекс.Метрика не подключена")
        if not row.enabled:
            raise mc.MetrikaError("Подключение к Метрике отключено")
        return decrypt_password(row.token_encrypted), row.counter_id

    # ── Отчёты ───────────────────────────────────────────────────────────
    _SUMMARY = ["ym:s:visits", "ym:s:users", "ym:s:pageviews", "ym:s:bounceRate",
                "ym:s:avgVisitDurationSeconds", "ym:s:pageDepth", "ym:s:percentNewVisitors"]

    async def summary(self, company_id, date1: str, date2: str) -> dict[str, Any]:
        token, counter = await self._creds(company_id)
        d = await mc.stat_data(token, counter_id=counter, metrics=self._SUMMARY, date1=date1, date2=date2)
        totals = (d.get("totals") or [[]])[0]
        keys = ["visits", "users", "pageviews", "bounce_rate", "avg_duration_sec", "page_depth", "new_pct"]
        vals = {k: round(float(v), 1) for k, v in zip(keys, totals)} if totals else {k: 0.0 for k in keys}
        return {"totals": vals, "sampled": bool(d.get("sampled")),
                "sample_share": d.get("sample_share", 1.0),
                "period": {"from": date1, "to": date2}}

    async def timeseries(self, company_id, date1: str, date2: str) -> dict[str, Any]:
        token, counter = await self._creds(company_id)
        d = await mc.stat_data(token, counter_id=counter,
                               metrics=["ym:s:visits", "ym:s:users", "ym:s:pageviews"],
                               dimensions=["ym:s:date"], date1=date1, date2=date2,
                               sort="ym:s:date", limit=400)
        rows = [{"date": r["dimensions"][0].get("name"),
                 "visits": r["metrics"][0], "users": r["metrics"][1], "pageviews": r["metrics"][2]}
                for r in d.get("data", [])]
        return {"rows": rows, "sampled": bool(d.get("sampled"))}

    async def sources(self, company_id, date1: str, date2: str) -> dict[str, Any]:
        token, counter = await self._creds(company_id)
        d = await mc.stat_data(token, counter_id=counter,
                               metrics=["ym:s:visits", "ym:s:users", "ym:s:bounceRate"],
                               dimensions=["ym:s:lastTrafficSource"], date1=date1, date2=date2,
                               sort="-ym:s:visits", limit=20)
        rows = [{"source": r["dimensions"][0].get("name"), "visits": r["metrics"][0],
                 "users": r["metrics"][1], "bounce_rate": round(float(r["metrics"][2]), 1)}
                for r in d.get("data", [])]
        return {"rows": rows}
