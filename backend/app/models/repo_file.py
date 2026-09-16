from app.core.db import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    UUID,
    String,
    Text,
    DateTime,
    ForeignKey,
    func,
    UniqueConstraint,
    BigInteger,
    Enum as EnumSQL,
)
from typing import TYPE_CHECKING
from datetime import datetime
import uuid
from enum import Enum

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.embedding import Embedding
    from app.models.file_imports import FileImport
    from app.models.ingest_logs import IngestLogs
    from app.models.dependencies import Dependencies
    from app.models.repo_dep_details import RepoDepDetails


class FileProcess(str, Enum):
    success = "SUCCESS"
    failed = "FAILED"
    rejected = "REJECTED"
    processing = "PROCESSING"
    canceled = "CANCELED"


class RepoFile(Base):
    __tablename__ = "repo_file"
    __table_args__ = (
        # Ensure file_path is unique PER repository, not globally
        UniqueConstraint("repo_id", "file_path", name="uq_repo_file_repo_id_file_path"),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repository.repo_id")
    )

    file_name: Mapped[str] = mapped_column(Text)
    file_path: Mapped[str] = mapped_column(Text)
    file_ext: Mapped[str] = mapped_column(Text)
    file_category: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(BigInteger)
    file_hash: Mapped[str] = mapped_column(String(64))

    status: Mapped[FileProcess] = mapped_column(
        EnumSQL(FileProcess), default=FileProcess.processing
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # Relationships (Using string forward-references for types)
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="files"
    )
    embedded_chunks: Mapped[list["Embedding"]] = relationship(
        "Embedding", back_populates="file", cascade="all, delete-orphan"
    )

    imports: Mapped[list["FileImport"]] = relationship(
        "FileImport",
        foreign_keys="FileImport.file_id",
        back_populates="file",
        cascade="all, delete-orphan",
    )
    imported_to: Mapped[list["FileImport"]] = relationship(
        "FileImport",
        foreign_keys="FileImport.imported_file_id",
        back_populates="imported_from",
        cascade="all, delete-orphan",
    )

    file_ingest_log: Mapped["IngestLogs"] = relationship(
        "IngestLogs", back_populates="file", cascade="all, delete-orphan"
    )
    deps: Mapped["Dependencies"] = relationship(
        "Dependencies", back_populates="file", cascade="all, delete-orphan"
    )
    dep_details: Mapped["RepoDepDetails"] = relationship(
        "RepoDepDetails", back_populates="file", cascade="all, delete-orphan"
    )
