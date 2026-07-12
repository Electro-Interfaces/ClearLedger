from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from collections.abc import AsyncIterator
from typing import Any

from app.services.onec.exceptions import (
    OneCAuthError,
    OneCConnectionError,
    OneCError,
)

logger = logging.getLogger("clearledger.onec.com")


# Команда запуска воркера в 32-bit Python. Берётся из ENV если переопределена,
# иначе — по умолчанию py launcher с явным выбором 32-bit интерпретатора.
COM_WORKER_CMD = os.environ.get(
    "CL_ONEC_COM_PYTHON",
    "py" if sys.platform == "win32" else "python",
)
COM_WORKER_FLAGS = os.environ.get(
    "CL_ONEC_COM_FLAGS",
    "-3.13-32" if sys.platform == "win32" else "",
).split()


class OneCComClient:
    """COM-клиент для стенда GIG Base2 (V83.COMConnector через subprocess 32-bit).

    Запускает дочерний 32-bit Python с com_worker.py, общается через
    stdin/stdout JSON-Lines. Реализует тот же публичный интерфейс, что и
    OneCODataClient — sync_service использует через factory.

    Использует СИНХРОННЫЙ subprocess в run_in_executor — потому что под
    Windows uvicorn идёт на SelectorEventLoop (для совместимости с asyncpg),
    а asyncio.create_subprocess_exec работает только на ProactorEventLoop.

    connection_string — в формате 1С COMConnector:
        File="D:\\...\\GIG Base2";Usr="...";Pwd="...";
    или для серверной:
        Srvr="host:port";Ref="GIG";Usr="...";Pwd="..."
    """

    def __init__(self, connection_string: str) -> None:
        if not connection_string:
            raise ValueError("connection_string не может быть пустым")
        self.connection_string = connection_string
        self._proc: subprocess.Popen[bytes] | None = None
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        proc = self._proc
        self._proc = None
        if proc and proc.poll() is None:
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.write(b'{"op":"exit"}\n')
                    proc.stdin.flush()
                    proc.stdin.close()
            except Exception:
                pass
            try:
                await asyncio.get_running_loop().run_in_executor(None, proc.wait, 3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

    async def __aenter__(self) -> OneCComClient:
        await self._ensure_started()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _ensure_started(self) -> None:
        if self._proc and self._proc.poll() is None:
            return

        worker_path = os.path.join(os.path.dirname(__file__), "com_worker.py")
        cmd = [COM_WORKER_CMD, *COM_WORKER_FLAGS, worker_path]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}

        def _spawn() -> subprocess.Popen[bytes]:
            return subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=env,
                bufsize=0,
            )

        loop = asyncio.get_running_loop()
        try:
            self._proc = await loop.run_in_executor(None, _spawn)
        except FileNotFoundError as exc:
            raise OneCConnectionError(f"Не найден python для COM-воркера: {cmd}") from exc

        connect_result = await self._call("connect", {"conn_string": self.connection_string})
        logger.info(
            "COM connect OK: %s v%s",
            connect_result.get("config_synonym"),
            connect_result.get("config_version"),
        )

    async def _call(self, op: str, args: dict[str, Any] | None = None) -> Any:
        if op != "connect" and (self._proc is None or self._proc.poll() is not None):
            await self._ensure_started()

        assert self._proc is not None
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None
        assert self._proc.stderr is not None
        proc = self._proc

        payload: dict[str, Any] = {"op": op}
        if args is not None:
            payload["args"] = args
        line = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")

        def _send_and_read() -> bytes:
            proc.stdin.write(line)
            proc.stdin.flush()
            return proc.stdout.readline()

        loop = asyncio.get_running_loop()
        async with self._lock:
            response_bytes = await loop.run_in_executor(None, _send_and_read)

        if not response_bytes:
            stderr = await loop.run_in_executor(None, proc.stderr.read)
            raise OneCConnectionError(
                f"COM worker exited unexpectedly. stderr: {stderr.decode('utf-8', errors='replace')[:500]}"
            )
        try:
            response = json.loads(response_bytes.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise OneCError(f"Bad JSON from COM worker: {response_bytes!r}") from exc

        if not response.get("ok"):
            err = str(response.get("error", "unknown COM error"))
            if "Невозможно установить соединение" in err or "пользователь" in err.lower():
                raise OneCAuthError(err)
            raise OneCError(err)
        return response.get("result")

    # ─── публичный API совместимый с OneCODataClient ─────────────────

    async def metadata_catalogs(self) -> list[str]:
        result = await self._call("metadata_catalogs")
        return list(result) if result else []

    async def fetch_entity(
        self,
        entity: str,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        top: int | None = None,
        skip: int | None = None,
    ) -> list[dict[str, Any]]:
        args: dict[str, Any] = {"entity": entity}
        if select is not None:
            args["select"] = select
        if filter_expr is not None:
            args["filter"] = filter_expr
        if orderby is not None:
            args["orderby"] = orderby
        if top is not None:
            args["top"] = top
        if skip is not None:
            args["skip"] = skip
        return await self._call("fetch_entity", args)

    async def iter_entity(
        self,
        entity: str,
        *,
        select: list[str] | None = None,
        filter_expr: str | None = None,
        orderby: str | None = None,
        page_size: int = 500,
    ) -> AsyncIterator[dict[str, Any]]:
        skip = 0
        while True:
            batch = await self.fetch_entity(
                entity,
                select=select,
                filter_expr=filter_expr,
                orderby=orderby,
                top=page_size,
                skip=skip,
            )
            if not batch:
                return
            for item in batch:
                yield item
            if len(batch) < page_size:
                return
            skip += page_size

    async def count_entity(
        self,
        entity: str,
        *,
        filter_expr: str | None = None,
    ) -> int:
        args: dict[str, Any] = {"entity": entity}
        if filter_expr is not None:
            args["filter"] = filter_expr
        result = await self._call("count_entity", args)
        return int(result or 0)

    async def metadata_registers(self, name_substring: str = "") -> list[str]:
        """Список InformationRegister_<имя> с опциональным фильтром по подстроке."""
        result = await self._call("metadata_registers", {"name_substring": name_substring})
        return list(result or [])

    async def metadata_documents(self, name_substring: str = "") -> list[str]:
        """Список Document_<имя> (probe товародвижения) с фильтром по подстроке."""
        result = await self._call("metadata_documents", {"name_substring": name_substring})
        return list(result or [])

    async def metadata_accum_registers(self, name_substring: str = "") -> list[str]:
        """Список AccumulationRegister_<имя> (остатки/партии) с фильтром по подстроке."""
        result = await self._call("metadata_accum_registers", {"name_substring": name_substring})
        return list(result or [])

    async def fetch_register_balance(
        self,
        register: str,
        *,
        dimensions: list[str] | None = None,
        resources: list[str] | None = None,
        on_date: str | None = None,
        top: int | None = None,
    ) -> list[dict[str, Any]]:
        """Остатки регистра накопления (виртуальная таблица <Регистр>.Остатки).
        Ресурсы возвращаются как <Ресурс> (Количество/Стоимость/НДС), ссылки — GUID."""
        args: dict[str, Any] = {"register": register}
        if dimensions is not None:
            args["dimensions"] = dimensions
        if resources is not None:
            args["resources"] = resources
        if on_date is not None:
            args["on_date"] = on_date
        if top is not None:
            args["top"] = top
        result = await self._call("fetch_register_balance", args)
        return list(result or [])

    async def query_tabular(
        self,
        doc_type: str,
        tabular: str,
        *,
        select: list[str] | None = None,
        where: str | None = None,
        top: int | None = None,
    ) -> list[dict[str, Any]]:
        """Строки ТЧ документа (для чтения движений): поля ТЧ + шапки через «Ссылка.Поле»,
        сырое условие where с префиксом Т. Ссылки → GUID."""
        args: dict[str, Any] = {"doc_type": doc_type, "tabular": tabular}
        if select is not None:
            args["select"] = select
        if where is not None:
            args["where"] = where
        if top is not None:
            args["top"] = top
        result = await self._call("query_tabular", args)
        return list(result or [])

    async def describe_entity(self, entity: str) -> dict[str, list[str]]:
        """Возвращает {dimensions, resources, attributes} объекта метаданных 1С.
        Нужен для устойчивого построения запросов к УчетнойПолитике и другим
        регистрам с переменным составом реквизитов от версии к версии БП."""
        result = await self._call("describe_entity", {"entity": entity})
        return dict(result or {})

    async def find_docs_by_nomenclature(self, nomenclature_ref: str, limit: int = 50) -> list[dict[str, Any]]:
        """Прямой поиск ПТУ-документов по GUID Номенклатуры в ТЧ Товары."""
        result = await self._call("find_docs_by_nomenclature", {
            "nomenclature_ref": nomenclature_ref,
            "limit": limit,
        })
        return list(result or [])

    async def fetch_cb_shifts(
        self,
        period_from: str,
        period_to: str,
        station: str = "208",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Извлечь смены ЦБ ЭЛСИ.АЗК (сопутка/общепит) за период → пакеты v2.

        Опорный — ОРП; Товары с КлассSKU/ЭтоБлюдо; блюда + recipe (ТТК).
        Результат — список пакетов для cb_normalize.normalize_shift_package.
        """
        result = await self._call("fetch_cb_shifts", {
            "period_from": period_from,
            "period_to": period_to,
            "station": station,
            "limit": limit,
        })
        return list(result or [])

    async def fetch_postings(self, doc_type: str, doc_ref: str) -> list[dict[str, Any]]:
        """Проводки документа из РегистрБухгалтерии.Хозрасчетный."""
        result = await self._call("fetch_postings", {
            "doc_type": doc_type, "doc_ref": doc_ref,
        })
        return list(result or [])

    async def enrich_nomenclature(self, refs: list[str]) -> dict[str, dict[str, Any]]:
        """Batch-резолв Catalog.Номенклатура по GUID → {ref: {name, unit, density, article}}."""
        result = await self._call("enrich_nomenclature", {"refs": refs})
        return dict(result or {})

    async def fetch_barcodes(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Штрихкоды из РегистрСведений.Штрихкоды: [{barcode, owner(GUID номенклатуры), type, main}]."""
        result = await self._call("fetch_barcodes", {"limit": limit} if limit is not None else {})
        return list(result or [])

    async def fetch_orgs(self) -> list[dict[str, Any]]:
        """Справочник.Организации → [{ref, name, full_name, inn, kpp, ogrn, okpo, jur_fiz, deleted}]."""
        return list(await self._call("fetch_orgs", {}) or [])

    async def fetch_warehouses(self) -> list[dict[str, Any]]:
        """Справочник.Склады → [{ref, code, name, kind, deleted}]."""
        return list(await self._call("fetch_warehouses", {}) or [])

    async def fetch_production(self, period_from: str, period_to: str, station: str = "208") -> list[dict[str, Any]]:
        """ВыпускПродукции → пакет-готовые production_release [{Тип, ИсточникUUID, ВыпускБлюд[], Ингредиенты[], …}]."""
        return list(await self._call("fetch_production", {
            "period_from": period_from, "period_to": period_to, "station": station}) or [])

    async def fetch_gain(self, period_from: str, period_to: str, station: str = "208") -> list[dict[str, Any]]:
        """ОприходованиеТоваров → пакет-готовые gain [{Тип, ИсточникUUID, Товары[], …}]."""
        return list(await self._call("fetch_gain", {
            "period_from": period_from, "period_to": period_to, "station": station}) or [])

    async def fetch_doc_lines(
        self,
        doc_type: str,
        doc_ref: str,
        tabular_name: str,
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Та же сигнатура что у OneCODataClient.fetch_doc_lines, но через
        прямой доступ к ОбъектДокумента в 1С (Документы.<Тип>.НайтиПоИдент…
        →.ПолучитьОбъект()→.<ТЧ>). Не строим SQL — это быстрее и надёжнее
        чем конструировать `Т.Ссылка = ССЫЛКА(<Тип>, "<guid>")`."""
        result = await self._call("fetch_doc_lines", {
            "doc_type": doc_type,
            "doc_ref": doc_ref,
            "tabular_name": tabular_name,
            "select": select or [],
        })
        return list(result or [])
