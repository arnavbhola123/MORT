"""Context assembler for gathering relevant context around a target function"""

from typing import Dict, List, Optional, Set

from constants import (
    CONTEXT_DEFAULT_MAX_CALLERS,
    CONTEXT_DEFAULT_MAX_CALLEES,
    CONTEXT_DEFAULT_CALLER_DEPTH,
    CONTEXT_DEFAULT_CALLEE_DEPTH,
)


class ContextBundle:
    """
    A bundle of context gathered around a target function.

    Provides formatting methods to convert the context into prompt-ready strings
    and utilities for token estimation.
    """

    def __init__(
        self,
        target_function: Dict,
        callers: List[Dict],
        callees: List[Dict],
        module_summaries: Dict[str, str],
        config: Dict,
    ):
        self._target_function = target_function
        self._callers = callers
        self._callees = callees
        self._module_summaries = module_summaries
        self._config = config

    @property
    def target_function(self) -> Dict:
        return self._target_function

    @property
    def callers(self) -> List[Dict]:
        return self._callers

    @property
    def callees(self) -> List[Dict]:
        return self._callees

    @property
    def module_summaries(self) -> Dict[str, str]:
        return self._module_summaries

    @property
    def config(self) -> Dict:
        return self._config

    def to_dict(self) -> Dict:
        """Return the bundle as a plain dict for serialization"""
        return {
            "target_function": self._target_function,
            "callers": self._callers,
            "callees": self._callees,
            "module_summaries": self._module_summaries,
            "config": self._config,
        }

    def format_for_prompt(self) -> str:
        """
        Format the context bundle into a prompt-ready string with clear sections.

        Returns:
            A formatted string suitable for inclusion in LLM prompts
        """
        sections = []

        # Module context (target file summary)
        target_file = self._target_function["file_path"]
        if target_file in self._module_summaries:
            sections.append("=== MODULE CONTEXT ===")
            sections.append(self._module_summaries[target_file])
            sections.append("")

        # Target function
        sections.append("=== TARGET FUNCTION ===")
        tf = self._target_function
        sections.append(
            f"File: {tf['file_path']} (lines {tf['start_line']}-{tf['end_line']})"
        )
        sections.append(f"'''{tf['source_code']}'''")
        sections.append("")

        # Callers
        if self._callers:
            sections.append("=== FUNCTIONS THAT CALL THIS (CALLERS) ===")
            for i, caller in enumerate(self._callers, 1):
                sections.append(
                    f"# Caller {i}: {caller['qualified_name']} "
                    f"({caller['file_path']}:{caller['call_line']})"
                )
                sections.append(f"'''{caller['source_code']}'''")
                sections.append("")

        # Callees
        if self._callees:
            sections.append("=== FUNCTIONS THIS CALLS (CALLEES) ===")
            for i, callee in enumerate(self._callees, 1):
                sections.append(
                    f"# Callee {i}: {callee['qualified_name']} "
                    f"({callee['file_path']}:{callee['call_line']})"
                )
                sections.append(f"'''{callee['source_code']}'''")
                sections.append("")

        # Related module summaries (excluding target file, already shown above)
        related_summaries = {
            fp: summary
            for fp, summary in self._module_summaries.items()
            if fp != target_file
        }
        if related_summaries:
            sections.append("=== RELATED MODULE SUMMARIES ===")
            for fp, summary in related_summaries.items():
                sections.append(f"# {fp}")
                sections.append(summary)
                sections.append("")

        return "\n".join(sections)

    def estimate_tokens(self) -> int:
        """
        Estimate the token count of the formatted context.

        Uses a simple heuristic of ~4 characters per token.

        Returns:
            Estimated token count
        """
        formatted = self.format_for_prompt()
        return len(formatted) // 4


