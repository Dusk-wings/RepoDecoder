import pandas as pd
from enum import Enum
from uuid import UUID
import logging
import httpx
import aiofiles
import tempfile
from python_calamine import CalamineWorkbook
from supabase import AsyncClient
import os
from pathlib import Path
import asyncio

from app.utils.storage import BucketStorage

from app.models.bucket_file import BucketFileType, BucketType
from app.models.repo_file import RepoFile

from app.core.config import env_config
from app.core.db import AsyncSessionLocal

from app.errors.validationError import ValidationError
from app.errors.networkError import NetworkError
from app.errors.serverError import ServerError
from app.errors.notFoundError import NotFoundError

from sqlalchemy.future import select

logger = logging.getLogger(__name__)

CHUNK_SIZE = 1000


class Operator(str, Enum):
    EQ = "eq"
    NEQ = "neq"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    CONTAINS = "contains"  # substring match, case-insensitive
    IN = "in"  # value is a list -- row matches if column value is in it
    BETWEEN = "between"  # value is [low, high]
    IS_NULL = "is_null"
    NOT_NULL = "not_null"


OPERATOR_FUNCS = {
    Operator.EQ: lambda col, val: col == val,
    Operator.NEQ: lambda col, val: col != val,
    Operator.GT: lambda col, val: col > val,
    Operator.GTE: lambda col, val: col >= val,
    Operator.LT: lambda col, val: col < val,
    Operator.LTE: lambda col, val: col <= val,
    Operator.CONTAINS: lambda col, val: col.astype(str).str.contains(
        str(val), case=False, na=False
    ),
    Operator.IN: lambda col, val: col.isin(val),
    Operator.BETWEEN: lambda col, val: col.between(val[0], val[1]),
    Operator.IS_NULL: lambda col, val: col.isna(),
    Operator.NOT_NULL: lambda col, val: col.notna(),
}

supported_spread_sheat_suffix = [
    ".xlsx",
    ".xls",
    ".ods",
]


