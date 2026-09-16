import json
from typing import Dict, Any, List
from rag.parser.markdown_parser import MarkDownParser
from rag.parser.code_parser import CodeParser
from pathlib import Path


class NotebookParseError(Exception):
    """Custom exception raised when notebook parsing fails due to invalid structure."""

    pass


class NoteBookParser(MarkDownParser, CodeParser):
    def __init__(self):
        super().__init__()

    def parse_ipynb(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Parses a Jupyter Notebook (.ipynb) file and extracts markdown and code cells.

        Raises:
            FileNotFoundError: If the path does not exist.
            PermissionError: If read permissions are lacking.
            ValueError: If the file is not valid JSON or UTF-8.
            NotebookParseError: If the JSON structure does not match a standard notebook schema.
        """
        if not self.file_path:
            raise ValueError("FILE DOES NOT EXIST")

        # 1. File Access & Read Handling
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                notebook = json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"File not found: '{self.file_path}'")
        except PermissionError:
            raise PermissionError(f"Permission denied when reading '{self.file_path}'")
        except UnicodeDecodeError as e:
            raise ValueError(
                f"File '{self.file_path}' is not encoded in valid UTF-8 format. Details: {e}"
            )
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Invalid notebook file. '{self.file_path}' is not valid JSON. Details: {e}"
            )

        # 2. Schema Validation
        if not isinstance(notebook, dict):
            raise NotebookParseError(
                "Malformed notebook: Root structure must be a JSON object."
            )

        if "cells" not in notebook or not isinstance(notebook["cells"], list):
            raise NotebookParseError(
                "Malformed notebook: Missing or invalid 'cells' list."
            )

        parsed_data: Dict[str, List[Dict[str, Any]]] = {"markdowns": [], "code": []}

        # 3. Safe Cell Extraction
        for index, cell in enumerate(notebook["cells"]):
            if not isinstance(cell, dict):
                continue  # Skip invalid non-dict cell entries

            cell_type = cell.get("cell_type")
            source = cell.get("source", "")

            # Safely normalize 'source' into a string
            if isinstance(source, list):
                source = "".join(str(line) for line in source)
            elif not isinstance(source, str):
                source = str(source)

            cell_details = {
                "cell_index": index,
                "source": source,
                "metadata": (
                    cell.get("metadata", {})
                    if isinstance(cell.get("metadata"), dict)
                    else {}
                ),
                "id": cell.get("id"),
            }

            if cell_type == "markdown":
                parsed_data["markdowns"].append(cell_details)

            elif cell_type == "code":
                cell_details["execution_count"] = cell.get("execution_count")
                cell_details["outputs"] = (
                    cell.get("outputs", [])
                    if isinstance(cell.get("outputs"), list)
                    else []
                )
                parsed_data["code"].append(cell_details)

        return parsed_data

    def parser(self, file_path: Path | None = None):
        if file_path is not None:
            self.file_path = file_path

        if self.file_path is None:
            raise ValueError("FILE PATH MUST BE DEFINED")

        parsed_notebook = self.parse_ipynb()

        markdown = parsed_notebook.get("markdowns", None)
        code = parsed_notebook.get("code", None)

        markdown_chunks = []
        code_chunks = []

        if markdown is not None:
            for md in markdown:
                if md.get("source", "") != "":
                    parsed_markdown = MarkDownParser.parser(
                        self, doc=md.get("source", ""), file_path=self.file_path
                    )
                    if parsed_markdown:
                        for p_md in parsed_markdown:
                            p_md["meta_info"] = {
                                "cell_id": md.get("id", None),
                                "cell_index": md.get("cell_index", None),
                            }
                        markdown_chunks.append(parsed_markdown)
                else:
                    continue

        if code is not None:
            for cd in code:
                if cd.get("source", "") != "":
                    parsed_code = CodeParser.parser(
                        self, doc=cd.get("source", ""), file_path=None
                    )
                    if parsed_code:
                        for p_c in parsed_code:
                            p_c["meta_info"] = {
                                "cell_id": cd.get("id", None),
                                "cell_index": cd.get("cell_index", None),
                                "execution_count": cd.get("execution_count", None),
                            }
                    code_chunks.append(parsed_code)
                else:
                    continue

        return {"markdown": markdown_chunks, "code": code_chunks}
