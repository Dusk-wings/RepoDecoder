from app.rag.parser.parser import Parser
from tree_sitter import Node
import re
from app.rag.parser.image_pipeline import VisionFilePipeline
from pathlib import Path
import logging
import uuid

logger = logging.getLogger(__name__)


class MarkDownParser(Parser, VisionFilePipeline):
    def __init__(self):
        super().__init__()

    async def parse_markdown(
        self,
        parent_node: Node,
        file_id: uuid.UUID,
        repo_id: uuid.UUID,
        metadata=None,
        use_vision_llm: bool = True,
        # is_image_internal: bool = False,
    ):
        if metadata is None:
            metadata = {}

        chunks = []

        for node in parent_node.children:
            # print(node) # Uncomment for debugging
            if node.type == "section":
                current_metadata = metadata.copy()
                current_metadata["headings"] = current_metadata.get(
                    "headings", {}
                ).copy()

                is_image = False
                is_code_block = False
                is_table = False

                # Arrays to hold content parts and image metadata for the current section
                section_content = []
                image_urls = []
                alt_texts = []
                image_descriptions = []

                for child in node.children:
                    # print("Child Type, " , child.type, "Text, ", child.text)
                    if child.type == "atx_heading":
                        content = self._text(child)
                        level = len(content) - len(content.lstrip("#"))

                        current_metadata["headings"] = {
                            k: v
                            for k, v in current_metadata["headings"].items()
                            if k < level
                        }
                        current_metadata["headings"][level] = content

                        # Add heading text to the content
                        section_content.append(content)

                    elif child.type == "paragraph":
                        paragraph_content = self._text(child)

                        # Use regex to find all markdown images: ![alt](url)
                        img_pattern = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")

                        if img_pattern.search(paragraph_content):
                            is_image = True

                            urls = []

                            def replace_md_image(match):
                                alt = match.group(1)
                                url = match.group(2)

                                image_urls.append(url)
                                alt_texts.append(alt)
                                try:
                                    if use_vision_llm:
                                        description = self._vission_LLM(image_url=url)
                                        image_descriptions.append(description)
                                        urls.append(url)
                                        return description
                                    return match.group(0)
                                except Exception as e:
                                    logger.exception(
                                        "[PARSE-MARKDOWN] FAILED TO GENERATE TEH IMAGE DESCRIPTION, ERROR %s",
                                        e,
                                    )
                                    return match.group(0)

                            for url in urls:
                                await self._save_image(
                                    file_id=file_id, repo_id=repo_id, url=url
                                )
                            urls = []
                            paragraph_content = img_pattern.sub(
                                replace_md_image, paragraph_content
                            )

                        html_img_pattern = re.compile(
                            r'<img\b(?=[^>]*\bsrc\s*=\s*["\']([^"\']*)["\'])'
                            r'(?=[^>]*\balt\s*=\s*["\']([^"\']*)["\'])'
                            r"[^>]*>",
                            re.IGNORECASE | re.DOTALL,
                        )

                        if html_img_pattern.search(paragraph_content):
                            print("HTML image found in paragraph:", paragraph_content)
                            is_image = True

                            urls = []

                            def replace_html_image(match):
                                url = match.group(1)  # src
                                alt = match.group(2)  # alt
                                image_urls.append(url)
                                alt_texts.append(alt)

                                try:
                                    if use_vision_llm:
                                        description = self._vission_LLM(image_url=url)
                                        image_descriptions.append(description)
                                        urls.append(url)
                                        return description
                                    return match.group(0)
                                except Exception as e:
                                    logger.exception(
                                        "[PARSE-MARKDOWN] FAILED TO GENERATE TEH IMAGE DESCRIPTION, ERROR %s",
                                        e,
                                    )
                                    return match.group(0)

                            for url in urls:
                                await self._save_image(
                                    file_id=file_id, repo_id=repo_id, url=url
                                )
                            urls = []

                            paragraph_content = html_img_pattern.sub(
                                replace_html_image, paragraph_content
                            )

                        # section_content.append(html)

                        section_content.append(paragraph_content)

                    elif child.type == "html_block":
                        print("Enter the html_block", child.text)
                        html = self._text(child)

                        # Use regex to find all HTML images: <img src="url" alt="alt">
                        html_img_pattern = re.compile(
                            r'<img\b(?=[^>]*\bsrc\s*=\s*["\']([^"\']*)["\'])'
                            r'(?=[^>]*\balt\s*=\s*["\']([^"\']*)["\'])'
                            r"[^>]*>",
                            re.IGNORECASE | re.DOTALL,
                        )

                        if html_img_pattern.search(html):
                            is_image = True

                            urls = []

                            def replace_html_image(match):
                                url = match.group(1)  # src
                                alt = match.group(2)  # alt
                                image_urls.append(url)
                                alt_texts.append(alt)

                                try:
                                    if use_vision_llm:
                                        description = self._vission_LLM(image_url=url)
                                        image_descriptions.append(description)
                                        urls.append(url)
                                        return description
                                    return match.group(0)
                                except Exception as e:
                                    logger.exception(
                                        "[PARSE-MARKDOWN] FAILED TO GENERATE TEH IMAGE DESCRIPTION, ERROR %s",
                                        e,
                                    )
                                    return match.group(0)

                            for url in urls:
                                await self._save_image(
                                    file_id=file_id, repo_id=repo_id, url=url
                                )
                            urls = []

                            html = html_img_pattern.sub(replace_html_image, html)

                        section_content.append(html)

                    elif child.type == "fenced_code_block":
                        is_code_block = True
                        # Add code block directly to content
                        section_content.append(self._text(child))

                    elif child.type == "pipe_table":
                        is_table = True
                        # Add the raw markdown table directly to the content
                        section_content.append(self._text(child))

                    elif child.type == "section":
                        # Skip nested sections in this loop.
                        # They will be processed by the recursive call below.
                        pass

                    else:
                        # Catch-all for lists, block_quotes, thematic_breaks, etc.
                        # Adds their text directly to the content.
                        section_content.append(self._text(child))

                # Compile metadata for this section chunk
                chunk_metadata = {
                    **current_metadata,
                    "is_image": is_image,
                    "is_code_block": is_code_block,
                    "is_table": is_table,
                }

                # If images were found, add their URLs and alts to the metadata
                if is_image:
                    chunk_metadata["image"] = {
                        "image_urls": image_urls,
                        "alt_texts": alt_texts,
                        "descriptions": image_descriptions,
                    }

                # Join all collected content pieces with double newlines for readability
                final_content = "\n\n".join(section_content).strip()

                # Append the completed chunk
                if final_content:
                    chunks.append(
                        {"metadata": chunk_metadata, "content": final_content}
                    )

                # Recursively process any nested sections
                chunks.extend(
                    await self.parse_markdown(
                        parent_node=node,
                        file_id=file_id,
                        repo_id=repo_id,
                        metadata=current_metadata,
                        use_vision_llm=use_vision_llm,
                        # is_image_internal=is_image_internal,
                    )
                )

            else:
                # Handle root-level nodes that aren't inside a section (if any exist)
                await self.parse_markdown(
                    parent_node=node,
                    metadata=metadata,
                    file_id=file_id,
                    repo_id=repo_id,
                    use_vision_llm=use_vision_llm,
                    # is_image_internal=is_image_internal,
                )

        return chunks

    def _count_words(self, text: str) -> int:
        return len(re.findall(r"\w+", text))

    async def parser(
        self,
        doc: str | bytes | None,
        file_path: Path | None,
        file_id: uuid.UUID,
        repo_id: uuid.UUID,
        use_vision_llm: bool = True,
        # is_image_internal: bool = False,
    ) -> list[dict] | None:
        if doc is None and file_path is None:
            raise ValueError("PLEASE PROVIDE EITHER THE DOCUMENT DATA OR FILE PATH")

        if doc is not None and file_path is not None:
            raise ValueError("EITHER DOCUMENT DATA OR THE FILE PATH CAN BE SUPPLIED")

        try:
            if doc is not None:
                self.file_path = None  # Clear any existing path
                self.language = "markdown"
                ast = self.parse_ast(file_data=doc)
            elif file_path is not None:
                self._set_file_path(file_path=file_path)
                ast = self.parse_ast()

            if not ast:
                logging.info("AST RECEIVED FOR THE MARKDOWN IS NONE")
                return None

            # Ensure parse_markdown uses self.source_code or self.file_path
            chunks = await self.parse_markdown(
                parent_node=ast.root_node,
                use_vision_llm=use_vision_llm,
                file_id=file_id,
                repo_id=repo_id,
                # is_image_internal=is_image_internal,
            )
            return chunks

        except Exception as e:
            logger.error("ERROR WHILE PARSING THE CHUNK: %s", e, exc_info=True)
            return None
