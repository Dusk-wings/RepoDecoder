from app.core.db import Base
from sqlalchemy import ForeignKey, UUID, func, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import TYPE_CHECKING
from datetime import datetime
import uuid

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.auth_user import AuthUser
    from app.models.chats import Chats


class UserRepo(Base):
    __tablename__ = "user_repo"

    user_repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.UUID
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("repository.repo_id", ondelete="CASCADE"),
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="users"
    )
    user: Mapped["AuthUser"] = relationship("AuthUser")

    chats: Mapped[list["Chats"]] = relationship(
        "Chats", back_populates="users", cascade="all, delete-orphan"
    )
