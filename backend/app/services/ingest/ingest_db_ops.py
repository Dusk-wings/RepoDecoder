from sqlalchemy import update, delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.future import select

from app.models.repo_file import RepoFile, FileProcess
from app.models.file_imports import FileImport
from app.models.ingest_logs import IngestLogs
from app.models.repo_dep_details import RepoDepDetails
from app.models.dependencies import Dependencies
from app.models.embedding import Embedding
from app.models.repository import Repository, RepoStatus
from app.models.bucket_file import BucketFileType

from app.core.db import AsyncSessionLocal
from app.core.config import env_config

from app.utils.storage import BucketStorage

from typing import Any
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


class IngestDbOps:
    def __init__(self) -> None:
        self.repo_id: uuid.UUID | None = None
        self.repo_name: str | None = None

    async def _update_file_status(self, file_path: str, status: FileProcess):
        query = (
            update(RepoFile)
            .where(
                RepoFile.file_path == str(file_path),
                RepoFile.repo_id == self.repo_id,
            )
            .values(status=status)
        )

        async with AsyncSessionLocal() as db:
            try:
                result = await db.execute(query)
                await db.commit()

            except Exception as e:
                logger.exception(
                    "[INGEST-DB-OPS-UPDATE-FILE-STATUS] UNABLE TO UPDATE THE FILE STATUS, %s",
                    e,
                )
                await db.rollback()
                raise

    async def _update_file_statuses(
        self,
        file_ids: list[uuid.UUID] | None = None,
        file_paths: list[str] | None = None,
        status: FileProcess = FileProcess.failed,
    ):
        if not file_ids and not file_paths:
            return

        conditions = [RepoFile.repo_id == self.repo_id]
        if file_ids:
            conditions.append(RepoFile.file_id.in_(file_ids))
        else:
            assert file_paths is not None
            conditions.append(RepoFile.file_path.in_(file_paths))

        async with AsyncSessionLocal() as db:
            try:
                await db.execute(
                    update(RepoFile).where(*conditions).values(status=status)
                )
                await db.commit()
            except Exception:
                await db.rollback()
                logger.exception(
                    "[INGEST-DB-OPS-UPDATE-FILE-STATUSES] UNABLE TO UPDATE FILE STATUSES"
                )
                raise

    async def get_existing_files(self) -> dict:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(RepoFile.file_hash, RepoFile.file_path, RepoFile.status).where(
                    RepoFile.repo_id == self.repo_id
                )
            )
            return {row["file_path"]: row for row in result.mappings().all()}

    async def save_file_imports(self, file_path: str, imports: list[dict]):
        async with AsyncSessionLocal() as db:
            try:
                current_file_id = await db.scalar(
                    select(RepoFile.file_id).where(
                        RepoFile.file_path == file_path,
                        RepoFile.repo_id == self.repo_id,
                    )
                )
                if current_file_id is None:
                    raise ValueError(f"Current file not found: {file_path}")

                resolved_paths = {
                    item.get("resolved_path")
                    for item in imports
                    if item.get("resolved_path")
                }
                resolved_file_rows = await db.execute(
                    select(RepoFile.file_path, RepoFile.file_id).where(
                        RepoFile.repo_id == self.repo_id,
                        RepoFile.file_path.in_(resolved_paths),
                    )
                )
                resolved_file_ids = {
                    path: file_id for path, file_id in resolved_file_rows.all()
                }

                rows = []
                logs = []
                for item in imports:
                    resolved_path = item.get("resolved_path")
                    imported_file_id = resolved_file_ids.get(resolved_path)
                    if imported_file_id is None:
                        logs.append(
                            {
                                "file_id": current_file_id,
                                "repo_id": self.repo_id,
                                "log": f"The file {file_path} have a import that points to {resolved_path}, but the file does not exist",
                            }
                        )

                    rows.append(
                        {
                            "file_id": current_file_id,
                            "imported_file_id": imported_file_id,
                            "source": item.get("source"),
                            "module_alias": item.get("module_alias"),
                            "symbols": item.get("symbols"),
                            "is_wildcard": item.get("is_wildcard"),
                        }
                    )

                if rows:
                    await db.execute(insert(FileImport), rows)
                if logs:
                    await db.execute(insert(IngestLogs), logs)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def save_repo_files(self, files: list[dict]) -> list:
        async with AsyncSessionLocal() as db:
            try:
                stmt = insert(RepoFile).values(files)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_repo_file_repo_id_file_path",
                    set_={
                        "file_name": stmt.excluded.file_name,
                        "file_hash": stmt.excluded.file_hash,
                        "file_size": stmt.excluded.file_size,
                        "file_ext": stmt.excluded.file_ext,
                        "file_category": stmt.excluded.file_category,
                        "status": stmt.excluded.status,
                        "updated_at": func.now(),
                    },
                ).returning(RepoFile.file_id, RepoFile.file_path, RepoFile.file_hash)

                result = await db.execute(stmt)
                saved_files = [dict(row) for row in result.mappings().all()]
                file_ids = [row["file_id"] for row in saved_files]
                await db.execute(
                    delete(Embedding).where(Embedding.file_id.in_(file_ids))
                )
                await db.commit()
                return saved_files
            except Exception:
                await db.rollback()
                raise

    async def save_embeddings(self, embeddings: list[dict], file_ids: list[uuid.UUID]):
        async with AsyncSessionLocal() as db:
            try:
                if embeddings:
                    await db.execute(insert(Embedding).values(embeddings))
                if file_ids:
                    await db.execute(
                        update(RepoFile)
                        .where(RepoFile.file_id.in_(file_ids))
                        .values(status=FileProcess.success)
                    )
                await db.execute(
                    update(Repository)
                    .where(Repository.repo_id == self.repo_id)
                    .values(status=RepoStatus.completed)
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def _save_deps(
        self,
        file_path: str,
        language: str,
        deps: list[dict[str, Any]],
        details: dict[str, Any],
    ):
        async with AsyncSessionLocal() as db:
            try:
                file_id = await db.scalar(
                    select(RepoFile.file_id).where(
                        RepoFile.file_path == file_path,
                        RepoFile.repo_id == self.repo_id,
                    )
                )

                if file_id is not None:
                    for data in deps:
                        data["file_id"] = file_id
                        data["language"] = language

                    repo_dep_query = insert(RepoDepDetails).values(
                        repo_id=self.repo_id, file_id=file_id, details=details
                    )

                    repo_dep_query.on_conflict_do_update(
                        index_elements=["repo_id", "file_id"], set_={"details": details}
                    )

                    await db.execute(repo_dep_query)

                    await db.execute(insert(Dependencies), deps)
                    await db.commit()
                else:
                    logger.warning(
                        "[INJEST-DB-OPS-SAVE-DEPS] FILE %s IS YET NOT PRESENT IN THE DATABASE, DEPS CAN'T BE SAVED",
                        file_path,
                    )
            except Exception as e:
                logger.exception(
                    "[INJEST-DB-OPS-SAVE-DEPS] FOR FILE %s FAILED TO SAVE THE DEPS, %s",
                    file_path,
                    e,
                )
                await db.rollback()
                raise

    async def save_repo_details(self, github_url: str, details: dict):
        async with AsyncSessionLocal() as db:
            try:
                raw_created_at = details["created_at"]

                # Convert ISO string to a Python datetime object
                parsed_repo_created_at = datetime.fromisoformat(
                    raw_created_at.replace("Z", "+00:00")
                )
                data = {
                    "repo_name": details["name"],
                    "repo_full_name": details["full_name"],
                    "description": details["description"],
                    "repo_created_at": parsed_repo_created_at,
                    "license": details["license"],
                    "owner": details.get("owner", {}).get("login"),
                    "owner_url": details.get("owner", {}).get("html_url"),
                    "repo_url": details.get("html_url", github_url),
                }

                result = await db.execute(
                    insert(Repository).returning(
                        Repository.repo_id, Repository.repo_full_name
                    ),
                    data,
                )
                data = result.mappings().one()
                self.repo_id = data["repo_id"]
                self.repo_name = data["repo_full_name"]

                await db.commit()

            except Exception:
                logger.exception(
                    "[INJEST-DB-OPS-SAVE-REPO] REPO %s DETAILS ARE NOT SAVED",
                    github_url,
                )
                await db.rollback()
                raise

    async def get_repo_detail(self, github_url: str):
        try:
            async with AsyncSessionLocal() as db:
                stmt = select(Repository.repo_id, Repository.repo_full_name).where(
                    Repository.repo_url == github_url
                )

                result = await db.execute(stmt)
                data = result.mappings().one_or_none()

                return data
        except Exception:
            logger.exception(
                "[INJEST-DB-OPS-GET-REPO-DETAILS] UNABELE TO GET THE REPO-DETAILS FOR %s",
                github_url,
            )
            raise

    async def add_file_to_bucket(
        self, file: str, file_id: uuid.UUID, repo_id: uuid.UUID
    ):
        try:
            file_path = Path(file)

            spreadsheat_bucket = env_config.SPREADSHEAT_BUCKET_NAME
            if not spreadsheat_bucket:
                return

            time = datetime.now(timezone.utc).strftime("%Y-%m-%d:%H-%M-%SZ")
            object_name = f"{repo_id}/{file_id}/{uuid.uuid4}-{time}{file_path.suffix}"

            BucketStorage.store_file(
                bucket_name=spreadsheat_bucket,
                object_name=object_name,
                file_path=file_path,
                public_bucket=False,
            )

            await BucketStorage.update_file_upload_status(
                file_id=file_id,
                repo_id=repo_id,
                url=file,
                storage_key=object_name,
                file_type=BucketFileType.spread_sheat,
            )
        except Exception as e:
            logging.exception(
                "[ADD-FILE-BUCKET] FAILED TO ADD FILE TO THE BUCKET, ERROR: %s", e
            )
            raise
