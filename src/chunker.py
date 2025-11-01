"""Code chunking utilities using LLM"""

import json
import re
import os
import hashlib
from typing import Dict, List, Optional
from src.llm_client import LLMClient
from constants import MODEL, MODEL_PROVIDER


class CodeChunker:
    """Extract mutable code chunks from Python files using LLM"""

    def __init__(self, cache_dir: str = ".chunk_cache"):
        self.llm = LLMClient(MODEL, MODEL_PROVIDER)
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def extract_chunks(self, code: str, file_path: str) -> Dict:
        """
        Extract code chunks from a Python file using LLM.
        Chunks should join back together to form the original file.
        """
        # Check cache first
        cache_key = hashlib.md5(code.encode()).hexdigest()
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")

        if os.path.exists(cache_file):
            print(f"  Using cached chunks from {cache_file}")
            with open(cache_file, "r") as f:
                cached_data = json.load(f)
                mutable_count = sum(1 for c in cached_data["chunks"] if c["is_mutable"])
                print(
                    f"  ✓ Loaded {len(cached_data['chunks'])} chunks ({mutable_count} mutable)"
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
            print(f"  ✓ Extracted {len(chunks)} chunks ({mutable_count} mutable)")

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
