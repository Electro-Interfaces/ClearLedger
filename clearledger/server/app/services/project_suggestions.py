from __future__ import annotations

import httpx
from sqlalchemy import func, select

from app.config import get_settings
from app.models import EzsSite


async def suggest(db, company_id, field, query, *, region="", city=""):
    query = query.strip()
    address_field = field in {"region", "city", "address"}
    token = get_settings().dadata_api_key if address_field else ""
    result = {"items": [], "registry": "available" if token else "local"}
    if len(query) < 2:
        return result

    column = {"title": EzsSite.title, "region": func.coalesce(EzsSite.region_norm, EzsSite.region),
              "city": EzsSite.city, "address": EzsSite.address,
              "install_place": EzsSite.install_place}[field]
    conditions = [EzsSite.company_id == company_id,
                  func.lower(column).contains(query.lower(), autoescape=True)]
    if field in {"city", "address"} and region:
        conditions.append(func.lower(func.coalesce(EzsSite.region_norm, EzsSite.region)) == region.lower())
    if field == "address" and city:
        conditions.append(func.lower(EzsSite.city) == city.lower())
    values = (await db.execute(select(column).where(*conditions).distinct().order_by(column).limit(10))).scalars().all()
    result["items"] = [{"value": value, "source": "projects"} for value in values if value]
    if not token:
        return result

    bound = {"region": "region", "city": "settlement", "address": "house"}[field]
    body = {"query": " ".join(v for v in [region if field != "region" else "",
                                           city if field == "address" else "", query] if v),
            "count": 10, "from_bound": {"value": "city" if field == "city" else "street" if field == "address" else "region"},
            "to_bound": {"value": bound}}
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            response = await client.post(
                "https://suggestions.dadata.ru/suggestions/api/4_1/rs/suggest/address",
                json=body, headers={"Authorization": f"Token {token}"})
            response.raise_for_status()
            items = response.json().get("suggestions", [])
        seen = {item["value"].casefold() for item in result["items"]}
        for item in items:
            data = item.get("data") or {}
            fields = {
                "region": data.get("region_with_type") or "",
                "city": ", ".join(filter(None, [data.get("city_with_type"), data.get("settlement_with_type")])),
                "address": ", ".join(filter(None, [data.get("street_with_type"),
                    " ".join(filter(None, [data.get("house_type"), data.get("house")])),
                    " ".join(filter(None, [data.get("block_type"), data.get("block")]))])),
            }
            value = fields[field]
            if not value or value.casefold() in seen:
                continue
            seen.add(value.casefold())
            result["items"].append({"value": value, "label": item.get("value") or value,
                                    "fields": {k: v for k, v in fields.items() if v}, "source": "registry"})
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        result["registry"] = "unavailable"
    return result
