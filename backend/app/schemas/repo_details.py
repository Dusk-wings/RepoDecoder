from datetime import datetime
from pydantic import BaseModel, ConfigDict


class RepoDepDetails(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    details: str


class RepoDetails(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repo_full_name: str
    description: str | None
    created_at: datetime | None
    owner: str | None
    dep_details: list[RepoDepDetails]
