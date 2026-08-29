from tree_sitter import Node
from pathlib import Path
from pygments.lexers import get_lexer_for_filename
from pygments.util import ClassNotFound
from tree_sitter_language_pack import get_parser, get_language
from tree_sitter import Node
import sys
from parser import Parser

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

        """
        Returns {"category": "stdlib" | "internal" | "external", "resolved_path": str | None}

        `context` carries per-repo data computed ONCE per indexing job (not per call):
        - context["go_module_name"]: str, from go.mod
        - context["rust_crates"]: dict[str, str] mapping crate name -> crate root dir,
                                    from workspace Cargo.toml
        Pass these in rather than re-reading go.mod/Cargo.toml on every import.
        """
        context = context or {}
        project_root_path = Path(self.root_path).resolve()
        current_dir = Path(self.file_path).parent.resolve()
        import_path = import_path.strip("'\"`;")

        # -------------------------------------------------------------------
        # GO
        # -------------------------------------------------------------------
        if language == "go":
            if import_path.startswith("./") or import_path.startswith("../"):
                resolved = (current_dir / import_path).resolve()
                return {"category": "internal", "resolved_path": str(resolved)}

            go_module_name = context.get("go_module_name")
            if go_module_name and import_path.startswith(go_module_name):
                # Go imports resolve to a PACKAGE (directory), not a single file --
                # a Go package is typically many files sharing one directory.
                sub_path = import_path[len(go_module_name) :].lstrip("/")
                resolved_dir = project_root_path / sub_path
                return {
                    "category": "internal",
                    "resolved_path": (
                        str(resolved_dir) if resolved_dir.exists() else None
                    ),
                }

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

            # Wildcard imports ke liye .* remove karein
            clean_path = import_path.removesuffix(".*")
            parts = clean_path.split(".")

            # Candidates generate karein taaki static imports aur inner classes handle ho sakein
            # Example: com.example.Car.MAX_SPEED -> pehle 'com/example/Car/MAX_SPEED.java' check karega,
            # fir fallback karke 'com/example/Car.java' check karega.
            path_candidates = []
            for i in range(len(parts), 0, -1):
                path_candidates.append("/".join(parts[:i]))

            for base_path in path_candidates:
                rel_file_path = base_path + ".java"
                rel_dir_path = base_path

                # 1. Fast direct checks in common roots (Flat layout, src, and Maven/Gradle layouts)
                for root_prefix in ["", "src", "src/main/java", "src/test/java"]:
                    root_path = (
                        project_root_path / root_prefix
                        if root_prefix
                        else project_root_path
                    )

                    # Check for exact file
                    candidate_file = root_path / rel_file_path
                    if candidate_file.exists() and candidate_file.is_file():
                        return {
                            "category": "internal",
                            "resolved_path": str(candidate_file),
                        }

                    # Check for directory (for wildcard package imports like com.example.vehicle.*)
                    candidate_dir = root_path / rel_dir_path
                    if candidate_dir.exists() and candidate_dir.is_dir():
                        return {
                            "category": "internal",
                            "resolved_path": str(candidate_dir),
                        }

                # 2. Multi-module Maven/Gradle layouts using globbing
                for pattern_root in ("src/main/java", "src/test/java"):
                    matches = list(
                        project_root_path.glob(f"**/{pattern_root}/{rel_file_path}")
                    )
                    if matches:
                        return {
                            "category": "internal",
                            "resolved_path": str(matches[0]),
                        }
                    dir_matches = list(
                        project_root_path.glob(f"**/{pattern_root}/{rel_dir_path}")
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
                    if suffix.startswith("/"):
                        candidate = base / suffix.lstrip("/")
                    else:
                        candidate = Path(str(base) + suffix)
                    if candidate.exists() and candidate.is_file():
                        return {"category": "internal", "resolved_path": str(candidate)}
                return {
                    "category": "internal",
                    "resolved_path": None,
                }  # relative but unresolved

            # Common alias convention (Next.js/Vue default) -- best-effort, not tsconfig-aware
            if import_path.startswith("@/") or import_path.startswith("~/"):
                rel = import_path.split("/", 1)[1]
                base = project_root_path / "src" / rel
                for suffix in JS_TS_SUFFIXES:
                    if suffix.startswith("/"):
                        candidate = base / suffix.lstrip("/")
                    else:
                        candidate = Path(str(base) + suffix)
                    if candidate.exists() and candidate.is_file():
                        return {"category": "internal", "resolved_path": str(candidate)}
                return {"category": "internal", "resolved_path": None}

            return {"category": "external", "resolved_path": None}

        # -------------------------------------------------------------------
        # PYTHON
        # -------------------------------------------------------------------
        elif language == "python":
            if import_path.split(".")[0] in STDLIB_MODULES:
                return {"category": "stdlib", "resolved_path": None}

            if import_path.startswith("."):
                # count leading dots = how many dirs up; strip them for the module part
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
            for src_root in (project_root_path, project_root_path / "src"):
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

    def _extract_js_ts_imports(self, parent_node: Node):
        chunks = []

        for node in parent_node.children:
            # ----------------------------------------------------
            # 1. ES6 Imports: import { Car } from './Car.js'
            # ----------------------------------------------------
            if node.type == "import_statement":
                data = {}
                for child in node.children:
                    if child.type == "string":
                        # Remove quotes: '"./Car.js"' -> './Car.js'
                        data["source"] = self._text(child).strip("'\"`")
                        resolved_import = self._resolve_import(
                            data["source"], "javascript"
                        )
                        data["file_type"] = resolved_import.get("category", "unkown")
                        data["resolved_path"] = resolved_import.get(
                            "resolved_path", None
                        )
                    elif child.type == "import_clause":
                        data["clause"] = [
                            item.strip()
                            for item in self._text(child).split(",")
                            if item.strip()
                        ]

                # Default for side-effect imports like: import './setup.js'
                if "clause" not in data:
                    data["clause"].extend("*")

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
                            category = resolved_import.get("category", "unkown")
                            resolved_path = resolved_import.get("resolved_path", None)
                            break

                    if not source:
                        continue

                    # Build data object only when a valid import is confirmed
                    data = {
                        "source": source,
                        "file_type": category,
                        "resolved_path": resolved_path,
                        "clause": [],
                    }
                    name_node = declarator.child_by_field_name("name")

                    if name_node:
                        if name_node.type == "object_pattern":
                            # Destructured: const { car, truck } = require(...)
                            raw_clause = self._text(name_node)
                            data["clause"].extend(
                                [
                                    item.strip()
                                    for item in raw_clause.strip("{} \n\r\t").split(",")
                                    if item.strip()
                                ]
                            )
                        else:
                            # Standard: const car = require(...)
                            data["clause"].extend(
                                [
                                    item.strip()
                                    for item in self._text(child).split(",")
                                    if item.strip()
                                ]
                            )
                    else:
                        data["clause"].extend(["*"])

                    chunks.append(data)

        return chunks

    def _check_dynamic_import(self, call_node: Node):
        """Helper to find importlib.import_module(...) or __import__(...)"""

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
                    if arg.type == "string":
                        # Quotes (' ' ya " ") hatana
                        mod_name = self._text(arg).strip("'\"")
                        resolved_import = self._resolve_import(mod_name, "python")
                        file_type = resolved_import.get("category", "unknown")
                        resolved_path = resolved_import.get("resolved_path", None)
                        return {
                            "source": mod_name,
                            "clause": [],
                            "file_type": file_type,
                            "is_dynamic": True,
                            "resolved_path": resolved_path,
                        }
        return None

    def _extract_py_imports(self, parent_node: Node):
        chunks = []

        for node in parent_node.children:
            # Case 1: handles "from foo import bar, baz"
            if node.type == "import_from_statement":
                data = {"source": "", "clause": []}

                # Tree-sitter standard field for the module source
                module_node = node.child_by_field_name("module_name")
                if module_node:
                    data["source"] = self._text(module_node)
                    resolved_import = self._resolve_import(data["source"], "python")
                    data["file_type"] = resolved_import.get("category", "unknown")
                    data["resolved_path"] = resolved_import.get("resolved_path", None)

                # Extract imported items (names)
                for child in node.children:
                    if child.type in ("dotted_name", "aliased_import", "identifier"):
                        # Avoid adding the module source itself to clauses
                        if child != module_node:
                            data["clause"].append(self._text(child))
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
                data = {"source": None, "clause": []}

                for child in node.children:
                    if child.type in ("dotted_name", "aliased_import"):
                        if child.type == "aliased_import":
                            for c in child.children:
                                if c.type == "dotted_name":
                                    source = self._text(c)
                                    resolved_import = self._resolve_import(
                                        source, "python"
                                    )
                                    data["file_type"] = resolved_import.get(
                                        "category", "unknown"
                                    )
                                    data["resolved_path"] = resolved_import.get(
                                        "resolved_path", None
                                    )
                        else:
                            source = self._text(child)
                            resolved_import = self._resolve_import(source, "python")
                            data["file_type"] = resolved_import.get(
                                "category", "unknown"
                            )
                            data["resolved_path"] = resolved_import.get(
                                "resolved_path", None
                            )
                        data["clause"].append(self._text(child))

                if data["clause"]:
                    chunks.append(data)

            elif node.type == "call":
                dyn_data = self._check_dynamic_import(node)
                if dyn_data:
                    chunks.append(dyn_data)

        return chunks

    def _extract_java_imports_and_package(self, parent_node: Node):
        result = {"package": None, "imports": []}

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
                import_info = {"path": "", "is_static": False, "is_wildcard": False}

                for child in node.children:
                    # Static imports check (e.g., import static ...)
                    if child.type == "static":
                        import_info["is_static"] = True

                    # Main path/class identifier (e.g., java.util.List)
                    elif child.type in ("scoped_identifier", "identifier"):
                        import_info["path"] = self._text(child)
                        resolved_import = self._resolve_import(
                            import_info["path"], "java"
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
                if import_info["is_wildcard"] and import_info["path"]:
                    resolved_import = self._resolve_import(import_info["path"], "java")
                    import_info["file_type"] = resolved_import.get(
                        "category", "unknown"
                    )
                    import_info["resolved_path"] = resolved_import.get(
                        "resolved_path", None
                    )
                    import_info["path"] += ".*"

                if import_info["path"]:
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

        return imports

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
            "alias": alias,  # e.g., "m", "_", "." ya None (agar standard import ho)
            "file_type": file_type,
            "resolved_path": resolved_path,
        }

    def extract_imports(self, file_path: Path, root_path: Path):
        if not file_path.exists():
            raise FileNotFoundError("The file send does not exist", file_path)

        self._set_file_path(file_path)
        self.source_bytes = self._get_source_bytes(file_path)
        self.root_path = root_path

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
            return ValueError(
                "Language is not supported so far, switched to simple chunking."
            )
