from app.core.db import Base
from sqlalchemy.orm import mapped_column, Mapped, relationship
from sqlalchemy import Text, UUID, DateTime, ForeignKey, func, JSON
from pgvector.sqlalchemy import Vector
from datetime import datetime
from typing import TYPE_CHECKING
import uuid

if TYPE_CHECKING:
    from models.repository import Repository
    from models.repo_file import RepoFile


class Embedding(Base):
    __tablename__ = "embedding"

    embed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("repo_file.file_id"), nullable=False
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("repository.repo_id"), nullable=False
    )

    chunk: Mapped[dict] = mapped_column(JSON, nullable=False)
    chunk_str: Mapped[str] = mapped_column(Text, nullable=False)
    vector: Mapped[list[float]] = mapped_column(Vector(384), nullable=False)

    created_on: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    file: Mapped["RepoFile"] = relationship(
        "RepoFile",
        back_populates="embedded_chunks",
    )

    repo: Mapped["Repository"] = relationship(
        "Repository", back_populates="file_chunks"
    )
