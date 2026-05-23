# Smoke-тест OData-клиента 1С на реальной публикации.
# Запуск: py -3.13 smoke_odata_client.py
#
# Берёт реквизиты из переменных окружения:
#   CL_1C_URL       — http://host/alias/odata/standard.odata
#   CL_1C_USERNAME  — логин 1С
#   CL_1C_PASSWORD  — пароль 1С
#
# Что проверяет:
#   1. GET /$metadata → список Catalog_*
#   2. GET /Catalog_Контрагенты?$top=10 → 10 записей
#   3. GET /Catalog_Контрагенты/$count → общее число записей

from __future__ import annotations

import asyncio
import os
import sys

# Локальный sys.path для запуска из server/scripts/
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.onec import OneCError, OneCODataClient  # noqa: E402
from app.services.onec.odata_client import ENTITY_COUNTERPARTIES  # noqa: E402


async def main() -> int:
    url = os.environ.get("CL_1C_URL")
    user = os.environ.get("CL_1C_USERNAME")
    pwd = os.environ.get("CL_1C_PASSWORD")

    if not url or not user or pwd is None:
        print("FAIL: не задан хотя бы один из CL_1C_URL / CL_1C_USERNAME / CL_1C_PASSWORD")
        print()
        print("Пример запуска (PowerShell):")
        print('  $env:CL_1C_URL = "http://192.168.40.31/<alias>/odata/standard.odata"')
        print('  $env:CL_1C_USERNAME = "ClearLedger"')
        print('  $env:CL_1C_PASSWORD = "***"')
        print("  py -3.13 scripts/smoke_odata_client.py")
        return 2

    print(f"Подключение: {url}")
    print(f"Логин:       {user}")
    print()

    async with OneCODataClient(url, user, pwd, timeout=20.0) as client:
        try:
            print("[1/3] metadata_catalogs() ...", flush=True)
            catalogs = await client.metadata_catalogs()
            print(f"      OK — найдено {len(catalogs)} Catalog_*")
            for c in catalogs[:5]:
                print(f"         {c}")
            if len(catalogs) > 5:
                print(f"         ... и ещё {len(catalogs) - 5}")
            print()

            print("[2/3] fetch_entity(Catalog_Контрагенты, top=10) ...", flush=True)
            rows = await client.fetch_entity(
                ENTITY_COUNTERPARTIES,
                select=["Ref_Key", "Description", "ИНН", "КПП"],
                top=10,
            )
            print(f"      OK — получено {len(rows)} строк")
            for i, r in enumerate(rows, 1):
                print(f"  {i:2d}. {r.get('Description','')!s:<50} ИНН={r.get('ИНН','')!s:<12} КПП={r.get('КПП','')!s}")
            print()

            print("[3/3] count_entity(Catalog_Контрагенты) ...", flush=True)
            n = await client.count_entity(ENTITY_COUNTERPARTIES)
            print(f"      OK — всего {n} записей в Catalog_Контрагенты")
        except OneCError as exc:
            print(f"FAIL OneC: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL unexpected: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

    print()
    print("=" * 60)
    print("SMOKE OData OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
