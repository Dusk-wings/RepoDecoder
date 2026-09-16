import magic
from pathlib import Path
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound
from PIL import Image, UnidentifiedImageError

DOCUMENT_MIMES = {
    # --- Microsoft Office (Modern OpenXML) ---
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    # --- Microsoft Office (Legacy Binary) ---
    "application/msword": "doc",
    "application/vnd.ms-excel": "xls",
    "application/vnd.ms-powerpoint": "ppt",
    # --- LibreOffice / OpenDocument Formats ---
    "application/vnd.oasis.opendocument.text": "odt",  # Writer
    "application/vnd.oasis.opendocument.spreadsheet": "ods",  # Calc (LibreOffice Excel equivalent)
    "application/vnd.oasis.opendocument.presentation": "odp",  # Impress
    "application/vnd.oasis.opendocument.graphics": "odg",  # Draw
    # --- Delimited / Data & PDF Documents ---
    "text/csv": "csv",
    "text/x-comma-separated-values": "csv",
    "application/csv": "csv",
    "application/pdf": "pdf",
    "application/rtf": "rtf",
    "text/rtf": "rtf",
}

NON_PARSEABLE_ALIASES = {"unknown", "text", "rst"}


class FileInspector:
    def __init__(self) -> None:
        self.file_path: Path | None = None
        self.mime_type: str | None = None

    def set_file_path(self, file_path: Path):
        self.file_path = file_path
        self.mime_type = self._detect_mime()

    def _detect_mime(self) -> str:
        if not self.file_path:
            raise ValueError("FILE PATH SHOULD BE DEFINED")

        try:
            return magic.from_file(self.file_path, mime=True)
        except:
            return "application/octet-stream"

    def _set_file(self, file_path: str) -> None:
        self.file_path = Path(file_path)

    def extension_to_language_name(
        self, file_path: Path | None = None
    ) -> tuple[str, str]:
        """Identify the language alias and full name using Pygments."""
        if not file_path:
            if not self.file_path:
                raise ValueError("FILE PATH SHOULD BE DEFINED")
            else:
                file_path = self.file_path

        try:
            if not file_path.name:
                return "unknown", "unknown"

            lexer = get_lexer_for_filename(str(file_path))

            lang_alias = lexer.aliases[0] if lexer.aliases else "text"
            lang_full = lexer.name

            return lang_alias, lang_full

        except ClassNotFound:
            return "unknown", "unknown"

    def _verify_image(self) -> dict:
        """Verify image integrity and extract metadata using Pillow."""
        if not self.file_path:
            raise ValueError("FILE PATH SHOULD BE DEFINED")

        try:
            with Image.open(self.file_path) as img:
                img.verify()  # Validates structural integrity without decoding pixel data
                return {
                    "is_valid": True,
                    "format": img.format,
                    "size": img.size,
                    "mode": img.mode,
                }
        except (UnidentifiedImageError, OSError, ValueError) as e:
            return {"is_valid": False, "error": str(e)}

    def inspect(self) -> dict:
        if not self.file_path:
            raise ValueError("FILE PATH SHOULD BE DEFINED")

        if not self.mime_type:
            raise ValueError("MIME TYPE IS NOT DEFINED, PLESE USE set_file_path")

        if not self.file_path.is_file():
            return {"status": "error", "message": "File does not exist"}

        # 1. Images
        if self.mime_type.startswith("image/"):
            return {
                "category": "image",
                "mime": self.mime_type,
                "image_metadata": self._verify_image(),
                "should_parse": False,
            }

        # 2. Office & Documents (Includes text/plain + .csv fallback check)
        is_csv_ext = self.file_path.suffix.lower() == ".csv"
        is_tsv_ext = self.file_path.suffix.lower() == ".tsv"

        if (
            self.mime_type in DOCUMENT_MIMES
            or (self.mime_type == "text/plain" and is_csv_ext)
            or (self.mime_type == "text/plain" and is_tsv_ext)
        ):
            doc_format = DOCUMENT_MIMES.get(
                self.mime_type, "csv" if is_csv_ext else "tsv" if is_tsv_ext else "txt"
            )
            return {
                "category": "document",
                "format": doc_format,
                "mime": self.mime_type,
                "should_parse": False,
            }

        # 3. Structured Data (JSON / XML)
        if self.mime_type in ["application/json", "application/xml"]:
            return {
                "category": "data",
                "mime": self.mime_type,
                "language": self.mime_type.split("/")[-1],
                "should_parse": False,
            }

        # 4. Code & Text (Tree-Sitter Targets)
        lang_alias, lang_full = self.extension_to_language_name()
        is_text_mime = (
            self.mime_type.startswith("text/")
            or self.mime_type.startswith("application/x-")
            or self.mime_type == "application/javascript"
        )

        if lang_alias != "unknown" or is_text_mime:
            should_parse = lang_alias not in NON_PARSEABLE_ALIASES
            return {
                "category": "code" if should_parse else "text",
                "mime": self.mime_type,
                "language_alias": lang_alias if lang_alias != "tsx" else "typescript",
                "language_name": lang_full if lang_full != "TSX" else "Typescript",
                "should_parse": should_parse,
            }

        # 5. Unsupported / Binary Fallback
        return {
            "category": "binary",
            "mime": self.mime_type,
            "should_parse": False,
        }
