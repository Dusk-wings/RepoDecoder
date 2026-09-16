from fastapi import datastructures
from tree_sitter import Node
from pathlib import Path
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound
from tree_sitter_language_pack import get_parser, get_language
import sys
from app.rag.parser.parser import Parser
import re, syslog as sl

NODE_BUILTINS = {
    "assert",
    "buffer",
    "child_process",
    "cluster",
    "crypto",
    "dgram",
    "dns",
    "events",
    "fs",
    "http",
    "http2",
    "https",
    "net",
    "os",
    "path",
    "perf_hooks",
    "process",
    "querystring",
    "readline",
    "stream",
    "string_decoder",
    "timers",
    "tls",
    "tty",
    "url",
    "util",
    "v8",
    "vm",
    "worker_threads",
    "zlib",
}

JAVA_STDLIB_PREFIXES = (
    "java.",
    "javax.",
    "jdk.",
    "sun.",
    "com.sun.",
    "org.w3c.dom",
    "org.xml.sax",
)

JS_TS_SUFFIXES = (
    "",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    "/index.ts",
    "/index.tsx",
    "/index.js",
    "/index.jsx",
)

STDLIB_MODULES = getattr(sys, "stdlib_module_names", None) or set(
    sys.builtin_module_names
)


class ImportParser(Parser):

    def __init__(self, root_path: Path):
        super().__init__()
        self.root_path: Path = root_path
        self._GO_MODULE_CACHE: dict[str, str | None] = {}

    def _get_go_module_name(self) -> str | None:
        """Reads the module path from go.mod if present."""
        root_str = str(self.root_path)
        if root_str in self._GO_MODULE_CACHE:
            return self._GO_MODULE_CACHE[root_str]

        go_mod_file = self.root_path / "go.mod"
        module_name = None
        if go_mod_file.exists():
            for line in go_mod_file.read_text(
                encoding="utf-8", errors="ignore"
            ).splitlines():
                line = line.strip()
                if line.startswith("module "):
                    module_name = line.split()[1].strip("'\"")
                    break

        self._GO_MODULE_CACHE[root_str] = module_name
        return module_name

    def _resolve_import(
        self,
        import_path: str,
        language: str,
        context: dict | None = None,
    ) -> dict:
        if not self.file_path:
            return {"category": "unknown", "resolved_path": None}

        context = context or {}
        project_root_path = Path(self.root_path).resolve()
        current_dir = Path(self.file_path).parent.resolve()
        import_path = import_path.strip("'\"`;")

        # -------------------------------------------------------------------
        # SMART ROOT RESOLUTION (Bottom-Up Traversal)
        # -------------------------------------------------------------------
        # Traverse upwards from the current file's directory to the provided root.
        # This makes resolution resilient if `self.root_path` is 2-4 levels too high.
        search_roots = [current_dir]
        curr = current_dir
        found_markers = []

        # Markers that indicate we've hit a true repository/project boundary
        repo_markers = {
            ".git",
            "package.json",
            "pom.xml",
            "build.gradle",
            "pyproject.toml",
            "go.mod",
        }

        while curr != project_root_path and curr != curr.parent:
            curr = curr.parent
            if curr not in search_roots:
                search_roots.append(curr)

            # Keep track of directories that have project markers
            if any((curr / m).exists() for m in repo_markers):
                found_markers.append(curr)

        if project_root_path not in search_roots:
            search_roots.append(project_root_path)

        if any((project_root_path / m).exists() for m in repo_markers):
            found_markers.append(project_root_path)

        # Use the highest found marker as the actual project boundary for heavy globbing.
        # Fallback to the provided project_root_path if no markers are found.
        actual_repo_root = found_markers[-1] if found_markers else project_root_path

        # -------------------------------------------------------------------
        # GO
        # -------------------------------------------------------------------
        if language == "go":
            if import_path.startswith("./") or import_path.startswith("../"):
                resolved = (current_dir / import_path).resolve()
                return {"category": "internal", "resolved_path": str(resolved)}

            # 1. Find nearest go.mod upwards through search_roots
            go_module_name = context.get("go_module_name")
            go_mod_dir = None

            for base_dir in search_roots:
                go_mod_file = base_dir / "go.mod"
                if go_mod_file.exists():
                    go_mod_dir = base_dir
                    # Auto-extract module name from go.mod if not provided in context
                    if not go_module_name:
                        try:
                            with open(go_mod_file, "r", encoding="utf-8") as f:
                                for line in f:
                                    line = line.strip()
                                    if line.startswith("module "):
                                        go_module_name = line.split()[1].strip("\"`'")
                                        break
                        except Exception:
                            pass
                    break  # Stop at the closest go.mod to current_dir

            # 2. Resolve internal package against the go.mod directory
            if go_module_name and import_path.startswith(go_module_name):
                sub_path = import_path[len(go_module_name) :].lstrip("/")

                # Internal package path is relative to where go.mod actually lives
                target_dir = (
                    (go_mod_dir / sub_path)
                    if go_mod_dir
                    else (project_root_path / sub_path)
                )
                resolved_dir = target_dir.resolve()

                if resolved_dir.exists() and resolved_dir.is_dir():
                    return {
                        "category": "internal",
                        "resolved_path": str(resolved_dir),
                    }
                return {"category": "internal", "resolved_path": None}

            # 3. Standard Library check (Go stdlib has no '.' in first segment, e.g. "fmt", "net/http")
            first_segment = import_path.split("/")[0]
            if "." not in first_segment:
                return {"category": "stdlib", "resolved_path": None}

            return {"category": "external", "resolved_path": None}

        # -------------------------------------------------------------------
        # JAVA
        # -------------------------------------------------------------------
        elif language == "java":
            if any(import_path.startswith(p) for p in JAVA_STDLIB_PREFIXES):
                return {"category": "stdlib", "resolved_path": None}

            clean_path = import_path.removesuffix(".*")
            parts = clean_path.split(".")

            path_candidates = []
            for i in range(len(parts), 0, -1):
                path_candidates.append("/".join(parts[:i]))

            for base_path in path_candidates:
                rel_file_path = base_path + ".java"
                rel_dir_path = base_path

                # 1. Fast direct checks walking UP the directory tree
                for base_dir in search_roots:
                    for root_prefix in ["", "src", "src/main/java", "src/test/java"]:
                        root_path = base_dir / root_prefix if root_prefix else base_dir

                        candidate_file = root_path / rel_file_path
                        if candidate_file.exists() and candidate_file.is_file():
                            return {
                                "category": "internal",
                                "resolved_path": str(candidate_file),
                            }

                        candidate_dir = root_path / rel_dir_path
                        if candidate_dir.exists() and candidate_dir.is_dir():
                            return {
                                "category": "internal",
                                "resolved_path": str(candidate_dir),
                            }

                # 2. Multi-module layouts using globbing (Restricted to actual_repo_root to prevent hanging)
                for pattern_root in ("src/main/java", "src/test/java"):
                    matches = list(
                        actual_repo_root.glob(f"**/{pattern_root}/{rel_file_path}")
                    )
                    if matches:
                        return {
                            "category": "internal",
                            "resolved_path": str(matches[0]),
                        }

                    dir_matches = list(
                        actual_repo_root.glob(f"**/{pattern_root}/{rel_dir_path}")
                    )
                    if dir_matches and dir_matches[0].is_dir():
                        return {
                            "category": "internal",
                            "resolved_path": str(dir_matches[0]),
                        }

            return {"category": "external", "resolved_path": None}

        # -------------------------------------------------------------------
        # JAVASCRIPT / TYPESCRIPT
        # -------------------------------------------------------------------
        elif language in ("javascript", "typescript"):
            if (
                import_path.startswith("node:")
                or import_path.split("/")[0] in NODE_BUILTINS
            ):
                return {"category": "stdlib", "resolved_path": None}

            if import_path.startswith("./") or import_path.startswith("../"):
                base = (current_dir / import_path).resolve()
                for suffix in JS_TS_SUFFIXES:
                    candidate = (
                        base / suffix.lstrip("/")
                        if suffix.startswith("/")
                        else Path(str(base) + suffix)
                    )
                    if candidate.exists() and candidate.is_file():
                        return {"category": "internal", "resolved_path": str(candidate)}
                return {"category": "internal", "resolved_path": None}

            # Handle Aliases (e.g., @/components or ~/utils) by checking up the tree
            if import_path.startswith("@/") or import_path.startswith("~/"):
                rel = import_path.split("/", 1)[1]
                for base_dir in search_roots:
                    # Aliases usually point directly to /src/ or the folder itself
                    for src_base in (base_dir / "src", base_dir):
                        candidate_base = src_base / rel
                        for suffix in JS_TS_SUFFIXES:
                            candidate = (
                                candidate_base / suffix.lstrip("/")
                                if suffix.startswith("/")
                                else Path(str(candidate_base) + suffix)
                            )
                            if candidate.exists() and candidate.is_file():
                                return {
                                    "category": "internal",
                                    "resolved_path": str(candidate),
                                }
                return {"category": "internal", "resolved_path": None}

            return {"category": "external", "resolved_path": None}

        # -------------------------------------------------------------------
        # PYTHON
        # -------------------------------------------------------------------
        elif language == "python":
            if import_path.split(".")[0] in STDLIB_MODULES:
                return {"category": "stdlib", "resolved_path": None}

            if import_path.startswith("."):
                level = len(import_path) - len(import_path.lstrip("."))
                module_part = import_path.lstrip(".")
                base_dir = current_dir
                for _ in range(level - 1):
                    base_dir = base_dir.parent
                if module_part:
                    candidate_file = base_dir / (module_part.replace(".", "/") + ".py")
                    candidate_pkg = (
                        base_dir / module_part.replace(".", "/") / "__init__.py"
                    )
                else:
                    candidate_file = None
                    candidate_pkg = base_dir / "__init__.py"

                for c in (candidate_file, candidate_pkg):
                    if c and c.exists():
                        return {"category": "internal", "resolved_path": str(c)}
                return {"category": "internal", "resolved_path": None}

            top_level_module = import_path.split(".")[0]
            rest = import_path.split(".")[1:]

            # Traverse upwards checking each root for the top-level module
            for base_dir in search_roots:
                for src_root in (base_dir, base_dir / "src"):
                    candidate_file = src_root / top_level_module
                    for part in rest:
                        candidate_file = candidate_file / part

                    py_file = Path(str(candidate_file) + ".py")
                    init_file = candidate_file / "__init__.py"

                    if py_file.exists():
                        return {"category": "internal", "resolved_path": str(py_file)}
                    if init_file.exists():
                        return {"category": "internal", "resolved_path": str(init_file)}

            return {"category": "external", "resolved_path": None}
        # -------------------------------------------------------------------
        # RUST
        # -------------------------------------------------------------------
        elif language == "rust":
            if import_path.startswith(("std::", "core::", "alloc::")):
                return {"category": "stdlib", "resolved_path": None}

            if import_path.startswith(("crate::", "super::", "self::")):
                # resolvable in principle by walking module tree from current file;
                # left unresolved here (best-effort) unless you build the mod-tree mapper
                return {"category": "internal", "resolved_path": None}

            first_segment = import_path.split("::")[0]
            rust_crates = context.get("rust_crates", {})
            if first_segment in rust_crates:
                return {
                    "category": "internal",
                    "resolved_path": rust_crates[first_segment],
                }

            return {"category": "external", "resolved_path": None}

        return {"category": "external", "resolved_path": None}

    def _parse_item(self, item: str) -> dict:
        cleaned = item.strip().strip("{}").strip()
        match = re.split(r"\bas\b", cleaned, maxsplit=1)
        if len(match) > 1:
            return {"name": match[0].strip(), "alias": match[1].strip()}
        return {"name": cleaned, "alias": None}

    def _extract_js_ts_imports(self, parent_node: Node):
        chunks = []

        for node in parent_node.children:
            # ----------------------------------------------------
            # 1. ES6 Imports: import { Car } from './Car.js'
            # ----------------------------------------------------
            if node.type == "import_statement":
                data = {
                    "source": None,
                    "module_alias": None,
                    "symbols": [],
                    "file_type": "unknown",
                    "resolved_path": None,
                    "is_wildcard": False,
                }
                for child in node.children:
                    if child.type == "string":
                        # Remove quotes: '"./Car.js"' -> './Car.js'
                        data["source"] = self._text(child).strip("'\"`")
                        resolved_import = self._resolve_import(
                            data["source"], "javascript"
                        )
                        data["file_type"] = resolved_import.get("category", "unknown")
                        data["resolved_path"] = resolved_import.get(
                            "resolved_path", None
                        )
                    elif child.type == "import_clause":
                        clause = self._text(child).strip()
                        if clause.startswith("* as "):
                            data["is_wildcard"] = True

                        data["symbols"] = [
                            self._parse_item(item)
                            for item in self._text(child).split(",")
                            if item.strip()
                        ]

                # Default for side-effect imports like: import './setup.js'
                if not data["symbols"]:
                    data["symbols"].append({"name": "*", "alias": None})

                chunks.append(data)

            # ----------------------------------------------------
            # 2. CommonJS Require: const car = require('./Car.js')
            # ----------------------------------------------------
            elif node.type in ("lexical_declaration", "variable_declaration"):
                for declarator in node.children:
                    if declarator.type != "variable_declarator":
                        continue

                    value_node = declarator.child_by_field_name("value")
                    if not value_node:
                        continue

                    # Identify if value_node is direct require() or chained require().property
                    req_call_node = None
                    if value_node.type == "call_expression":
                        req_call_node = value_node
                    elif value_node.type == "member_expression":
                        obj = value_node.child_by_field_name("object")
                        if obj and obj.type == "call_expression":
                            req_call_node = obj

                    if not req_call_node:
                        continue

                    # Ensure the function being called is actually 'require'
                    func_node = req_call_node.child_by_field_name("function")
                    if not func_node or self._text(func_node) != "require":
                        continue

                    # Extract the imported path safely from string node children
                    args_node = req_call_node.child_by_field_name("arguments")
                    if not args_node:
                        continue

                    source = None
                    for arg in args_node.children:
                        if arg.type == "string":
                            source = self._text(arg).strip("'\"`")
                            resolved_import = self._resolve_import(source, "javascript")
                            category = resolved_import.get("category", "unknown")
                            resolved_path = resolved_import.get("resolved_path", None)
                            break

                    if not source:
                        continue

                    # Build data object with standardized fields
                    data = {
                        "source": source,
                        "module_alias": None,
                        "symbols": [],
                        "file_type": category,
                        "resolved_path": resolved_path,
                        "is_wildcard": False,
                    }
                    name_node = declarator.child_by_field_name("name")

                    if name_node:
                        if name_node.type == "object_pattern":
                            # Destructured: const { car, truck } = require(...)
                            raw_clause = self._text(name_node)
                            data["symbols"].extend(
                                [
                                    (
                                        {
                                            "name": item.split(":")[0].strip(),
                                            "alias": item.split(":")[1].strip(),
                                        }
                                        if ":" in item
                                        else {"name": item.strip(), "alias": None}
                                    )
                                    for item in raw_clause.strip("{} \n\r\t").split(",")
                                    if item.strip()
                                ]
                            )
                        else:
                            # Standard: const car = require(...)
                            raw_clause = self._text(name_node)
                            data["symbols"].extend(
                                [
                                    {"name": item.strip(), "alias": None}
                                    for item in raw_clause.split(",")
                                    if item.strip()
                                ]
                            )
                    else:
                        data["symbols"].extend([{"name": "*", "alias": None}])

                    chunks.append(data)

        return {"package": None, "language": self.language, "imports": chunks}

    def _check_dynamic_import(self, node: Node):
        """Helper to find importlib.import_module(...) or __import__(...)"""

        # If passed an assignment node, extract the call node from the right-hand side
        call_node = node
        if node.type == "assignment":
            call_node = node.child_by_field_name("right")
            if not call_node or call_node.type != "call":
                call_node = next((c for c in node.children if c.type == "call"), None)

        if not call_node or call_node.type != "call":
            return None

        func_node = call_node.child_by_field_name("function")
        if not func_node:
            return None

        func_text = self._text(func_node)

        # Check if it's importlib.import_module or __import__
        if func_text in ("importlib.import_module", "__import__"):
            args_node = call_node.child_by_field_name("arguments")
            if args_node and args_node.children:
                # Pehla argument package/module ka name hota hai
                for arg in args_node.children:
                    # Skip commas and parentheses
                    if arg.type in ("(", ")", ","):
                        continue

                    mod_name = None
                    if arg.type == "string":
                        # Quotes (' ' ya " ") hatana
                        mod_name = self._text(arg).strip("'\"")
                    elif arg.type in ("identifier", "dotted_name"):
                        # For variables like module_name
                        mod_name = self._text(arg)

                    if mod_name:
                        resolved_import = self._resolve_import(mod_name, "python")
                        file_type = resolved_import.get("category", "unknown")
                        resolved_path = resolved_import.get("resolved_path", None)
                        return {
                            "source": mod_name,
                            "module_alias": None,
                            "symbols": [],
                            "file_type": file_type,
                            "resolved_path": resolved_path,
                            "is_wildcard": False,
                            "is_dynamic": True,
                        }
        return None

    def _extract_py_imports(self, parent_node: Node):
        chunks = []

        for node in parent_node.children:
            # Case 1: handles "from foo import bar, baz"
            if node.type == "import_from_statement":
                data = {
                    "source": None,
                    "module_alias": None,
                    "symbols": [],
                    "file_type": "unknown",
                    "resolved_path": None,
                    "is_wildcard": False,
                }

                # Tree-sitter standard field for the module source
                module_node = node.child_by_field_name("module_name")
                if module_node:
                    data["source"] = self._text(module_node)
                    resolved_import = self._resolve_import(data["source"], "python")
                    data["file_type"] = resolved_import.get("category", "unknown")
                    data["resolved_path"] = resolved_import.get("resolved_path", None)

                # Extract imported items (names)
                for child in node.children:
                    if (
                        child.type in ("wildcard_import", "*")
                        or self._text(child) == "*"
                    ):
                        data["is_wildcard"] = True
                    elif child.type in ("dotted_name", "aliased_import", "identifier"):
                        # Avoid adding module source or keywords to symbols
                        if child != module_node and self._text(child) not in (
                            "from",
                            "import",
                        ):
                            text = self._text(child)
                            data["symbols"].append(self._parse_item(text))
                    elif child.type == "import_prefix":
                        # For relative imports like "from . import foo"
                        if not data["source"]:
                            data["source"] = self._text(child)
                            resolved_import = self._resolve_import(
                                data["source"], "python"
                            )
                            data["file_type"] = resolved_import.get(
                                "category", "unknown"
                            )
                            data["resolved_path"] = resolved_import.get(
                                "resolved_path", None
                            )

                chunks.append(data)

            # Case 2: handles "import foo, bar as b"
            elif node.type == "import_statement":
                chunk_data = []

                for child in node.children:
                    if child.type in ("dotted_name", "aliased_import"):
                        data = {
                            "source": None,
                            "module_alias": None,
                            "symbols": [],
                            "file_type": "unknown",
                            "resolved_path": None,
                            "is_wildcard": False,
                        }

                        if child.type == "aliased_import":
                            # Extract 'name' (source) and 'alias' nodes from tree-sitter
                            name_node = child.child_by_field_name("name")
                            alias_node = child.child_by_field_name("alias")

                            # Fallbacks in case tree-sitter field names are absent in your grammar build
                            if not name_node:
                                name_node = next(
                                    (
                                        c
                                        for c in child.children
                                        if c.type in ("dotted_name", "identifier")
                                    ),
                                    None,
                                )
                            if not alias_node:
                                alias_node = next(
                                    (
                                        c
                                        for c in reversed(child.children)
                                        if c.type == "identifier" and c != name_node
                                    ),
                                    None,
                                )

                            if name_node:
                                data["source"] = self._text(name_node)
                            if alias_node:
                                data["module_alias"] = self._text(alias_node)
                        else:
                            # Standard import without alias (e.g., import os)
                            data["source"] = self._text(child)

                        # Resolve paths and categories once source is set
                        if data["source"]:
                            resolved_import = self._resolve_import(
                                data["source"], "python"
                            )
                            data["file_type"] = resolved_import.get(
                                "category", "unknown"
                            )
                            data["resolved_path"] = resolved_import.get(
                                "resolved_path", None
                            )
                            chunk_data.append(data)

                if chunk_data:
                    chunks.extend(chunk_data)
            # print("Node Type : ", node.type, "Text : ", self._text(node))
            # if node.type == "assignment":
            #     print("call node found", self._text(node), node.type)
            #     dyn_data = self._check_dynamic_import(node)
            #     if dyn_data:
            #         chunks.append(dyn_data)

        return {"package": None, "language": self.language, "imports": chunks}

    def _extract_java_imports_and_package(self, parent_node: Node):
        result = {"package": None, "language": self.language, "imports": []}

        # Java me top-level nodes direct parent_node (program) ke children hote hain
        for node in parent_node.children:

            # Case 1: Package declaration (e.g., "package com.example.project;")
            if node.type == "package_declaration":
                for child in node.children:
                    if child.type in ("scoped_identifier", "identifier"):
                        result["package"] = self._text(child)
                        break

            # Case 2: Import statements
            elif node.type == "import_declaration":
                import_info = {
                    "source": None,
                    "module_alias": None,
                    "symbols": [],
                    "file_type": "unknown",
                    "resolved_path": None,
                    "is_wildcard": False,
                    "is_static": False,
                }

                for child in node.children:
                    # Static imports check (e.g., import static ...)
                    if child.type == "static":
                        import_info["is_static"] = True

                    # Main path/class identifier (e.g., java.util.List)
                    elif child.type in ("scoped_identifier", "identifier"):
                        import_info["source"] = self._text(child)
                        resolved_import = self._resolve_import(
                            import_info["source"], "java"
                        )
                        import_info["file_type"] = resolved_import.get(
                            "category", "unknown"
                        )
                        import_info["resolved_path"] = resolved_import.get(
                            "resolved_path", None
                        )

                    # Wildcard imports check (e.g., import java.util.*)
                    elif child.type == "asterisk":
                        import_info["is_wildcard"] = True

                # Agar wildcard star (*) tha to path me suffix append kar do
                if import_info["is_wildcard"] and import_info["source"]:
                    resolved_import = self._resolve_import(
                        import_info["source"], "java"
                    )
                    import_info["file_type"] = resolved_import.get(
                        "category", "unknown"
                    )
                    import_info["resolved_path"] = resolved_import.get(
                        "resolved_path", None
                    )
                    import_info["source"] += ".*"

                if import_info["source"]:
                    result["imports"].append(import_info)

        return result

    def _extract_go_imports(self, parent_node: Node, context: str | None):
        imports = []

        for node in parent_node.children:
            if node.type == "import_declaration":
                # import_declaration ke andar single import_spec ya import_spec_list hota hai
                for child in node.children:
                    if child.type == "import_spec_list":
                        # Grouped import block: import ( ... )
                        for spec in child.children:
                            if spec.type == "import_spec":
                                imports.append(
                                    self._parse_go_import_spec(spec, context)
                                )

                    elif child.type == "import_spec":
                        # Single import line: import "fmt"
                        imports.append(self._parse_go_import_spec(child, context))

        return {"package": None, "language": self.language, "imports": imports}

    def _parse_go_import_spec(self, spec_node: Node, context: str | None):

        path_node = spec_node.child_by_field_name("path")
        name_node = spec_node.child_by_field_name("name")

        # Path se surrounding double quotes (" ") hatane ke liye .strip('"')
        path = self._text(path_node).strip('"`') if path_node else ""
        alias = self._text(name_node) if name_node else None
        resolved_import = self._resolve_import(path, "go", {"go_module_name": context})
        file_type = resolved_import.get("category", "unknown")
        resolved_path = resolved_import.get("resolved_path", None)

        return {
            "source": path,  # e.g., "math/rand" ya "github.com/lib/pq"
            "module_alias": alias,  # e.g., "m", "_", "." ya None (agar standard import ho)
            "symbols": [],
            "file_type": file_type,
            "resolved_path": resolved_path,
            "is_wildcard": False,
        }

    def extract_imports(self, file_path: Path) -> dict[str, str | list]:
        if not file_path.exists():
            raise FileNotFoundError("The file send does not exist", file_path)

        self._set_file_path(file_path)
        self.source_bytes = self._get_source_bytes()
        # self.root_path = root_path

        tree = self.parse_ast()
        if not tree:
            raise ValueError("Either language or file_path is not defined.")

        parent_node = tree.root_node

        if self.language == "java":
            return self._extract_java_imports_and_package(parent_node)
        elif self.language == "python":
            return self._extract_py_imports(parent_node)
        elif self.language in ("javascript", "typescript"):
            return self._extract_js_ts_imports(parent_node)
        elif self.language == "go":
            context = self._get_go_module_name()
            return self._extract_go_imports(parent_node, context)
        else:
            raise ValueError(
                "Language is not supported so far, switched to simple chunking."
            )
