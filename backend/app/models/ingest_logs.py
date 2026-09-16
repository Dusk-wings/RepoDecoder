from app.core.db import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import ForeignKey, UUID, Text, func, DateTime
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.repo_file import RepoFile


class IngestLogs(Base):
    __tablename__ = "ingest_logs"

    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, default=uuid.uuid4
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("repository.repo_id"), nullable=False
    )
    file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID, ForeignKey("repo_file.file_id"), nullable=True
    )

    log: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="repo_ingest_log"
    )
    file: Mapped["RepoFile"] = relationship(
        "RepoFile", back_populates="file_ingest_log"
    )
