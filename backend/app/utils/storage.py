from pathlib import Path
import magic
import mimetypes
from tusclient import client
from tusclient.exceptions import TusCommunicationError
import logging
import time
import uuid

from app.core.config import env_config
from app.core.db import AsyncSessionLocal
from app.models.bucket_file import BucketFile, BucketFileType

from sqlalchemy.dialects.postgresql import insert

logger = logging.getLogger(__name__)

GENERIC_TYPES = {"application/octet-stream", "text/plain", "application/x-empty"}


class BucketStorage:

    @staticmethod
    def store_file(
        bucket_name: str,
        object_name: str,
        file_path: Path | None = None,
        max_retries: int = 5,
        base_backoff: float = 2.0,
        public_bucket: bool = False,
    ):
        "Given the file path, stores the file to the SupaBase Object Store"

        if file_path:
            try:
                mime_type = magic.from_file(filename=file_path, mime=True)
            except Exception as e:
                logger.warning(
                    "[BUCKET-STORAGE] MAGIC FAILED TO GET THE MIME-TYPE OF THE FILE GETTING THE DEFAULT"
                )
                mime_type = None

            if not mime_type or mime_type in GENERIC_TYPES:
                guessed_type, _ = mimetypes.guess_type(file_path)
                if guessed_type:
                    mime_type = guessed_type

            if not mime_type:
                mime_type = "application/octet-stream"

            tus_endpoint = f"https://{env_config.SUPABASE_PROJECT_ID}.storage.supabase.co/storage/v1/upload/resumable"

            tus_client = client.TusClient(
                url=tus_endpoint,
                headers={
                    "Authorization": f"Bearer {env_config.SUPABASE_SECRET_KEY}",
                    "x-upsert": "true",
                },
            )

            uploader = tus_client.uploader(
                file_path=file_path,
                chunk_size=6 * 1024 * 1024,
                metadata={
                    "bucketName": bucket_name,
                    "objectName": object_name,
                    "contentType": mime_type,
                },
            )

            while uploader.offset < uploader.get_file_size():
                retry_count = 0
                chunk_uploaded = False

                while not chunk_uploaded:
                    try:
                        uploader.upload_chunk()
                        chunk_uploaded = True

                        progress = (uploader.offset / uploader.get_file_size()) * 100
                        logger.info(
                            f"[BUCKET-STORAGE] UPLOADED CHUNK: {uploader.offset}/{uploader.get_file_size()} BYTES ({progress:.2f}%)"
                        )

                    except (TusCommunicationError, Exception) as err:
                        retry_count += 1
                        if retry_count > max_retries:
                            logger.exception(
                                f"[BUCKET-STORAGE] MAX RETRIES ({max_retries}) REACHED. UPLOAD FAILED."
                            )
                            raise err

                        sleep_time = base_backoff**retry_count
                        logger.info(
                            f"[BUCKET-STORAGE] CHUNK UPLOAD ERROR: {err}. RETRYING IN {sleep_time}s... (ATTEMPT {retry_count}/{max_retries})"
                        )
                        time.sleep(sleep_time)

            if public_bucket:
                return f"https://{env_config.SUPABASE_PROJECT_ID}.supabase.co/storage/v1/object/public/{bucket_name}/{object_name}"

            else:
                return None

        else:
            raise ValueError(
                "[BUCKET-STORAGE] FILE PATH NEEDED TO BE DEFINED FOR THE UPLOAD"
            )

    @staticmethod
    async def update_file_upload_status(
        file_id: uuid.UUID,
        repo_id: uuid.UUID,
        url: str,
        storage_key: str,
        file_type: BucketFileType,
    ):
        logger.info("[BUCKET-FILE-UPDATE] STARTING THE FILE SAVE OPERATION")
        async with AsyncSessionLocal() as db:
            try:
                stmt = insert(BucketFile).values(
                    repo_id=repo_id,
                    file_id=file_id,
                    url=url,
                    bucket_key=storage_key,
                    file_type=file_type,
                )

                stmt = stmt.on_conflict_do_update(
                    constraint="repo_file_url_unique",
                    set_={"bucket_key": stmt.excluded.bucket_name},
                )

                await db.execute(stmt)
                await db.commit()
                logger.info("[BUCKET-FILE-UPDATE] FILE SAVED TO THE DB")
            except Exception as e:
                logger.exception(
                    "[BUCKET-FILE-UPDATE] FAILED TO SAVE THE DETAILS OF THE UPDATE TO THE DB %s",
                    e,
                )

                await db.rollback()
                raise
