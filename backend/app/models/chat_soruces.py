from app.core.db import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UUID, ForeignKey
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from app.models.embedding import Embedding
    from app.models.conversation import Conversation


class ChatSources(Base):
    __tablename__ = "chat_source"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    embed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("embedding.embed_id"), nullable=False
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversation.conversation_id"), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="sources"
    )
    chunk: Mapped["Embedding"] = relationship("Embedding", back_populates="chats")