class SpreadSheetAnalyzer:
    def __init__(self, _client: AsyncClient) -> None:
        self._client = _client

    def _coerce_scalar(self, series: pd.Series, value):
        """Coerce one value to match the Series dtype."""
        if value is None:
            return None

        # Check bool before numeric because bool is numeric-like in pandas
        if pd.api.types.is_bool_dtype(series):
            if isinstance(value, bool):
                return value

            if isinstance(value, str):
                normalized = value.strip().lower()

                if normalized in {"true", "1", "yes"}:
                    return True

                if normalized in {"false", "0", "no"}:
                    return False

            return value

        if pd.api.types.is_numeric_dtype(series):
            try:
                if pd.api.types.is_integer_dtype(series):
                    return int(value)

                return float(value)
            except (ValueError, TypeError, OverflowError):
                return value

        if pd.api.types.is_datetime64_any_dtype(series):
            try:
                return pd.to_datetime(value)
            except (ValueError, TypeError):
                return value

        return value

    def _coerce(self, series: pd.Series, value):
        """Coerce scalar or collection values to match the Series dtype."""
        if isinstance(value, (list, tuple, set)):
            return [self._coerce_scalar(series, item) for item in value]

        return self._coerce_scalar(series, value)

    def _apply_filters(
        self,
        df: pd.DataFrame,
        conditions: list[dict],
        combine: str = "and",
    ) -> list[dict]:
        if combine not in {"and", "or"}:
            raise ValueError("`combine` MUST BE EITHER `and` OR `or`")

        if not conditions:
            return df.to_dict(orient="records")

        masks = []

        for condition in conditions:
            column_name = condition.get("column")
            operator_value = condition.get("operator")
            value = condition.get("value")

            if column_name not in df.columns:
                raise ValueError(f"Unknown column: {column_name}")

            if operator_value is None:
                raise ValueError("Missing operator")

            try:
                operator = Operator(operator_value)
            except ValueError as exc:
                raise ValueError(f"UNSUPPORTED OPERATOR: {operator_value}") from exc

            column = df[column_name]

            if operator == Operator.BETWEEN:
                if not isinstance(value, (list, tuple)) or len(value) != 2:
                    raise ValueError("'between' REQUIRES EXACTLY TWO VALUES")

                coerced = self._coerce(column, value)
                mask = OPERATOR_FUNCS[operator](column, coerced)

            elif operator == Operator.IN:
                if not isinstance(value, (list, tuple, set)):
                    raise ValueError("'in' REQUIRES A LIST OF VALUES")

                coerced = self._coerce(column, value)
                mask = OPERATOR_FUNCS[operator](column, coerced)

            elif operator in {Operator.IS_NULL, Operator.NOT_NULL}:
                mask = OPERATOR_FUNCS[operator](column, None)

            else:
                if value is None:
                    raise ValueError(f"Operator '{operator.value}' requires a value")

                coerced = self._coerce(column, value)
                mask = OPERATOR_FUNCS[operator](column, coerced)

            masks.append(mask)

        combined = masks[0]

        for mask in masks[1:]:
            if combine == "and":
                combined = combined & mask
            else:
                combined = combined | mask

        return df.loc[combined].to_dict(orient="records")

    async def process_csv_file(
        self,
        signed_url: str,
        conditions: list[dict],
        combine: str,
    ):
        filtered_data = []
        for chunk_df in pd.read_csv(signed_url, chunksize=CHUNK_SIZE):
            if not conditions:
                return chunk_df.head().to_dict(orient="records")

            rows = self._apply_filters(
                df=chunk_df,
                conditions=conditions,
                combine=combine,
            )

            filtered_data.extend(rows)

            if len(filtered_data) >= 20:
                break

        return filtered_data[:20]

    def _process_calamine_in_chunks_sync(self, file_path: str):
        # Load workbook metadata via Calamine (Rust)
        workbook = CalamineWorkbook.from_path(file_path)
        sheet = workbook.get_sheet_by_index(0)

        # Convert to Python row generator
        rows_iter = iter(sheet.to_python())

        # Get header rowasync with httpx.AsyncClient() as client:
        headers = next(rows_iter, None)
        if not headers:
            return

        current_chunk = []

        for row in rows_iter:
            current_chunk.append(row)

            # When chunk capacity is reached, build DataFrame and yield
            if len(current_chunk) >= CHUNK_SIZE:
                yield pd.DataFrame(current_chunk, columns=headers)
                current_chunk = []  # Clear memory!

        # Process final leftover rows
        if current_chunk:
            yield pd.DataFrame(current_chunk, columns=headers)

    async def _download_spreadsheat(self, signed_url: str):
        temp_path = None
        try:
            suffix = os.path.splitext(signed_url)[1].lower() or ".xlsx"

            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
                temp_path = temp_file.name

            async with httpx.AsyncClient() as client:
                async with client.stream("GET", signed_url) as response:
                    if response.status_code != 200:
                        logger.warning(
                            "[DOWNLOAD-SPREADSHEAT] UNABLE TO DOWNLOAD THE FILE"
                        )
                        raise NetworkError("NETWORK ERROR, UNABLE TO DOWNLOAD THE FILE")

                    async with aiofiles.open(temp_path, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            await f.write(chunk)

            logger.info("[DOWNLOAD-SPREADSHEAT] DOWNLOAD PROCESS COMPLETE")
            return temp_path

        except NetworkError as e:
            raise e
        except Exception as e:
            logger.exception("[DOWNLOAD-SPREADSHEAT] UNEXPECTED ERRROR, ERROR: %s", e)
            raise ServerError("INTERNAL SERVER ERROR")

    async def process_spreadsheat(
        self,
        temp_path: str,
        conditions: list[dict],
        combine: str,
    ):
        try:
            filtered_data = []
            for chunk_df in self._process_calamine_in_chunks_sync(temp_path):
                if not conditions:
                    return chunk_df.head().to_dict(orient="records")

                rows = self._apply_filters(
                    df=chunk_df,
                    conditions=conditions,
                    combine=combine,
                )

                filtered_data.extend(rows)

                if len(filtered_data) >= 20:
                    break

            return filtered_data[:20]
        except ValueError as e:
            raise

        except Exception as e:
            logger.exception(
                "[PROCESS-SPREADSHEAT] UNABLE TO PROCESS THE SPREADSHEAT VIA CALAMINE, ERROR: %s",
                e,
            )
            raise ServerError(
                "UNABLE TO PROCESS THE SPREADSHEAT, FILTER APPLICATION FAILED OR CALAMINE FILE LOADING FAILED"
            )

        finally:
            if temp_path is not None and isinstance(temp_path, str):
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    async def process_file(
        self,
        repo_id: UUID,
        file_path: str,
        conditions: list[dict],
        combine: str,
    ):
        try:
            file_id = None
            async with AsyncSessionLocal() as db:
                stmt = select(RepoFile.file_id).where(
                    RepoFile.file_path == file_path, RepoFile.repo_id == repo_id
                )
                file_id = await db.scalar(stmt)

            if not file_id:
                return {
                    "status": "error",
                    "message": "`file_path` SPECEFIED, DOES NOT EXIST FOR THE REPO",
                    "data": None,
                }

            bucket_object = await BucketStorage.get_signed_url(
                supabase_client=self._client,
                repo_id=repo_id,
                file_id=file_id,
                url=file_path,
                file_type=BucketFileType.spread_sheat,
                bucket_name=env_config.SPREADSHEAT_BUCKET_NAME or "",
                bucket_type=BucketType.private,
            )

            if bucket_object:
                filtered_data = []
                file_suffix = Path(bucket_object.get("bucket_key") or "").suffix

                if file_suffix:
                    if file_suffix in supported_spread_sheat_suffix:
                        temp_path = await self._download_spreadsheat(
                            signed_url=(bucket_object.get("url") or "")
                        )

                        if isinstance(temp_path, str):
                            filtered_data = await asyncio.to_thread(
                                self.process_spreadsheat,
                                temp_path=temp_path,
                                conditions=conditions,
                                combine=combine,
                            )
                    elif file_suffix in [".csv", ".tsv"]:
                        filtered_data = await asyncio.to_thread(
                            self.process_csv_file,
                            signed_url=(bucket_object.get("url") or ""),
                            conditions=conditions,
                            combine=combine,
                        )
                    else:
                        raise ValidationError("UNSUPPORTED, FILE TYPE RECEIVED")

                    return {
                        "status": "success",
                        "message": "DATA FILTERED",
                        "data": filtered_data,
                    }
            else:
                raise NotFoundError(
                    "OPERATION FAILED, UNABLE TO LOCATE THE FILE IN THE OBJECT STORE, PROBLEM IN PARAMETER"
                )

        except (
            NotFoundError,
            ValidationError,
            ServerError,
            NetworkError,
            ValueError,
        ) as e:
            return {
                "status": "error",
                "message": str(e),
                "data": None,
            }

        except Exception:
            logger.exception("[PROCESS-FILE] UNABLE TO GET THE FILE SIGNED URL")
            return {
                "status": "error",
                "message": (
                    "OPERATION FAILED, UNABLE TO CONNECT TO THE OBJECT STORE, "
                    "SERVER ERROR"
                ),
                "data": None,
            }
