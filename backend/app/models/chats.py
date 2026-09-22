from app.core.db import Base
from sqlalchemy import UUID, ForeignKey, VARCHAR, ARRAY, Enum, DateTime, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
import uuid
import enum
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.conversation import Conversation
    from app.models.user_repo import UserRepo


class Chats(Base):
    __tablename__ = "chat"

    chat_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)

    user_repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_repo.user_repo_id", ondelete="CASCADE")
    )

    chat_name: Mapped[str] = mapped_column(VARCHAR(150))

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    users: Mapped["UserRepo"] = relationship(
        "UserRepo",
        back_populates="chats",
    )
