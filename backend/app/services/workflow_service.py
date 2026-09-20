import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi.exceptions import HTTPException
from fastapi import status

from app.core.config import env_config
from app.schemas.user import UserDetails


async def start_ingest_service(github_url: str, user: UserDetails, db: AsyncSession) -> dict:
    try:
        github_user = env_config.GITHUB_USER
        github_repo = env_config.GITHUB_REPO
        github_token = env_config.GITHUB_TOKEN

        url = f"https://api.github.com/repos/{github_user}/{github_repo}/dispatches"
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        payload = {
            "event_type": "start-ingest",
            "client_payload": {"github_url": github_url},
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url=url, json=payload, headers=headers)

    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=exc.response.status_code,
            detail=(
                exc.response.json()
                if exc.response.content
                else "FAILED TO TRIGGER GITHUB ACTIONS"
            ),
        )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"GITHUB API CONNECTION ERROR: {str(exc)}",
        )

    return {
        "success": True,
        "message": "INGEST PIPELINE TRIGGERED SUCCESSFULLY",
        "status": response.status_code,
    }
