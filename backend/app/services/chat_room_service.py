from uuid import UUID
from typing import NoReturn
from datetime import datetime, timezone
import logging

from random import random

from sqlalchemy.future import select
from sqlalchemy import insert, delete, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chats import Chats
from app.models.user_repo import UserRepo
from app.models.conversation import Conversation
from app.rag.generator.generator import Generator

from app.errors.not_found_error import NotFoundError
from app.errors.http_error import HTTPError
from app.errors.validation_error import ValidationError

logger = logging.getLogger(__name__)


class ChatRoom:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def load_all_chat_room_repo(self, user_id: UUID, repo_id: UUID):
        try:
            result = await self.db.scalars(
                select(Chats)
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(UserRepo.user_id == user_id, UserRepo.repo_id == repo_id)
                .order_by(Chats.updated_at.desc())
            )
            return result.all()
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def load_all_chat_room(self, user_id: UUID):
        try:
            result = await self.db.scalars(
                select(Chats)
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(UserRepo.user_id == user_id)
                .order_by(Chats.updated_at.desc())
            )

            return result.all()
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def load_conversation(self, user_id: UUID, chat_id: UUID):
        try:
            await self._get_owned_room(user_id, chat_id)

            conversation = await self.db.scalars(
                select(Conversation).where(Conversation.chat_id == chat_id)
            )

            return conversation.all()

        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def delete_chat_room(self, user_id: UUID, chat_id: UUID):
        try:
            verefied_chat_id = await self._get_owned_room(user_id, chat_id)
            stmt = delete(Chats).where(Chats.chat_id == verefied_chat_id)
            await self.db.execute(stmt)
            await self.db.commit()
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def rename_chat_room(
        self, user_id: UUID, chat_id: UUID, name: str, is_named_by_user: bool = False
    ):
        try:
            verefied_chat_id = await self._get_owned_room(user_id, chat_id)

            new_name = name.strip()[:150]
            if not new_name:
                raise ValidationError(
                    "CHAT NAME CAN NOT BE EMPTY OR WHITESPACE ONLY",
                )

            stmt = (
                update(Chats)
                .where(Chats.chat_id == verefied_chat_id)
                .values(chat_name=new_name, named_by_user=is_named_by_user)
                .returning(Chats.chat_id, Chats.chat_name, Chats.updated_at)
            )
            result = await self.db.execute(stmt)
            chat = result.mappings().one_or_none()

            if not chat:
                raise NotFoundError(
                    "CHAT NOT FOUND, NAME OF THE CHAT IS NOT MODIFIED",
                )

            await self.db.commit()

            return chat
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def create_chat_room(self, user_id: UUID, repo_id: UUID, first_msg: str):
        try:
            user_repo = await self.db.scalar(
                select(UserRepo).where(
                    UserRepo.user_id == user_id,
                    UserRepo.repo_id == repo_id,
                )
            )
            if user_repo is None:
                raise NotFoundError("REPOSITORY IS NOT ASSOCIATED WITH USER")

            name = first_msg.strip()[:150]
            if not name:
                name = f"Chat-{datetime.now(timezone.utc)}-{int(random() * 1000000)}"

            stmt = (
                insert(Chats)
                .values(user_repo_id=user_repo.user_repo_id, chat_name=name)
                .returning(Chats.chat_id, Chats.chat_name, Chats.updated_at)
            )

            room = (await self.db.execute(stmt)).mappings().one_or_none()
            await self.db.commit()

            return room
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def _get_owned_room(self, user_id: UUID, chat_id: UUID) -> UUID:
        try:
            room = await self.db.scalar(
                select(Chats.chat_id)
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(
                    Chats.chat_id == chat_id,
                    UserRepo.user_id == user_id,
                )
            )

            if room is None:
                raise NotFoundError("CHAT ROOM NOT FOUND OR NOT OWNED BY USER")
            return room
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def _give_chat_a_title(self, first_message: str) -> str:
        system_message = (
            "You are an expert AI title generator. Your task is to generate a concise, relevant, and descriptive title for a chat conversation based on the user's initial message.\n\n"
            "Guidelines:\n"
            "- Keep the title descriptive but should be strictly under 150 characters.\n"
            "- Capture the core topic or intent of the conversation.\n"
            "- Do not use quotes, labels (e.g., 'Title:'), or introductory text—return only the title.\n"
            "- Remember to only return the title, without any additional text or formatting.\n"
        )

        messages = [
            {
                "role": "system",
                "content": system_message,
            },
            {
                "role": "user",
                "content": f"{first_message}",
            },
        ]

        try:
            result = await Generator().LLM(
                model="groq/qwen/qwen3.8-27b", messages=messages, max_tokens=200
            )
        except Exception as exc:
            raise HTTPError(
                status=502,
                detail="UNABLE TO GENERATE A CHAT ROOM NAME",
            ) from exc

        if result.get("type") != "success":
            raise HTTPError(
                status=502,
                detail="UNABLE TO GENERATE A CHAT ROOM NAME",
            )

        content = getattr(result.get("content"), "content", None)
        if not isinstance(content, str) or not content.strip():
            raise HTTPError(
                status=502,
                detail="UNABLE TO GENERATE A CHAT ROOM NAME",
            )
        return content.strip()[:150]

    async def rewrite_chat_title(
        self, user_id: UUID, chat_id: UUID, first_message: str
    ):
        try:
            verefied_chat_id = await self._get_owned_room(user_id, chat_id)
            new_name = await self._give_chat_a_title(first_message=first_message)

            chat = await self.rename_chat_room(
                user_id=user_id, chat_id=verefied_chat_id, name=new_name
            )

            return chat

        except NotFoundError:
            raise
        except Exception as e:
            logger.exception("AN ERROR OCCURRED WHILE REWRITING CHAT TITLE, %s", e)
            raise HTTPError(status=500, detail="INTERNAL SERVER ERROR")

    async def _handle_database_error(self, error: SQLAlchemyError) -> NoReturn:
        await self.db.rollback()
        raise error
