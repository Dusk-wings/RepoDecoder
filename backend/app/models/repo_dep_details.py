from app.core.db import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import JSON, UUID, DateTime, ForeignKey, func, UniqueConstraint
import uuid
from typing import TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.repo_file import RepoFile


class RepoDepDetails(Base):
    __tablename__ = "repo_dep_details"
    __table_args__ = (
        UniqueConstraint("repo_id", "file_id", name="uq_repo_dep_repo_file"),
    )

    detail_id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, default=uuid.uuid4
    )
    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("repository.repo_id"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("repo_file.file_id"), nullable=False
    )

    details: Mapped[dict] = mapped_column(JSON, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), server_onupdate=func.now()
    )

    # relationship
    repo: Mapped["Repository"] = relationship("Repository", back_populates="dep_details")
    file: Mapped["RepoFile"] = relationship("RepoFile", back_populates="dep_details")
