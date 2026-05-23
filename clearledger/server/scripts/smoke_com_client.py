# Smoke OneCComClient (64-bit обёртка над 32-bit COM worker) на стенде GIG Base2.

from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.onec.com_client import OneCComClient  # noqa: E402


CONN_STRING = (
    r'File="D:\Users\magsp\GIG Base2";'
    r'Usr="Гайворонская Татьяна";'
    r'Pwd="12345";'
)


async def main() -> int:
    async with OneCComClient(CONN_STRING) as c:
        print("[1] metadata_catalogs ...", flush=True)
        cats = await c.metadata_catalogs()
        print(f"    OK — {len(cats)} catalogs. First 5:")
        for x in cats[:5]:
            print("       ", x)

        print("[2] fetch_entity Contractors top=5 ...", flush=True)
        rows = await c.fetch_entity(
            "Catalog_Контрагенты",
            select=["Ref_Key", "Description", "ИНН", "КПП"],
            top=5,
        )
        print(f"    OK — {len(rows)} rows")
        for r in rows:
            name = r.get("Description") or ""
            inn = r.get("ИНН") or ""
            kpp = r.get("КПП") or ""
            print(f"       {name!s:<50} ИНН={inn!s:<12} КПП={kpp!s}")

        print("[3] count_entity ...", flush=True)
        n = await c.count_entity("Catalog_Контрагенты")
        print(f"    OK — total Контрагенты: {n}")

    print()
    print("SMOKE COM-client OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
