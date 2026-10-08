from app.core.db import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UUID, ForeignKey
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from app.models.embedding import Embedding
    from app.models.conversation import Conversation
    from app.models.repo_file import RepoFile


class ChatSources(Base):
    __tablename__ = "chat_source"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    embed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("embedding.embed_id", name="fk_chat_source_embed_id_embedding"),
        nullable=False,
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repo_file.file_id", name="fk_chat_source_file_id_repo_file"),
        nullable=True,
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "conversation.conversation_id",
            name="fk_chat_source_conversation_id_conversation",
        ),
        nullable=False,
    )

    conversation: Mapped["Conversation"] = relationship(
        "Conversation", back_populates="sources"
    )
    chunk: Mapped["Embedding"] = relationship("Embedding", back_populates="chats")
    file: Mapped["RepoFile"] = relationship("RepoFile", back_populates="chats")