class ContextAssembler:
    """
    Assembles context around a target function using the codebase index.

    Given a function name, collects:
    - The target function's source code
    - Direct callers (functions that call the target)
    - Direct callees (functions the target calls)
    - Module summaries for relevant files
    """

    def __init__(self, index: Dict):
        """
        Initialize the context assembler.

        Args:
            index: The codebase index dict (from codebase_index.json)
        """
        self._index = index
        self._functions = index.get("functions", [])
        self._call_graph = index.get("call_graph", [])
        self._summaries = index.get("module_summaries", [])

        # Build lookup indexes for efficient querying
        self._qualified_index = {f["qualified_name"]: f for f in self._functions}
        self._name_index = self._build_name_index()
        self._summary_index = {s["file_path"]: s["summary"] for s in self._summaries}

    def _build_name_index(self) -> Dict[str, List[Dict]]:
        """Build a lookup from simple function name to list of matching functions"""
        index = {}
        for func in self._functions:
            name = func["name"]
            if name not in index:
                index[name] = []
            index[name].append(func)
        return index

    def assemble(
        self,
        function_name: str,
        max_callers: int = CONTEXT_DEFAULT_MAX_CALLERS,
        max_callees: int = CONTEXT_DEFAULT_MAX_CALLEES,
        caller_depth: int = CONTEXT_DEFAULT_CALLER_DEPTH,
        callee_depth: int = CONTEXT_DEFAULT_CALLEE_DEPTH,
        include_summaries: bool = True,
    ) -> ContextBundle:
        """
        Assemble context around a target function.

        Args:
            function_name: Qualified name (e.g., "ClassName.method") or simple name
            max_callers: Maximum number of callers to include
            max_callees: Maximum number of callees to include
            caller_depth: How many levels of callers to traverse (1 = direct only)
            callee_depth: How many levels of callees to traverse (1 = direct only)
            include_summaries: Whether to include module summaries

        Returns:
            ContextBundle with the assembled context

        Raises:
            ValueError: If function not found or name is ambiguous
        """
        # Find the target function
        target = self._find_function(function_name)
        qualified_name = target["qualified_name"]

        # Collect callers and callees
        callers = self._get_callers(qualified_name, caller_depth, max_callers)
        callees = self._get_callees(qualified_name, callee_depth, max_callees)

        # Collect module summaries
        summaries = {}
        if include_summaries:
            file_paths = {target["file_path"]}
            file_paths.update(c["file_path"] for c in callers)
            file_paths.update(c["file_path"] for c in callees)
            summaries = self._get_module_summaries(file_paths)

        config = {
            "max_callers": max_callers,
            "max_callees": max_callees,
            "caller_depth": caller_depth,
            "callee_depth": callee_depth,
            "include_summaries": include_summaries,
        }

        return ContextBundle(
            target_function={
                "qualified_name": target["qualified_name"],
                "file_path": target["file_path"],
                "source_code": target["source_code"],
                "start_line": target["start_line"],
                "end_line": target["end_line"],
                "docstring": target.get("docstring"),
            },
            callers=callers,
            callees=callees,
            module_summaries=summaries,
            config=config,
        )

    def _find_function(self, name: str) -> Dict:
        """
        Find a function by name in the index.

        Args:
            name: Qualified name or simple name

        Returns:
            The function dict

        Raises:
            ValueError: If not found or ambiguous
        """
        # Try exact qualified name match first
        if name in self._qualified_index:
            return self._qualified_index[name]

        # Try simple name match
        candidates = self._name_index.get(name, [])
        if len(candidates) == 1:
            return candidates[0]
        elif len(candidates) > 1:
            qualified_names = [c["qualified_name"] for c in candidates]
            raise ValueError(
                f"Ambiguous function name '{name}'. "
                f"Matches: {', '.join(qualified_names)}. "
                f"Please use the qualified name."
            )
        else:
            raise ValueError(f"Function '{name}' not found in index")

    def _get_callers(
        self, qualified_name: str, depth: int, max_count: int
    ) -> List[Dict]:
        """
        Get functions that call the target function.

        Args:
            qualified_name: Target function's qualified name
            depth: How many levels to traverse
            max_count: Maximum callers to return

        Returns:
            List of caller dicts with source code and call line info
        """
        callers = []
        visited: Set[str] = set()
        to_visit = [(qualified_name, 0)]  # (name, current_depth)

        while to_visit and len(callers) < max_count:
            current_name, current_depth = to_visit.pop(0)

            if current_depth >= depth:
                continue

            # Find edges where this function is the callee
            for edge in self._call_graph:
                if edge["callee_qualified_name"] != current_name:
                    continue

                caller_qname = edge["caller_qualified_name"]
                if caller_qname in visited:
                    continue
                visited.add(caller_qname)

                # Get the caller function's info
                if caller_qname not in self._qualified_index:
                    continue

                func = self._qualified_index[caller_qname]
                callers.append({
                    "qualified_name": caller_qname,
                    "file_path": func["file_path"],
                    "source_code": func["source_code"],
                    "call_line": edge["line_number"],
                })

                if len(callers) >= max_count:
                    break

                # Queue for deeper traversal
                if current_depth + 1 < depth:
                    to_visit.append((caller_qname, current_depth + 1))

        return callers[:max_count]

    def _get_callees(
        self, qualified_name: str, depth: int, max_count: int
    ) -> List[Dict]:
        """
        Get functions that the target function calls.

        Args:
            qualified_name: Target function's qualified name
            depth: How many levels to traverse
            max_count: Maximum callees to return

        Returns:
            List of callee dicts with source code and call line info
        """
        callees = []
        visited: Set[str] = set()
        to_visit = [(qualified_name, 0)]

        while to_visit and len(callees) < max_count:
            current_name, current_depth = to_visit.pop(0)

            if current_depth >= depth:
                continue

            # Find edges where this function is the caller
            for edge in self._call_graph:
                if edge["caller_qualified_name"] != current_name:
                    continue

                # Only include resolved callees
                if not edge.get("is_resolved", False):
                    continue

                callee_qname = edge["callee_qualified_name"]
                if callee_qname in visited:
                    continue
                visited.add(callee_qname)

                # Get the callee function's info
                if callee_qname not in self._qualified_index:
                    continue

                func = self._qualified_index[callee_qname]
                callees.append({
                    "qualified_name": callee_qname,
                    "file_path": func["file_path"],
                    "source_code": func["source_code"],
                    "call_line": edge["line_number"],
                })

                if len(callees) >= max_count:
                    break

                # Queue for deeper traversal
                if current_depth + 1 < depth:
                    to_visit.append((callee_qname, current_depth + 1))

        return callees[:max_count]

    def _get_module_summaries(self, file_paths: Set[str]) -> Dict[str, str]:
        """
        Get module summaries for the given file paths.

        Args:
            file_paths: Set of file paths to get summaries for

        Returns:
            Dict mapping file_path to summary text
        """
        return {
            fp: self._summary_index[fp]
            for fp in file_paths
            if fp in self._summary_index
        }

    def list_functions(self) -> List[str]:
        """
        List all function qualified names in the index.

        Returns:
            Sorted list of qualified names
        """
        return sorted(self._qualified_index.keys())
