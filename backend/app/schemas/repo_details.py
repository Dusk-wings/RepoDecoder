from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import Any


class RepoDepDetails(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    details: Any


class RepoDetails(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    repo_full_name: str
    description: str | None
    created_at: datetime | None
    owner: str | None
    dep_details: list[RepoDepDetails]
