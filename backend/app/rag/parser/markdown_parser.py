from parser import Parser
from tree_sitter import Node
import re
from image_pipeline import VisionFilePipeline


class MarkDownParser(Parser, VisionFilePipeline):
    def __init__(self):
        super().__init__()

    def _parse_markdown(self, parent_node: Node, metadata=None):
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

                            def replace_md_image(match):
                                alt = match.group(1)
                                url = match.group(2)
                                image_urls.append(url)
                                alt_texts.append(alt)

                                # Call the Vision LLM to get the description
                                description = self._vission_LLM(url)
                                return description

                            # Replace the image markdown with the LLM description
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

                            def replace_html_image(match):
                                url = match.group(1)  # src
                                alt = match.group(2)  # alt
                                image_urls.append(url)
                                alt_texts.append(alt)

                                # Call the Vision LLM to get the description
                                description = self._vission_LLM(url)
                                return description

                            # Replace the HTML img tag with the LLM description
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

                            def replace_html_image(match):
                                url = match.group(1)  # src
                                alt = match.group(2)  # alt
                                image_urls.append(url)
                                alt_texts.append(alt)

                                # Call the Vision LLM to get the description
                                description = self._vission_LLM(url)
                                return description

                            # Replace the HTML img tag with the LLM description
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
                    }

                # Join all collected content pieces with double newlines for readability
                final_content = "\n\n".join(section_content).strip()

                # Append the completed chunk
                if final_content:
                    chunks.append(
                        {"metadata": chunk_metadata, "content": final_content}
                    )

                # Recursively process any nested sections
                chunks.extend(self._parse_markdown(node, current_metadata))

            else:
                # Handle root-level nodes that aren't inside a section (if any exist)
                self._parse_markdown(node, metadata)

        return chunks

    def _count_words(self, text: str) -> int:
        return len(re.findall(r"\w+", text))

    def _split_image_chunk(self, chunk: dict) -> list:
        """Splits a single chunk containing multiple images into localized sliding windows."""
        meta = chunk.get("metadata", {})

        # Handle both nested "image" dict and flat structures dynamically
        if "image" in meta and isinstance(meta["image"], dict):
            urls = meta["image"].get("image_urls", [])
            alts = meta["image"].get("alt_texts", [])
            is_nested = True
        else:
            urls = meta.get("image_urls", [])
            alts = meta.get("alt_texts", [])
            is_nested = False

        content = chunk.get("content", "")

        if len(urls) <= 1:
            chunk["word_count"] = self._count_words(content)
            return [chunk]

        split_chunks = []
        lines = content.split("\n")

        # 1. Map each URL to its exact line number in the content
        url_indices = []
        for url in urls:
            for idx, line in enumerate(lines):
                if url in line:
                    url_indices.append((url, idx))
                    break

        # 2. Create a localized sliding window for each image
        for i, (target_url, target_idx) in enumerate(url_indices):
            new_meta = meta.copy()

            if is_nested:
                new_meta["image"] = {
                    "image_urls": [target_url],
                    "alt_texts": [alts[i]] if i < len(alts) else [],
                }
            else:
                new_meta["image_urls"] = [target_url]
                new_meta["alt_texts"] = [alts[i]] if i < len(alts) else []

            # --- LOCALIZED WINDOW LOGIC ---
            # Start just after the PREVIOUS image (or at the very beginning)
            start_idx = url_indices[i - 1][1] + 1 if i > 0 else 0

            # End right at the NEXT image (or at the very end)
            end_idx = url_indices[i + 1][1] if i < len(url_indices) - 1 else len(lines)

            # Slice the lines for this specific image
            chunk_lines = lines[start_idx:end_idx]

            new_content = "\n".join(chunk_lines).strip()
            new_content = re.sub(r"\n{3,}", "\n\n", new_content)

            split_chunks.append(
                {
                    "metadata": new_meta,
                    "content": new_content,
                    "word_count": self._count_words(new_content),
                }
            )

        return split_chunks

    def _split_table_chunk(self, chunk: dict, max_table_rows: int) -> list:
        """Splits large markdown tables into smaller tables, repeating the headers."""
        meta = chunk.get("metadata", {})
        content = chunk.get("content", "")

        lines = content.split("\n")
        table_lines, before_table, after_table = [], [], []

        in_table = False
        for line in lines:
            if "|" in line and line.strip().startswith("|"):
                in_table = True
                table_lines.append(line)
            else:
                if in_table:
                    after_table.append(line)
                else:
                    before_table.append(line)

        if len(table_lines) <= max_table_rows + 2 or not table_lines:
            chunk["word_count"] = self._count_words(content)
            return [chunk]

        header_lines = table_lines[:2]
        body_lines = table_lines[2:]

        split_chunks = []
        for i in range(0, len(body_lines), max_table_rows):
            chunk_body = body_lines[i : i + max_table_rows]

            new_lines = list(before_table)
            new_lines.extend(header_lines)
            new_lines.extend(chunk_body)

            if i + max_table_rows >= len(body_lines):
                new_lines.extend(after_table)

            new_content = "\n".join(new_lines).strip()
            split_chunks.append(
                {
                    "metadata": meta.copy(),
                    "content": new_content,
                    "word_count": self._count_words(new_content),
                }
            )

        return split_chunks

    def _flush_text_buffer(self, merged_chunks, current_buffer, overlap_chunks):
        if not current_buffer:
            return

        # Combine the text
        merged_content = "\n\n".join(c["content"] for c in current_buffer)
        total_words = sum(c["word_count"] for c in current_buffer)

        # Smart Metadata Aggregation:
        # Collect all unique H1s and H2s touched in this merged chunk so context isn't lost
        all_h1s = list(
            dict.fromkeys(
                c.get("metadata", {}).get("headings", {}).get(1)
                for c in current_buffer
                if c.get("metadata", {}).get("headings", {}).get(1)
            )
        )
        all_h2s = list(
            dict.fromkeys(
                c.get("metadata", {}).get("headings", {}).get(2)
                for c in current_buffer
                if c.get("metadata", {}).get("headings", {}).get(2)
            )
        )

        # If ANY sub-chunk had code, flag the final chunk
        contains_code = any(
            c.get("metadata", {}).get("is_code_block", False) for c in current_buffer
        )

        merged_chunks.append(
            {
                "content": merged_content,
                "word_count": total_words,
                "metadata": {
                    # Keep the primary starting heading for standard reference
                    "headings": current_buffer[0]
                    .get("metadata", {})
                    .get("headings", {}),
                    # Add a new field showing all sections this chunk spans across
                    "sections_covered": {"h1": all_h1s, "h2": all_h2s},
                    "is_image": False,
                    "is_table": False,
                    "contains_code_block": contains_code,
                },
            }
        )

        # --- Handle the Overlap ---
        if overlap_chunks > 0 and len(current_buffer) > overlap_chunks:
            # Keep the last N chunks in the buffer for the next round
            # If your incoming chunks are ~60 words, overlap_chunks=1 leaves ~60 words in the buffer
            current_buffer[:] = current_buffer[-overlap_chunks:]
        else:
            current_buffer.clear()

    def _merge_rag_chunks(
        self,
        chunks: list,
        target_words: int = 300,
        max_words: int = 500,
        min_words: int = 150,
        max_table_rows: int = 15,
        overlap_chunks: int = 1,
    ) -> list:
        merged_chunks = []
        current_buffer = []

        # Helper to check top-level headings
        def get_top_headings(chunk):
            headings = chunk.get("metadata", {}).get("headings", {})
            return (headings.get(1), headings.get(2))

        for chunk in chunks:
            content = chunk.get("content", "").strip()
            if not content:
                continue

            chunk["word_count"] = self._count_words(content)
            meta = chunk.get("metadata", {})

            # --- Handle Atomic Chunks (Images and Tables) ---
            if meta.get("is_image", False):
                self._flush_text_buffer(merged_chunks, current_buffer, overlap_chunks=0)
                merged_chunks.extend(
                    self._split_image_chunk(chunk)
                )  # Assuming this function exists
                continue

            if meta.get("is_table", False):
                self._flush_text_buffer(merged_chunks, current_buffer, overlap_chunks=0)
                merged_chunks.extend(
                    self._split_table_chunk(chunk, max_table_rows)
                )  # Assuming this exists
                continue

            # --- Check for Semantic Boundaries with a MINIMUM SIZE limit ---
            if current_buffer:
                prev_headings = get_top_headings(current_buffer[-1])
                curr_headings = get_top_headings(chunk)
                current_words = sum(c["word_count"] for c in current_buffer)

                # ONLY flush on a topic change if the chunk is already big enough.
                # If it's too small, we swallow the boundary and keep building toward 300 words.
                if prev_headings != curr_headings and current_words >= min_words:
                    self._flush_text_buffer(
                        merged_chunks, current_buffer, overlap_chunks=0
                    )

            # --- Handle Standard Text Chunks ---
            current_words = sum(c["word_count"] for c in current_buffer)

            # Flush if adding this chunk forces us over the absolute max_words limit
            if current_words > 0 and (current_words + chunk["word_count"] > max_words):
                self._flush_text_buffer(merged_chunks, current_buffer, overlap_chunks)

            current_buffer.append(chunk)

            # Flush if we hit our target size (e.g., 300 words)
            current_words = sum(c["word_count"] for c in current_buffer)
            if current_words >= target_words:
                self._flush_text_buffer(merged_chunks, current_buffer, overlap_chunks)

        # Flush any remaining text at the very end
        self._flush_text_buffer(merged_chunks, current_buffer, overlap_chunks=0)

        return merged_chunks
