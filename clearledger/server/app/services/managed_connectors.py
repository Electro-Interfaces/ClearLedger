"""Управление подключениями из общей витрины, хранение и исполнение — у приложения."""
import uuid

import httpx
from fastapi import HTTPException
from sqlalchemy import select

from app.models import App, AppCompanyLink
from app.services import sso
from app.services.space_projection import _internal_base_url

MANAGED_APPS = {"support"}


async def owner_context(db, company_id, app_code):
    if app_code not in MANAGED_APPS:
        raise HTTPException(404, "Приложение не предоставляет настройку подключений")
    result = (await db.execute(
        select(App, AppCompanyLink).join(AppCompanyLink, AppCompanyLink.app_id == App.id)
        .where(AppCompanyLink.company_id == company_id, App.code == app_code, App.is_active.is_(True))
    )).first()
    if not result:
        raise HTTPException(409, "Поддержка не связана с этой компанией. Настройте её в разделе «Приложения и модули».")
    app, link = result
    try:
        remote_company = str(uuid.UUID(str(link.external_company_id)))
    except (ValueError, TypeError):
        raise HTTPException(409, "Не задана компания в приложении-владельце") from None
    return app, remote_company


async def owner_request(db, company_id, actor_id, app_code, method, path, body=None):
    app, remote_company = await owner_context(db, company_id, app_code)
    token = sso.sign_service_token(aud=app_code, scope="connections", company_id=remote_company, actor_id=str(actor_id))
    if not token:
        raise HTTPException(503, "Служебная связь с Поддержкой не настроена: нет ключа единого входа")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=5.0)) as client:
            response = await client.request(
                method, f"{_internal_base_url(app, app_code)}/api/v1/eco/connector-management{path}",
                params={"companyId": remote_company}, headers={"Authorization": f"Bearer {token}"}, json=body,
            )
    except httpx.HTTPError:
        raise HTTPException(503, "Поддержка не ответила. Настройки не подтверждены, повторите запрос.") from None
    if response.status_code in (401, 403):
        raise HTTPException(502, "Поддержка не приняла служебный запрос. Проверьте настройку единого входа и версии приложений.")
    try:
        data = response.json()
    except ValueError:
        raise HTTPException(502, "Поддержка ответила не по контракту") from None
    if not isinstance(data, dict):
        raise HTTPException(502, "Поддержка ответила не по контракту")
    if response.status_code >= 400:
        code = response.status_code if response.status_code in (400, 404, 409, 422, 503) else 502
        raise HTTPException(code, data.get("error", "Не удалось выполнить действие с подключением"))
    data.pop("credentials", None)
    data["app"] = app_code
    data["app_name"] = app.name
    data["owner_base_url"] = app.base_url or f"/{app_code}"
    return data


async def catalog(db, company_id, actor_id):
    providers, problems = [], []
    for app_code in sorted(MANAGED_APPS):
        try:
            result = await owner_request(db, company_id, actor_id, app_code, "GET", "/catalog")
            for item in result.get("providers", []):
                providers.append({**item, "app": app_code, "app_name": result["app_name"], "owner_base_url": result["owner_base_url"]})
        except HTTPException as error:
            problems.append({"app": app_code, "message": error.detail})
    return {"providers": providers, "problems": problems}
