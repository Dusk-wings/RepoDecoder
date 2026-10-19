from sqlalchemy.future import select
from sqlalchemy import func, Select

import logging
from uuid import UUID
import json
from textwrap import dedent

from app.core.config import env_config
from app.core.db import AsyncSessionLocal

from app.models.repo_file import RepoFile
from app.models.embedding import Embedding

from app.rag.generator.generator import Generator

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

    async def _retrive_by_vector_distance(
        self, embeded_query, repo_id: UUID, limit: int = 20
    ):
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
            .where(Embedding.repo_id == repo_id)
            .order_by(distance)
            .limit(limit)
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

    async def _retrive_by_trigram_similarity(
        self, query: str, repo_id: UUID, limit: int = 20
    ):
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
                func.similarity(Embedding.chunk_str, query) > 0.05,
                Embedding.repo_id == repo_id,
            )  # Filter out completely irrelevant text
            .order_by(lexical_score.desc())
            .limit(limit)
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

    async def _retrive_by_fts(self, query: str, repo_id: UUID, limit: int = 20):
        ts_query = func.plainto_tsquery("english", query)
        fts_score = func.ts_rank(Embedding.fts_vector, ts_query).label("fts_score")

        stmt = (
            select(
                Embedding.embed_id,
                Embedding.file_id,
                # RepoFile.file_path,
                Embedding.chunk,
                Embedding.chunk_str,
                fts_score,
            )
            # .join(RepoFile, RepoFile.file_id == Embedding.file_id)
            # Perform FTS match: to_tsvector(chunk_str) @@ plainto_tsquery(query)
            .where(
                Embedding.fts_vector.op("@@")(ts_query),
                # Embedding.repo_id == repo_id,
            )
            .order_by(fts_score.desc())
            .limit(limit)
        )
        print(stmt)

        try:
            result = await self._call_db(stmt, "full_text_search")
            return result
        except Exception as e:
            logger.exception(
                "[RETRIVAL-TRIGRAM-SIMILARITY] FAILED TO FETCH THE CHUNKS FROM THE TRIGRAM SIMILARITY QUERY, ERROR %s",
                e,
            )
            raise

    async def _rewrite_query(
        self,
        query: str,
        history: list[dict] | None = None,
        model: str = "groq/qwen/qwen3.8-27b",
        api_key: str | None = None,
        base_url: str | None = None,
    ):

        generator = Generator()
        supported_models = generator.list_models()

        if model not in supported_models:
            raise ValueError(
                f"MODEL '{model}' IS NOT SUPPORTED. SUPPORTED MODELS: {supported_models}"
            )

        if history is not None:
            system_prompt = dedent(f"""\
                You are a query contextualization component for a code-focused conversational RAG system.
                Your task is to convert the latest user message into astandalone query suitable for retrieving relevant source-code chunks.
                Instructions:
                1. Identify what information the latest user message requests.
                2. Use conversation history only to resolve references, omitted entities, identifiers, and necessary context.
                3. Preserve technical identifiers exactly.
                4. Preserve intent. Do not answer the question.
                5. Do not assume all earlier details remain relevant.
                6. Add synonyms only when they preserve meaning and improve retrieval.
                7. Do not invent identifiers or implementation details.
                8. Prefer concise, specific queries.
                9. If the latest message is self-contained, keep it substantially unchanged.
                10. If it starts a new topic, do not force old context into it.
                Return only the standalone retrieval query.
                Do not include explanations or commentary.
                """).strip()

            try:
                user_message = dedent(f"""\
                    <conversation_history>
                    {json.dumps(history, default=str)}
                    </conversation_history>
                    
                    <latest_user_message>
                    {query}
                    </latest_user_message>
                    """).strip()
            except:
                user_message = dedent(f"""\
                    <conversation_history>
                    {json.dumps(history, default=str)}
                    </conversation_history>

                    <latest_user_message>
                    {query}
                    </latest_user_message>
                    """).strip()

        else:
            system_prompt = dedent(f"""\
                You are a query optimizer for a code-focused Retrieval-Augmented Generation (RAG) system.
                Rewrite the user's query to improve retrieval of relevant source-code chunks.
                Rules:
                - Preserve the original intent and all explicitly mentioned identifiers, function names, event names, variable names, and technologies.
                - Keep distinctive terms and phrases from the original query.
                - Clarify ambiguous references only when the clarification is supported by the original query.
                - Add technical synonyms only when they express the same concept and are likely to improve retrieval.
                - Do not invent function names, implementation details, relationships, or requirements.
                - Do not turn a narrow question into a broad search query.
                - Prefer concise, information-dense queries over longer queries.
                - Do not answer the user's question.
                Return only the rewritten query, without explanations or commentary. If the original query is already clear and specific, return it unchanged. The rewritten query should be under 400 tokens.
                """).strip()

            user_message = query

        messages = [
            {
                "role": "system",
                "content": system_prompt,
            },
            {"role": "user", "content": user_message},
        ]

        new_prompt = await generator.LLM(
            model=model,
            messages=messages,
            max_tokens=400,
            api_key=api_key,
            base_url=base_url,
        )
        return new_prompt

    async def retrive(
        self, query: str, embedded_query, repo_id: UUID, top_chunk: int = 20
    ):
        try:
            searcher = list(embedded_query)[0].tolist()

            vector_chunks = await self._retrive_by_vector_distance(
                embeded_query=searcher, repo_id=repo_id, limit=top_chunk
            )
            lexical_chunks = await self._retrive_by_trigram_similarity(
                query=query, repo_id=repo_id, limit=top_chunk
            )
            # fts_chunks = await self._retrive_by_fts(query=query, repo_id=repo_id, limit=top_chunk)

            top_chunks = self._merge_results_rrf_multi(
                result_lists=[vector_chunks, lexical_chunks],
                k=60,
                id_key="embed_id",
            )

            return top_chunks[:top_chunk]

        except Exception as e:
            logger.exception(
                "[RETRIVAL-ERROR] FAILED TO FETCH THE CHUNKS FROM THE RETRIVAL QUERY, ERROR %s",
                e,
            )
            raise
