"""
DEV: наполнить кеши НСИ ЦБ ЭЛСИ.АЗК для компании gig из локальной копии (COM):
  CbNomenclature — номенклатура (имя/артикул/НДС/маркировка/группа/вид) для всех товарных экранов;
  CbRef          — контрагенты + номенклатурные группы (GUID→имя) для Приёмки/Поставщиков/Категорий.

Пароль из ext-cb-msn/scripts/secrets.json. Запуск (из server/): py -3 scripts/enrich_cb_nomenclature_dev.py
"""
import asyncio
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select, delete  # noqa: E402

from app.database import async_session_factory, engine, Base  # noqa: E402
from app.models import CbNomenclature, CbRef, CbBarcode  # noqa: E402
from app.services.onec.com_client import OneCComClient  # noqa: E402
from app.utils import resolve_company_id  # noqa: E402

COMPANY = "gig"
SECRETS = Path(r"D:\Users\magsp\ELSYPLUS\Ledger\ext-cb-msn\scripts\secrets.json")
NOM_FIELDS = ["Ref", "Description", "Артикул", "Маркированный", "Весовой",
              "СтавкаНДС", "НоменклатурнаяГруппа", "ВидНоменклатуры"]
# справочник ЦБ → kind в CbRef
REF_SOURCES = {
    "counterparty": "Catalog_Контрагенты",
    "nom_group": "Catalog_НоменклатурныеГруппы",
    "nom_kind": "Catalog_ВидыНоменклатуры",
}
_NULL_GUID = "00000000-0000-0000-0000-000000000000"


def _norm_ref(v):
    v = str(v or "")
    return None if not v or v == _NULL_GUID else v


async def main() -> None:
    s = json.loads(SECRETS.read_text(encoding="utf-8"))
    conn = s.get("tsb_conn") or f'File="{s["tsb_base"]}";Usr="{s["tsb_user"]}";Pwd="{s["tsb_pwd"]}";'

    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)

    items = []
    refs: dict[str, list] = {k: [] for k in REF_SOURCES}
    async with OneCComClient(conn) as client:
        async for row in client.iter_entity("Catalog_Номенклатура", select=NOM_FIELDS, page_size=1000):
            items.append(row)
        for kind, entity in REF_SOURCES.items():
            try:
                async for row in client.iter_entity(entity, select=["Ref", "Description"], page_size=1000):
                    refs[kind].append(row)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {entity}: {e}")
        barcodes = []
        try:
            barcodes = await client.fetch_barcodes()
        except Exception as e:  # noqa: BLE001
            print(f"  ! barcodes: {e}")
    print(f"получено: номенклатура {len(items)}, контрагенты {len(refs['counterparty'])}, группы {len(refs['nom_group'])}, штрихкоды {len(barcodes)}")

    async with async_session_factory() as db:
        cid = await resolve_company_id(COMPANY, db)

        # ── номенклатура ──
        existing = {x.external_ref: x for x in (await db.execute(
            select(CbNomenclature).where(CbNomenclature.company_id == cid))).scalars().all()}
        n_new = n_upd = 0
        for r in items:
            ref = str(r.get("Ref") or "")
            if not ref or ref == _NULL_GUID:
                continue
            vals = dict(
                name=str(r.get("Description") or ""),
                article=(str(r.get("Артикул")) or None) if r.get("Артикул") else None,
                vat=(str(r.get("СтавкаНДС")) or None) if r.get("СтавкаНДС") else None,
                marked=bool(r.get("Маркированный")),
                weighed=bool(r.get("Весовой")),
                group_ref=_norm_ref(r.get("НоменклатурнаяГруппа")),
                kind_ref=_norm_ref(r.get("ВидНоменклатуры")),
            )
            obj = existing.get(ref)
            if obj:
                for k, v in vals.items():
                    setattr(obj, k, v)
                n_upd += 1
            else:
                db.add(CbNomenclature(company_id=cid, external_ref=ref, **vals))
                n_new += 1

        # ── ссылки (контрагенты, группы) ──
        existing_ref = {(x.kind, x.external_ref): x for x in (await db.execute(
            select(CbRef).where(CbRef.company_id == cid))).scalars().all()}
        r_new = 0
        for kind, rows in refs.items():
            for r in rows:
                ref = str(r.get("Ref") or "")
                if not ref or ref == _NULL_GUID:
                    continue
                nm = str(r.get("Description") or "")
                obj = existing_ref.get((kind, ref))
                if obj:
                    obj.name = nm
                else:
                    db.add(CbRef(company_id=cid, kind=kind, external_ref=ref, name=nm))
                    r_new += 1

        # ── штрихкоды (перезалив) ──
        await db.execute(delete(CbBarcode).where(CbBarcode.company_id == cid))
        for r in barcodes:
            b = str(r.get("barcode") or "")
            if not b:
                continue
            db.add(CbBarcode(
                company_id=cid, barcode=b,
                owner_name=str(r.get("owner_name") or ""),
                owner_ref=_norm_ref(r.get("owner")),
                btype=(str(r.get("type")) or None) if r.get("type") else None,
                main=bool(r.get("main")),
            ))

        await db.commit()
        marked = sum(1 for r in items if r.get("Маркированный"))
        print(f"CbNomenclature: +{n_new}/~{n_upd}, маркир. {marked}; CbRef: +{r_new}; штрихкоды {len(barcodes)}")


if __name__ == "__main__":
    asyncio.run(main())
