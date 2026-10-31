from fastapi import APIRouter, Depends, Body

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_database
from app.services.workflow_service import WorkflowService
from app.schemas.response import StandardResponse
from app.schemas.user import UserDetails
from app.api.deps import get_current_user

from pydantic import BaseModel
from typing import Annotated

router = APIRouter(prefix="/workflow", tags=["Workflow"])


class WorkSpaceInput(BaseModel):
    github_url: str


db_depends = Annotated[AsyncSession, Depends(get_database)]


def get_workflow_service(db: db_depends):
    return WorkflowService(db)


@router.post("/add-repo-user", response_model=StandardResponse[None])
async def start_workflow(
    user: Annotated[UserDetails, Depends(get_current_user)],
    body: Annotated[WorkSpaceInput, Body()],
    workflow: Annotated[WorkflowService, Depends(get_workflow_service)],
):
    if user.is_anonymous:
        response = await workflow.save_anon_workflow_request(
            user_id=user.user_id, repo_url=body.github_url
        )
    else:
        response = await workflow.start_ingest_service(
            github_url=body.github_url, user_id=user.user_id
        )

    if response.get("success") == True:
        return {
            "status": response.get("status"),
            "message": response.get("message"),
            "data": None,
        }
