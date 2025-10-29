from src.llm_client import LLMClient
from src.validators import CodeValidator
from src.chunker import CodeChunker
from src.stitcher import FileStitcher
from prompts.templates import PromptTemplates
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading


class ACHWorkflow:
    def __init__(self, model: str, provider: str, max_workers: int = 3):
        self.llm = LLMClient(model, provider)
        self.validator = CodeValidator()
        self.prompts = PromptTemplates()
        self.chunker = CodeChunker()
        self.stitcher = FileStitcher()
        self.max_workers = max_workers
        self._print_lock = threading.Lock()

    def _thread_safe_print(self, message: str, chunk_id: str = None):
        """Thread-safe printing with optional chunk identification"""
        with self._print_lock:
            if chunk_id:
                print(f"[{chunk_id}] {message}")
            else:
                print(message)

    def run_workflow(self, code_file: str, test_file: str) -> Optional[Dict]:
        """Run the ACH workflow with chunk-based mutation"""
        print("Starting ACH Workflow (chunk-based mutation)...")
        print(f"Using model: {self.llm.model}")
        print(f"Processing: {code_file}, {test_file}")
        print(f"Max parallel workers: {self.max_workers}")

        # Read input files
        with open(code_file, "r", encoding="utf-8") as f:
            code_content = f.read()
        with open(test_file, "r", encoding="utf-8") as f:
            existing_test_class = f.read()

        # Context about privacy concerns
        context_about_concern = """Privacy violations in user data handling:
        - Logging personally identifiable information (emails, names, IDs) without sanitization
        - Exposing password hashes, salts, or authentication tokens in responses
        - Missing authorization checks allowing unauthorized data access
        - Storing sensitive data unencrypted or in application logs"""

        diff = """Real bug example: User profile endpoint returned
        password_hash and salt_hex fields in JSON response, exposing sensitive
        authentication data. Fix removed these fields from public() method."""

        # STEP 0: Chunk the code file
        print("\n" + "=" * 60)
        print("STEP 0: Chunking code file")
        print("=" * 60)
        file_data = self.chunker.extract_chunks(code_content, code_file)

        if not file_data:
            print("  ✗ Failed to chunk file")
            return None

        mutable_chunks = self.chunker.get_mutable_chunks(file_data)
        print(
            f"  ✓ Found {len(file_data['chunks'])} chunks ({len(mutable_chunks)} mutable)"
        )

        if not mutable_chunks:
            print("  ✗ No mutable chunks found")
            return None

        # Process each mutable chunk in parallel
        successful_mutants = []
        total_chunks = len(mutable_chunks)

        print(f"\n{'=' * 60}")
        print(f"PROCESSING {total_chunks} CHUNKS IN PARALLEL")
        print(f"{'=' * 60}\n")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_chunk = {
                executor.submit(
                    self._process_chunk_with_index,
                    idx,
                    chunk,
                    file_data,
                    existing_test_class,
                    context_about_concern,
                    diff,
                    code_file,
                    test_file,
                    total_chunks,
                ): (idx, chunk)
                for idx, chunk in enumerate(mutable_chunks)
            }

            # Process completed tasks as they finish
            for future in as_completed(future_to_chunk):
                idx, chunk = future_to_chunk[future]
                try:
                    result = future.result()
                    if result:
                        successful_mutants.append(result)
                except Exception as e:
                    self._thread_safe_print(f"✗ Exception: {e}", chunk["chunk_id"])

        # Summary
        print("\n" + "=" * 60)
        print(
            f"WORKFLOW COMPLETE: {len(successful_mutants)}/{len(mutable_chunks)} successful mutants"
        )
        print("=" * 60)

        if successful_mutants:
            return {
                "file_data": file_data,
                "mutants": successful_mutants,
                "total_chunks": len(mutable_chunks),
                "successful_count": len(successful_mutants),
            }

        return None

    def _process_chunk_with_index(
        self,
        idx: int,
        chunk: Dict,
        file_data: Dict,
        existing_test_class: str,
        context: str,
        diff: str,
        code_file: str,
        test_file: str,
        total_chunks: int,
    ) -> Optional[Dict]:
        """Process a single chunk with its index (for parallel execution)"""
        chunk_id = chunk["chunk_id"]

        self._thread_safe_print(
            f"{'=' * 50}\nStarting chunk {idx + 1}/{total_chunks}\n{'=' * 50}", chunk_id
        )

        result = self._process_chunk(
            chunk,
            file_data,
            existing_test_class,
            context,
            diff,
            code_file,
            test_file,
        )

        if result:
            self._thread_safe_print(
                f"✓ Successfully generated mutant and test", chunk_id
            )
            return result
        else:
            self._thread_safe_print(f"✗ Failed to generate valid mutant", chunk_id)
            return None

    def _process_chunk(
        self,
        chunk: Dict,
        file_data: Dict,
        existing_test_class: str,
        context: str,
        diff: str,
        code_file: str,
        test_file: str,
    ) -> Optional[Dict]:
        """Process a single chunk through the ACH workflow"""
        chunk_id = chunk["chunk_id"]

        # STEP 1: Generate mutant for chunk
        self._thread_safe_print("STEP 1: Generate mutant for chunk", chunk_id)
        mutated_chunk_code = self._make_fault_for_chunk(
            context, chunk, file_data, existing_test_class, diff
        )

        if not mutated_chunk_code:
            self._thread_safe_print("  ✗ Failed to generate mutant", chunk_id)
            return None

        # Stitch full file with mutated chunk
        mutated_file = self.stitcher.stitch_file(
            file_data,
            chunk["chunk_id"],
            mutated_chunk_code,
        )

        # STEP 2: Check syntactic identity
        self._thread_safe_print("STEP 2: Check syntactic identity", chunk_id)
        if self.validator.is_syntactically_identical(
            chunk["original_code"], mutated_chunk_code
        ):
            self._thread_safe_print("  ✗ Syntactically identical - DISCARD", chunk_id)
            return None
        self._thread_safe_print("  ✓ Syntactically different", chunk_id)

        # STEP 3: Validate mutant builds and passes
        self._thread_safe_print("STEP 3: Validate mutant", chunk_id)
        builds, passes = self.validator.run_tests(
            mutated_file, existing_test_class, code_file, test_file
        )

        if not builds:
            self._thread_safe_print("  ✗ Mutant doesn't build - DISCARD", chunk_id)
            return None
        if not passes:
            self._thread_safe_print(
                "  ✗ Mutant fails existing tests - DISCARD", chunk_id
            )
            return None
        self._thread_safe_print("  ✓ Mutant builds and passes", chunk_id)

        # STEP 4: Equivalence detection
        self._thread_safe_print("STEP 4: Equivalence detection", chunk_id)
        is_equivalent = self._equivalence_detector(file_data["full_code"], mutated_file)

        if is_equivalent:
            self._thread_safe_print("  ✗ Equivalent mutant - DISCARD", chunk_id)
            return None
        self._thread_safe_print("  ✓ Non-equivalent", chunk_id)

        # STEP 5: Generate test
        self._thread_safe_print("STEP 5: Generate test to kill mutant", chunk_id)
        new_test_class = self._make_test_to_catch_fault(
            file_data["full_code"], mutated_file, existing_test_class
        )

        if not new_test_class:
            self._thread_safe_print("  ✗ Failed to generate test", chunk_id)
            return None

        # STEP 6: Validate test
        self._thread_safe_print("STEP 6: Validate generated test", chunk_id)

        # 6a: Passes on original?
        builds_orig, passes_orig = self.validator.run_tests(
            file_data["full_code"], new_test_class, code_file, test_file
        )
        if not builds_orig or not passes_orig:
            self._thread_safe_print("  ✗ Test fails on original - DISCARD", chunk_id)
            return None
        self._thread_safe_print("  ✓ Test passes on original", chunk_id)

        # 6b: Fails on mutant?
        builds_mut, passes_mut = self.validator.run_tests(
            mutated_file, new_test_class, code_file, test_file
        )
        if not builds_mut:
            self._thread_safe_print(
                "  ✗ Test doesn't build with mutant - DISCARD", chunk_id
            )
            return None
        if passes_mut:
            self._thread_safe_print("  ✗ Test doesn't kill mutant - DISCARD", chunk_id)
            return None
        self._thread_safe_print("  ✓ Test kills mutant!", chunk_id)

        # Success! Store mutant info
        return {
            "chunk_id": chunk["chunk_id"],
            "chunk_type": chunk["chunk_type"],
            "original_chunk": chunk["original_code"],
            "mutated_chunk": mutated_chunk_code,
            "mutated_file": mutated_file,
            "test": new_test_class,
        }

    def _make_fault_for_chunk(
        self,
        context: str,
        chunk: Dict,
        file_data: Dict,
        existing_test_class: str,
        diff: str,
    ) -> Optional[str]:
        """Generate fault for a specific code chunk"""
        # Get full class context if this is a method
        full_class_context = ""
        if chunk["chunk_type"] == "method" and chunk["context"]["parent_class"]:
            # Get all chunks from the same class
            parent_class = chunk["context"]["parent_class"]
            class_chunks = [
                c
                for c in file_data["chunks"]
                if c["context"].get("parent_class") == parent_class
            ]

            # Build class context (header + all methods)
            if class_chunks and class_chunks[0]["context"].get("class_header"):
                full_class_context = class_chunks[0]["context"]["class_header"] + "\n"
                for c in class_chunks:
                    full_class_context += "\n" + c["original_code"]

        prompt = self.prompts.make_fault_for_chunk(
            context=context,
            chunk_code=chunk["original_code"],
            chunk_type=chunk["chunk_type"],
            parent_class=chunk["context"].get("parent_class"),
            full_class_context=full_class_context,
            existing_test_class=existing_test_class,
            diff=diff,
        )

        text = self.llm.invoke(prompt)
        return self.llm.extract_code_from_response(text)

    def _equivalence_detector(self, class_version1, class_version2):
        """Table 1: Equivalence detector"""
        prompt = self.prompts.equivalence_detector(class_version1, class_version2)
        answer = self.llm.invoke(prompt).strip()
        return answer.lower().startswith("yes")

    def _make_test_to_catch_fault(
        self, original_class, mutated_class, existing_test_class
    ):
        """Table 1: Make a test to catch fault"""
        prompt = self.prompts.make_test_to_catch_fault(
            original_class, mutated_class, existing_test_class
        )
        text = self.llm.invoke(prompt)
        return self.llm.extract_code_from_response(text)
