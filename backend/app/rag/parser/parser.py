from pathlib import Path
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound
from tree_sitter_language_pack import get_parser, get_language
from tree_sitter import Node, Tree
import pandas as pd
import logging
from typing import Callable

logger = logging.getLogger(__name__)


class ASTParseError(ValueError):
    """Raised when an AST cannot be generated."""


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

    def _get_source_bytes(self) -> bytes | None:
        if not self.file_path:
            print("Content is not provided")
            return None
        return self.file_path.read_bytes()

    def _set_file_path(self, file_path: Path) -> None:
        self.file_path = file_path
        self.source_bytes = self._get_source_bytes()
        self.language = self.extension_to_language_name()
        if self.language == "tsx":
            self.language = "typescript"
        if self.language == "jsx":
            self.language = "javascript"

    def extension_to_language_name(self, get_full_name: bool = False) -> str:
        if not self.file_path:
            raise ValueError("FILE PATH SHOULD BE DEFINED")

        try:
            if not self.file_path.name:
                return "unknown"

            lexer = get_lexer_for_filename(str(self.file_path))

            lang_alias = lexer.aliases[0] if lexer.aliases else "text"
            # lang_full = lexer.name

            return lang_alias

        except ClassNotFound:
            return "unknown"

    def find_repo_root(self, start_path: Path = Path(__file__)) -> Path:
        """Traverses up from start_path to locate the root repository folder (.git)."""
        resolved_path = start_path.resolve()
        for parent in [resolved_path] + list(resolved_path.parents):
            if (parent / ".git").exists():
                return parent
        # Fallback to script's parent if .git directory is not found
        return resolved_path.parent

    # def has_syntax_errors(node: Node) -> bool:
    #     """
    #     Check whether a Tree-sitter node contains syntax errors.
    #     """
    #     if node.is_error or node.is_missing:
    #         return True

    #     return any(has_syntax_errors(child) for child in node.children)

    def parse_ast(
        self,
        file_data: str | bytes | None = None,
    ) -> Tree | None:
        if not self.language:
            raise ValueError("LANGUAGE MUST BE PROVIDED")

        if file_data is None and self.file_path is None:
            raise ValueError("EITHER file_path OR file_data MUST BE PROVIDED")

        try:
            parser = get_parser(self.language)

            if file_data is None:
                if self.file_path is None:
                    raise ValueError("File path is not provided")
                self.source_code = self.file_path.read_bytes()

            elif isinstance(file_data, str):
                self.source_code = file_data.encode("utf-8", errors="replace")

            elif isinstance(file_data, bytes):
                # Safely convert raw bytes (Latin-1, CP1252, etc.) to valid UTF-8
                self.source_code = file_data.decode("utf-8", errors="replace").encode(
                    "utf-8"
                )

            else:
                raise TypeError("file_data must be str, bytes, or None")

            # Keep node text extraction in sync for both file and in-memory input.
            self.source_bytes = self.source_code

            tree = parser.parse(self.source_code)

            if tree is None:
                raise ASTParseError(
                    f"FAILED TO GENERATE AST FOR THE LANGUAGE '{self.language}'"
                )

            return tree

        except (ASTParseError, ValueError, TypeError):
            raise
        except Exception as exc:
            file_name = (
                self.file_path.name if self.file_path else "<provided file data>"
            )
            raise ASTParseError(
                f"FAILED TO GENERATE AST FOR {file_name} USING LANGUAGE '{self.language}'"
            ) from exc

    def create_embeding_text(self, chunk: dict) -> str:
        parts = []

        metadata = chunk.get("metadata", {})
        content = chunk.get("content")

        name = metadata.get("file_name", None)
        file_type = metadata.get("file_type", None)

        parts.append(
            f"File: {str(self.file_path)} | Language: {self.extension_to_language_name()}"
        )

        if name is not None:
            parts.append(f"Name: {name}")
        if file_type is not None:
            parts.append(f"File Type: {file_type}")

        parts.append(f"Content: \n{content}")

        return " | ".join(parts)

    def general_parser(
        self, count_token: Callable, target: int = 300, overlap: int = 50
    ) -> list[dict]:
        if target <= overlap:
            raise ValueError("target size must be strictly greater than overlap size")

        if not self.file_path:
            raise ValueError("File Path is not yet provided")

        try:
            with open(self.file_path, "r", encoding="utf-8") as fr:
                words = fr.read().split()
        except (OSError, UnicodeDecodeError) as e:
            raise IOError(f"Could not open or read file {self.file_path}: {e}")

        if not words:
            return []

        chunks = []
        start_idx = 0
        total_words = len(words)

        while start_idx < total_words:
            low = start_idx + 1
            high = total_words
            best_end = start_idx + 1

            # Binary search to find the maximum slice fitting within target tokens
            while low <= high:
                mid = (low + high) // 2
                candidate_text = " ".join(words[start_idx:mid])

                if count_token(candidate_text) <= target:
                    best_end = mid
                    low = mid + 1
                else:
                    high = mid - 1

            chunk_words = words[start_idx:best_end]
            content = " ".join(chunk_words)

            metadata = {
                "word_count": len(chunk_words),
                "token_count": count_token(content),
                "file_name": (
                    self.file_path.name
                    if hasattr(self.file_path, "name")
                    else str(self.file_path)
                ),
                "file_path": str(self.file_path),
                "file_type": self.extension_to_language_name(),
            }
            chunks.append({"content": content, "metadata": metadata})

            # Break if we reached the end of the words list
            if best_end >= total_words:
                break

            # Calculate overlap in tokens by stepping backward from best_end
            overlap_start = best_end - 1
            while overlap_start > start_idx:
                overlap_text = " ".join(words[overlap_start:best_end])
                if count_token(overlap_text) >= overlap:
                    break
                overlap_start -= 1

            # Move forward, preventing infinite loops if a single word exceeds limits
            start_idx = max(overlap_start, start_idx + 1)

        return chunks

    def parse_csv_and_spreadsheets(
        self,
        file_name: Path | None = None,
        language: str | None = None,
    ) -> dict | None:

        # Resolve the current file path
        file_path = file_name if file_name is not None else self.file_path

        if file_path is None:
            raise ValueError("File path is not defined")

        # Resolve the current extension/language
        file_extension = language if language is not None else self.language

        if file_extension is None:
            raise ValueError("Language is not defined")

        # Optionally keep the values on the object
        self.file_path = file_path
        self.language = file_extension

        extension = file_extension.lower()

        csv_variants = {".csv", ".tsv"}
        excel_variants = {".xls", ".xlsx", ".xlsm", ".ods"}

        if extension in csv_variants:
            if extension == ".tsv":
                data = pd.read_csv(
                    file_path,
                    sep="\t",
                    nrows=6,
                )
            else:
                data = pd.read_csv(
                    file_path,
                    nrows=6,
                )

        elif extension in excel_variants:
            # if extension == ".xlsb":
            #     data = pd.read_excel(
            #         file_path,
            #         nrows=31,
            #         engine="pyxlsb",
            #     )
            # else:
                data = pd.read_excel(
                    file_path,
                    nrows=6,
                    engine="calamine",
                )

        else:
            print("Not a supported CSV or spreadsheet file:", extension)
            return None

        # Because nrows=31, exactly 31 rows means the file may contain more
        has_more = len(data) == 6

        data_types = {column: str(dtype) for column, dtype in data.dtypes.items()}

        metadata = {
            "is_complete": not has_more,
            "schema": data_types,
            "file_path": str(file_path),
            "file_name": file_path.name,
        }

        return {
            "metadata": metadata,
            "sample-data": data.to_dict(orient="records"),
        }
