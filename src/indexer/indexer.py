"""Codebase indexer orchestrator"""

import json
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

import tree_sitter_python as tspython
from tree_sitter import Language, Parser, Node

from src.indexer.parser import TreeSitterParser
from src.indexer.call_graph import CallGraphBuilder
from src.indexer.summarizer import ModuleSummarizer
from src.shared.llm_client import LLMClient
from constants import INDEXER_EXCLUDE_PATTERNS, INDEXER_OUTPUT_FILE


PY_LANGUAGE = Language(tspython.language())


class CodebaseIndexer:
    """Indexes a Python codebase: parses functions, builds call graph, generates summaries"""

    def __init__(self, repo_path: str, llm_client: Optional[LLMClient] = None):
        """
        Initialize the codebase indexer.

        Args:
            repo_path: Absolute path to the repository root
            llm_client: LLM client for generating summaries (None to skip summaries)
        """
        self._repo_path = os.path.abspath(repo_path)
        self._parser = TreeSitterParser()
        self._summarizer = ModuleSummarizer(llm_client) if llm_client else None

    def index(self, output_path: Optional[str] = None, skip_summaries: bool = False) -> Dict:
        """
        Index the entire codebase.

        Args:
            output_path: Path to write the JSON index file. If None, uses default.
            skip_summaries: If True, skip LLM-generated module summaries.

        Returns:
            The complete index dict
        """
        print("Starting codebase indexing...")
        print(f"Repository: {self._repo_path}")

        # Step 1: Discover Python files
        py_files = self._discover_python_files()
        print(f"Found {len(py_files)} Python files")

        # Step 2: Parse all files
        all_functions = []
        file_data_list = []
        skipped_files = []
        errors = []

        for file_path in py_files:
            relative_path = os.path.relpath(file_path, self._repo_path)

            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    source_code = f.read()
            except Exception as e:
                print(f"WARNING: Could not read {relative_path}: {e}")
                skipped_files.append(relative_path)
                continue

            try:
                functions = self._parser.parse_file(file_path, self._repo_path)
                all_functions.extend(functions)

                class_count = self._count_classes_in_file(source_code)
                file_data_list.append({
                    "file_path": relative_path,
                    "source_code": source_code,
                    "function_count": len(functions),
                    "class_count": class_count,
                })

                print(f"  Parsed {relative_path}: {len(functions)} functions, {class_count} classes")
            except Exception as e:
                print(f"WARNING: Could not parse {relative_path}: {e}")
                errors.append(f"Parse error in {relative_path}: {e}")

        print(f"Extracted {len(all_functions)} function definitions")

        # Step 3: Build call graph
        print("Building call graph...")
        builder = CallGraphBuilder(all_functions)
        call_graph = builder.build()
        resolved_count = sum(1 for e in call_graph if e["is_resolved"])
        print(f"Built call graph with {len(call_graph)} edges ({resolved_count} resolved)")

        # Step 4: Generate module summaries
        summaries = []
        if skip_summaries or not self._summarizer:
            print("Skipping module summaries")
        else:
            print("Generating module summaries...")
            summaries = self._summarizer.summarize_files(file_data_list)
            print(f"Generated {len(summaries)} module summaries")

        # Step 5: Assemble index
        index = {
            "repo_path": self._repo_path,
            "indexed_at": datetime.now(timezone.utc).isoformat(),
            "python_files_count": len(py_files),
            "functions": all_functions,
            "call_graph": call_graph,
            "module_summaries": summaries,
            "skipped_files": skipped_files,
            "errors": errors,
        }

        # Step 6: Write to JSON
        if output_path is None:
            output_path = os.path.join(self._repo_path, INDEXER_OUTPUT_FILE)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

        print(f"Index written to {output_path}")
        return index

    def _discover_python_files(self) -> List[str]:
        """Walk the repo and find all .py files, excluding patterns from constants."""
        py_files = []

        for root, dirs, files in os.walk(self._repo_path):
            # Filter out excluded directories in-place (prevents os.walk from descending)
            dirs[:] = [
                d for d in dirs
                if not self._should_skip_dir(d)
            ]

            for filename in files:
                if not filename.endswith(".py"):
                    continue

                file_path = os.path.join(root, filename)
                if self._should_skip_file(filename, file_path):
                    continue

                py_files.append(file_path)

        py_files.sort()
        return py_files

    def _should_skip_dir(self, dirname: str) -> bool:
        """Check if a directory should be excluded from traversal."""
        for pattern in INDEXER_EXCLUDE_PATTERNS:
            # Directory patterns end with /
            if pattern.endswith("/") and dirname == pattern.rstrip("/"):
                return True
            # Exact directory name match
            if dirname == pattern:
                return True
        return False

    def _should_skip_file(self, filename: str, file_path: str) -> bool:
        """Check if a file should be skipped based on exclude patterns."""
        for pattern in INDEXER_EXCLUDE_PATTERNS:
            if pattern.endswith("/"):
                # Directory pattern, skip for files
                continue
            # File prefix pattern (e.g., "test_")
            if not pattern.startswith(".") and not pattern.startswith("_") and filename.startswith(pattern):
                return True
            # File suffix pattern (e.g., "_test.py")
            if pattern.startswith("_") and filename.endswith(pattern):
                return True
            # Exact filename match (e.g., "conftest.py")
            if filename == pattern:
                return True
        return False

    def _count_classes_in_file(self, source_code: str) -> int:
        """Count top-level class definitions in source code using tree-sitter."""
        parser = Parser(PY_LANGUAGE)
        source_bytes = source_code.encode("utf-8")
        tree = parser.parse(source_bytes)

        count = 0
        for child in tree.root_node.children:
            if child.type == "class_definition":
                count += 1
            elif child.type == "decorated_definition":
                for sub in child.children:
                    if sub.type == "class_definition":
                        count += 1
                        break
        return count
