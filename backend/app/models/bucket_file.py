from app.core.db import Base

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import (
    Text,
    UUID,
    ForeignKey,
    DateTime,
    func,
    Enum as SQLEnum,
    UniqueConstraint,
)

import uuid
from datetime import datetime
from typing import TYPE_CHECKING
from enum import Enum

if TYPE_CHECKING:
    from app.models.repository import Repository
    from app.models.repo_file import RepoFile


class BucketFileType(str, Enum):
    image = "IMAGE"
    spread_sheat = "SPREAD_SHEAT"


class BucketFile(Base):
    __tablename__ = "bucket_file"

    __table_args__ = (
        UniqueConstraint("repo_id", "file_id", "url", name="repo_file_url_unique"),
    )
    bucket_file_id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, default=uuid.uuid4
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("repository.repo_id"), nullable=False
    )
    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID, ForeignKey("repo_file.file_id"), nullable=False
    )

    url: Mapped[str] = mapped_column(Text, nullable=False)
    bucket_key: Mapped[str] = mapped_column(Text, nullable=False)
    file_type: Mapped[BucketFileType] = mapped_column(
        SQLEnum(BucketFileType), default=BucketFileType.image
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), server_onupdate=func.now()
    )

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="bucket_files"
    )
    file: Mapped[list["RepoFile"]] = relationship(
        "RepoFile", back_populates="bucket_files"
    )
