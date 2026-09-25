from app.models.embedding import Embedding
from app.models.repo_file import RepoFile
from sqlalchemy.future import select
from sqlalchemy import func, Select
from app.core.db import AsyncSessionLocal
from app.core.config import env_config
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)


class Retrival:
    def __init__(self) -> None:
        pass

    def _merge_results_rrf_multi(
        self, result_lists: list, k: int = 60, id_key: str = "embed_id"
    ) -> list[dict]:
        rrf_scores = {}
        doc_map = {}

        for record_list in result_lists:
            for rank, record in enumerate(record_list, start=1):
                doc_id = record[id_key]
                if doc_id not in doc_map:
                    doc_map[doc_id] = record

                rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank))

        sorted_docs = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

        final_records = []
        for doc_id, score in sorted_docs:
            # Convert SQLAlchemy RowMapping / Row to a plain python dict
            rec = dict(doc_map[doc_id])
            rec["rrf_score"] = score
            final_records.append(rec)

        return final_records

    async def _call_db(self, stmt: Select, query_for: str):
        try:
            async with AsyncSessionLocal() as db:
                response = await db.execute(stmt)
                result = response.mappings().all()

                return result
        except Exception as e:
            logger.exception(
                "[RETRIVAL-DB-CALL] FAILED TO FETCH THE CHUNKS FROM THE %s QUERY, ERROR %s",
                query_for,
                e,
            )
            raise

    async def _retrive_by_vector_distance(self, embeded_query: list[float]):
        distance = Embedding.vector.cosine_distance(embeded_query).label("distance")
        stmt = (
            select(
                Embedding.embed_id,
                Embedding.file_id,
                RepoFile.file_path,
                Embedding.chunk,
                Embedding.chunk_str,
                distance,
            )
            .join(RepoFile, RepoFile.file_id == Embedding.file_id)
            .order_by(distance)
            .limit(20)
        )

        try:
            result = await self._call_db(stmt, "vector_distance")
            return result
        except Exception as e:
            logger.exception(
                "[RETRIVAL-VECTOR-DISTANCE] FAILED TO FETCH THE CHUNKS FROM THE VECTOR DISTANCE QUERY, ERROR %s",
                e,
            )
            raise

    async def _retrive_by_trigram_similarity(self, query: str):
        lexical_score = func.similarity(Embedding.chunk_str, query).label("similarity")
        stmt = (
            select(
                Embedding.embed_id,
                Embedding.file_id,
                RepoFile.file_path,
                Embedding.chunk,
                Embedding.chunk_str,
                lexical_score,
            )
            .join(RepoFile, RepoFile.file_id == Embedding.file_id)
            .where(
                func.similarity(Embedding.chunk_str, query) > 0.05
            )  # Filter out completely irrelevant text
            .order_by(lexical_score.desc())
            .limit(20)
        )

        try:
            result = await self._call_db(stmt, "lexical_or_trigram_similarity")
            return result
        except Exception as e:
            logger.exception(
                "[RETRIVAL-TRIGRAM-SIMILARITY] FAILED TO FETCH THE CHUNKS FROM THE TRIGRAM SIMILARITY QUERY, ERROR %s",
                e,
            )
            raise

    async def _retrive_by_fts(self, query: str):
        ts_query = func.plainto_tsquery("english", query)
        fts_score = func.ts_rank(
            func.to_tsvector("english", Embedding.chunk_str), ts_query
        ).label("fts_score")

        stmt = (
            select(
                Embedding.embed_id,
                Embedding.file_id,
                RepoFile.file_path,
                Embedding.chunk,
                Embedding.chunk_str,
                fts_score,
            )
            .join(RepoFile, RepoFile.file_id == Embedding.file_id)
            # Perform FTS match: to_tsvector(chunk_str) @@ plainto_tsquery(query)
            .where(func.to_tsvector("english", Embedding.chunk_str).op("@@")(ts_query))
            .order_by(fts_score.desc())
            .limit(20)
        )

        try:
            result = await self._call_db(stmt, "full_text_search")
            return result
        except Exception as e:
            logger.exception(
                "[RETRIVAL-TRIGRAM-SIMILARITY] FAILED TO FETCH THE CHUNKS FROM THE TRIGRAM SIMILARITY QUERY, ERROR %s",
                e,
            )
            raise

    def _rewrite_query(self, query: str):
        groq_connector = OpenAI(
            api_key=env_config.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )

        new_query = groq_connector.chat.completions.create(
            model="qwen/qwen3.8-27b",
            messages=[
                {
                    "role": "system",
                    "content": "You are a profesional prompt writer, who is specialized in writing prompt for the RAG system and you need to rewrite the prompt given to you. The prompt is supposed to do retrival from a database, your role is to rewrite the prompt in a way that the retrival becomes way better then what it is now, the user will give a prompt you will enhance it and even use some other word terminolgies so that the correct retrival can be done, just return the prompt and nothing else should be returned by you. Rembember just a good prompt, nothing else. Maintain the user's original intent but vastly improve clarity and depth.",
                },
                {"role": "user", "content": query},
            ],
        )
        new_prompt = new_query.choices[0].message.content
        return new_prompt

    async def retrive(self, query: str, embeded_query: list[float]):
        try:
            vector_chunks = await self._retrive_by_vector_distance(
                embeded_query=embeded_query
            )
            lexical_chunks = await self._retrive_by_trigram_similarity(query=query)
            fts_chunks = await self._retrive_by_fts(query=query)

            top_chunks = self._merge_results_rrf_multi(
                result_lists=[vector_chunks, lexical_chunks, fts_chunks],
                k=60,
                id_key="embed_id",
            )

            return top_chunks

        except Exception as e:
            logger.exception(
                "[RETRIVAL-ERROR] FAILED TO FETCH THE CHUNKS FROM THE RETRIVAL QUERY, ERROR %s",
                e,
            )
            raise
