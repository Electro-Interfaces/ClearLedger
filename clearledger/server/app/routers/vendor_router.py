from __future__ import annotations

from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log_audit
from app.auth import assert_company_product, get_company_by_api_key, get_current_user
from app.database import get_db
from app.models import (
    App, Company, CompanyApp, PartnerAttachment, PartnerMessage, PartnerTopic,
    SiteCabinetUser, SourceFile, User,
)
from app.routers.site_router import _call
from app.routers.space_bridge_router import _verify_visit
from app.services import partner_bridge, sso

router = APIRouter(tags=["Элси+"])


class VendorRequest(BaseModel):
    space: str = Field(min_length=1, max_length=50)
    token: str = Field(min_length=1, max_length=8192)


class DemoRequest(BaseModel):
    demo_id: str = Field(pattern=r"^[a-z0-9-]{1,50}$")


async def _vendor(db: AsyncSession, company_id: str, code: str, user: User):
    cid = await assert_company_product(company_id, user, db, "elsy")
    enabled = (await db.execute(select(CompanyApp.id).join(App, App.id == CompanyApp.app_id)
        .where(CompanyApp.company_id == cid, CompanyApp.enabled.is_(True),
               App.code == "elsy", App.is_active.is_(True)))).scalar_one_or_none()
    if enabled is None:
        raise HTTPException(404, "Приложение Элси+ не подключено в этом пространстве")
    vendor = await partner_bridge.get_partner(db, cid, code, role="vendor")
    if vendor is None:
        raise HTTPException(404, "Связь с поставщиком не найдена")
    if not vendor.base_url or not partner_bridge.partner_key(vendor):
        raise HTTPException(409, "Связь с поставщиком пока не настроена")
    return cid, vendor


async def _remote(db, cid, vendor, user, operation, demo_id=None):
    company = await db.get(Company, cid)
    token = sso.sign_vendor_token(
        user=user, company_id=str(cid), self_code=company.slug,
        vendor_code=vendor.code, operation=operation, demo_id=demo_id,
    )
    if not token:
        raise HTTPException(503, "Переход к поставщику пока не настроен")
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(
                f"{vendor.base_url.rstrip('/')}/api/eco/vendor/{operation}",
                headers={"X-Cloud-API-Key": partner_bridge.partner_key(vendor)},
                json={"space": company.slug, "token": token},
            )
    except httpx.HTTPError:
        raise HTTPException(503, "Не удалось связаться с поставщиком. Попробуйте ещё раз")
    if response.status_code >= 400:
        status = response.status_code if response.status_code in {403, 404, 409} else 503
        detail = "Показ пока недоступен. Напишите нам по этому продукту" if operation == "demo" \
            else "Каталог сейчас недоступен. Попробуйте ещё раз"
        raise HTTPException(status, detail)
    try:
        return response.json()
    except ValueError:
        raise HTTPException(502, "Не удалось прочитать ответ поставщика")


async def _client(db, company, payload, operation):
    partner = await partner_bridge.get_partner(db, company.id, payload.space, role="client")
    if partner is None or not partner.counterparty_id:
        raise HTTPException(403, "Отношение с клиентом не настроено")
    try:
        keys = await partner_bridge.partner_jwks(partner)
    except partner_bridge.BridgeError:
        raise HTTPException(503, "Не удалось проверить пространство клиента")
    claims = _verify_visit(payload.token, keys, audience=f"vendor:{company.slug}")
    if (claims.get("space") != partner.code or claims.get("operation") != operation
            or not claims.get("company_id") or not claims.get("sub")
            or not claims.get("exp") or not claims.get("email")):
        raise HTTPException(403, "Пропуск не подходит для этого действия")
    row = (await db.execute(select(SiteCabinetUser).where(
        SiteCabinetUser.company_id == company.id,
        SiteCabinetUser.counterparty_id == partner.counterparty_id,
        SiteCabinetUser.email == str(claims["email"]).strip().lower(),
        SiteCabinetUser.is_active.is_(True),
        SiteCabinetUser.level.in_(["client", "partner", "admin"]),
    ))).scalar_one_or_none()
    return partner, claims, row


