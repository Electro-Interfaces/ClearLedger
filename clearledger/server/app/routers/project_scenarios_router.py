from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth import assert_company_member, get_current_user
from app.database import get_db
from app.services import project_scenario_settings as settings

router = APIRouter(prefix="/project-scenarios", tags=["Сценарии проектов"])


class DraftBody(BaseModel):
    expected_revision: int = Field(ge=0)
    definition: settings.ScenarioDefinition


class PublishBody(BaseModel):
    expected_revision: int = Field(ge=0)


@router.get("")
async def catalog(company_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    from app.services import project_scenario_demo
    return {**await settings.catalog(db, cid, user), "demo_available": await project_scenario_demo.available(db, cid, user)}


@router.post("/demo")
async def demo(company_id: str, user=Depends(get_current_user), db=Depends(get_db)):
    from app.services import project_scenario_demo
    cid = await assert_company_member(company_id, user, db)
    return await project_scenario_demo.prepare(db, cid, user)


@router.put("/{kind}/draft")
async def draft(kind: str, body: DraftBody, company_id: str,
                user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    return await settings.save(db, cid, user, kind, body.expected_revision, body.definition)


@router.post("/{kind}/publish")
async def publish(kind: str, body: PublishBody, company_id: str,
                  user=Depends(get_current_user), db=Depends(get_db)):
    cid = await assert_company_member(company_id, user, db)
    return await settings.save(db, cid, user, kind, body.expected_revision, publish=True)
