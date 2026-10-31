from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, UUID, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.db import Base

from typing import TYPE_CHECKING
import uuid
from datetime import datetime

if TYPE_CHECKING:
    from app.models.auth_user import AuthUser


class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("auth.users.id", ondelete="CASCADE"),
        nullable=False,
    )

    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    username: Mapped[str | None] = mapped_column(String(50), unique=True)

    # bio: Mapped[str | None] = mapped_column(Text)

    profile_picture: Mapped[str | None] = mapped_column(String(255))
    # phone_number: Mapped[str | None] = mapped_column(String(20))
    #
    # location: Mapped[str | None] = mapped_column(String(150))
    # website: Mapped[str | None] = mapped_column(String(255))
    is_ingesting: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationship with User model
    user: Mapped["AuthUser"] = relationship("AuthUser")
