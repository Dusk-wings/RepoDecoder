from pathlib import Path
from typing import Callable


class CodeChunker:
    def __init__(self, ext_lang_name: Callable) -> None:
        self.parsed_chunks: list[dict] | None = None
        self.file_path: Path | None = None
        self.extension_to_lang_name: Callable = ext_lang_name

    def _set_file_path(self, file_path: Path) -> None:
        self.file_path = file_path

    def _create_embeding_text(self, chunk: dict) -> str:
        parts = []

        kind = chunk.get("kind")
        name = chunk.get("name")
        comment = chunk.get("comment")
        content = chunk.get("content")
        parent_class = chunk.get("parent_class")
        parent_function = chunk.get("parent_function")
        meta_info = chunk.get("meta_info", None)

        parts.append(
            f"File: {str(self.file_path)} | Language: {self.extension_to_lang_name(self.file_path)}"
        )

        if kind is not None:
            parts.append(f"Kind: {kind}")

        if name is not None:
            parts.append(f"Name: {name}")

        if parent_class is not None:
            parts.append(f"Parent class: {parent_class}")

        if parent_function is not None:
            parts.append(f"Parent function: {parent_function}")

        if meta_info is not None:
            parts.append(f"Meta Information: {meta_info}")

        code_parts = []

        if comment is not None:
            code_parts.append(str(comment))

        if content is not None:
            code_parts.append(str(content))

        if code_parts:
            parts.append("Code: " + "\n".join(code_parts))

        # Use append, not extend
        text_to_embed = " | ".join(parts)
        return text_to_embed

    def split_oversized_chunk(
        self,
        chunk: dict,
        source_bytes: bytes,
        count_tokens: Callable,
        token_limit: int = 450,
    ) -> list[dict]:
        clean_chunk = {k: v for k, v in chunk.items() if k != "_node"}

        # 1. Base Check: Does it already fit?
        # print(count_tokens(_create_embeding_text(clean_chunk)))
        if count_tokens(self._create_embeding_text(clean_chunk)) <= token_limit:
            return [clean_chunk]

        node = chunk.get("_node")
        sub_chunks = []

        # 2. Try Tree-Sitter Statement-Level Splitting
        if node:
            body = node.child_by_field_name("body") or node
            statements = [c for c in body.children if c.is_named]

            signature = source_bytes[node.start_byte : body.start_byte].decode(
                "utf-8"
            )
            closes_with_brace = source_bytes[body.start_byte : body.start_byte + 1] == b"{"

            current_group = []
            part = 1

            def create_ts_candidate(group, p):
                start = group[0].start_byte
                end = group[-1].end_byte
                text = signature + source_bytes[start:end].decode("utf-8")
                if closes_with_brace:
                    text += "\n}"
                return {
                    **clean_chunk,
                    "content": text,
                    "name": f"{clean_chunk.get('name', 'unnamed')} (part {p})",
                    "parent_chunk_id": clean_chunk.get("id"),
                    "start_line": group[0].start_point[0],
                    "end_line": group[-1].end_point[0],
                }

            for stmt in statements:
                test_group = current_group + [stmt]
                candidate = create_ts_candidate(test_group, part)

                if (
                    count_tokens(self._create_embeding_text(candidate)) > token_limit
                    and current_group
                ):
                    sub_chunks.append(create_ts_candidate(current_group, part))
                    part += 1
                    current_group = [stmt]
                else:
                    current_group.append(stmt)

            if current_group:
                sub_chunks.append(create_ts_candidate(current_group, part))

        # 3. Validation & Text Fallback
        # If _node was missing, or Tree-sitter returned a single statement still over the limit,
        # we force a line-by-line split.
        needs_fallback = False
        if not sub_chunks:
            needs_fallback = True
        else:
            for sc in sub_chunks:
                if count_tokens(self._create_embeding_text(sc)) > token_limit:
                    needs_fallback = True
                    break

        if needs_fallback:
            sub_chunks = []
            lines = clean_chunk["content"].split("\n")
            current_lines = []
            part = 1

            for line in lines:
                test_lines = current_lines + [line]
                candidate_text = "\n".join(test_lines)

                candidate = {
                    **clean_chunk,
                    "content": candidate_text,
                    "name": f"{clean_chunk.get('name', 'unnamed')} (part {part})",
                    "parent_chunk_id": clean_chunk.get("id"),
                }

                if (
                    count_tokens(self._create_embeding_text(candidate)) > token_limit
                    and current_lines
                ):
                    # Flush previous lines
                    sub_chunks.append(
                        {
                            **clean_chunk,
                            "content": "\n".join(current_lines),
                            "name": f"{clean_chunk.get('name', 'unnamed')} (part {part})",
                            "parent_chunk_id": clean_chunk.get("id"),
                        }
                    )
                    part += 1
                    current_lines = [line]
                else:
                    current_lines.append(line)

            if current_lines:
                sub_chunks.append(
                    {
                        **clean_chunk,
                        "content": "\n".join(current_lines),
                        "name": f"{clean_chunk.get('name', 'unnamed')} (part {part})",
                        "parent_chunk_id": clean_chunk.get("id"),
                    }
                )

        return sub_chunks

    def create_code_embeding_content(
        self,
        chunks: list[dict],
        file_path: Path | None,
        count_tokens: Callable,
        token_limit: int = 450,
    ) -> list[dict]:
        if file_path:
            self.file_path = file_path

        if not self.file_path:
            raise ValueError("FILE PATH IS NOT DEFINED")

        data = []
        source_bytes = self.file_path.read_bytes()

        for chunk in chunks:
            splited_chunk = self.split_oversized_chunk(
                chunk=chunk,
                source_bytes=source_bytes,
                count_tokens=count_tokens,
                token_limit=token_limit,
            )
            for sc in splited_chunk:
                data.append(
                    {"chunk": sc, "embedding_str": self._create_embeding_text(sc)}
                )

        return data
