"""Call graph construction from parsed function definitions"""

import textwrap
from typing import Dict, List, Optional, Tuple

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node


PY_LANGUAGE = Language(tspython.language())


class CallGraphBuilder:
    """Build a call graph from parsed function definitions"""

    def __init__(self, functions: List[Dict]):
        self._parser = Parser(PY_LANGUAGE)
        self._functions = functions
        self._name_index = self._build_name_index(functions)
        self._qualified_index = {f["qualified_name"]: f for f in functions}

    def build(self) -> List[Dict]:
        """
        Build the complete call graph.

        Returns:
            List of call graph edge dicts
        """
        edges = []
        for func in self._functions:
            try:
                func_edges = self._extract_calls_from_function(func)
                edges.extend(func_edges)
            except Exception as e:
                print(f"WARNING: Failed to extract calls from {func['qualified_name']}: {e}")
        return edges

    def _build_name_index(self, functions: List[Dict]) -> Dict[str, List[Dict]]:
        """
        Build a lookup from simple function name -> list of function dicts.
        Used for cross-file resolution by name.
        """
        index = {}
        for func in functions:
            name = func["name"]
            if name not in index:
                index[name] = []
            index[name].append(func)
        return index

    def _extract_calls_from_function(self, func: Dict) -> List[Dict]:
        """
        Parse the source code of a single function and find all function calls.

        Returns:
            List of call graph edge dicts with this function as the caller
        """
        source = func["source_code"]
        # Dedent so tree-sitter can parse method bodies as valid code
        dedented = textwrap.dedent(source)
        source_bytes = dedented.encode("utf-8")
        tree = self._parser.parse(source_bytes)

        raw_calls = self._find_calls_in_node(tree.root_node, source_bytes)

        edges = []
        seen = set()
        for callee_name, relative_line, is_self_call in raw_calls:
            # Compute absolute line number
            line_number = func["start_line"] + relative_line

            resolved_qname, resolved_file, is_resolved = self._resolve_callee(
                callee_name, func, is_self_call
            )

            # Deduplicate edges within the same function
            edge_key = (func["qualified_name"], resolved_qname, line_number)
            if edge_key in seen:
                continue
            seen.add(edge_key)

            edges.append({
                "caller_qualified_name": func["qualified_name"],
                "callee_qualified_name": resolved_qname,
                "caller_file": func["file_path"],
                "callee_file": resolved_file,
                "line_number": line_number,
                "is_resolved": is_resolved,
            })

        return edges

    def _find_calls_in_node(self, node: Node, source_bytes: bytes) -> List[Tuple[str, int, bool]]:
        """
        Recursively find all call expressions within a tree-sitter node.

        Returns:
            List of (callee_name, line_number_0indexed, is_self_call) tuples
        """
        calls = []

        if node.type == "call":
            func_node = node.children[0] if node.children else None
            if func_node:
                callee_name, is_self_call = self._extract_callee_name(func_node, source_bytes)
                if callee_name:
                    line = node.start_point[0]
                    calls.append((callee_name, line, is_self_call))

        for child in node.children:
            calls.extend(self._find_calls_in_node(child, source_bytes))

        return calls

    def _extract_callee_name(self, node: Node, source_bytes: bytes) -> Tuple[str, bool]:
        """
        Extract the callee name from the function part of a call expression.

        Returns:
            (callee_name, is_self_call)
        """
        if node.type == "identifier":
            return self._node_text(node, source_bytes), False

        if node.type == "attribute":
            # e.g., self.foo, obj.bar, a.b.c
            parts = self._get_attribute_parts(node, source_bytes)
            if len(parts) >= 2 and parts[0] == "self":
                # self.method() -> method name, is_self_call=True
                return parts[-1], True
            else:
                # obj.method() -> just the method name, best-effort
                return parts[-1], False

        return None, False

    def _get_attribute_parts(self, node: Node, source_bytes: bytes) -> List[str]:
        """Get all parts of a dotted attribute access (e.g., a.b.c -> ['a', 'b', 'c'])."""
        if node.type == "identifier":
            return [self._node_text(node, source_bytes)]

        if node.type == "attribute":
            parts = []
            for child in node.children:
                if child.type == "identifier":
                    parts.append(self._node_text(child, source_bytes))
                elif child.type == "attribute":
                    parts.extend(self._get_attribute_parts(child, source_bytes))
            return parts

        return []

    def _resolve_callee(
        self, callee_name: str, caller: Dict, is_self_call: bool
    ) -> Tuple[str, Optional[str], bool]:
        """
        Resolve a callee name to a qualified_name and file_path.

        Resolution strategy (in priority order):
        1. self.method() -> same-class method in same file
        2. Same-file, module-level function
        3. Cross-file, exact qualified_name match
        4. Cross-file, unqualified name match (best-effort, pick first)
        5. Unresolved

        Returns:
            (resolved_qualified_name, resolved_file_path, is_resolved)
        """
        caller_file = caller["file_path"]
        caller_class = caller.get("parent_class")

        # 1. self.method() -> same-class method in same file
        if is_self_call and caller_class:
            qualified = f"{caller_class}.{callee_name}"
            if qualified in self._qualified_index:
                match = self._qualified_index[qualified]
                if match["file_path"] == caller_file:
                    return qualified, match["file_path"], True

        # 2. Same-file, module-level function
        candidates = self._name_index.get(callee_name, [])
        for candidate in candidates:
            if candidate["file_path"] == caller_file and not candidate["is_method"]:
                return candidate["qualified_name"], candidate["file_path"], True

        # 3. Cross-file, exact qualified_name match
        if callee_name in self._qualified_index:
            match = self._qualified_index[callee_name]
            return match["qualified_name"], match["file_path"], True

        # 4. Cross-file, unqualified name match (best-effort)
        if candidates:
            match = candidates[0]
            return match["qualified_name"], match["file_path"], True

        # 5. Unresolved
        return callee_name, None, False

    def _node_text(self, node: Node, source_bytes: bytes) -> str:
        """Get the text content of a tree-sitter node."""
        return source_bytes[node.start_byte:node.end_byte].decode("utf-8")
