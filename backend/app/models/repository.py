from app.core.db import Base
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import Text, UUID, String, DateTime, func, Enum as SQLEnum, JSON
from enum import Enum
from datetime import datetime
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from app.models.repo_file import RepoFile
    from app.models.embedding import Embedding
    from app.models.ingest_logs import IngestLogs
    from app.models.dependencies import Dependencies
    from app.models.repo_dep_details import RepoDepDetails


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
    repo_name: Mapped[str] = mapped_column(String(110), nullable=False)
    repo_full_name: Mapped[str] = mapped_column(String(210), nullable=False, unique=True)

    repo_url: Mapped[str] = mapped_column(Text, unique=True, nullable=False)

    description: Mapped[str] = mapped_column(Text, nullable=True)
    repo_created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    license: Mapped[dict] = mapped_column(JSON, nullable=True)

    owner: Mapped[str] = mapped_column(String(100), nullable=False)
    owner_url: Mapped[str] = mapped_column(Text, nullable=False)

    # fork: Mapped[bool] = mapped_column(nullable=False, default=False)
    # forked_from: Mapped[str] = mapped_column(Text, nullable=True)

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

    repo_ingest_log: Mapped[list["IngestLogs"]] = relationship(
        "IngestLogs", back_populates="repository", cascade="all, delete-orphan"
    )
    repo_dep: Mapped[list["Dependencies"]] = relationship(
        "Dependencies", back_populates="repository", cascade="all, delete-orphan"
    )

    dep_details: Mapped[list["RepoDepDetails"]] = relationship(
        "RepoDepDetails", back_populates="file", cascade="all, delete-orphan"
    )
