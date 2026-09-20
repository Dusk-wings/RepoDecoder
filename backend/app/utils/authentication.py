from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends

from sqlalchemy.ext.asyncio import AsyncSession

from typing import Annotated
from jwt import decode

from app.core.config import env_config
from app.core.db import get_database

security = HTTPBearer()


def get_token(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> str | None:
    token = credentials.credentials
    return token


def get_current_user(
    token: Annotated[str | None, get_token], db: Annotated[AsyncSession, get_database]
):
    if not token:
        return {"auth": False, "user_id": None, "email": None}

    
