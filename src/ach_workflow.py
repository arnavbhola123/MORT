"""Core ACH workflow implementation"""

from src.llm_client import LLMClient
from src.validators import CodeValidator
from src.chunker import CodeChunker
from src.stitcher import FileStitcher
from prompts.templates import PromptTemplates
from typing import List, Dict, Optional


class ACHWorkflow:
    def __init__(self, model: str, provider: str):
        self.llm = LLMClient(model, provider)
        self.validator = CodeValidator()
        self.prompts = PromptTemplates()
        self.chunker = CodeChunker()
        self.stitcher = FileStitcher()

    def run_workflow(self, code_file: str, test_file: str) -> Optional[Dict]:
        """Run the ACH workflow with chunk-based mutation"""
        print("Starting ACH Workflow (chunk-based mutation)...")
        print(f"Using model: {self.llm.model}")
        print(f"Processing: {code_file}, {test_file}")

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

        # Process each mutable chunk
        successful_mutants = []

        for idx, chunk in enumerate(mutable_chunks):
            print(f"\n{'=' * 60}")
            print(
                f"Processing chunk {idx + 1}/{len(mutable_chunks)}: {chunk['chunk_id']}"
            )
            print(f"{'=' * 60}")

            result = self._process_chunk(
                chunk,
                file_data,
                existing_test_class,
                context_about_concern,
                diff,
                code_file,
                test_file,
            )

            if result:
                successful_mutants.append(result)
                print(
                    f"  ✓ Successfully generated mutant and test for {chunk['chunk_id']}"
                )
            else:
                print(f"  ✗ Failed to generate valid mutant for {chunk['chunk_id']}")

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

        # STEP 1: Generate mutant for chunk
        print("\n  STEP 1: Generate mutant for chunk")
        mutated_chunk_code = self._make_fault_for_chunk(
            context, chunk, file_data, existing_test_class, diff
        )

        if not mutated_chunk_code:
            print("    ✗ Failed to generate mutant")
            return None

        # Stitch full file with mutated chunk
        mutated_file = self.stitcher.stitch_file(
            file_data, chunk["chunk_id"], mutated_chunk_code
        )

        # STEP 2: Check syntactic identity
        print("  STEP 2: Check syntactic identity")
        if self.validator.is_syntactically_identical(
            chunk["original_code"], mutated_chunk_code
        ):
            print("    ✗ Syntactically identical - DISCARD")
            return None
        print("    ✓ Syntactically different")

        # STEP 3: Validate mutant builds and passes
        print("  STEP 3: Validate mutant")
        builds, passes = self.validator.run_tests(
            mutated_file, existing_test_class, code_file, test_file
        )

        if not builds:
            print("    ✗ Mutant doesn't build - DISCARD")
            return None
        if not passes:
            print("    ✗ Mutant fails existing tests - DISCARD")
            return None
        print("    ✓ Mutant builds and passes")

        # STEP 4: Equivalence detection
        print("  STEP 4: Equivalence detection")
        is_equivalent = self._equivalence_detector(file_data["full_code"], mutated_file)

        if is_equivalent:
            print("    ✗ Equivalent mutant - DISCARD")
            return None
        print("    ✓ Non-equivalent")

        # STEP 5: Generate test
        print("  STEP 5: Generate test to kill mutant")
        new_test_class = self._make_test_to_catch_fault(
            file_data["full_code"], mutated_file, existing_test_class
        )

        if not new_test_class:
            print("    ✗ Failed to generate test")
            return None

        # STEP 6: Validate test
        print("  STEP 6: Validate generated test")

        # 6a: Passes on original?
        builds_orig, passes_orig = self.validator.run_tests(
            file_data["full_code"], new_test_class, code_file, test_file
        )
        if not builds_orig or not passes_orig:
            print("    ✗ Test fails on original - DISCARD")
            return None
        print("    ✓ Test passes on original")

        # 6b: Fails on mutant?
        builds_mut, passes_mut = self.validator.run_tests(
            mutated_file, new_test_class, code_file, test_file
        )
        if not builds_mut:
            print("    ✗ Test doesn't build with mutant - DISCARD")
            return None
        if passes_mut:
            print("    ✗ Test doesn't kill mutant - DISCARD")
            return None
        print("    ✓ Test kills mutant!")

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

    # Legacy methods (for backward compatibility)
    # def _make_fault(self, context, class_under_test, existing_test_class, diff):
    #     """Table 1: Make a fault (legacy method for full-file mutation)"""
    #     prompt = self.prompts.make_fault(context, class_under_test, existing_test_class, diff)
    #     text = self.llm.invoke(prompt)
    #     return self.llm.extract_code_from_response(text)
