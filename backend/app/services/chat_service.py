import asyncio
import json
import logging
from collections.abc import Iterable, Mapping
from typing import Any, AsyncGenerator
from uuid import UUID

from sqlalchemy.future import select
from sqlalchemy import insert, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from supabase import AsyncClient

from app.rag.generator.generator import Generator
from app.rag.retrival.retrival import Retrival
from app.rag.embedder.embedder import Embedder

from app.models.chat_soruces import ChatSources
from app.models.conversation import Conversation
from app.models.bucket_file import BucketFileType, BucketType
from app.models.chats import Chats
from app.models.user_repo import UserRepo

from app.utils.storage import BucketStorage
from app.core.config import env_config

from app.errors.generation_error import GenerationError
from app.errors.server_error import ServerError
from app.errors.validation_error import ValidationError

logger = logging.getLogger(__name__)


class Chat:
    def __init__(
        self,
        db: AsyncSession,
        bucket_client: AsyncClient,
        embedder: Embedder,
        retriver: Retrival,
        generator: Generator,
    ) -> None:
        self.bucket_client = bucket_client
        self.db = db
        self.embedder = embedder
        self.retriver = retriver
        self.generator = generator

    async def save_chat_to_db(
        self, query: str, response: str, model: str, chat_id: UUID
    ) -> UUID:

        stmt = (
            insert(Conversation)
            .values(
                chat_id=chat_id,
                query=query,
                response=response,
                models=model,
            )
            .returning(Conversation.conversation_id)
        )

        try:
            conversation_id = await self.db.scalar(stmt)
            if conversation_id is None:
                raise ServerError("FAILED TO SAVE THE CONVERSATION")
            return conversation_id
        except SQLAlchemyError:
            await self.db.rollback()
            raise

    async def validate_operation(self, user_id: UUID, conversation_id: UUID) -> bool:
        try:
            chat_id = await self.db.scalar(
                select(Conversation.chat_id).where(
                    Conversation.conversation_id == conversation_id
                )
            )

            user_repo_id = await self.db.scalar(
                select(Chats.user_repo_id).where(Chats.chat_id == chat_id)
            )

            check = await self.db.scalar(
                select(1).where(
                    UserRepo.user_id == user_id, UserRepo.user_repo_id == user_repo_id
                )
            )

            if check:
                return True
            else:
                return False

        except Exception as e:
            logger.exception("UNABLE TO VALIDATE THE USER, ERROR %s", e)
            raise ServerError(message="INTERNAL SERVER ERROR")

    async def get_autherization_stmt(self, user_id: UUID, conversation_id: UUID):
        try:
            chat_id = await self.db.scalar(
                select(Conversation.chat_id).where(
                    Conversation.conversation_id == conversation_id
                )
            )
        except SQLAlchemyError:
            logger.exception("UNABLE TO GET THE CHAT_ID FOR THE CONVERATION")

        if not chat_id:
            raise ValidationError(message="CHAT DOES NOT EXIST", status=404)

        return (
            select(1)
            .select_from(Chats)
            .join(UserRepo, UserRepo.user_repo_id == Chats.user_repo_id)
            .where(
                Chats.chat_id == chat_id,
                UserRepo.user_id == user_id,
            )
            .exists()
        )

    async def update_chat(
        self,
        user_id: UUID,
        conversation_id: UUID,
        response: str,
        tool: list[dict] | None = None,
        error_info: dict | None = None,
    ) -> None:

        try:
            autherization = await self.get_autherization_stmt(user_id, conversation_id)

            stmt = (
                update(Conversation)
                .where(Conversation.conversation_id == conversation_id, autherization)
                .values(response=response, tool=tool, error=error_info)
                .returning(Conversation.conversation_id)
            )

            result = await self.db.execute(stmt)
            updated_con_id = result.scalar_one_or_none()

            if updated_con_id is None:
                raise ValidationError(
                    message="PERMESSION DENIED, FAILED TO UPDATE THE MESSAGE",
                    status=403,
                )

            await self.db.commit()

        except SQLAlchemyError:
            await self.db.rollback()
            raise

    async def delete_chat(self, user_id: UUID, conversation_id: UUID, is_deleted: bool):
        try:
            autherization = await self.get_autherization_stmt(
                user_id=user_id, conversation_id=conversation_id
            )
            stmt = (
                update(Conversation)
                .where(Conversation.conversation_id == conversation_id, autherization)
                .values(is_deleted=is_deleted)
                .returning(Conversation.conversation_id)
            )

            result = await self.db.execute(stmt)
            conv_id = result.scalar_one_or_none()
            if not conv_id:
                raise ValidationError(message="MESSAGE IS NOT DELETED", status=403)
            await self.db.commit()

        except SQLAlchemyError:
            await self.db.rollback()
            raise

    async def save_source_to_db(
        self,
        retrieved_content: Iterable[Mapping[str, Any]],
        user_id: UUID,
        conversation_id: UUID,
    ) -> None:

        source_detail = []

        for item in retrieved_content:
            try:
                embed_id = UUID(str(item["embed_id"]))
            except (KeyError, ValueError):
                print(f"Skipping item: invalid or missing embed_id in {item!r}")
                continue

            try:
                file_id = UUID(str(item["file_id"]))
            except (KeyError, ValueError):
                file_id = None

            source_detail.append(
                {
                    "embed_id": embed_id,
                    "file_id": file_id,
                }
            )

        if not source_detail:
            return

        try:
            is_validated = await self.validate_operation(
                user_id=user_id, conversation_id=conversation_id
            )
            if is_validated:
                try:
                    self.db.add_all(
                        [
                            ChatSources(
                                embed_id=item.get("embed_id"),
                                file_id=item.get("file_id"),
                                conversation_id=conversation_id,
                            )
                            for item in source_detail
                        ]
                    )
                    await self.db.commit()
                except SQLAlchemyError:
                    await self.db.rollback()
                    raise
            else:
                raise ValidationError(
                    message="SOURCES AREN'T SAVED, VALIDATION ERROR", status=403
                )

        except ServerError:
            raise

        except Exception as e:
            logger.exception("UNEXPECTED EXCEPTION, ERROR %s", e)
            raise ServerError(message="INTERNAL SERVER ERROR")

    async def fetch_chat_history(
        self, user_id: UUID, conversation_id: UUID, chat_id: UUID, limit: int = 3
    ) -> list[dict[str, str]]:
        try:
            authenticate = await self.get_autherization_stmt(
                user_id=user_id, conversation_id=conversation_id
            )

            result = await self.db.scalars(
                select(Conversation)
                .where(Conversation.chat_id == chat_id, authenticate)
                .order_by(Conversation.created_at.desc())
                .limit(limit)
            )

            conversations = list(reversed(result.all()))
            history: list[dict[str, str]] = []

            for conversation in conversations:
                history.extend(
                    [
                        {"role": "user", "content": conversation.query},
                        {"role": "assistant", "content": conversation.response},
                    ]
                )
            return history
        except SQLAlchemyError:
            raise

    async def context_formatter(
        self, context: Iterable[Mapping[str, Any]], repo_id: UUID
    ) -> str:
        bucket_name = env_config.IMAGE_BUCKET_NAME
        formatted_sources: list[str] = []
        signed_url_cache: dict[tuple[UUID, str], str] = {}

        for item in context:
            if not isinstance(item, Mapping):
                logger.warning("[CHAT-CONTEXT-FORMATTER] SKIPPING NON-MAPPING RESULT")
                continue

            raw_chunk = item.get("chunk")
            chunk = dict(raw_chunk) if isinstance(raw_chunk, Mapping) else raw_chunk
            if not chunk:
                chunk = item.get("chunk_str")
            if not chunk:
                continue

            if isinstance(chunk, dict):
                metadata = chunk.get("metadata")
                image = metadata.get("image") if isinstance(metadata, Mapping) else None
                if (
                    isinstance(metadata, Mapping)
                    and metadata.get("is_image") is True
                    and isinstance(image, Mapping)
                ):
                    raw_file_id = item.get("file_id")
                    raw_urls = image.get("image_urls")
                    image_urls = (
                        raw_urls if isinstance(raw_urls, (list, tuple)) else [raw_urls]
                    )
                    actual_image_urls: list[str] = []

                    try:
                        file_id = UUID(str(raw_file_id))
                    except (TypeError, ValueError, AttributeError):
                        file_id = None

                    for image_url in image_urls:
                        if not isinstance(image_url, str) or not image_url.strip():
                            continue
                        if not bucket_name or file_id is None:
                            actual_image_urls.append(image_url)
                            continue

                        cache_key = (file_id, image_url)
                        if cache_key not in signed_url_cache:
                            try:
                                signed_url = await BucketStorage.get_signed_url(
                                    supabase_client=self.bucket_client,
                                    bucket_name=bucket_name,
                                    repo_id=repo_id,
                                    file_id=file_id,
                                    file_type=BucketFileType.image,
                                    bucket_type=BucketType.public,
                                    url=image_url,
                                )
                                resolved_url = signed_url.get("url")
                                if isinstance(resolved_url, str) and resolved_url:
                                    signed_url_cache[cache_key] = resolved_url
                                else:
                                    signed_url_cache[cache_key] = image_url
                                    logger.warning(
                                        "[CHAT-CONTEXT-FORMATTER] IMAGE SIGNING RETURNED NO URL"
                                    )
                            except Exception:
                                signed_url_cache[cache_key] = image_url
                                logger.warning(
                                    "[CHAT-CONTEXT-FORMATTER] UNABLE TO SIGN IMAGE URL",
                                    exc_info=True,
                                )

                        actual_image_urls.append(
                            signed_url_cache.get(cache_key, image_url)
                        )

                    if actual_image_urls:
                        chunk["actual_image_urls"] = actual_image_urls

                content = json.dumps(chunk, ensure_ascii=False, default=str)
            elif isinstance(chunk, str):
                content = chunk.strip()
            else:
                content = json.dumps(chunk, ensure_ascii=False, default=str)

            if not content:
                continue

            formatted_sources.append(f"{content}")

        return "\n\n".join(formatted_sources)

    def _clean_text(self, value: str) -> str:
        return value.replace("\x00", "")

    def _set_top_chunks(self, provider: str) -> int:
        top_chunk = 30

        if provider == "groq":
            top_chunk = 8
        elif provider == "google":
            top_chunk = 20

        return top_chunk

    async def retrieve_relevant_context(
        self,
        query: str,
        repo_id: UUID,
        rewriting_model: str = "groq/qwen/qwen3.8-27b",
        top_chunks: int = 8,
        history: list[dict] | None = None,
    ) -> list:
        retry_count = 0

        while retry_count < 3:
            retry_count += 1

            try:
                rewriten_query = await self.retriver._rewrite_query(
                    query=query, history=history, model=rewriting_model
                )

                ai_res_type = rewriten_query["type"]
                content = rewriten_query.get("content", None)

                if ai_res_type == "error":
                    status_code = rewriten_query["status_code"]
                    if status_code == 413 and history:
                        logger.warning("[CHAT-RETRIVAL] REDUCIGN THE HISTORY SIZE")
                        history = history[retry_count:]
                        continue
                    else:
                        logger.exception(
                            "[CHAT-RETRIVAL] UNABLE TO REWRITE THE QUERY, STATUS_CODE %s, ERROR %s",
                            status_code,
                            rewriten_query["status"],
                        )

                if content is not None:
                    embeded_query = self.embedder.embed(content)
                    for retrying in range(4):
                        try:
                            content = self._clean_text(content)
                            retrived_chunks = await self.retriver.retrive(
                                content,
                                embeded_query,
                                repo_id=repo_id,
                                top_chunk=top_chunks,
                            )
                            if not retrived_chunks:
                                logger.warning(
                                    "[CHAT-RETRIVAL] NO CHUNKS RETRIVED, RETRYING %s",
                                    retrying,
                                )
                                continue
                            return retrived_chunks
                        except Exception as e:
                            logger.exception(
                                "[CHAT-RETRIVAL] ERROR WHILE RETRIVING CHUNKS, %s", e
                            )
                    return []
            except Exception as e:
                logger.exception("[CHAT-RETRIVAL] ERROR WHILE PROCESSING QUERY, %s", e)

        return []

    async def generate_response(
        self,
        model: str,
        repo_id: UUID,
        conversation_id: UUID,
        retrieved_content: Iterable[Mapping[str, Any]],
        messages: list[dict],
        stop_event: asyncio.Event,
        complete_response: list,
        tools: list,
    ):
        async for event in self.generator.LLM_generator(
            model=model,
            bucket_client=self.bucket_client,
            repo_id=repo_id,
            messages=messages,
            stop_event=stop_event,
        ):
            if stop_event.is_set():
                break

            event_type = event.get("type")
            if event_type == "token":
                content = event.get("content")
                if isinstance(content, str):
                    complete_response.append(content)

            elif event_type == "tool_call":
                tool_name = event.get("name")
                tool_input = event.get("argument")
                if isinstance(tool_name, str) and isinstance(tool_input, str):
                    tools.append({"tool_name": tool_name, "tool_input": tool_input})

            elif event_type == "end":
                break

            elif event_type == "error":
                raise GenerationError(
                    status_code=event["status_code"], message=event["content"]
                )

            yield event

    async def chat(
        self,
        query: str,
        model: str,
        repo_id: UUID,
        chat_id: UUID,
        user_id: UUID,
        stop_event: asyncio.Event,
        top_chunk: int | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        conversation_id = await self.save_chat_to_db(
            query=query, response="", model=model, chat_id=chat_id
        )
        complete_response: list[str] = []
        tools: list[dict[str, str]] = []
        retrieved_content: list[Mapping[str, Any]] = []
        error_info: dict[str, Any] | None = None

        try:
            history = await self.fetch_chat_history(
                chat_id=chat_id, conversation_id=conversation_id, user_id=user_id
            )

            gen_model_provider = model.split("/", 1)[0]

            if top_chunk is None or top_chunk < 3:
                top_chunk = self._set_top_chunks(gen_model_provider)

            retrieved_content = await self.retrieve_relevant_context(
                query=query,
                repo_id=repo_id,
                history=history,
                top_chunks=top_chunk,
            )

            context = await self.context_formatter(retrieved_content, repo_id)

            messages = self.generator.generate_chat_content(
                user_message=query, retrived_content=context, history=history
            )

            try:
                retry_count = 0
                least_chunks = 4
                while retry_count < 3:
                    try:
                        async for event in self.generate_response(
                            model=model,
                            repo_id=repo_id,
                            conversation_id=conversation_id,
                            retrieved_content=retrieved_content,
                            messages=messages,
                            stop_event=stop_event,
                            complete_response=complete_response,
                            tools=tools,
                        ):
                            yield event
                        await self.save_source_to_db(
                            retrieved_content=retrieved_content,
                            user_id=user_id,
                            conversation_id=conversation_id,
                        )
                        break

                    except GenerationError as err:
                        if (
                            err.status_code == 413
                            and top_chunk > least_chunks
                            and retry_count < 2
                        ):
                            retry_count += 1
                            top_chunk -= 1
                            logger.warning(
                                "[CHAT]: REQUEST SIZE IS BIG FOR THE MODEL %s, REDUCING CHUNK SIZE, CURRENT `top_chunk` %s, RETRYING....",
                                model,
                                top_chunk,
                            )
                            retrieved_content = retrieved_content[:top_chunk]
                            context = await self.context_formatter(
                                retrieved_content, repo_id
                            )
                            messages = self.generator.generate_chat_content(
                                user_message=query,
                                retrived_content=context,
                                history=history,
                            )
                            complete_response.clear()
                            tools.clear()
                            continue

                        error_info = {
                            "type": "generation_error",
                            "status_code": err.status_code,
                            "message": err.message,
                        }
                        raise RuntimeError(
                            f"Generation failed for query {query!r}: {err.message} "
                            f"(status_code={err.status_code})"
                        ) from err

            except asyncio.CancelledError:
                raise
            
        except Exception as exc:
            if error_info is None:
                error_info = {"type": type(exc).__name__, "message": str(exc)}
            try:
                await self.update_chat(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    response="".join(complete_response),
                    tool=tools or None,
                    error_info=error_info,
                )
            except Exception:
                logger.exception(
                    "[CHAT] FAILED TO SAVE GENERATION ERROR FOR CONVERSATION %s",
                    conversation_id,
                )
            raise
        else:
            await self.update_chat(
                user_id=user_id,
                conversation_id=conversation_id,
                response="".join(complete_response),
                tool=tools or None,
                error_info=None,
            )
