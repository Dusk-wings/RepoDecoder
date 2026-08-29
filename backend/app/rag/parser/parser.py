from pathlib import Path
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound
from tree_sitter_language_pack import get_parser, get_language
from tree_sitter import Node, Tree
import pandas as pd
import logging

logger = logging.getLogger(__name__)


class Parser:
    def __init__(self):
        self.file_path: Path | None = None
        self.source_bytes: bytes | None = None
        self.language: str | None = None

    def _text(self, node: Node) -> str:
        if self.source_bytes:
            return self.source_bytes[node.start_byte : node.end_byte].decode("utf-8")
        else:
            return "unknown"

    def _get_source_bytes(self, file_path: Path) -> bytes:
        return file_path.read_bytes()

    def _set_file_path(self, file_path: Path) -> None:
        self.file_path = file_path
        self.language = self.extension_to_language_name()

    def extension_to_language_name(self, get_full_name: bool = False) -> str:
        try:
            if not self.file_path:
                return "unknown"
            lexer = get_lexer_for_filename(self.file_path)
            if get_full_name:
                return lexer.name
            return lexer.aliases[0] if lexer.aliases else "text"
        except ClassNotFound:
            return "unknown"  # Fallback agar extension parse na ho paaye

    def find_repo_root(self, start_path: Path = Path(__file__)) -> Path:
        """Traverses up from start_path to locate the root repository folder (.git)."""
        resolved_path = start_path.resolve()
        for parent in [resolved_path] + list(resolved_path.parents):
            if (parent / ".git").exists():
                return parent
        # Fallback to script's parent if .git directory is not found
        return resolved_path.parent

    def parse_ast(self) -> None | Tree:
        if not self.language or not self.file_path:
            return None

        try:
            parser = get_parser(self.language)
            language = get_language(self.language)

            source_code = self.file_path.read_text(encoding="utf-8")
            tree = parser.parse(bytes(source_code, "utf-8"))

            return tree
        except Exception:
            logger.info(
                f"Skipping {self.file_path.name}: No parser found for language '{self.language}'"
            )
            return None

    def general_parser(self, target: int = 300, overlap: int = 50) -> list[dict]:
        if target <= overlap:
            raise ValueError("target size must be strictly greater than overlap size")

        if not self.file_path:
            raise ValueError("File Path is not yet provided")

        with open(self.file_path, "r", encoding="utf-8") as fr:
            words = fr.read().split()

        if not words:
            return []

        chunks = []
        step = target - overlap

        for i in range(0, len(words), step):
            chunk_words = words[i : i + target]
            content = " ".join(chunk_words)

            metadata = {
                "word_count": len(chunk_words),
                "file_name": self.file_path.name,
                "file_path": str(self.file_path),
                "file_type": self.extension_to_language_name(),
            }
            chunks.append({"content": content, "metadata": metadata})

            # Stop once the end of the word list is reached
            if i + target >= len(words):
                break

        return chunks

    def parse_csv_and_spreadsheats(self) -> dict | None:
        # Ensure we get a lowercase extension with the dot stripped or kept depending on your helper function

        if not self.language:
            raise ValueError("Language is yet not defined")

        if not self.file_path:
            raise ValueError("File Path is yet not defined")

        language = self.language.lower()

        # Expanded CSV / Tabular formats
        csv_variants = {"csv", ".csv", "tsv", ".tsv"}

        # Expanded Excel formats
        excel_variants = {
            "xls",
            ".xls",
            "xlsx",
            ".xlsx",
            "xlsm",
            ".xlsm",
            "xlsb",
            ".xlsb",
            "ods",
            ".ods",
        }

        data = None
        if language in csv_variants:
            data = pd.read_csv(self.file_path, nrows=31)
        elif language in excel_variants:
            data = pd.read_excel(self.file_path, nrows=31)
        else:
            print("not csv or excel:", language)

        if data is not None:
            has_more = len(data) > 30
            data_types = data.dtypes.to_dict()

            metadata = {
                "is_complete": has_more,
                "schema": str(data_types),
                "file_path": str(self.file_path),
                "file_name": self.file_path.name,
            }

            result = data.to_dict(orient="records")

            return {"metadata": metadata, "sample-data": result}
        else:
            return None
