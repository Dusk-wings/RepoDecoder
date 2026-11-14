from app.core.db import Base

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UUID, DateTime, ForeignKey, UniqueConstraint, func

from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from app.models.user_repo import UserRepo
    from app.models.chats import Chats


class PinnedChat(Base):
    __tablename__ = "pinned_chats"
    __table_args__ = (
            UniqueConstraint("chat_id", "user_repo_id", name="chat_user_unique"),
        )

    pin_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    chat_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat.chat_id", ondelete="CASCADE")
    )
    user_repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_repo.user_repo_id", ondelete="CASCADE")
    )

    created_at: Mapped[DateTime] = mapped_column(DateTime, server_default=func.now())

    chat: Mapped["Chats"] = relationship(
        "Chats",
        back_populates="pinned_chats",
    )
    user_repo: Mapped["UserRepo"] = relationship(
        "UserRepo",
        back_populates="pinned_chats",
    )
