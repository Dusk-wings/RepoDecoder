from core.db import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UUID, String, Text, DateTime, Float, ForeignKey, func
from typing import TYPE_CHECKING
from datetime import datetime
import uuid

if TYPE_CHECKING:
    from models.repository import Repository
    from models.embedding import Embedding


class RepoFile(Base):
    __tablename__ = "repo_file"

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("repository.repo_id"), nullable=False
    )

    file_name: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    file_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[float] = mapped_column(Float, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    # relationship
    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="files"
    )
    embedded_chunks: Mapped[list["Embedding"]] = relationship(
        "Embedding", back_populates="file", cascade="all, delete-orphan"
    )
