from core.db import Base
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import Text, UUID, String, DateTime, func, Enum as SQLEnum
from enum import Enum
from datetime import datetime
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from models.repo_file import RepoFile
    from models.embedding import Embedding


class RepoStatus(str, Enum):
    completed = "COMPLETED"
    processing = "PROCESSING"
    failed = "FAILED"


class Repository(Base):
    __tablename__ = "repository"

    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    repo_name: Mapped[str] = mapped_column(String(100), nullable=False)

    repo_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(
        SQLEnum(RepoStatus, name="status_enum"),
        nullable=False,
        default=RepoStatus.processing,
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    files: Mapped[list["RepoFile"]] = relationship(
        "RepoFile", back_populates="repository", cascade="all, delete-orphan"
    )
    file_chunks: Mapped[list["Embedding"]] = relationship(
        "Embedding", back_populates="repo", cascade="all, delete-orphan"
    )
