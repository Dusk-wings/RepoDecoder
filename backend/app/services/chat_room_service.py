from uuid import UUID
from typing import NoReturn
from datetime import datetime, timezone
import logging

from random import random

from sqlalchemy.future import select
from sqlalchemy import insert, delete, update, func
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chats import Chats
from app.models.user_repo import UserRepo
from app.models.conversation import Conversation
from app.models.pinned_chats import PinnedChat

from app.rag.generator.generator import Generator

from app.errors.not_found_error import NotFoundError
from app.errors.http_error import HTTPError
from app.errors.validation_error import ValidationError
from app.errors.server_error import ServerError

logger = logging.getLogger(__name__)


class ChatRoomService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_chat_repo_id(self, user_id: UUID, chat_id: UUID):
        try:
            repo_id = await self.db.scalar(
                select(UserRepo.repo_id)
                .join(Chats, (Chats.user_repo_id == UserRepo.user_repo_id))
                .where(
                    UserRepo.user_id == user_id,
                    Chats.chat_id == chat_id,
                    Chats.deleted.is_(False),
                )
            )

            if not repo_id:
                raise NotFoundError(
                    message="THE RESOURCE THAT YOU ARE REQUESTING OF DOES NOT EXIST"
                )

            return {
                "success": True,
                "status": 200,
                "data": repo_id,
                "message": "REPO_ID FETCHED",
            }

        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def load_pinned_chat_room(
        self, user_id: UUID, repo_id: UUID, limit: int = 5, offset: int = 0
    ):
        try:
            result = await self.db.execute(
                select(
                    Chats.chat_id,
                    Chats.chat_name,
                    Chats.created_at,
                    Chats.updated_at,
                    PinnedChat.created_at.label("pinned_at"),
                )
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .join(
                    PinnedChat,
                    (PinnedChat.chat_id == Chats.chat_id)
                    & (PinnedChat.user_repo_id == UserRepo.user_repo_id),
                )
                .where(
                    UserRepo.user_id == user_id,
                    UserRepo.repo_id == repo_id,
                    Chats.deleted.is_(False),
                )
                .order_by(PinnedChat.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return {
                "success": True,
                "status": 200,
                "message": "PINNED CHAT ROOMS LOADED",
                "data": result.mappings().all(),
            }
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def load_all_chat_room_repo(
        self, user_id: UUID, repo_id: UUID, limit: int = 10, offset: int = 0
    ):
        try:
            is_pinned = (
                select(PinnedChat.chat_id)
                .where(
                    PinnedChat.user_repo_id == UserRepo.user_repo_id,
                    PinnedChat.chat_id == Chats.chat_id,
                )
                .exists()
            )

            result = await self.db.execute(
                select(
                    Chats.chat_id, Chats.chat_name, Chats.created_at, Chats.updated_at
                )
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(
                    UserRepo.user_id == user_id,
                    UserRepo.repo_id == repo_id,
                    Chats.deleted.is_(False),
                    ~is_pinned,
                )
                .order_by(Chats.updated_at.desc())
                .limit(limit)
                .offset(offset)
            )
            return {
                "success": True,
                "status": 200,
                "message": "CHAT ROOMS LOADED",
                "data": result.mappings().all(),
            }
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def load_all_chat_room(self, user_id: UUID):
        try:
            result = await self.db.execute(
                select(
                    Chats.chat_id, Chats.chat_name, Chats.created_at, Chats.updated_at
                )
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(
                    UserRepo.user_id == user_id,
                    Chats.deleted.is_(False),
                )
                .order_by(Chats.updated_at.desc())
            )

            return result.mappings().all()
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def pin_chat_room(self, user_id: UUID, chat_id: UUID):
        try:
            user_repo_id = await self.db.scalar(
                select(UserRepo.user_repo_id)
                .join(Chats, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(
                    UserRepo.user_id == user_id,
                    Chats.chat_id == chat_id,
                )
            )

            if not user_repo_id:
                raise NotFoundError(
                    message="THE RESOURCE THAT YOU ARE REQUESTING OF DOES NOT EXIST"
                )

            stmt = (
                insert(PinnedChat)
                .values(chat_id=chat_id, user_repo_id=user_repo_id)
                .returning(PinnedChat.pin_id, PinnedChat.chat_id, PinnedChat.created_at)
            )

            result = await self.db.execute(stmt)
            pin = result.mappings().one_or_none()

            if not pin:
                raise ServerError(message="INTERNAL SERVER ERROR")

            await self.db.commit()

            return {
                "success": True,
                "data": dict(pin),
                "message": "CHAT PINNED",
                "status": 200,
            }

        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def delete_chat_room(self, user_id: UUID, chat_id: UUID):
        try:
            owned_by_user = self._authenticate_user(user_id)

            stmt = (
                update(Chats)
                .where(Chats.chat_id == chat_id, owned_by_user)
                .values(deleted=True)
            )

            await self.db.execute(stmt)
            await self.db.commit()

            return {
                "success": True,
                "data": None,
                "message": "CHAT DELETED",
                "status": 200,
            }

        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def rename_chat_room(
        self, user_id: UUID, chat_id: UUID, name: str, is_named_by_user: bool = False
    ):
        try:
            owned_by_user = self._authenticate_user(user_id)
            new_name = name.strip()[:150]
            if not new_name:
                raise ValidationError(
                    "CHAT NAME CAN NOT BE EMPTY OR WHITESPACE ONLY",
                )

            stmt = (
                update(Chats)
                .where(Chats.chat_id == chat_id, owned_by_user)
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

            return {
                "status": 200,
                "success": True,
                "message": "ROOM NAME UPDATED",
                "data": dict(chat),
            }
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    async def count_chat_room(
        self, user_id: UUID, is_anonymous: bool, repo_id: UUID | None
    ):
        if is_anonymous:
            stmt = (
                select(func.count(Chats.chat_id))
                .select_from(Chats)
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(UserRepo.user_id == user_id)
            )
        else:
            if not repo_id:
                raise ValueError("NO REPO WAS FOUND")
            stmt = (
                select(func.count(Chats.chat_id))
                .select_from(Chats)
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(UserRepo.repo_id == repo_id, UserRepo.user_id == user_id)
            )

        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_chat_room(
        self, user_id: UUID, repo_id: UUID, is_anonymous: bool, first_msg: str
    ):
        try:
            user_repo_id = await self.db.scalar(
                select(UserRepo.user_repo_id).where(
                    UserRepo.user_id == user_id,
                    UserRepo.repo_id == repo_id,
                )
            )
            if user_repo_id is None:
                raise NotFoundError("REPOSITORY IS NOT ASSOCIATED WITH USER")

            chat_room_count = await self.count_chat_room(
                user_id=user_id, is_anonymous=is_anonymous, repo_id=repo_id
            )

            if not chat_room_count:
                raise HTTPError(
                    status=409, message="CONFLICT, UNABLE TO LOCATE NUMBER OF COUNTS"
                )

            if is_anonymous and chat_room_count > 5:
                raise HTTPError(
                    status=429,
                    message="MAXIMUM CHAT ROOM CREATION COUNT REACHED, PLEASE LOGIN FOR MORE USAGE",
                )

            if chat_room_count > 20:
                raise HTTPError(
                    status=429,
                    message="MAXIMUM CHAT ROOM CREATION COUNT REACHED FOR REPO, DELETE SOME CHAT-ROOM OR UPGRADE (IF AVAILABLE)",
                )

            name = first_msg.strip()[:150]
            if not name:
                name = f"Chat-{datetime.now(timezone.utc)}-{int(random() * 1000000)}"

            stmt = (
                insert(Chats)
                .values(user_repo_id=user_repo_id, chat_name=name)
                .returning(Chats.chat_id, Chats.chat_name, Chats.updated_at)
            )

            room = (await self.db.execute(stmt)).mappings().one_or_none()

            if not room:
                raise ServerError(message="INTERNAL SERVER ERROR")

            await self.db.commit()

            return {
                "success": True,
                "status": 200,
                "message": "ROOM CREATED",
                "data": dict(room),
            }
        except SQLAlchemyError as exc:
            await self._handle_database_error(exc)

    def _authenticate_user(self, user_id: UUID):
        stmt = (
            select(UserRepo.user_repo_id)
            .where(
                UserRepo.user_repo_id == Chats.user_repo_id,
                UserRepo.user_id == user_id,
            )
            .exists()
        )

        return stmt

    async def chat_belongs(self, user_id: UUID, chat_id: UUID) -> UUID | None:
        try:
            room_id = await self.db.scalar(
                select(Chats.chat_id)
                .join(UserRepo, Chats.user_repo_id == UserRepo.user_repo_id)
                .where(
                    Chats.chat_id == chat_id,
                    UserRepo.user_id == user_id,
                )
            )

            # if room_id is None:
            #     raise NotFoundError("CHAT ROOM NOT FOUND OR NOT OWNED BY USER")

            return room_id
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
                message="UNABLE TO GENERATE A CHAT ROOM NAME",
            ) from exc

        if result.get("type") != "success":
            raise HTTPError(
                status=502,
                message="UNABLE TO GENERATE A CHAT ROOM NAME",
            )

        content = getattr(result.get("content"), "content", None)
        if not isinstance(content, str) or not content.strip():
            raise HTTPError(
                status=502,
                message="UNABLE TO GENERATE A CHAT ROOM NAME",
            )
        return content.strip()[:150]

    async def rewrite_chat_title(
        self, user_id: UUID, chat_id: UUID, first_message: str
    ):
        try:
            new_name = await self._give_chat_a_title(first_message=first_message)

            chat = await self.rename_chat_room(
                user_id=user_id, chat_id=chat_id, name=new_name
            )

            return chat

        except NotFoundError:
            raise
        except Exception as e:
            logger.exception("AN ERROR OCCURRED WHILE REWRITING CHAT TITLE, %s", e)
            raise HTTPError(status=500, message="INTERNAL SERVER ERROR")

    async def _handle_database_error(self, error: SQLAlchemyError) -> NoReturn:
        await self.db.rollback()
        raise error
