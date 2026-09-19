from typing import Callable
from pathlib import Path
import re
from typing import Any


class MarkdownChunker:
    def __init__(
        self,
        file_path: Path,
        ext_lang_name: Callable,
        *,
        target_tokens: int = 300,
        max_tokens: int = 450,
        min_tokens: int = 150,
        max_table_rows: int = 15,
        overlap_chunks: int = 0,
    ) -> None:
        self.target_tokens = target_tokens
        self.max_tokens = max_tokens
        self.min_tokens = min_tokens
        self.max_table_rows = max_table_rows
        self.overlap_chunks = overlap_chunks

        self.file_path = file_path
        self.extension_to_lang_name = ext_lang_name

    def _create_embedding_text(self, chunk: dict[str, Any]) -> str:
        """Convert a document chunk into descriptive embedding text."""

        parts: list[str] = []
        metadata = chunk.get("metadata") or {}
        meta_info = chunk.get("meta_info", None)

        parts.append(f"File: {self.file_path}")
        parts.append(f"Language: {self.extension_to_lang_name(self.file_path)}")

        if meta_info is not None:
            parts.append(f"Meta Information: {meta_info}")

        chunk_types: list[str] = []

        if metadata.get("is_image"):
            chunk_types.append("image")

        if metadata.get("is_table"):
            chunk_types.append("table")

        if metadata.get("contains_code_block") or metadata.get("is_code_block"):
            chunk_types.append("code")

        parts.append(
            "Content type: " + (", ".join(chunk_types) if chunk_types else "text")
        )

        headings = metadata.get("headings") or {}

        if headings:
            heading_parts: list[str] = []

            for level in sorted(headings):
                values = headings[level]

                if not isinstance(values, list):
                    values = [values]

                for heading in values:
                    heading = str(heading).strip()

                    if heading:
                        heading_parts.append(f"H{level}: {heading}")

            if heading_parts:
                parts.append("Section context:\n" + "\n".join(heading_parts))

        sections_covered = metadata.get("sections_covered") or {}

        if sections_covered:
            section_parts: list[str] = []

            for level, values in sections_covered.items():
                if not isinstance(values, list):
                    values = [values]

                for section in values:
                    section = str(section).strip()

                    if section:
                        section_parts.append(f"{str(level).upper()}: {section}")

            if section_parts:
                parts.append("Sections covered:\n" + "\n".join(section_parts))

        image_metadata = metadata.get("image") or {}

        alt_texts = image_metadata.get("alt_texts") or []

        if alt_texts:
            parts.append("Image descriptions:\n" + "\n".join(map(str, alt_texts)))

        # Usually keep URLs out of embeddings because they consume tokens.
        if metadata.get("include_image_urls_in_embedding"):
            image_urls = image_metadata.get("image_urls") or []

            if image_urls:
                parts.append("Image URLs:\n" + "\n".join(map(str, image_urls)))

        if metadata.get("is_oversized_fragment"):
            fragment_index = metadata.get("fragment_index")
            parts.append(f"Content fragment: {fragment_index}")

        content = chunk.get("content")

        if content is not None:
            content = str(content).strip()

            if content:
                parts.append("Content:\n" + content)

        return "\n\n".join(parts)

    def _split_image_chunk(
        self, chunk: dict, count_tokens: Callable, max_tokens: int
    ) -> list:
        """Splits a single chunk containing multiple images into localized sliding windows."""
        meta = chunk.get("metadata", {})

        # Handle both nested "image" dict and flat structures dynamically
        if "image" in meta and isinstance(meta["image"], dict):
            urls = meta["image"].get("image_urls", [])
            alts = meta["image"].get("alt_texts", [])
            descriptions = meta["image"].get("descriptions", [])
            is_nested = True
        else:
            urls = meta.get("image_urls", [])
            alts = meta.get("alt_texts", [])
            descriptions = meta.get("image_descriptions", [])
            is_nested = False

        content = chunk.get("content", "")

        if len(urls) <= 1:
            chunk["token_count"] = count_tokens(self._create_embedding_text(chunk))
            if chunk["token_count"] <= max_tokens:
                return [chunk]

            return self._split_text_chunk_by_tokens(
                chunk,
                max_tokens=max_tokens,
                count_token=count_tokens,
                overlap_words=20,
            )

        split_chunks = []
        lines = content.split("\n")

        # Vision descriptions replace image syntax in content, so URLs may not
        # be present. Use the descriptions as boundaries when available.
        image_boundaries = []
        search_from = 0
        boundary_values = descriptions or urls
        for image_value in boundary_values:
            value = str(image_value).strip()
            position = content.find(value, search_from) if value else -1
            if position < 0:
                image_boundaries = []
                break
            image_boundaries.append(position)
            search_from = position + len(value)

        if len(image_boundaries) != len(urls):
            # Do not drop the image chunk when its source text cannot be mapped.
            chunk["token_count"] = count_tokens(self._create_embedding_text(chunk))
            if chunk["token_count"] <= max_tokens:
                return [chunk]
            return self._split_text_chunk_by_tokens(
                chunk,
                max_tokens=max_tokens,
                count_token=count_tokens,
                overlap_words=20,
            )

        # 2. Create a localized sliding window for each image
        for i, target_url in enumerate(urls):
            new_meta = meta.copy()

            if is_nested:
                new_meta["image"] = {
                    "image_urls": [target_url],
                    "alt_texts": [alts[i]] if i < len(alts) else [],
                    "descriptions": [descriptions[i]] if i < len(descriptions) else [],
                }
            else:
                new_meta["image_urls"] = [target_url]
                new_meta["alt_texts"] = [alts[i]] if i < len(alts) else []
                new_meta["image_descriptions"] = (
                    [descriptions[i]] if i < len(descriptions) else []
                )

            # --- LOCALIZED WINDOW LOGIC ---
            # Start just after the PREVIOUS image (or at the very beginning)
            start_idx = image_boundaries[i - 1] if i > 0 else 0

            # End right at the NEXT image (or at the very end)
            end_idx = (
                image_boundaries[i + 1]
                if i < len(image_boundaries) - 1
                else len(content)
            )

            new_content = content[start_idx:end_idx].strip()
            new_content = re.sub(r"\n{3,}", "\n\n", new_content)

            split_chunks.append(
                {
                    "metadata": new_meta,
                    "content": new_content,
                    "token_count": count_tokens(
                        self._create_embedding_text(
                            {
                                "metadata": new_meta,
                                "content": new_content,
                            }
                        )
                    ),
                }
            )

        return split_chunks

    def _split_oversized_table_row(
        self,
        before_table: list[str],
        header_lines: list[str],
        row: str,
        after_table: list[str],
        meta: dict,
        max_tokens: int,
        count_token: Callable,
        overlap_chars: int = 100,
    ) -> list[dict]:
        """Split one oversized table row into overlapping embedding chunks."""

        chunks = []
        start = 0
        row_length = len(row)

        while start < row_length:
            # Leave room for the table headers and surrounding content.
            low = start + 1
            high = row_length
            best_end = None

            while low <= high:
                middle = (low + high) // 2
                row_fragment = row[start:middle]

                content_lines = (
                    before_table
                    + header_lines
                    + [
                        f"<!-- Oversized table row fragment -->",
                        row_fragment,
                    ]
                )

                candidate_content = "\n".join(content_lines).strip()

                candidate_chunk = {
                    "metadata": {
                        **meta,
                        "oversized_table_row": True,
                    },
                    "content": candidate_content,
                }

                token_count = count_token(self._create_embedding_text(candidate_chunk))

                if token_count <= max_tokens:
                    best_end = middle
                    low = middle + 1
                else:
                    high = middle - 1

            # This can happen if headers and metadata alone exceed max_tokens.
            if best_end is None:
                raise ValueError(
                    "The table headers and metadata alone exceed max_tokens."
                )

            row_fragment = row[start:best_end]

            is_last_fragment = best_end >= row_length

            content_lines = (
                before_table
                + header_lines
                + [
                    "<!-- Oversized table row fragment -->",
                    row_fragment,
                ]
            )

            if is_last_fragment:
                content_lines.extend(after_table)

            new_content = "\n".join(content_lines).strip()

            new_chunk = {
                "metadata": {
                    **meta,
                    "oversized_table_row": True,
                    "row_fragment_start": start,
                    "row_fragment_end": best_end,
                },
                "content": new_content,
            }

            new_chunk["token_count"] = count_token(
                self._create_embedding_text(new_chunk)
            )

            chunks.append(new_chunk)

            if is_last_fragment:
                break

            # Character overlap. The actual overlap should be kept modest
            # because headers are already repeated in every chunk.
            next_start = best_end - overlap_chars

            # Always make progress.
            start = max(start + 1, next_start)

        return chunks

    def _split_table_chunk(
        self,
        chunk: dict,
        max_tokens: int,
        count_token: Callable,
    ) -> list[dict]:
        """Split a markdown table so each chunk stays within max_tokens."""

        meta = chunk.get("metadata", {}).copy()
        content = chunk.get("content", "")

        lines = content.splitlines()

        table_lines = []
        before_table = []
        after_table = []

        in_table = False
        table_finished = False

        for line in lines:
            is_table_line = line.strip().startswith("|") and "|" in line

            if is_table_line and not table_finished:
                in_table = True
                table_lines.append(line)
            elif in_table:
                table_finished = True
                after_table.append(line)
            else:
                before_table.append(line)

        if len(table_lines) < 2:
            new_chunk = dict(chunk)
            new_chunk["token_count"] = count_token(
                self._create_embedding_text(new_chunk)
            )
            return [new_chunk]

        header_lines = table_lines[:2]
        body_lines = table_lines[2:]

        split_chunks = []
        current_body = []

        for row in body_lines:
            candidate_body = current_body + [row]

            candidate_content = "\n".join(
                before_table + header_lines + candidate_body
            ).strip()

            candidate_chunk = {
                "metadata": meta.copy(),
                "content": candidate_content,
            }

            candidate_tokens = count_token(self._create_embedding_text(candidate_chunk))

            if candidate_tokens <= max_tokens:
                current_body.append(row)
                continue

            # If the current chunk already has rows, save it first.
            if current_body:
                current_content = "\n".join(
                    before_table + header_lines + current_body
                ).strip()

                current_chunk = {
                    "metadata": meta.copy(),
                    "content": current_content,
                }

                current_chunk["token_count"] = count_token(
                    self._create_embedding_text(current_chunk)
                )

                split_chunks.append(current_chunk)
                current_body = []

            # Check whether the row itself can fit in a fresh chunk.
            row_content = "\n".join(before_table + header_lines + [row]).strip()

            row_chunk = {
                "metadata": meta.copy(),
                "content": row_content,
            }

            row_tokens = count_token(self._create_embedding_text(row_chunk))

            if row_tokens <= max_tokens:
                current_body.append(row)
            else:
                # The individual row is too large, so fragment it.
                split_chunks.extend(
                    self._split_oversized_table_row(
                        before_table=before_table,
                        header_lines=header_lines,
                        row=row,
                        after_table=after_table,
                        meta=meta,
                        max_tokens=max_tokens,
                        count_token=count_token,
                        overlap_chars=100,
                    )
                )

        if current_body:
            current_content = "\n".join(
                before_table + header_lines + current_body + after_table
            ).strip()
            current_chunk = {
                "metadata": meta.copy(),
                "content": current_content,
            }
            current_chunk["token_count"] = count_token(
                self._create_embedding_text(current_chunk)
            )
            split_chunks.append(current_chunk)

        return split_chunks

    def _split_text_chunk_by_tokens(
        self, chunk: dict, max_tokens: int, count_token: Callable, overlap_words: int
    ) -> list[dict]:
        """Split one regular text chunk into chunks no larger than max_tokens."""

        content = chunk.get("content", "").strip()

        if not content:
            return []

        # Prefer paragraph/line boundaries first.
        units = [part.strip() for part in content.split("\n\n") if part.strip()]

        result = []
        current_units = []

        def make_chunk(units_to_use: list[str]) -> dict:
            new_chunk = dict(chunk)
            new_chunk["content"] = "\n\n".join(units_to_use).strip()
            new_chunk["metadata"] = chunk.get("metadata", {}).copy()
            new_chunk["token_count"] = count_token(
                self._create_embedding_text(new_chunk)
            )
            return new_chunk

        for unit in units:
            candidate_units = current_units + [unit]
            candidate_chunk = make_chunk(candidate_units)

            if current_units and candidate_chunk["token_count"] > max_tokens:
                result.append(make_chunk(current_units))
                current_units = [unit]
            else:
                current_units = candidate_units

        if current_units:
            result.append(make_chunk(current_units))

        # A single paragraph may itself be too large.
        final_result = []

        for item in result:
            if item["token_count"] <= max_tokens:
                final_result.append(item)
                continue

            final_result.extend(
                self._split_oversized_text_unit(
                    item,
                    max_tokens=max_tokens,
                    count_token=count_token,
                    overlap_words=overlap_words,
                )
            )

        return final_result

    def _split_oversized_text_unit(
        self,
        chunk: dict,
        max_tokens: int,
        count_token: Callable,
        overlap_words: int = 30,
    ) -> list[dict]:
        """Split an oversized text unit with word overlap."""

        words = chunk.get("content", "").split()

        if not words:
            return []

        result = []
        start = 0
        fragment_index = 0

        while start < len(words):
            low = start + 1
            high = len(words)
            best_end = None

            while low <= high:
                middle = (low + high) // 2
                fragment_words = words[start:middle]

                new_chunk = dict(chunk)
                new_chunk["content"] = " ".join(fragment_words)
                new_chunk["metadata"] = {
                    **chunk.get("metadata", {}),
                    "is_oversized_fragment": True,
                    "fragment_index": fragment_index,
                }

                token_count = count_token(self._create_embedding_text(new_chunk))

                if token_count <= max_tokens:
                    best_end = middle
                    low = middle + 1
                else:
                    high = middle - 1

            if best_end is None:
                raise ValueError(
                    "Chunk metadata or embedding prefix exceeds max_tokens."
                )

            fragment_words = words[start:best_end]

            new_chunk = dict(chunk)
            new_chunk["content"] = " ".join(fragment_words)
            new_chunk["metadata"] = {
                **chunk.get("metadata", {}),
                "is_oversized_fragment": True,
                "fragment_index": fragment_index,
            }
            new_chunk["token_count"] = count_token(
                self._create_embedding_text(new_chunk)
            )

            result.append(new_chunk)

            if best_end >= len(words):
                break

            # Start the next fragment with the last N words of this fragment.
            overlap_start = max(start, best_end - overlap_words)
            next_start = max(start + 1, best_end - overlap_words)
            start = next_start
            fragment_index += 1

        return result

    def _flush_text_buffer(self, merged_chunks, current_buffer, overlap_chunks):
        if not current_buffer:
            return

        # Combine the text
        merged_content = "\n\n".join(c["content"] for c in current_buffer)
        total_tokens = sum(c["token_count"] for c in current_buffer)

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
                "token_count": total_tokens,
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

    def _merge_one_normal_chunk(
        self,
        chunk,
        merged_chunks,
        current_buffer,
        count_token,
        *,
        target_tokens,
        max_tokens,
        min_tokens,
        overlap_chunks,
    ):
        def get_top_headings(item):
            headings = item.get("metadata", {}).get("headings", {})
            return headings.get(1), headings.get(2)

        current_tokens = sum(item["token_count"] for item in current_buffer)

        if current_buffer:
            previous_headings = get_top_headings(current_buffer[-1])
            current_headings = get_top_headings(chunk)

            if previous_headings != current_headings and current_tokens >= min_tokens:
                self._flush_text_buffer(
                    merged_chunks,
                    current_buffer,
                    overlap_chunks=0,
                )

        current_tokens = sum(item["token_count"] for item in current_buffer)

        if current_buffer and current_tokens + chunk["token_count"] > max_tokens:
            self._flush_text_buffer(
                merged_chunks,
                current_buffer,
                overlap_chunks,
            )

        current_buffer.append(chunk)

        current_tokens = sum(item["token_count"] for item in current_buffer)

        if current_tokens >= target_tokens:
            self._flush_text_buffer(
                merged_chunks,
                current_buffer,
                overlap_chunks,
            )

    def _merge_rag_chunks(
        self,
        chunks: list,
        count_token: Callable,
        *,
        target_tokens: int | None = None,
        max_tokens: int | None = None,
        min_tokens: int | None = None,
        max_table_rows: int | None = None,
        overlap_chunks: int | None = None,
    ) -> list:
        if target_tokens is None:
            target_tokens = self.target_tokens
        if max_tokens is None:
            max_tokens = self.max_tokens
        if min_tokens is None:
            min_tokens = self.min_tokens
        if overlap_chunks is None:
            overlap_chunks = self.overlap_chunks
        if max_table_rows is None:
            max_table_rows = self.max_table_rows

        merged_chunks = []
        current_buffer = []

        for chunk in chunks:
            content = chunk.get("content", "").strip()

            if not content:
                continue

            chunk["content"] = content
            chunk["token_count"] = count_token(self._create_embedding_text(chunk))

            meta = chunk.get("metadata", {})

            if meta.get("is_image", False):
                self._flush_text_buffer(
                    merged_chunks,
                    current_buffer,
                    overlap_chunks=0,
                )

                image_parts = self._split_image_chunk(
                    chunk,
                    count_token,
                    max_tokens=max_tokens,
                )

                for image_part in image_parts:
                    if image_part["token_count"] > max_tokens:
                        image_parts_to_add = self._split_text_chunk_by_tokens(
                            image_part,
                            max_tokens=max_tokens,
                            count_token=count_token,
                            overlap_words=20,
                        )
                        merged_chunks.extend(image_parts_to_add)
                    else:
                        merged_chunks.append(image_part)
                continue

            if meta.get("is_table", False):
                self._flush_text_buffer(
                    merged_chunks,
                    current_buffer,
                    overlap_chunks=0,
                )

                table_parts = self._split_table_chunk(
                    chunk,
                    # max_table_rows=max_table_rows,
                    max_tokens=max_tokens,
                    count_token=count_token,
                )

                merged_chunks.extend(table_parts)
                continue

            if chunk["token_count"] > max_tokens:
                oversized_parts = self._split_text_chunk_by_tokens(
                    chunk,
                    max_tokens=max_tokens,
                    count_token=count_token,
                    overlap_words=20,
                )

                for part in oversized_parts:
                    self._merge_one_normal_chunk(
                        part,
                        merged_chunks,
                        current_buffer,
                        count_token,
                        target_tokens=target_tokens,
                        max_tokens=max_tokens,
                        min_tokens=min_tokens,
                        overlap_chunks=overlap_chunks,
                    )

                continue

            # This is required for ordinary chunks.
            self._merge_one_normal_chunk(
                chunk,
                merged_chunks,
                current_buffer,
                count_token,
                target_tokens=target_tokens,
                max_tokens=max_tokens,
                min_tokens=min_tokens,
                overlap_chunks=overlap_chunks,
            )

        # Flush any remaining text at the very end
        self._flush_text_buffer(merged_chunks, current_buffer, overlap_chunks=0)

        return merged_chunks

    def create_md_embedding_content(
        self, chunks: list[dict], optimize: bool, count_token: Callable | None = None
    ) -> list[dict]:
        if optimize == True:
            if not count_token:
                raise ValueError("FOR OPTIMIZATION, count_token MUST BE DEFINED")
            splited_chunks = self._merge_rag_chunks(
                chunks=chunks, count_token=count_token
            )
        else:
            splited_chunks = chunks

        data = []
        for chunk in splited_chunks:
            data.append({"chunk": chunk, "embedding_str": self._create_embedding_text(chunk) })

        return data
