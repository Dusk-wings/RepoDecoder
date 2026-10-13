from app.core.db import AsyncSessionLocal
from app.models.embedding import Embedding
from app.rag.embedder.embedder import Embedder

from sqlalchemy.future import select
from sqlalchemy import update
from sqlalchemy.exc import SQLAlchemyError

import logging
import asyncio

logger = logging.getLogger(__name__)
embedder = Embedder(model_name="BAAI/bge-base-en-v1.5")


async def get_chunks():
    stmt = select(Embedding.embed_id, Embedding.chunk_str)

    try:
        async with AsyncSessionLocal() as db:
            result = await db.stream(stmt)
            async for batch in result.mappings().partitions(25):
                yield [dict(row) for row in batch]

    except SQLAlchemyError as e:
        logger.exception("[UPDATE-CHUNK-GET] UNABLE TO FETCH THE CHUNKS")
        raise
    except Exception:
        logger.exception("[UPDATE-CHUNK-GET] UNKNOWN ERROR")
        raise


async def update_embedding_db(rows: list[dict]):
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(update(Embedding), rows)
            await db.commit()
        except SQLAlchemyError as e:
            await db.rollback()
            logger.exception("[UPDATE-CHUNK] UNABLE TO UPDATE THE CHUNKS, %s", e)
            raise


async def update_embedding():
    try:
        async for batch in get_chunks():
            embedding_result = await asyncio.to_thread(
                lambda: embedder.generate_embeddings(content=batch)
            )

            if len(embedding_result) != len(batch):
                raise ValueError(
                    f"Embedder returned {len(embedding_result)} results "
                    f"for a batch of {len(batch)} chunks"
                )

            expected_ids = {item["embed_id"] for item in batch}
            rows: list[dict] = []

            for item in embedding_result:
                embed_id = item["embed_id"]
                vector = item["vector"]

                if embed_id not in expected_ids:
                    raise ValueError(
                        f"Embedder returned unexpected embed_id: {embed_id}"
                    )

                rows.append({"embed_id": embed_id, "vector": vector})

            await update_embedding_db(rows)
    except (KeyError, TypeError, ValueError) as e:
        logger.exception("[UPDATE-CHUNK] UNABLE TO GENERATE THE CHUNKS, %s", e)
    except SQLAlchemyError as e:
        logger.exception("[UPDATE-CHUNK] UNABLE TO GET THE CHUNKS, %s", e)
    except Exception as e:
        logger.exception("[UPDATE-CHUNK] UNKNOWN ERROR, %s", e)

asyncio.run(update_embedding())