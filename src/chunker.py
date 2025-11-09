"""Code chunking utilities using LLM or AST"""

import json
import re
import os
import ast
import hashlib
from typing import Dict, List, Optional
from src.llm_client import LLMClient
from constants import MODEL, MODEL_PROVIDER


class CodeChunker:
    """Extract mutable code chunks from Python files using LLM or AST"""

    def __init__(self, mode: str = "llm", cache_dir: str = ".chunk_cache"):
        """
        Initialize the code chunker.

        Args:
            mode: Chunking mode - "llm" for LLM-based or "ast" for AST-based
            cache_dir: Directory for caching chunks (used in both modes)
        """
        self.mode = mode.lower()
        if self.mode not in ["llm", "ast"]:
            raise ValueError(f"Invalid mode: {mode}. Must be 'llm' or 'ast'")

        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

        if self.mode == "llm":
            self.llm = LLMClient(MODEL, MODEL_PROVIDER)

    def extract_chunks(self, code: str, file_path: str) -> Dict:
        """
        Extract code chunks from a Python file.
        Chunks should join back together to form the original file.

        Args:
            code: Source code to chunk
            file_path: Path to the file being chunked

        Returns:
            Dictionary with file_path, chunks list, and full_code
        """
        if self.mode == "ast":
            return self._extract_chunks_ast(code, file_path)
        else:
            return self._extract_chunks_llm(code, file_path)

    def _extract_chunks_llm(self, code: str, file_path: str) -> Dict:
        """Extract code chunks using LLM"""
        # Check cache first
        cache_key = hashlib.md5(code.encode()).hexdigest()
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")

        if os.path.exists(cache_file):
            print(f"  Using cached chunks from {cache_file}")
            with open(cache_file, "r") as f:
                cached_data = json.load(f)
                mutable_count = sum(1 for c in cached_data["chunks"] if c["is_mutable"])
                print(
                    f"  Loaded {len(cached_data['chunks'])} chunks ({mutable_count} mutable)"
                )
                return cached_data

        print(f"  Using LLM to chunk file...")

        # TODO: Might want to include additional check to see if mutation is "good" or "important"
        prompt = f"""Analyze this Python file and break it into chunks for mutation testing.

                    FILE:
                    ```python
                    {code}
                    ```

                    TASK: Split this file into logical chunks where:
                    1. Each chunk is either:
                    - A complete function/method (mutable)
                    - A complete class (mutable if simple, like dataclasses)
                    - Module-level code like imports, constants, main blocks (NOT mutable)

                    2. When all chunks are joined together IN ORDER, they must form the original file exactly

                    3. For each chunk provide:
                    - chunk_id: identifier (e.g., "imports", "constants", "function_name", "ClassName")
                    - is_mutable: true if this chunk should be mutated (functions, methods, classes), false for imports/constants/config
                    - code: the complete code for this chunk (preserve ALL whitespace, newlines, comments)

                    IMPORTANT:
                    - Preserve ALL whitespace, blank lines, and formatting
                    - Each chunk must be complete and valid
                    - The chunks must reconstruct the file perfectly when joined
                    - Mark imports, constants, and config as NOT mutable
                    - Mark functions, methods, and classes as mutable (except __init__, __str__, etc.)

                    Return ONLY valid JSON:
                    {{
                    "chunks": [
                        {{
                        "chunk_id": "imports",
                        "is_mutable": false,
                        "code": "import statements\\n\\n"
                        "line_start": integer,
                        "line_end": integer
                        }},
                        {{
                        "chunk_id": "function_name",
                        "is_mutable": true,
                        "code": "def function_name():\\n    pass\\n\\n"
                        "line_start": integer,
                        "line_end": integer
                        }}
                    ]
                    }}"""

        response = self.llm.invoke(prompt)

        # Extract JSON from response
        try:
            # Try to find JSON in markdown code block
            json_match = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```", response, re.DOTALL
            )
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find raw JSON
                json_match = re.search(r"(\{.*\})", response, re.DOTALL)
                if json_match:
                    json_str = json_match.group(1)
                else:
                    print("ERROR: Could not find JSON in LLM response")
                    print("Response:", response[:500])
                    return None

            data = json.loads(json_str)

            # Verify chunks reconstruct the file
            reconstructed = "".join([c["code"] for c in data["chunks"]])
            if reconstructed.strip() != code.strip():
                print("WARNING: Chunks don't perfectly reconstruct the file")
                print(f"  Original length: {len(code)}")
                print(f"  Reconstructed length: {len(reconstructed)}")

            # Convert to our format
            chunks = []
            for chunk_data in data["chunks"]:
                chunks.append(
                    {
                        "chunk_id": chunk_data["chunk_id"],
                        "chunk_type": "unknown",  # LLM doesn't need to specify
                        "original_code": chunk_data["code"],
                        "context": {
                            "parent_class": None,
                            "class_header": None,
                            "line_start": chunk_data["line_start"],
                            "line_end": chunk_data["line_end"],
                            "indentation": 0,
                            "decorators": [],
                            "file_path": file_path,
                        },
                        "is_mutable": chunk_data.get("is_mutable", False),
                        "mutated_versions": [],
                    }
                )

            mutable_count = sum(1 for c in chunks if c["is_mutable"])
            print(f"  Extracted {len(chunks)} chunks ({mutable_count} mutable)")

            result = {"file_path": file_path, "chunks": chunks, "full_code": code}

            # Save to cache
            with open(cache_file, "w") as f:
                json.dump(result, f, indent=2)
            print(f"  Cached chunks to {cache_file}")

            return result

        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to parse LLM JSON response: {e}")
            print("Response:", response[:500])
            return None
        except Exception as e:
            print(f"ERROR: Failed to process LLM response: {e}")
            return None

    def get_mutable_chunks(self, file_data: Dict) -> List[Dict]:
        """Filter and return only mutable chunks"""
        if not file_data or "chunks" not in file_data:
            return []
        return [chunk for chunk in file_data["chunks"] if chunk["is_mutable"]]

    def get_chunk_by_id(self, file_data: Dict, chunk_id: str) -> Optional[Dict]:
        """Get a specific chunk by its ID"""
        if not file_data or "chunks" not in file_data:
            return None
        for chunk in file_data["chunks"]:
            if chunk["chunk_id"] == chunk_id:
                return chunk
        return None

    # ===== AST-based chunking methods =====

    def _extract_chunks_ast(self, code: str, file_path: str) -> Dict:
        """
        Extract code chunks using AST parsing.
        Chunks include functions, methods, and classes.
        All remaining code (imports, globals, etc.) is preserved in separate chunks.
        """
        # Check cache first
        cache_key = hashlib.md5(code.encode()).hexdigest()
        cache_file = os.path.join(self.cache_dir, f"ast_{cache_key}.json")

        if os.path.exists(cache_file):
            print(f"  Using cached AST chunks from {cache_file}")
            with open(cache_file, "r") as f:
                cached_data = json.load(f)
                mutable_count = sum(1 for c in cached_data["chunks"] if c["is_mutable"])
                print(
                    f"  Loaded {len(cached_data['chunks'])} chunks ({mutable_count} mutable)"
                )
                return cached_data

        print(f"  Using AST parser to chunk file...")

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            print(f"ERROR: Failed to parse Python file: {e}")
            return None

        lines = code.splitlines(keepends=True)
        chunks = []

        # Extract top-level functions and classes
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Only process top-level definitions (not nested functions/classes)
                if self._is_top_level(node, tree):
                    chunk = self._extract_node_chunk(node, lines, file_path)
                    if chunk:
                        chunks.append(chunk)

        # Sort chunks by line number
        chunks.sort(key=lambda c: c["context"]["line_start"])

        # Extract "gap" code (imports, globals, etc.) between chunks
        all_chunks_with_gaps = []
        current_line = 1
        gap_counter = 0

        for chunk in chunks:
            chunk_start = chunk["context"]["line_start"]

            # If there's a gap before this chunk, create a gap chunk
            if current_line < chunk_start:
                gap_code = "".join(lines[current_line - 1:chunk_start - 1])
                if gap_code.strip():  # Only create chunk if there's actual code
                    gap_chunk = {
                        "chunk_id": f"gap_{gap_counter}",
                        "chunk_type": "gap",
                        "original_code": gap_code,
                        "context": {
                            "parent_class": None,
                            "class_header": None,
                            "line_start": current_line,
                            "line_end": chunk_start - 1,
                            "indentation": 0,
                            "decorators": [],
                            "file_path": file_path,
                        },
                        "is_mutable": False,
                        "mutated_versions": [],
                    }
                    all_chunks_with_gaps.append(gap_chunk)
                    gap_counter += 1

            # Add the actual chunk
            all_chunks_with_gaps.append(chunk)
            current_line = chunk["context"]["line_end"] + 1

        # Handle any remaining code after the last chunk
        if current_line <= len(lines):
            gap_code = "".join(lines[current_line - 1:])
            if gap_code.strip():
                gap_chunk = {
                    "chunk_id": f"gap_{gap_counter}",
                    "chunk_type": "gap",
                    "original_code": gap_code,
                    "context": {
                        "parent_class": None,
                        "class_header": None,
                        "line_start": current_line,
                        "line_end": len(lines),
                        "indentation": 0,
                        "decorators": [],
                        "file_path": file_path,
                    },
                    "is_mutable": False,
                    "mutated_versions": [],
                }
                all_chunks_with_gaps.append(gap_chunk)

        # Verify reconstruction
        reconstructed = "".join([c["original_code"] for c in all_chunks_with_gaps])
        if reconstructed != code:
            print("WARNING: AST chunks don't perfectly reconstruct the file")
            print(f"  Original length: {len(code)}")
            print(f"  Reconstructed length: {len(reconstructed)}")
        else:
            mutable_count = sum(1 for c in all_chunks_with_gaps if c["is_mutable"])
            print(f"  Extracted {len(all_chunks_with_gaps)} chunks ({mutable_count} mutable) using AST")

        result = {
            "file_path": file_path,
            "chunks": all_chunks_with_gaps,
            "full_code": code,
        }

        # Save to cache
        with open(cache_file, "w") as f:
            json.dump(result, f, indent=2)
        print(f"  Cached AST chunks to {cache_file}")

        return result

    def _is_top_level(self, node: ast.AST, tree: ast.Module) -> bool:
        """Check if a node is at the top level of the module"""
        return node in tree.body

    def _extract_node_chunk(self, node: ast.AST, lines: List[str], file_path: str) -> Optional[Dict]:
        """Extract a chunk for a function, async function, or class definition"""
        # Get the actual line numbers including decorators
        line_start = node.lineno
        line_end = node.end_lineno

        # Include decorators
        if hasattr(node, 'decorator_list') and node.decorator_list:
            first_decorator_line = min(d.lineno for d in node.decorator_list)
            line_start = first_decorator_line

        # Include trailing blank lines that follow this definition
        # This ensures proper spacing is preserved when stitching
        while line_end < len(lines) and lines[line_end].strip() == "":
            line_end += 1

        # Extract the code for this node
        chunk_code = "".join(lines[line_start - 1:line_end])

        # Determine chunk type and mutability
        chunk_type = "unknown"
        is_mutable = True
        chunk_id = node.name

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            chunk_type = "function"
            chunk_id = node.name
            # Don't mutate special methods like __init__, __str__, etc.
            if node.name.startswith("__") and node.name.endswith("__"):
                is_mutable = False
        elif isinstance(node, ast.ClassDef):
            chunk_type = "class"
            chunk_id = node.name
            is_mutable = True

        # Extract decorators
        decorators = []
        if hasattr(node, 'decorator_list'):
            for dec in node.decorator_list:
                dec_line = lines[dec.lineno - 1].strip()
                decorators.append(dec_line)

        return {
            "chunk_id": chunk_id,
            "chunk_type": chunk_type,
            "original_code": chunk_code,
            "context": {
                "parent_class": None,
                "class_header": None,
                "line_start": line_start,
                "line_end": line_end,
                "indentation": node.col_offset if hasattr(node, 'col_offset') else 0,
                "decorators": decorators,
                "file_path": file_path,
            },
            "is_mutable": is_mutable,
            "mutated_versions": [],
        }
