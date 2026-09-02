from core.db import Base
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
)
from typing import TYPE_CHECKING
from datetime import datetime
import uuid

if TYPE_CHECKING:
    from models.repository import Repository
    from models.embedding import Embedding
    from models.file_imports import FileImport


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
    file_type: Mapped[str] = mapped_column(Text)
    file_size: Mapped[int] = mapped_column(BigInteger)  
    file_hash: Mapped[str] = mapped_column(String(64))  

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
