"""Tree-sitter based Python parser for extracting function definitions"""

import os
import textwrap
from typing import Dict, List, Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node


PY_LANGUAGE = Language(tspython.language())


class TreeSitterParser:
    """Parse Python files using tree-sitter and extract function definitions"""

    def __init__(self):
        self._parser = Parser(PY_LANGUAGE)

    def parse_file(self, file_path: str, repo_root: str) -> List[Dict]:
        """
        Parse a Python file and return all function/method definitions.

        Args:
            file_path: Absolute path to the Python file
            repo_root: Absolute path to the repository root

        Returns:
            List of function dicts for every function/method in the file
        """
        with open(file_path, "r", encoding="utf-8") as f:
            source_code = f.read()

        relative_path = os.path.relpath(file_path, repo_root)
        return self.parse_source(source_code, relative_path)

    def parse_source(self, source_code: str, relative_path: str) -> List[Dict]:
        """
        Parse source code string and return all function definitions.

        Args:
            source_code: Python source code as string
            relative_path: Relative file path for metadata

        Returns:
            List of function dicts
        """
        source_bytes = source_code.encode("utf-8")
        tree = self._parser.parse(source_bytes)
        return self._extract_functions(tree.root_node, source_bytes, relative_path)

    def _extract_functions(
        self,
        node: Node,
        source_bytes: bytes,
        relative_path: str,
        parent_class: Optional[str] = None,
        parent_function: Optional[str] = None,
    ) -> List[Dict]:
        """
        Recursively walk the tree-sitter AST and extract function definitions.
        Handles: top-level functions, class methods, nested functions, async functions.
        """
        functions = []

        for child in node.children:
            # Handle decorated definitions (unwrap to get the inner function/class)
            actual_node = child
            decorators = []
            if child.type == "decorated_definition":
                decorators = self._get_decorators(child, source_bytes)
                # The actual function or class is the last child of decorated_definition
                for sub in child.children:
                    if sub.type in ("function_definition", "class_definition"):
                        actual_node = sub
                        break

            if actual_node.type == "function_definition":
                func_info = self._build_function_dict(
                    actual_node, child, source_bytes, relative_path,
                    parent_class, parent_function, decorators,
                )
                functions.append(func_info)

                # Recurse into the function body for nested functions
                body_node = self._get_body_node(actual_node)
                if body_node:
                    nested = self._extract_functions(
                        body_node, source_bytes, relative_path,
                        parent_class=parent_class,
                        parent_function=func_info["qualified_name"],
                    )
                    functions.extend(nested)

            elif actual_node.type == "class_definition":
                class_name = self._get_node_name(actual_node, source_bytes)
                if class_name:
                    # Recurse into class body with parent_class set
                    body_node = self._get_body_node(actual_node)
                    if body_node:
                        methods = self._extract_functions(
                            body_node, source_bytes, relative_path,
                            parent_class=class_name,
                            parent_function=parent_function,
                        )
                        functions.extend(methods)

        return functions

    def _build_function_dict(
        self,
        func_node: Node,
        outer_node: Node,
        source_bytes: bytes,
        relative_path: str,
        parent_class: Optional[str],
        parent_function: Optional[str],
        decorators: List[str],
    ) -> Dict:
        """Build a function info dict from a function_definition node."""
        name = self._get_node_name(func_node, source_bytes)

        # Build qualified name
        if parent_function:
            qualified_name = f"{parent_function}.{name}"
        elif parent_class:
            qualified_name = f"{parent_class}.{name}"
        else:
            qualified_name = name

        # Use outer_node (decorated_definition if present) for full source and line numbers
        # tree-sitter lines are 0-indexed, convert to 1-indexed
        start_line = outer_node.start_point[0] + 1
        end_line = outer_node.end_point[0] + 1
        source_code = self._node_text(outer_node, source_bytes)

        docstring = self._get_docstring(func_node, source_bytes)
        if not decorators:
            decorators = self._get_decorators_from_func(func_node, source_bytes)
        parameters = self._get_parameters(func_node, source_bytes)

        is_method = parent_class is not None
        is_nested = parent_function is not None

        return {
            "name": name,
            "qualified_name": qualified_name,
            "file_path": relative_path,
            "start_line": start_line,
            "end_line": end_line,
            "source_code": source_code,
            "docstring": docstring,
            "is_method": is_method,
            "parent_class": parent_class,
            "is_nested": is_nested,
            "parent_function": parent_function,
            "decorators": decorators,
            "parameters": parameters,
        }

    def _get_node_name(self, node: Node, source_bytes: bytes) -> str:
        """Get the name identifier from a function or class definition node."""
        for child in node.children:
            if child.type == "identifier":
                return self._node_text(child, source_bytes)
        return ""

    def _get_body_node(self, node: Node) -> Optional[Node]:
        """Get the block (body) node from a function or class definition."""
        for child in node.children:
            if child.type == "block":
                return child
        return None

    def _get_docstring(self, func_node: Node, source_bytes: bytes) -> Optional[str]:
        """Extract docstring from the first expression_statement child if it is a string."""
        body = self._get_body_node(func_node)
        if not body or not body.children:
            return None

        first_stmt = body.children[0]
        if first_stmt.type == "expression_statement":
            for child in first_stmt.children:
                if child.type == "string":
                    raw = self._node_text(child, source_bytes)
                    # Strip triple quotes
                    for quote in ('"""', "'''", '"', "'"):
                        if raw.startswith(quote) and raw.endswith(quote):
                            raw = raw[len(quote):-len(quote)]
                            break
                    return textwrap.dedent(raw).strip()
        return None

    def _get_decorators(self, decorated_node: Node, source_bytes: bytes) -> List[str]:
        """Extract decorator names from a decorated_definition node."""
        decorators = []
        for child in decorated_node.children:
            if child.type == "decorator":
                # Get the text after '@'
                dec_text = self._node_text(child, source_bytes)
                # Strip the '@' prefix and whitespace
                dec_text = dec_text.lstrip("@").strip()
                decorators.append(dec_text)
        return decorators

    def _get_decorators_from_func(self, func_node: Node, source_bytes: bytes) -> List[str]:
        """Extract decorators directly attached to a function_definition (if any)."""
        # In tree-sitter-python, decorators are children of decorated_definition,
        # not function_definition directly. This is a fallback that returns empty.
        return []

    def _get_parameters(self, func_node: Node, source_bytes: bytes) -> List[str]:
        """Extract parameter names from function parameters node."""
        params = []
        for child in func_node.children:
            if child.type == "parameters":
                for param_child in child.children:
                    if param_child.type == "identifier":
                        params.append(self._node_text(param_child, source_bytes))
                    elif param_child.type in (
                        "default_parameter",
                        "typed_parameter",
                        "typed_default_parameter",
                    ):
                        # First child is the name identifier
                        for sub in param_child.children:
                            if sub.type == "identifier":
                                params.append(self._node_text(sub, source_bytes))
                                break
                    elif param_child.type == "list_splat_pattern":
                        # *args
                        for sub in param_child.children:
                            if sub.type == "identifier":
                                params.append("*" + self._node_text(sub, source_bytes))
                                break
                    elif param_child.type == "dictionary_splat_pattern":
                        # **kwargs
                        for sub in param_child.children:
                            if sub.type == "identifier":
                                params.append("**" + self._node_text(sub, source_bytes))
                                break
                break
        return params

    def _node_text(self, node: Node, source_bytes: bytes) -> str:
        """Get the text content of a tree-sitter node."""
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8")
