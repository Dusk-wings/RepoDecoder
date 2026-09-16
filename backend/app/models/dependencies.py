from app.core.db import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UUID, Text, ForeignKey
import uuid
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.repo_file import RepoFile
    from app.models.repository import Repository


class Dependencies(Base):
    __tablename__ = "dependencies"

    dep_id: Mapped[uuid.UUID] = mapped_column(
        UUID, primary_key=True, default=uuid.uuid4
    )

    repo_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("repository.repo_id"))
    file_id: Mapped[uuid.UUID] = mapped_column(UUID, ForeignKey("repo_file.file_id"))

    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)

    language: Mapped[str] = mapped_column(Text)
    

    repository: Mapped["Repository"] = relationship(
        "Repository", back_populates="repo_dep"
    )
    file: Mapped["RepoFile"] = relationship("RepoFile", back_populates="deps")
