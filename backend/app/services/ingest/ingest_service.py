import uuid
import logging
from pathlib import Path
import hashlib
import json
from openai import OpenAI

from app.rag.parser.import_parser import ImportParser
from app.rag.parser.parser import Parser
from app.rag.parser.code_parser import CodeParser
from app.rag.parser.document_parser import DocumentParser
from app.rag.parser.markdown_parser import MarkDownParser
from app.rag.parser.pdf_parser import PdfParser
from app.rag.parser.dependencies_parser import DependenciesParser
from app.rag.parser.notebook_parser import NoteBookParser

from app.rag.chunker.markdown_chunker import MarkdownChunker
from app.rag.chunker.code_chunker import CodeChunker

from app.rag.embedder.embedder import Embedder

from app.rag.utils.file_validator import FileInspector

from app.services.ingest.github_client import GithubClient

from app.models.repo_file import FileProcess
from app.core.config import env_config

import asyncio

logger = logging.getLogger(__name__)

ALLOWED_DOC_FORMAT = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "rtf": "text/rtf",
}

ALLOWED_CODE_FORMAT = {"go", "python", "javascript", "typescript", "java"}

ALLOWED_SPREAD_SHEAT = {
    "csv": "text/csv",
    "tsv": "text/plain",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

FILE_EMBEDDING_LIMIT = 25
MODEL_NAME = "qwen/qwen3.8-27b"


class Ingest(GithubClient):
    def __init__(self, github_url: str) -> None:
        super().__init__(github_url=github_url)

        self.repo_id: uuid.UUID | None = None
        self.repo_name: str | None = None

        self.parser = Parser()
        self.import_extractor = ImportParser(self.absolute_path)
        self.file_inspector = FileInspector()
        self.document_parser = DocumentParser()
        self.markdown_parser = MarkDownParser()
        self.code_parser = CodeParser()
        self.dep_parser = DependenciesParser()
        self.pdf_parser = PdfParser()

        self.embedder = Embedder()

    def _parse_tabular_data_to_str(self, data: dict) -> str:
        try:
            if not isinstance(data, dict):
                raise TypeError("Tabular data must be a dictionary")

            metadata = data.get("metadata") or {}
            file_name = metadata.get("file_name") or "unknown"
            file_path = metadata.get("file_path") or ""
            extension = Path(str(file_path or file_name)).suffix.lstrip(".")
            file_language = extension or "unknown"

            if not env_config.GROQ_API_KEY:
                raise RuntimeError("GROQ_API_KEY is not configured")

            client = OpenAI(
                api_key=env_config.GROQ_API_KEY,
                base_url="https://api.groq.com/openai/v1",
            )

            if "is_complete" in data:
                del data["is_complete"]

            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Describe the tabular file for semantic search. "
                            "Mention the subject, important columns, and the kind or the datatype of the column. "
                            "Return only the description, "
                            "with no title or formatting, in under 200 tokens."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(data, default=str),
                    },
                ],
                max_tokens=200,
            )

            description = response.choices[0].message.content
            if not description:
                raise RuntimeError("The tabular description model returned no text")

            embedding_text = (
                f"File: {file_name} | Language: {file_language} | "
                f"AI Description: {description.strip()}"
            )

            # Keep the complete embedding input below the model's 490-token budget.
            while self.embedder.count_tokens(embedding_text) >= 490:
                words = embedding_text.rsplit(" ", 1)
                if len(words) != 2:
                    break
                embedding_text = words[0].rstrip(" ,.;:")

            return embedding_text
        except Exception as e:
            logger.exception(
                "[INJEST-PARSE-TABULAR] FAILED TO PARSE TABULAR DATA: %s", e
            )
            raise

    async def _extract_file_imports(self, file_path: Path):
        if not file_path.exists():
            logger.warning(
                "[INJEST-EXTRACT-IMPORTS] FILE PATH DOES NOT EXIST: %s",
                file_path,
            )
            raise FileNotFoundError(file_path)

        if not self.repo_id:
            logger.exception("[INJEST-EXTRACT-IMPORTS] REPO ID IS YET NOT DEFINED")
            raise ValueError("DEFINED THE repo_id FILED")

        try:
            result = await asyncio.to_thread(
                self.import_extractor.extract_imports, file_path
            )
            raw_imports = result.get("imports")
            imports: list[dict] = (
                [item for item in raw_imports if isinstance(item, dict)]
                if isinstance(raw_imports, list)
                else []
            )

            if not imports:
                return

            await self.save_file_imports(file_path=str(file_path), imports=imports)

        except ValueError as e:
            logger.exception(
                "[INJEST-EXTRACT-IMPORTS] UNABLE TO PERFORM OPERATION FOR %s: %s",
                file_path,
                e,
            )
            raise

        except Exception as e:
            logger.exception(
                "[INJEST-EXTRACT-IMPORTS] IMPORTS NOT SAVED FOR FILE %s: %s",
                file_path,
                e,
            )
            raise

    async def _chunk_file(
        self, file_path: Path, file_id: uuid.UUID
    ) -> None | list[dict]:
        if not file_path.exists():
            logger.warning(
                "[INJEST-CHUNKING] WARNING THE FILE PATH DESCRIBED DOES NOT EXIST, %s",
                file_path,
            )
            raise FileNotFoundError(file_path)

        try:
            return await self._chunk_file_impl(file_path=file_path, file_id=file_id)
        except Exception as e:
            logger.exception(
                "[INJEST-CHUNKING] FAILED TO CHUNK FILE %s: %s", file_path, e
            )
            raise

    async def _chunk_file_impl(
        self, file_path: Path, file_id: uuid.UUID
    ) -> None | list[dict]:

        self.file_inspector.set_file_path(file_path)
        file_details = self.file_inspector.inspect()
        # self.parser._set_file_path(file_path)

        if not self.repo_id:
            return None

        chunks = []
        # chunks_dict = []
        try:
            category = file_details.get("category", "")
            if category == "document":
                file_format = file_details.get("format", "")

                if file_format in ALLOWED_DOC_FORMAT.keys():
                    if file_details.get("mime", "") == ALLOWED_DOC_FORMAT.get(
                        file_format, None
                    ):
                        document_markdown = self.document_parser.parse(file_path)
                        markdown_chunker = MarkdownChunker(
                            file_path, self.parser.extension_to_language_name
                        )

                        parsed_markdown = await self.markdown_parser.parser(
                            doc=document_markdown,
                            file_path=None,
                            repo_id=self.repo_id,
                            file_id=file_id,
                        )
                        if parsed_markdown:
                            chunks = markdown_chunker.create_md_embedding_content(
                                chunks=parsed_markdown,
                                optimize=True,
                                count_token=self.embedder.count_tokens,
                            )
                            self.document_parser.delete_converted_doc()

                        else:
                            logger.info(
                                "[INJEST-CHUNKING] PARSING PROCESS FAILED WHILE CHUNKING THE FILE %s",
                                file_path,
                            )
                            self.document_parser.delete_converted_doc()
                            await self._update_file_status(
                                file_path=str(file_path), status=FileProcess.failed
                            )
                            return None
                elif (
                    file_format == "pdf"
                    and file_details.get("mime", "") == "application/pdf"
                ):
                    markdown_file_path = self.pdf_parser.convert_file(
                        file_path=file_path
                    )
                    parsed_markdown = await self.markdown_parser.parser(
                        doc=None,
                        file_path=markdown_file_path,
                        file_id=file_id,
                        repo_id=self.repo_id,
                        use_vision_llm=True,
                        # is_image_internal=True,
                    )

                    if parsed_markdown is not None:
                        markdown_chunker = MarkdownChunker(
                            file_path, self.parser.extension_to_language_name
                        )
                        chunks = markdown_chunker.create_md_embedding_content(
                            chunks=parsed_markdown,
                            optimize=True,
                            count_token=self.embedder.count_tokens,
                        )

                    else:
                        logger.info(
                            "[INJEST-CHUNKING] UNABLE TO PARSE THE PDF FILE: %s",
                            file_path,
                        )
                        await self._update_file_status(
                            file_path=str(file_path), status=FileProcess.failed
                        )
                        return None

                elif file_format in ALLOWED_SPREAD_SHEAT.keys():
                    if file_details.get("mime", "") == ALLOWED_SPREAD_SHEAT.get(
                        file_format, None
                    ):
                        tabular_data = self.parser.parse_csv_and_spreadsheets(
                            file_name=file_path, language=file_path.suffix
                        )
                        if tabular_data:
                            tabular_description = self._parse_tabular_data_to_str(
                                tabular_data
                            )
                            chunks.append(
                                {
                                    "chunk": tabular_data,
                                    "embedding_str": tabular_description,
                                }
                            )
                            await self.add_file_to_bucket(
                                file=str(file_path),
                                file_id=file_id,
                                repo_id=self.repo_id,
                            )
                            # chunks_dict.append(tabular_data)
                        else:
                            logger.info(
                                "[INJEST-CHUNKING] FILE FORMAT FOR TABULAR DATA IS NOT SUPPORTED, FILE: %s, SUFFIX: %s",
                                file_path,
                                file_path.suffix,
                            )
                            await self._update_file_status(
                                file_path=str(file_path), status=FileProcess.failed
                            )
                            return None

                else:
                    parsed_data = self.parser.general_parser(self.embedder.count_tokens)
                    # chunks_dict = parsed_data
                    for data in parsed_data:
                        chunks.append(
                            {
                                "chunk": data,
                                "embedding_str": self.parser.create_embeding_text(data),
                            }
                        )

            elif category == "code":
                code_alias = file_details.get("language_alias", "")
                if code_alias in ALLOWED_CODE_FORMAT:
                    parsed_code = self.code_parser.parser(file_path=file_path, doc=None)
                    code_chunker = CodeChunker(self.parser.extension_to_language_name)
                    if parsed_code:
                        chunks = code_chunker.create_code_embeding_content(
                            chunks=parsed_code,
                            file_path=file_path,
                            count_tokens=self.embedder.count_tokens,
                        )

                    else:
                        logger.info(
                            "[INJEST-CHUNKING] CHUNKING FOR CODE FILE %s FAILED",
                            file_path,
                        )
                        await self._update_file_status(
                            file_path=str(file_path), status=FileProcess.failed
                        )
                        return None

                elif code_alias == "markdown":
                    parsed_markdown = await self.markdown_parser.parser(
                        doc=None,
                        file_path=file_path,
                        repo_id=self.repo_id,
                        file_id=file_id,
                    )

                    if parsed_markdown is not None:
                        markdown_chunker = MarkdownChunker(
                            file_path, self.parser.extension_to_language_name
                        )
                        chunks = markdown_chunker.create_md_embedding_content(
                            chunks=parsed_markdown,
                            optimize=True,
                            count_token=self.embedder.count_tokens,
                        )

                    else:
                        logger.info(
                            "[INJEST-CHUNKING] UNABLE TO PARSE THE MARKDOWN FILE: %s",
                            file_path,
                        )
                        await self._update_file_status(
                            file_path=str(file_path), status=FileProcess.failed
                        )
                        return None
                elif (
                    code_alias == "modula2"
                    and file_path.name == "go"
                    and file_path.suffix == ".mod"
                ):
                    self.dep_parser.set_file_path(file_path=file_path)
                    dependencies = self.dep_parser.parse_go_mod()
                    deps = dependencies.get("dependencies")
                    details = dependencies.get("details")
                    if deps and details is not None:
                        await self._save_deps(
                            file_path=str(file_path),
                            language="go",
                            deps=deps,
                            details=details,
                        )
                    else:
                        logger.warning(
                            "[INJEST-CHUNKING] FAILED TO EXTRACT DEPS OR DETAILS FROM FILE %s",
                            file_path,
                        )
                        await self._update_file_status(
                            file_path=str(file_path), status=FileProcess.failed
                        )
                    return None

                elif code_alias == "xml" and file_path.name == "pom":
                    self.dep_parser.set_file_path(file_path=file_path)
                    dependencies = self.dep_parser.parse_pom_xml()
                    deps = dependencies.get("dependencies")
                    details = dependencies.get("details")
                    if deps and details is not None:
                        await self._save_deps(
                            file_path=str(file_path),
                            language="java",
                            deps=deps,
                            details=details,
                        )
                    else:
                        logger.warning(
                            "[INJEST-CHUNKING] FAILED TO EXTRACT DEPS OR DETAILS FROM FILE %s",
                            file_path,
                        )
                        await self._update_file_status(
                            file_path=str(file_path), status=FileProcess.failed
                        )
                    return None
                elif code_alias == "toml" and file_path.name == "pyproject":
                    self.dep_parser.set_file_path(file_path=file_path)
                    dependencies = self.dep_parser.parse_pyproject_toml()
                    deps = dependencies.get("dependencies")
                    details = dependencies.get("details")
                    if deps and details is not None:
                        await self._save_deps(
                            file_path=str(file_path),
                            language="python",
                            deps=deps,
                            details=details,
                        )
                    else:
                        logger.warning(
                            "[INJEST-CHUNKING] FAILED TO EXTRACT DEPS FROM FILE %s",
                            file_path,
                        )
                        await self._update_file_status(
                            file_path=str(file_path), status=FileProcess.failed
                        )
                    return None
                elif code_alias == "yaml" and file_path.name == "environment":
                    self.dep_parser.set_file_path(file_path=file_path)
                    dependencies = self.dep_parser.parse_environment_yml()
                    deps = dependencies.get("dependencies")
                    details = dependencies.get("details")
                    if deps and details is not None:
                        await self._save_deps(
                            file_path=str(file_path),
                            language="python",
                            deps=deps,
                            details=details,
                        )
                    else:
                        logger.warning(
                            "[INJEST-CHUNKING] FAILED TO EXTRACT DEPS FROM FILE %s",
                            file_path,
                        )
                        await self._update_file_status(
                            file_path=str(file_path), status=FileProcess.failed
                        )
                    return None
                else:
                    self.parser._set_file_path(file_path=file_path)
                    parsed_data = self.parser.general_parser(self.embedder.count_tokens)
                    # chunks_dict = parsed_data
                    for data in parsed_data:
                        chunks.append(
                            {
                                "chunk": data,
                                "embedding_str": self.parser.create_embeding_text(data),
                            }
                        )

            elif category == "data":
                if file_details.get("mime") == "application/json":
                    if file_path.name == "package" and file_path.suffix == ".json":
                        self.dep_parser.set_file_path(file_path=file_path)
                        dependencies = self.dep_parser.parse_package_json()
                        deps = dependencies.get("dependencies")
                        details = dependencies.get("details")
                        if deps and details is not None:
                            await self._save_deps(
                                file_path=str(file_path),
                                language="javascript/typescript",
                                deps=deps,
                                details=details,
                            )
                        else:
                            logger.warning(
                                "[INJEST-CHUNKING] FAILED TO EXTRACT DEPS FROM FILE %s",
                                file_path,
                            )
                            await self._update_file_status(
                                file_path=str(file_path), status=FileProcess.failed
                            )
                        return None
                    elif file_path.suffix == ".ipynb":
                        notebook_parser = NoteBookParser()
                        parsed_notebook = await notebook_parser.parser(
                            file_path=file_path, file_id=file_id, repo_id=self.repo_id
                        )
                        parsed_notebook_md = parsed_notebook.get("markdown", None)
                        parsed_notebook_code = parsed_notebook.get("code", None)

                        if parsed_notebook_md is not None:
                            markdown_chunker = MarkdownChunker(
                                file_path, self.parser.extension_to_language_name
                            )

                            chunks.extend(
                                markdown_chunker.create_md_embedding_content(
                                    chunks=parsed_notebook_md,
                                    optimize=True,
                                    count_token=self.embedder.count_tokens,
                                )
                            )
                        if parsed_notebook_code is not None:
                            code_chunker = CodeChunker(
                                self.file_inspector.extension_to_language_name
                            )

                            chunks.extend(
                                code_chunker.create_code_embeding_content(
                                    chunks=parsed_notebook_code,
                                    file_path=file_path,
                                    count_tokens=self.embedder.count_tokens,
                                )
                            )

                    else:
                        self.parser._set_file_path(file_path=file_path)
                        parsed_json = self.parser.general_parser(
                            self.embedder.count_tokens, target=450
                        )
                        # chunk_dict = parsed_json
                        for data in parsed_json:
                            chunks.append(
                                {
                                    "chunk": data,
                                    "embedding_str": self.parser.create_embeding_text(
                                        data
                                    ),
                                }
                            )

            elif category == "text":
                if file_path.name == "requirements":
                    self.dep_parser.set_file_path(file_path=file_path)
                    dependencies = self.dep_parser.parse_requirements_txt()
                    deps = dependencies.get("dependencies")
                    details = dependencies.get("details")
                    if deps and details is not None:
                        await self._save_deps(
                            file_path=str(file_path),
                            language="python",
                            deps=deps,
                            details=details,
                        )
                        return None
                    else:
                        logger.warning(
                            "[INJEST-CHUNKING] FAILED TO EXTRACT DEPS FROM REQUIREMENT FILE %s, USING GENERAL PARSER",
                            file_path,
                        )
                        self.parser._set_file_path(file_path=file_path)
                        parsed_text = self.parser.general_parser(
                            self.embedder.count_tokens
                        )
                        # chunks_dict = parsed_text
                        for data in parsed_text:
                            chunks.append(
                                {
                                    "chunk": data,
                                    "embedding_str": self.parser.create_embeding_text(
                                        data
                                    ),
                                }
                            )
                else:
                    self.parser._set_file_path(file_path=file_path)
                    parsed_text = self.parser.general_parser(self.embedder.count_tokens)
                    for data in parsed_text:
                        chunks.append(
                            {
                                "chunk": data,
                                "embedding_str": self.parser.create_embeding_text(data),
                            }
                        )

            else:
                logger.warning(
                    "[INJEST-CHUNKING] THIS CATEGORY OF FILE IS NOT SUPPORTED CATEGORY %s, FILE PATH %s",
                    category,
                    file_path,
                )
                await self._update_file_status(
                    file_path=str(file_path), status=FileProcess.rejected
                )
                return None
        except Exception as e:
            logger.exception(
                "[INJEST-CHUNKING] UNABLE TO CHUNK THE FILE %s: %s", file_path, e
            )
            raise

        return chunks

    async def _process_file_batch(self, files: list[dict]) -> None:
        file_ids = [file["file_id"] for file in files if file.get("file_id")]

        try:
            all_embedding = []
            embedding_file_ids = []
            for file in files:
                stored_file_path = file.get("file_path", "")
                file_id = file.get("file_id", None)
                if not file_id:
                    raise KeyError("[INJEST-PROCESS-BATCH] FILE-ID IS REQUIRED")
                if stored_file_path:
                    chunks = await self._chunk_file(
                        file_path=Path(self.target_dir) / stored_file_path,
                        file_id=file_id,
                    )
                    if chunks:
                        embedding = self.embedder.generate_embeddings(
                            content=chunks,
                            file_id=file.get("file_id"),
                            repo_id=self.repo_id,
                        )
                        all_embedding.extend(embedding)
                        if embedding:
                            embedding_file_ids.append(file["file_id"])

            for embed in all_embedding:
                if "content" in embed:
                    embed["chunk"] = embed.pop("content")

                if "embedding_text" in embed:
                    embed["chunk_str"] = embed.pop("embedding_text")

                if "embedding" in embed:
                    embed["vector"] = embed.pop("embedding")

            await self.save_embeddings(
                embeddings=all_embedding, file_ids=embedding_file_ids
            )
        except Exception:
            try:
                await self._update_file_statuses(file_ids=file_ids)
            except Exception:
                logger.exception(
                    "[INJEST-PROCESS-BATCH] FAILED TO MARK FILES AS FAILED"
                )
            raise

    def calculate_file_hash(
        self,
        file_path: str,
        algorithm: str = "sha256",
        chunk_size: int = 1024 * 1024,  # 1 MB
    ) -> str:
        hasher = hashlib.new(algorithm)

        with Path(file_path).open("rb") as file:
            while chunk := file.read(chunk_size):
                hasher.update(chunk)

        return hasher.hexdigest()

    async def ingest_repo(self):
        try:
            does_exist = await self._fetch_github_repo()
            logger.info(
                "[INGEST-REPO] STARTING THE INGEST PROCESS FOR REPO: %s",
                self.github_url,
            )

            existing_files = {}
            if does_exist:
                existing_files = await self.get_existing_files()

            files_to_insert = []

            for file_path in self.target_dir.rglob("*"):
                if not file_path.is_file():
                    continue

                relative_path = file_path.relative_to(self.target_dir)
                stored_path = relative_path.as_posix()

                file_hash = self.calculate_file_hash(file_path=str(file_path))
                existing_file = existing_files.get(stored_path)

                if (
                    does_exist
                    and existing_file
                    and existing_file["file_hash"] == file_hash
                ):
                    continue

                self.file_inspector.set_file_path(file_path)
                file_details = self.file_inspector.inspect()

                files_to_insert.append(
                    {
                        "repo_id": self.repo_id,
                        "file_path": str(relative_path),
                        "file_name": file_path.name,
                        "file_hash": file_hash,
                        "file_size": file_path.stat().st_size,
                        "file_ext": file_path.suffix,
                        "file_category": file_details.get("category", "unknown"),
                        "status": FileProcess.processing,
                    }
                )

            inserted_files = []
            if files_to_insert:
                try:
                    inserted_files = await self.save_repo_files(files_to_insert)
                except Exception:
                    try:
                        await self._update_file_statuses(
                            file_paths=[file["file_path"] for file in files_to_insert]
                        )
                    except Exception:
                        logger.exception("[INJEST-REPO] FAILED TO MARK FILES AS FAILED")
                    raise
            else:
                if does_exist:
                    logger.info(
                        "[INGEST-REPO] NO CHANGE IN THE REPO: %s", self.github_url
                    )
                else:
                    logger.info(
                        "[INGEST-REPO] NO FILE FOUND IN THE REPO %s", self.github_url
                    )

                return

            # start = 0
            for start in range(0, len(inserted_files), FILE_EMBEDDING_LIMIT):
                files_batch = [
                    dict(row)
                    for row in inserted_files[start : start + FILE_EMBEDDING_LIMIT]
                ]
                await self._process_file_batch(files=files_batch)

        except Exception as e:
            logger.exception(
                "[INGEST-REPO] UNABLE TO INGEST THE REPO %s: %s", self.github_url, e
            )
            raise

        finally:
            self._remove_github_repo()
