from fastapi import HTTPException
from sqlalchemy import or_, select

from app.models import ServiceLocation


class ObjectsContext:
    prefix = "object"
    application = "ops"
    label = "Объекты сети"

    async def search(self, db, cid, user, q):
        rows = (await db.execute(select(ServiceLocation).where(ServiceLocation.company_id == cid,
            or_(ServiceLocation.name.ilike(f"%{q}%"), ServiceLocation.code.ilike(f"%{q}%")))
            .order_by(ServiceLocation.name, ServiceLocation.id).limit(20))).scalars().all()
        return [{"ref": f"object:{r.id}", "title": r.name or r.code or r.id, "hint": r.code or ""} for r in rows]

    async def resolve(self, db, cid, user, key):
        row = await db.scalar(select(ServiceLocation).where(ServiceLocation.id == key, ServiceLocation.company_id == cid))
        if row is None:
            raise HTTPException(404, "Объект не найден")
        return {"ref": f"object:{row.id}", "application": self.application, "title": row.name or row.code or row.id,
                "url": f"/ops?object={row.id}", "object_id": row.id, "defaults": {}, "actions": []}