def _allowed(row, code):
    return row is not None and (not row.demos or code in row.demos)


@router.get("/vendor/{code}/catalog")
async def catalog(code: str, company_id: str = Query(...),
                  user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid, vendor = await _vendor(db, company_id, code, user)
    return await _remote(db, cid, vendor, user, "catalog")


@router.post("/vendor/{code}/demo")
async def launch_demo(code: str, payload: DemoRequest, company_id: str = Query(...),
                      user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid, vendor = await _vendor(db, company_id, code, user)
    result = await _remote(db, cid, vendor, user, "demo", payload.demo_id)
    await log_audit(db, actor=user, company_id=cid, action="vendor.demo", target=payload.demo_id)
    await db.commit()
    return result


@router.post("/eco/vendor/catalog")
async def provide_catalog(payload: VendorRequest,
                          company: Company = Depends(get_company_by_api_key),
                          db: AsyncSession = Depends(get_db)):
    _, _, account = await _client(db, company, payload, "catalog")
    result = await _call(db, company.id, "/api/space/catalog")
    if not result.get("connected") or not isinstance(result.get("data"), dict):
        raise HTTPException(503, "Каталог пока недоступен")
    data = result["data"]
    products = []
    for raw in data.get("products", []):
        product = dict(raw)
        image = product.get("image")
        product["image"] = urljoin(result["url"].rstrip('/') + '/', image.lstrip('/')) \
            if isinstance(image, str) and image.startswith("/products/") and ".." not in image else None
        demo = product.get("demo")
        if demo:
            product["demo"] = {**demo, "allowed": _allowed(account, demo.get("code"))}
        products.append(product)
    return {"products": products, "help": data.get("help", [])}


@router.post("/eco/vendor/demo")
async def provide_demo(payload: VendorRequest,
                       company: Company = Depends(get_company_by_api_key),
                       db: AsyncSession = Depends(get_db)):
    _, claims, account = await _client(db, company, payload, "demo")
    demo_id = claims.get("demo_id")
    if not demo_id or not _allowed(account, demo_id):
        raise HTTPException(403, "Доступ к показу ещё не открыт")
    result = await _call(db, company.id, "/api/space/demo/launch", method="POST",
                         json_body={"email": account.email, "demo_id": demo_id})
    data = result.get("data")
    if not result.get("connected") or not isinstance(data, dict):
        raise HTTPException(503, "Показ сейчас недоступен. Попробуйте ещё раз")
    path = data.get("url", "")
    parsed = urlsplit(path)
    if parsed.scheme or parsed.netloc or parsed.path != f"/demo-run/{demo_id}/":
        raise HTTPException(502, "Получен неверный адрес показа")
    return {"url": urljoin(result["url"].rstrip('/') + '/', path.lstrip('/')),
            "expires_in": data.get("expires_in")}


@router.get("/vendor/{code}/documents")
async def documents(code: str, company_id: str = Query(...),
                    user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    cid, vendor = await _vendor(db, company_id, code, user)
    await assert_company_product(str(cid), user, db, "docs")
    rows = (await db.execute(select(PartnerAttachment, SourceFile, PartnerMessage, PartnerTopic)
        .join(PartnerMessage, PartnerMessage.id == PartnerAttachment.message_id)
        .join(SourceFile, SourceFile.id == PartnerAttachment.file_id)
        .outerjoin(PartnerTopic, PartnerTopic.id == PartnerMessage.topic_id)
        .where(PartnerAttachment.company_id == cid, PartnerMessage.company_id == cid,
               SourceFile.company_id == cid, PartnerMessage.partner_id == vendor.id,
               PartnerMessage.direction == "in")
        .order_by(PartnerAttachment.created_at.desc()).limit(100))).all()
    return {"items": [{
        "id": str(attachment.id), "name": file.file_name, "size": file.size,
        "createdAt": attachment.created_at.isoformat() if attachment.created_at else None,
        "author": message.author_name or vendor.name,
        "topicCode": topic.code if topic else None, "topicTitle": topic.title if topic else None,
    } for attachment, file, message, topic in rows]}
