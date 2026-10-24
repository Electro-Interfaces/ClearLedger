"""V1: только чтение обзора; scoped credential принимается лишь source-overview."""
from datetime import date

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import assert_company_member, bearer_scheme, decode_token, get_current_user
from app.database import get_db
from app.deps import capture_company_header
from app.models import User
from app.services.management_config import Kind, ManagementConfigError, load_config
from app.services.management_delegation import verify_access
from app.services.management_local import read_local
from app.services.management_overview import calendar_bounds, now, overview
from app.services.management_schemas import ManagementOverview, SourceOverview

router = APIRouter(prefix="/management", tags=["Управляющее пространство"])


def _config():
    try:
        return load_config()
    except ManagementConfigError:
        raise HTTPException(503, "Конфигурация обзора недоступна")


@router.get("/status")
async def management_status(
    response: Response,
    x_company_id: str = Header(..., alias="X-Company-Id", min_length=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    await assert_company_member(x_company_id, current_user, db)
    config = _config()
    return {"enabled": config.enabled and config.hub_enabled}


@router.get("/overview", response_model=ManagementOverview)
async def management_overview(
    response: Response,
    kind: Kind = Query(...),
    space: str = Query("all", max_length=40, pattern=r"^[a-z][a-z0-9_-]*$"),
    query: str = Query("", max_length=200),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    time_zone: str = Query("Europe/Moscow", min_length=1, max_length=100),
    limit: int = Query(100, ge=1, le=200),
    x_company_id: str = Header(..., alias="X-Company-Id", min_length=1),
    current_user: User = Depends(get_current_user),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    # Заголовок обязателен: ни default company, ни соседние членства не подставляем.
    cid = await assert_company_member(x_company_id, current_user, db)
    await capture_company_header(str(cid))
    config = _config()
    return await overview(config, db, current_user, cid, kind, space, query.strip(),
                          date_from, date_to, time_zone, limit,
                          allow_remote=bool(credentials) and not bool(
                              decode_token(credentials.credentials).get("scp")))


@router.get("/source-overview", response_model=SourceOverview)
async def management_source_overview(
    response: Response,
    kind: Kind = Query(...),
    query: str = Query("", max_length=200),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    time_zone: str = Query("Europe/Moscow", min_length=1, max_length=100),
    limit: int = Query(100, ge=1, le=200),
    authorization: str | None = Header(None),
    db: AsyncSession = Depends(get_db),
):
    response.headers["Cache-Control"] = "no-store"
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Требуется scoped доступ к источнику")
    config = _config()
    actor = await verify_access(authorization[7:], kind, config, db)
    await capture_company_header(str(actor.company_id))
    start, end = calendar_bounds(kind, date_from, date_to, time_zone)
    try:
        records, truncated = await read_local(db, actor.user, actor.company_id, kind,
                                              query=query.strip(), date_from=start,
                                              date_to=end, limit=limit)
    except HTTPException:
        raise HTTPException(403, "Источник отказал в доступе")
    except Exception:
        raise HTTPException(503, "Не удалось прочитать источник")
    return SourceOverview(fetched_at=now(), items=records, truncated=truncated)
