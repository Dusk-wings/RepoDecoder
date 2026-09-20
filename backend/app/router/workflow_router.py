from fastapi import APIRouter, Depends, Body

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_database
from app.services.workflow_service import start_ingest_service
from app.schemas.response import StandardResponse
from app.schemas.user import UserDetails
from app.utils.authentication import get_current_user

from pydantic import BaseModel
from typing import Annotated

router = APIRouter(prefix="/workflow", tags=["Workflow"])


class WorkSpaceInput(BaseModel):
    github_url: str

db_depends = Annotated[AsyncSession, Depends(get_database)]

@router.post("/start-ingest", response_model=StandardResponse[None])
async def start_workflow(
    user: Annotated[UserDetails, Depends(get_current_user)],
    body: Annotated[WorkSpaceInput, Body()],
    db: db_depends,
):
    response = await start_ingest_service(github_url=body.github_url, user=user, db=db)
    
    if response.get("success") == True:
        return {
            "status": response.get("status"),
            "message": response.get("message"),
            "data": None
        }
