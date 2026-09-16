from pathlib import Path
from typing import Union
import sys
import json
import re
import yaml
import xml.etree.ElementTree as ET

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


class DependenciesParser:
    def __init__(self, file_path: Union[str, Path] | None = None) -> None:
        self.file_path = Path(file_path) if file_path else None

    def set_file_path(self, file_path: Union[str, Path]) -> None:
        self.file_path = Path(file_path)

    def parse_package_json(self) -> dict:
        if not self.file_path:
            raise ValueError("FILE PATH IS NOT DEFINED, PLEASE DEFINE THE FILE PATH")
        file_path = Path(self.file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            raise ValueError(f"Failed to read or parse JSON file: {e}")

        # Standard dependency sections in package.json and their mapped type names
        dependency_types = {
            "dependencies": "prod",
            "devDependencies": "dev",
            "peerDependencies": "peer",
            "optionalDependencies": "optional",
            "bundledDependencies": "bundled",
        }

        dependencies = []
        details = {}

        # Extract details vs dependencies
        for key, value in data.items():
            if key in dependency_types:
                dep_type = dependency_types.get(key, key)
                if isinstance(value, dict):
                    for dep_name, dep_version in value.items():
                        dependencies.append(
                            {
                                "name": dep_name,
                                "version": str(dep_version),
                                "type": dep_type,
                            }
                        )
                elif isinstance(value, list) and key == "bundledDependencies":
                    # bundledDependencies can sometimes be a list of string names
                    for dep_name in value:
                        dependencies.append(
                            {
                                "name": str(dep_name),
                                "version": "*",
                                "type": dep_type,
                            }
                        )
            else:
                details[key] = value

        return {
            "details": details,
            "dependencies": dependencies,
        }

    def parse_pyproject_toml(self) -> dict:
        if not self.file_path:
            raise ValueError("FILE PATH IS NOT DEFINED, PLEASE DEFINE THE FILE PATH")
        file_path = Path(self.file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "rb") as f:
                data = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as e:
            raise ValueError(f"Failed to read or parse TOML file: {e}")

        dependencies = []

        # 1. PEP 621 Standard metadata ([project])
        project = data.get("project", {})

        for dep in project.get("dependencies", []):
            name, version = self._parse_dependency_string(dep)
            dependencies.append({"name": name, "version": version, "type": "prod"})

        optional_deps = project.get("optional-dependencies", {})
        for group_name, group_deps in optional_deps.items():
            for dep in group_deps:
                name, version = self._parse_dependency_string(dep)
                dependencies.append(
                    {"name": name, "version": version, "type": f"optional:{group_name}"}
                )

        # 2. PEP 735 / uv Dependency Groups ([dependency-groups])
        dep_groups = data.get("dependency-groups", {})
        for group_name, group_deps in dep_groups.items():
            if isinstance(group_deps, list):
                for dep in group_deps:
                    if isinstance(dep, str):
                        name, version = self._parse_dependency_string(dep)
                        dependencies.append(
                            {"name": name, "version": version, "type": group_name}
                        )

        # 3. Poetry format ([tool.poetry])
        poetry = data.get("tool", {}).get("poetry", {})
        if poetry:
            for dep_name, dep_val in poetry.get("dependencies", {}).items():
                if dep_name.lower() == "python":
                    continue
                version = self._extract_poetry_version(dep_val)
                dependencies.append(
                    {"name": dep_name, "version": version, "type": "prod"}
                )

            for dep_name, dep_val in poetry.get("dev-dependencies", {}).items():
                version = self._extract_poetry_version(dep_val)
                dependencies.append(
                    {"name": dep_name, "version": version, "type": "dev"}
                )

            groups = poetry.get("group", {})
            for group_name, group_data in groups.items():
                for dep_name, dep_val in group_data.get("dependencies", {}).items():
                    version = self._extract_poetry_version(dep_val)
                    dependencies.append(
                        {"name": dep_name, "version": version, "type": group_name}
                    )

        # Clean up details dict to remove extracted dependency keys
        details = data.copy()

        if "dependency-groups" in details:
            del details["dependency-groups"]

        if "project" in details:
            details["project"] = {
                k: v
                for k, v in details["project"].items()
                if k not in ("dependencies", "optional-dependencies")
            }

        if "tool" in details and "poetry" in details["tool"]:
            poetry_details = details["tool"]["poetry"].copy()
            for key in ("dependencies", "dev-dependencies", "group"):
                poetry_details.pop(key, None)

            # If python version constraint was under dependencies, keep python in project details
            if "dependencies" in poetry and "python" in poetry["dependencies"]:
                poetry_details["python"] = poetry["dependencies"]["python"]

            details["tool"]["poetry"] = poetry_details

        return {
            "details": details,
            "dependencies": dependencies,
        }

    def _parse_dependency_string(self, req_str: str) -> tuple[str, str]:
        """Extract the package name and version specifier."""
        match = re.split(
            r"(===|==|>=|<=|~=|=~|!=|<|>|=)",
            req_str,
            maxsplit=1,
        )

        if len(match) > 1:
            name = match[0].strip()
            version = f"{match[1]}{match[2]}".strip()
            return name, version

        return req_str.strip(), "*"

    def _extract_poetry_version(self, dep_val: Union[str, dict]) -> str:
        """Extracts version specifier from Poetry's string or dictionary notation."""
        if isinstance(dep_val, str):
            return dep_val
        elif isinstance(dep_val, dict):
            return dep_val.get("version", "*")
        return "*"

    def parse_requirements_txt(self) -> dict:
        if not self.file_path:
            raise ValueError("FILE PATH IS NOT DEFINED, PLEASE DEFINE THE FILE PATH")
        file_path = Path(self.file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except OSError as e:
            raise ValueError(f"Failed to read file: {e}")

        # Infer type based on file name or parent folder (e.g., 'dev-requirements.txt' -> 'dev')
        dep_type = self._infer_dependency_type(file_path)
        dependencies = []

        for line in lines:
            cleaned_line = line.strip()

            # Skip empty lines, comments, and file reference flags (-r, -c, --extra-index-url, etc.)
            if (
                not cleaned_line
                or cleaned_line.startswith("#")
                or cleaned_line.startswith("-")
            ):
                continue

            # Strip inline comments (e.g., "requests>=2.25.0 # HTTP library")
            cleaned_line = cleaned_line.split("#")[0].strip()

            # Strip environment markers (e.g., "importlib-metadata; python_version < '3.8'")
            cleaned_line = cleaned_line.split(";")[0].strip()

            if cleaned_line:
                name, version = self._parse_dependency_string(cleaned_line)
                dependencies.append(
                    {
                        "name": name,
                        "version": version,
                        "type": dep_type,
                    }
                )

        return {
            "details": {},
            "dependencies": dependencies,
        }

    def _infer_dependency_type(self, file_path: Path) -> str:
        """Infers dependency type from file name or containing directory."""
        name_lower = file_path.stem.lower()  # Filename without extension
        parent_lower = file_path.parent.name.lower()

        # Common keyword mappings
        keywords = ["dev", "test", "prod", "production", "local", "doc", "docs", "base"]

        for kw in keywords:
            if kw in name_lower or kw in parent_lower:
                return "prod" if kw in ("production", "base") else kw

        return "prod"

    def parse_environment_yml(self) -> dict:
        if not self.file_path:
            raise ValueError("FILE PATH IS NOT DEFINED, PLEASE DEFINE THE FILE PATH")
        file_path = Path(self.file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (OSError, yaml.YAMLError) as e:
            raise ValueError(f"Failed to read or parse YAML file: {e}")

        dependencies = []
        details = {}

        # Extract top-level metadata into details
        for key, value in data.items():
            if key != "dependencies":
                details[key] = value

        # Parse dependencies section
        raw_deps = data.get("dependencies", [])
        for dep in raw_deps:
            if isinstance(dep, str):
                # Standard Conda package string (e.g. "python=3.11", "numpy>=1.20")
                name, version = self._parse_dependency_string(dep)
                dependencies.append(
                    {
                        "name": name,
                        "version": version,
                        "type": "conda",
                    }
                )
            elif isinstance(dep, dict) and "pip" in dep:
                # Nested pip packages under Conda environment
                pip_deps = dep.get("pip", [])
                for pip_dep in pip_deps:
                    if isinstance(pip_dep, str):
                        name, version = self._parse_pip_dependency(pip_dep)
                        dependencies.append(
                            {
                                "name": name,
                                "version": version,
                                "type": "pip",
                            }
                        )

        return {
            "details": details,
            "dependencies": dependencies,
        }

    def _parse_pip_dependency(self, dep_str: str) -> tuple[str, str]:
        """Parses standard pip package strings and strips comments or environment markers."""

        cleaned = dep_str.split("#")[0].split(";")[0].strip()
        match = re.split(r"(==|>=|<=|~=|=~|!=|<|>)", cleaned, maxsplit=1)
        if len(match) > 1:
            name = match[0].strip()
            version = f"{match[1]}{match[2]}".strip()
            return name, version

        return cleaned.strip(), "*"

    def parse_pom_xml(self) -> dict:
        if not self.file_path:
            raise ValueError("FILE PATH IS NOT DEFINED, PLEASE DEFINE THE FILE PATH")
        file_path = Path(self.file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
        except (OSError, ET.ParseError) as e:
            raise ValueError(f"Failed to read or parse XML file: {e}")

        namespace = ""
        if root.tag.startswith("{"):
            namespace = root.tag.split("}")[0] + "}"

        def ns(tag: str) -> str:
            return f"{namespace}{tag}"

        # 1. Parent POM details (extracted early for fallback)
        parent_info = {}
        parent_node = root.find(ns("parent"))
        if parent_node is not None:
            for p_key in ["groupId", "artifactId", "version"]:
                p_elem = parent_node.find(ns(p_key))
                if p_elem is not None and p_elem.text:
                    parent_info[p_key] = p_elem.text.strip()

        # 2. Extract Project Details with parent fallback
        details = {}
        direct_details_keys = [
            "groupId",
            "artifactId",
            "version",
            "name",
            "description",
            "packaging",
            "url",
        ]
        for key in direct_details_keys:
            node = root.find(ns(key))
            if node is not None and node.text:
                details[key] = node.text.strip()

        # Inherit groupId/version from parent if missing at root level
        if "groupId" not in details and "groupId" in parent_info:
            details["groupId"] = parent_info["groupId"]
        if "version" not in details and "version" in parent_info:
            details["version"] = parent_info["version"]

        # 3. Build Properties Dictionary (Explicit + Implicit)
        properties = {}
        properties_node = root.find(ns("properties"))
        if properties_node is not None:
            for prop in properties_node:
                tag_name = prop.tag.replace(namespace, "")
                properties[tag_name] = prop.text.strip() if prop.text else ""

        # Inject implicit Maven variables
        properties["project.version"] = details.get("version", "")
        properties["project.groupId"] = details.get("groupId", "")
        properties["project.artifactId"] = details.get("artifactId", "")
        properties["version"] = details.get("version", "")
        properties["groupId"] = details.get("groupId", "")

        # Regex-based variable resolver for inline & nested properties
        def resolve_val(value: str) -> str:
            if not value:
                return ""

            def replace_match(match):
                key = match.group(1)
                return properties.get(key, match.group(0))

            previous = None
            current = value
            while current != previous and "${" in current:
                previous = current
                current = re.sub(r"\$\{([^}]+)\}", replace_match, current)
            return current

        # Resolve variables inside project details
        for k, v in details.items():
            details[k] = resolve_val(v)

        if properties:
            details["properties"] = properties

        if parent_info:
            details["parent"] = {k: resolve_val(v) for k, v in parent_info.items()}

        # 4. Extract Dependencies
        dependencies = []

        def parse_dep_node(dep_node, default_type="compile"):
            group_id = dep_node.find(ns("groupId"))
            artifact_id = dep_node.find(ns("artifactId"))
            version_node = dep_node.find(ns("version"))
            scope_node = dep_node.find(ns("scope"))

            if group_id is not None and artifact_id is not None:
                g_text = resolve_val(group_id.text.strip()) if group_id.text else ""
                a_text = (
                    resolve_val(artifact_id.text.strip()) if artifact_id.text else ""
                )
                v_text = (
                    resolve_val(version_node.text.strip())
                    if (version_node is not None and version_node.text)
                    else "managed"
                )
                scope = (
                    scope_node.text.strip()
                    if (scope_node is not None and scope_node.text)
                    else default_type
                )

                dependencies.append(
                    {
                        "name": f"{g_text}:{a_text}",
                        "version": v_text,
                        "type": scope,
                    }
                )

        deps_node = root.find(ns("dependencies"))
        if deps_node is not None:
            for dep in deps_node.findall(ns("dependency")):
                parse_dep_node(dep)

        dep_mgmt_node = root.find(ns("dependencyManagement"))
        if dep_mgmt_node is not None:
            mgmt_deps_node = dep_mgmt_node.find(ns("dependencies"))
            if mgmt_deps_node is not None:
                for dep in mgmt_deps_node.findall(ns("dependency")):
                    parse_dep_node(dep, default_type="dependency-management")

        return {
            "details": details,
            "dependencies": dependencies,
        }

    def parse_go_mod(self) -> dict:
        if not self.file_path:
            raise ValueError("FILE PATH IS NOT DEFINED, PLEASE DEFINE THE FILE PATH")
        file_path = Path(self.file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        try:
            content = file_path.read_text(encoding="utf-8")
        except OSError as e:
            raise ValueError(f"Failed to read go.mod file: {e}")

        details = {}
        dependencies = []
        in_block = None

        for line in content.splitlines():
            line = line.strip()

            # Skip empty lines or top-level comment-only lines
            if not line or line.startswith("//"):
                continue

            # Handle block openings (e.g., "require (") and closures
            if line.endswith("("):
                in_block = line.split()[0]
                continue
            elif line == ")":
                in_block = None
                continue

            # Determine directive context
            if in_block:
                directive = in_block
                statement = line
            else:
                parts = line.split(maxsplit=1)
                directive = parts[0]
                statement = parts[1] if len(parts) > 1 else ""

            # Extract root module details
            if directive == "module":
                details["name"] = statement.split("//")[0].strip()
            elif directive == "go":
                details["goVersion"] = statement.split("//")[0].strip()
            elif directive == "toolchain":
                details["toolchain"] = statement.split("//")[0].strip()

            # Extract dependencies
            elif directive == "require":
                is_indirect = "// indirect" in statement
                clean_stmt = statement.split("//")[0].strip()
                parts = clean_stmt.split()

                if len(parts) >= 2:
                    dependencies.append(
                        {
                            "name": parts[0],
                            "version": parts[1],
                            "type": "indirect" if is_indirect else "direct",
                        }
                    )

        return {
            "details": details,
            "dependencies": dependencies,
        }
