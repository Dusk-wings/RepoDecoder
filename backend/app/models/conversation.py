from app.core.db import Base
from sqlalchemy import ForeignKey, UUID, Text, DateTime, func, Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from datetime import datetime
from enum import Enum
import uuid

if TYPE_CHECKING:
    from app.models.chats import Chats
    from app.models.chat_soruces import ChatSources


class Status(str, Enum):
    LIKE = "like"
    DISLIKE = "dislike"
    NONE = "none"


class Conversation(Base):
    __tablename__ = "conversation"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat.chat_id", ondelete="CASCADE"),
        nullable=False,
    )

    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    models: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(SqlEnum(Status), default=Status.NONE)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    chat: Mapped["Chats"] = relationship("Chats", back_populates="conversation")
    sources: Mapped[list["ChatSources"]] = relationship(
        "ChatSources", back_populates="conversation", cascade="all, delete-orphan"
    )
