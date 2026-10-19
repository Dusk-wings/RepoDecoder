import httpx
from app.errors.github_error import GitHubResponseError, GitHubConnectionError

from app.core.config import env_config


async def start_ingest_service(github_url: str) -> dict:
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
        try:
            detail = (
                exc.response.json()
                if exc.response.content
                else "FAILED TO TRIGGER REQUEST TO GITHUB"
            )
        except ValueError:
            detail = "FAILED TO TRIGGER REQUEST TO GITHUB"

        raise GitHubResponseError(
            status_code=exc.response.status_code,
            message=detail,
        )
    except httpx.RequestError as exc:
        # status 503
        raise GitHubConnectionError(
            f"UNABLE TO CONNECT TO THE GITHUB, SERVICE UNAVAILABLE, SERVER ERROR",
        )

    return {
        "success": True,
        "message": "INGEST PIPELINE TRIGGERED SUCCESSFULLY",
        "status": response.status_code,
    }
