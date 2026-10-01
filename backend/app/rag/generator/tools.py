from app.core.db import AsyncSessionLocal
from app.core.config import env_config

from backend.app.rag.utils.spread_sheet_analyzer import SpreadSheetAnalyzer
from app.utils.storage import BucketStorage
from app.errors.serverError import ServerError
from app.errors.notFoundError import NotFoundError

from app.models.bucket_file import BucketType, BucketFileType
from app.models.repository import Repository
from app.models.repo_dep_details import RepoDepDetails
from app.models.dependencies import Dependencies
from app.models.repo_file import RepoFile

from app.schemas.repo_details import RepoDetails
from app.schemas.repo_deps import RepoDependencies

from sqlalchemy.future import select
from sqlalchemy.orm import load_only, selectinload
from sqlalchemy import or_

import uuid
import logging
from supabase import AsyncClient
import json

logger = logging.getLogger(__name__)


class Tools(SpreadSheetAnalyzer):
    def __init__(self, _client: AsyncClient) -> None:
        super().__init__(_client)

    async def get_image_url(
        self, repo_id: uuid.UUID, file_id: uuid.UUID, image_path: str
    ):
        try:
            image_url = await BucketStorage.get_signed_url(
                supabase_client=self._client,
                repo_id=repo_id,
                file_id=file_id,
                url=image_path,
                file_type=BucketFileType.image,
                bucket_name=env_config.IMAGE_BUCKET_NAME or "",
                bucket_type=BucketType.public,
            )

            return {
                "status": "success",
                "message": "IMAGE URL FETCHED",
                "url": image_url.get("url") or None,
            }

        except (ValueError, ServerError) as e:
            return {"status": "error", "message": e, "url": None}

        except Exception as e:
            return {
                "status": "error",
                "message": "UNEXPECTED ERROR WHILE FETCHING FILE URL",
                "url": None,
            }

    async def get_repo_details(self, repo_id: uuid.UUID):
        try:
            async with AsyncSessionLocal() as db:
                stmt = (
                    select(Repository)
                    .options(
                        load_only(
                            Repository.repo_full_name,
                            Repository.description,
                            Repository.created_at,
                            Repository.owner,
                        ),
                        selectinload(Repository.dep_details).load_only(
                            RepoDepDetails.details
                        ),
                    )
                    .where(Repository.repo_id == repo_id)
                )

                result = await db.execute(stmt)
                repo_details = result.scalar_one_or_none()

                if repo_details is None:
                    raise NotFoundError("THE REPOSITORY DOES NOT EXIST")

                response = RepoDetails.model_validate(repo_details)
                return {
                    "status": "success",
                    "message": "DETAILS FETCHED",
                    "data": response.model_dump_json(),
                }

        except NotFoundError as e:
            logger.exception("[REPO-DETAILS] THE REPO DETAILS REQUESTED DOES NOT EXIST")
            return {"status": "error", "message": e, "data": None}
        except Exception as e:
            logger.exception(
                "[REPO-DETAILS] THERE IS A PROBLEM WHILE FETCHING REPO DETAILS, ERROR: %s",
                e,
            )
            return {"status": "error", "message": "INTERNAL SERVER ERROR", "data": None}

    async def get_dep_version(self, repo_id: uuid.UUID, dep_name: str):
        try:
            async with AsyncSessionLocal() as db:
                stmt = (
                    select(Dependencies)
                    .options(
                        selectinload(Dependencies.file).load_only(RepoFile.file_path),
                        load_only(
                            Dependencies.name,
                            Dependencies.version,
                            Dependencies.type,
                            Dependencies.language,
                        ),
                    )
                    .where(
                        Dependencies.name.ilike(f"%{dep_name}%"),
                        Dependencies.repo_id == repo_id,
                    )
                )

                result = await db.execute(stmt)
                dependencies = result.scalars().all()

                response = [
                    RepoDependencies.model_validate(dependency)
                    for dependency in dependencies
                ]

                return {
                    "status": "success",
                    "message": "DETAILS FETCHED",
                    "data": [item.model_dump() for item in response],
                }

        except Exception as e:
            logger.exception(
                "[REPO-DEPENDENCIES] PROBLEM WHILE FETCHING DEPENDENCY DETAILS, ERROR: %s",
                e,
            )
            return {"status": "error", "message": "INTERNAL SERVER ERROR", "data": None}

    def get_tool_defination(self) -> list:
        spread_sheet_tool = {
            "type": "function",
            "function": {
                "name": "process_tabular_data",
                "description": (
                    "Filter a spreadsheet or delimited text files and return up to 20 matching records. "
                    "Use an empty conditions list to return the first 5 records."
                    "Supports .xlsx, .ods, .csv, .tsv"
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "Path of the spreadsheet or delimited text file as stored in the DB.",
                        },
                        "conditions": {
                            "type": "array",
                            "description": (
                                "Filter conditions. Use a scalar value for most "
                                "operators, a list for 'in' and 'between', and omit "
                                "value for 'is_null' and 'not_null'."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "column": {
                                        "type": "string",
                                        "description": "Exact spreadsheet or delimited text file column name.",
                                    },
                                    "operator": {
                                        "type": "string",
                                        "enum": [
                                            "eq",
                                            "neq",
                                            "gt",
                                            "gte",
                                            "lt",
                                            "lte",
                                            "contains",
                                            "in",
                                            "between",
                                            "is_null",
                                            "not_null",
                                        ],
                                    },
                                    "value": {
                                        "description": (
                                            "Comparison value. Use a list for "
                                            "'in' or 'between'."
                                        ),
                                        "oneOf": [
                                            {"type": "string"},
                                            {"type": "number"},
                                            {"type": "boolean"},
                                            {"type": "array", "items": {}},
                                        ],
                                    },
                                },
                                "required": ["column", "operator"],
                                "additionalProperties": False,
                            },
                        },
                        "combine": {
                            "type": "string",
                            "enum": ["and", "or"],
                            "default": "and",
                            "description": "How to combine multiple conditions.",
                        },
                    },
                    "required": ["file_path", "conditions"],
                    "additionalProperties": False,
                },
            },
        }

        repo_detail_tool = {
            "type": "function",
            "function": {
                "name": "get_repo_details",
                "description": (
                    "Fetch the details of the current repository. "
                    "Use this when the user asks the questions about repository like `what's the repo about?`,"
                    "or its description, ownership, creation date, or details in the dependencies file not the dependencies version"
                    "This does not replace the requirements of the retrived chunks but add's the useful information about the repo."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
            },
        }

        repo_dependencies_tool = {
            "type": "function",
            "function": {
                "name": "get_dep_version",
                "description": (
                    "Find dependency details and versions in the current repository."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "dep_name": {
                            "type": "string",
                            "description": (
                                "The dependency name to search for, "
                                "such as requests or django or react."
                            ),
                        }
                    },
                    "required": ["dep_name"],
                    "additionalProperties": False,
                },
            },
        }

        tools = [spread_sheet_tool, repo_detail_tool, repo_dependencies_tool]

        return tools

    async def use_tool(
        self,
        repo_id: uuid.UUID,
        tool_name: str,
        function_arguments: str,
    ):
        try:
            arguments = json.loads(function_arguments)
        except json.JSONDecodeError:
            return {
                "status": "error",
                "message": "Invalid tool arguments",
                "data": None,
            }

        if tool_name == "get_dep_version":
            dep_name = arguments.get("dep_name")
            if not dep_name:
                return {
                    "status": "error",
                    "message": "`dep_name` DOES NOT EXIST, REQUIRED FOR `get_dep_version`",
                    "data": None,
                }

            result = await self.get_dep_version(repo_id=repo_id, dep_name=dep_name)
            return result

        elif tool_name == "get_repo_details":
            result = await self.get_repo_details(repo_id=repo_id)
            return result

        elif tool_name == "process_tabular_data":
            file_path = arguments.get("file_path")
            conditions = arguments.get("conditions")
            combine = arguments.get("combine")

            if not file_path:
                return {
                    "status": "error",
                    "message": "`file_path` DOES NOT EXIST, REQUIRED FOR `process_tabular_data`",
                    "data": None,
                }

            if not conditions or not isinstance(conditions, list):
                return {
                    "status": "error",
                    "message": "`conditions` MUST EXIST AND IT SHOULD BE A LIST, EITHER EMPTY OR EITHER WITH `dict` CONTAINING `column`, `operator` and `value`",
                    "data": None,
                }

            if not combine:
                combine = "and"

            result = await self.process_file(
                repo_id=repo_id,
                file_path=file_path,
                conditions=conditions,
                combine=combine,
            )

            return result
        else:
            return {
                "status": "error",
                "message": f"UNDEFINED FUNCTION NAME {tool_name}",
                "data": None,
            }
