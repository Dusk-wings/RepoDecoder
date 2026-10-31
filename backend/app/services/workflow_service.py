import httpx
from uuid import UUID

from app.errors.github_error import GitHubResponseError, GitHubConnectionError
from app.errors.server_error import ServerError
from app.errors.not_found_error import NotFoundError

from app.core.config import env_config

from app.models.user_repo import UserRepo
from app.models.repository import Repository, RepoStatus

from sqlalchemy.future import select
from sqlalchemy import insert, func, literal
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession


class WorkflowService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def save_anon_workflow_request(self, user_id: UUID, repo_url: str):
        stmt = select(Repository.status, Repository.repo_id).where(
            Repository.repo_url == repo_url
        )
        try:
            response = await self.db.execute(stmt)
            repo_data = response.one_or_none()

            if not repo_data:
                raise NotFoundError(message="REPO REQUESTED DOES NOT EXIST")

            if (
                repo_data.status == RepoStatus.processing
                or repo_data.status == RepoStatus.failed
            ):
                raise ServerError(message="THE REPO IS UNPROCESSABLE", status=422)

            count_query = (
                select(func.count())
                .select_from(UserRepo)
                .where(UserRepo.user_id == user_id)
                .scalar_subquery()
            )

            stmt = (
                insert(UserRepo)
                .from_select(
                    ["user_id", "repo_id"],
                    select(literal(user_id), literal(repo_data.repo_id)).where(
                        count_query < 3
                    ),
                )
                .returning(UserRepo.user_repo_id)
            )

            result = await self.db.execute(stmt)
            user_repo_id = result.scalar_one_or_none()
            await self.db.commit()

            if not user_repo_id:
                raise ServerError(
                    message="MAXIMUM REPO-COUNT REACHED, PLEASE LOGIN", status=403
                )

            return {
                "success": True,
                "message": "USER ASSOCIATED WITH THE REPO",
                "status": 201,
            }

        except SQLAlchemyError:
            raise ServerError(message="INTERNAL SERVER ERROR")

    async def start_ingest_service(self, github_url: str, user_id: UUID) -> dict:
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
                "client_payload": {"github_url": github_url, "user_id": user_id},
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
