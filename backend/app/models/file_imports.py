from app.core.db import Base
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy import UUID, String, Text, ForeignKey, Boolean, Enum as SQLEnum, JSON
import uuid
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.repo_file import RepoFile


class FileType(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    STDLIB = "stdlib"


class FileImport(Base):
    __tablename__ = "file_import"

    import_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_file.file_id"), nullable=False
    )

    # Updated to optional if external imports don't exist in repo_file
    imported_file_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("repo_file.file_id")
    )

    source: Mapped[str] = mapped_column(Text)
    module_alias: Mapped[str | None] = mapped_column(Text)

    symbols: Mapped[list[dict[str, Any]]] = mapped_column(JSON)

    file_type: Mapped[FileType] = mapped_column(
        SQLEnum(FileType, name="file_type_name")
    )
    module: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_path: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_static: Mapped[bool] = mapped_column(default=False)
    is_wildcard: Mapped[bool] = mapped_column(default=False)

    # Specified foreign_keys to resolve ambiguity
    file: Mapped["RepoFile"] = relationship(
        "RepoFile", foreign_keys=[file_id], back_populates="imports"
    )
    imported_from: Mapped["RepoFile | None"] = relationship(
        "RepoFile",
        foreign_keys=[imported_file_id],
        back_populates="imported_to",
    )
