from app.rag.parser.parser import Parser
from tree_sitter import Node
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

CHUNK_NODE_TYPES = {
    "python": {
        "class_definition": "class",
        "function_definition": "function",
    },
    "javascript": {
        "class_declaration": "class",
        "function_declaration": "function",
        "method_definition": "function",
        # arrow/function-expression consts handled separately (pattern match, not type match)
        "interface_declaration": "interface",  # only present when parsing .ts/.tsx grammar
        "type_alias_declaration": "type",
    },
    "typescript": {
        "class_declaration": "class",
        "function_declaration": "function",
        "method_definition": "function",
        "interface_declaration": "interface",
        "type_alias_declaration": "type",
        "enum_declaration": "enum",
    },
    "go": {
        "function_declaration": "function",
        "method_declaration": "function",
        "type_declaration": "type",  # covers struct + interface, disambiguated below
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "method_declaration": "function",
        "enum_declaration": "enum",
    },
    "rust": {
        "function_item": "function",
        "impl_item": "class",  # closest analogue: groups methods for a type
        "struct_item": "type",
        "enum_item": "enum",
        "trait_item": "interface",
    },
}


class CodeParser(Parser):
    def __init__(self):
        super().__init__()

    # Node types that ARE function/method-like, used to decide whether to
    # recurse into a class body for per-method chunks.
    METHOD_KINDS = {"function"}
    # Minimum size (in lines) for a NESTED function to get its own chunk.
    # Below this, it stays inline as part of the parent chunk's text.
    NESTED_FN_LINE_THRESHOLD = 10
    # chunker.py

    # Hierarchical AST-based chunk extractor with comment attachment,
    # type/interface support, and module-level variable filtering.

    # Only pull OUT module-level variables that look meaningful (exported,
    # UPPER_CASE constants, or config-like objects) -- not every `let i = 0`.
    def _is_significant_variable(
        self, name: str | None, value_node: Node | None, include_all_globals: bool
    ) -> bool:
        """Check if variable should be extracted. Set include_all_globals=True to retain all global vars."""
        if not name:
            return False
        if include_all_globals:
            return True
        if name.isupper():  # CONSTANT_CASE
            return True
        if value_node and value_node.type in (
            "object",
            "object_pattern",
            "dictionary",
            "call_expression",
            "array",
        ):
            return True
        return False

    def _leading_comment(self, node: Node) -> str | None:
        """Walk backwards through preceding siblings, collecting a contiguous
        comment block immediately above this node (no blank-line gap)."""
        prev = node.prev_sibling
        # print("Prev: ", prev)
        collected = []
        expected_end_row = node.start_point[0]  # comment must end right before this row
        # print(prev)
        i = 0
        # print(prev.type)
        # print(prev is not None and prev.type == "comment")

        while prev is not None and (
            prev.type == "line_comment"
            or prev.type == "block_comment"
            or prev.type == "comment"
        ):
            # print(f"iteration {i}")
            # gap = expected_end_row - prev.end_point[0]
            # if gap > 1:  # blank line between comment and code -> not attached
            #     break
            collected.insert(0, self._text(prev))
            expected_end_row = prev.start_point[0]
            prev = prev.prev_sibling
            i += 1
        comments = "\n".join(collected) if collected else None
        # print(comments)
        return comments

    def _kind_of(self, node_type: str, node: Node | None = None):
        # print("Lang:    ", lang)
        if not self.language:
            raise ValueError("Language needed to be defined")

        kind = CHUNK_NODE_TYPES.get(self.language, {}).get(node_type)
        # print("Kind:    ", kind)
        # Go's type_declaration covers both struct and interface -- disambiguate
        if (
            self.language == "go"
            and node_type == "type_declaration"
            and node is not None
        ):
            text = node.type
            # crude check on child type_spec's underlying type node
            for child in node.children:
                if child.type == "type_spec":
                    for gc in child.children:
                        if gc.type == "interface_type":
                            return "interface"
                        if gc.type == "struct_type":
                            return "type"
        return kind

    def _add_to_global_chunk(
        self,
        comment_text: str | None,
        code_text: str,
        chunks: list[dict],
        node: Node,
    ):
        if not chunks or chunks[0].get("kind") != "global_variables":
            return

        parts = [chunks[0]["content"]]
        if comment_text:
            parts.append(comment_text)
        parts.append(code_text)
        chunks[0]["content"] = "\n".join(filter(None, parts)).strip()

        node_type = node.type
        kind = self._kind_of(node_type, node)

    def extract_chunks(
        self,
        node,
        # source_bytes: bytes | bool | None = None,
        include_all_globals: bool = False,
        merge_all_global_var: bool = False,
    ):
        # if isinstance(source_bytes, (bytes, bytearray)):
        #     self.source_bytes = source_bytes
        # elif isinstance(source_bytes, bool):
        #     merge_all_global_var = include_all_globals
        #     include_all_globals = source_bytes

        # if not self.source_bytes and self.file_path:
        #     self.source_bytes = self._get_source_bytes()

        chunks = []

        # Agar global vars merge karne hain, to shuru me hi 1st chunk bana do
        if merge_all_global_var:
            chunks.append(
                {
                    "kind": "global_variables",
                    "name": "Global Scope Variables",
                    "content": "",
                    "comment": None,
                    "start_line": -1,
                    "end_line": -1,
                }
            )

        # Ab actual recursion start karo
        self._extract_chunks_rec(
            node,
            chunks=chunks,
            include_all_globals=include_all_globals,
            merge_all_global_var=merge_all_global_var,
        )

        if (
            merge_all_global_var
            and chunks
            and chunks[0].get("kind") == "global_variables"
            and not chunks[0].get("content", "").strip()
        ):
            chunks.pop(0)

        return chunks

    def _extract_chunks_rec(
        self,
        node: Node,
        chunks: list[dict],
        parent_class=None,
        parent_function=None,
        depth=0,
        include_all_globals=False,
        merge_all_global_var=False,
    ):
        if chunks is None:
            # print("Chunk does")
            return None

        node_type = node.type
        # if node.type != "program":
        # print(node.type)
        # print(f"Node: {node.type} Name: {node.text.decode("utf-8")}")
        kind = self._kind_of(node_type, node)

        # -------------------------------------------------------------
        # 1. JS/TS Lexical & Variable Declarations (const / let / var)
        # -------------------------------------------------------------
        if self.language in ("javascript", "typescript") and node_type in (
            "lexical_declaration",
            "variable_declaration",
        ):
            comment = self._leading_comment(node)
            for child in node.children:
                if child.type == "variable_declarator":
                    name_node = child.child_by_field_name("name")
                    value_node = child.child_by_field_name("value")

                    var_name = self._text(name_node) if name_node else None

                    # Check if value is an Arrow Function or Function Expression
                    if value_node and value_node.type in (
                        "arrow_function",
                        "function_expression",
                        "generator_function",
                    ):
                        fn_name = var_name or "<anonymous>"
                        n_lines = node.end_point[0] - node.start_point[0]

                        if (
                            parent_function is not None
                            and n_lines < self.NESTED_FN_LINE_THRESHOLD
                        ):
                            continue

                        chunks.append(
                            {
                                "_node": child,
                                "kind": "function",
                                "name": fn_name,
                                "is_arrow": value_node.type == "arrow_function",
                                "comment": comment,
                                "parent_class": parent_class,
                                "parent_function": parent_function,
                                "content": self._text(node),
                                "start_line": node.start_point[0],
                                "end_line": node.end_point[0],
                            }
                        )
                    # Otherwise, treat as Module/Global Level Variable
                    elif parent_class is None and parent_function is None:
                        if self._is_significant_variable(
                            var_name, value_node, include_all_globals
                        ):
                            content = self._text(node)
                            if merge_all_global_var:
                                self._add_to_global_chunk(
                                    comment, content, chunks, node
                                )
                            else:
                                chunks.append(
                                    {
                                        "_node": child,
                                        "kind": "variable",
                                        "name": var_name,
                                        "comment": comment,
                                        "content": content,
                                        "start_line": node.start_point[0],
                                        "end_line": node.end_point[0],
                                    }
                                )
            return chunks

        # -------------------------------------------------------------
        # 2. Classes, Interfaces, Types, Enums
        # -------------------------------------------------------------
        if kind in ("class", "interface", "type", "enum"):
            name_node = node.child_by_field_name("name")
            # print("Name Node:", name_node)
            name = self._text(name_node) if name_node else None
            comment = self._leading_comment(node)
            # print(comment)

            if kind == "class":
                # 1) class-summary chunk: signature-only, not full bodies
                method_sigs = []
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        if self._kind_of(child.type, child) == "function":
                            mname_node = child.child_by_field_name("name")
                            mname = self._text(mname_node) if mname_node else "?"
                            method_sigs.append(mname)
                chunks.append(
                    {
                        "_node": node,
                        "kind": "class_summary",
                        "name": name,
                        "comment": comment,
                        "content": f"class {name}: methods = {', '.join(method_sigs)}",
                        "start_line": node.start_point[0],
                        "end_line": node.end_point[0],
                    }
                )
                # 2) recurse so each method becomes its own chunk, tagged with parent_class
                if body:
                    for child in body.children:
                        self._extract_chunks_rec(
                            child,
                            parent_class=name,
                            depth=depth + 1,
                            chunks=chunks,
                            merge_all_global_var=merge_all_global_var,
                            include_all_globals=include_all_globals,
                        )
                return chunks
            else:
                # interface / type / enum -> single chunk, no further recursion needed
                chunks.append(
                    {
                        "_node": node,
                        "kind": kind,
                        "name": name,
                        "comment": comment,
                        "content": self._text(node),
                        "start_line": node.start_point[0],
                        "end_line": node.end_point[0],
                    }
                )
                return chunks

        # -------------------------------------------------------------
        # 3. Functions
        # -------------------------------------------------------------
        if kind == "function":
            name_node = node.child_by_field_name("name")
            # if node.type == "lexical_declaration":
            #     print(node)
            #     print(_text(name_node,  if name_node else None)
            #     print("Name Node: ", name_node)
            name = self._text(name_node) if name_node else None
            comment = self._leading_comment(node)
            n_lines = node.end_point[0] - node.start_point[0]

            # nested + small -> don't split out, let it stay inside parent's text
            if parent_function is not None and n_lines < self.NESTED_FN_LINE_THRESHOLD:
                return chunks  # caller already captured full parent text

            chunks.append(
                {
                    "_node": node,
                    "kind": "function",
                    "name": name,
                    "comment": comment,
                    "parent_class": parent_class,
                    "parent_function": parent_function,
                    "content": self._text(node),
                    "start_line": node.start_point[0],
                    "end_line": node.end_point[0],
                }
            )
            # still recurse, in case there's a sizeable nested function inside
            for child in node.children:
                self._extract_chunks_rec(
                    child,
                    parent_class=parent_class,
                    parent_function=name,
                    depth=depth + 1,
                    chunks=chunks,
                    merge_all_global_var=merge_all_global_var,
                    include_all_globals=include_all_globals,
                )
            return chunks

        # module-level variable/const, only if it looks significant, only at depth 0
        if depth == 0 and node_type in (
            "assignment",
            "variable_declarator",
            "const_spec",
        ):
            name_node = node.child_by_field_name("name") or node.child_by_field_name(
                "left"
            )
            value_node = node.child_by_field_name("value") or node.child_by_field_name(
                "right"
            )
            name = self._text(name_node) if name_node else None
            if self._is_significant_variable(name, value_node, include_all_globals):
                comment = self._leading_comment(node)
                content = self._text(node)
                if merge_all_global_var:
                    self._add_to_global_chunk(comment, content, chunks, node)
                else:
                    chunks.append(
                        {
                            "_node": node,
                            "kind": "variable",
                            "name": name,
                            "comment": self._leading_comment(node),
                            "content": self._text(node),
                            "start_line": node.start_point[0],
                            "end_line": node.end_point[0],
                        }
                    )
            return chunks  # don't recurse into it either way

        # -------------------------------------------------------------
        # 4. Python & General Module-Level Variables / Assignments
        # -------------------------------------------------------------
        if (
            parent_class is None
            and parent_function is None
            and node_type
            in (
                "assignment",
                "const_spec",
                "expression_statement",
                "variable_declarator",
            )
        ):
            target_node = node
            if node_type == "expression_statement" and len(node.children) > 0:
                target_node = node.children[0]

            if target_node.type in ("assignment", "augmented_assignment"):
                name_node = target_node.child_by_field_name(
                    "left"
                ) or target_node.child_by_field_name("name")
                value_node = target_node.child_by_field_name(
                    "right"
                ) or target_node.child_by_field_name("value")

                var_name = self._text(name_node) if name_node else None

                if self._is_significant_variable(
                    var_name, value_node, include_all_globals
                ):
                    comment = self._leading_comment(node)
                    content = self._text(node)
                    if merge_all_global_var:
                        self._add_to_global_chunk(comment, content, chunks, node)
                    else:
                        chunks.append(
                            {
                                "_node": node,
                                "kind": "variable",
                                "name": var_name,
                                "comment": comment,
                                "content": content,
                                "start_line": node.start_point[0],
                                "end_line": node.end_point[0],
                            }
                        )
                return chunks

        # default: keep walking
        for child in node.children:
            self._extract_chunks_rec(
                child,
                parent_class=parent_class,
                parent_function=parent_function,
                depth=depth,
                chunks=chunks,
                include_all_globals=include_all_globals,
                merge_all_global_var=merge_all_global_var,
            )
        return chunks

    def parser(
        self,
        doc: str | bytes | None,
        file_path: Path | None,
        include_global_var: bool = True,
        group_all_var: bool = True,
    ) -> list[dict] | None:
        

        if not doc and not file_path:
            raise ValueError("PLEASE PROVIDE EITHER THE DOCUMENT DATA OR FILE PATH")

        if doc and file_path:
            raise ValueError("EITHER DOCUMENT DATA OR THE FILE PATH CAN BE SUPPLIED")

        try:
            if doc:
                self.language = "markdown"
                ast = self.parse_ast(file_data=doc)
            elif file_path:
                self._set_file_path(file_path=file_path)
                ast = self.parse_ast()

            if not ast:
                logging.info("AST RECIVED FOR THE MARKDOWN IS NONE")
                return None

            chunks = self.extract_chunks(
                ast.root_node,
                include_all_globals=include_global_var,
                merge_all_global_var=group_all_var,
            )
            return chunks

        except Exception as e:
            logger.error("ERROR WHILE PARSING THE CHUNK, ERROR : %s", e)
            return None
