"""Mutation testing pipeline for ACH workflow"""

from src.mutation.llm_orchestrator import LLMOrchestrator
from src.shared.validators import CodeValidator
from src.mutation.stitcher import FileStitcher
from typing import Dict, Optional, Callable, Set
import hashlib


class MutationPipeline:
    """Handles the 7-step mutation testing pipeline for a single chunk"""

    def __init__(
        self,
        llm_orchestrator: LLMOrchestrator,
        validator: CodeValidator,
        stitcher: FileStitcher,
        thread_safe_print: Callable,
    ):
        self.llm_orchestrator = llm_orchestrator
        self.validator = validator
        self.stitcher = stitcher
        self._thread_safe_print = thread_safe_print

    def process_chunk(
        self,
        chunk: Dict,
        file_data: Dict,
        existing_test_class: str,
        context: str,
        diff: str,
        temp_repo: str,
        code_relpath: str,
        test_relpath: str,
        venv_python: str,
        existing_chunk_ids: Set[str],
    ) -> Optional[Dict]:
        """Process a single chunk through the ACH workflow"""
        chunk_id = chunk["chunk_id"]

        # Check for duplicates BEFORE doing anything expensive
        if chunk_id in existing_chunk_ids:
            self._thread_safe_print("DUPLICATE CHECK: Chunk already processed - SKIP", chunk_id)
            return {"skipped": True, "chunk_id": chunk_id}

        self._thread_safe_print("DUPLICATE CHECK: New chunk, proceeding", chunk_id)

        # STEP 1: Generate mutant for chunk
        self._thread_safe_print("STEP 1: Generate mutant for chunk", chunk_id)
        mutated_chunk_code = self.llm_orchestrator.make_fault_for_chunk(
            context, chunk, file_data, existing_test_class, diff
        )

        if not mutated_chunk_code:
            self._thread_safe_print("  Failed to generate mutant", chunk_id)
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
            self._thread_safe_print("  Syntactically identical - DISCARD", chunk_id)
            return None
        self._thread_safe_print("  Syntactically different", chunk_id)

        # STEP 3: Validate mutant builds and passes (now we know it's not a duplicate)
        self._thread_safe_print("STEP 3: Validate mutant", chunk_id)
        builds, passes = self.validator.run_tests(
            mutated_file,
            existing_test_class,
            temp_repo,
            code_relpath,
            test_relpath,
            venv_python
        )

        if not builds:
            self._thread_safe_print("  Mutant doesn't build - DISCARD", chunk_id)
            return None
        if not passes:
            self._thread_safe_print(
                "  Mutant fails existing tests - DISCARD", chunk_id
            )
            return None
        self._thread_safe_print("  Mutant builds and passes", chunk_id)

        # STEP 4: Equivalence detection
        self._thread_safe_print("STEP 4: Equivalence detection", chunk_id)
        is_equivalent = self.llm_orchestrator.equivalence_detector(
            file_data["full_code"], mutated_file
        )

        if is_equivalent:
            self._thread_safe_print("  Equivalent mutant - DISCARD", chunk_id)
            return None
        self._thread_safe_print("  Non-equivalent", chunk_id)

        # STEP 5: Generate test
        self._thread_safe_print("STEP 5: Generate test to kill mutant", chunk_id)
        new_test_class = self.llm_orchestrator.make_test_to_catch_fault(
            file_data["full_code"], mutated_file, existing_test_class
        )

        if not new_test_class:
            self._thread_safe_print("  Failed to generate test", chunk_id)
            return None

        # STEP 6: Validate test
        self._thread_safe_print("STEP 6: Validate generated test", chunk_id)

        # 6a: Passes on original?
        builds_orig, passes_orig = self.validator.run_tests(
            file_data["full_code"],
            new_test_class,
            temp_repo,
            code_relpath,
            test_relpath,
            venv_python
        )
        if not builds_orig or not passes_orig:
            self._thread_safe_print("  Test fails on original - DISCARD", chunk_id)
            return None
        self._thread_safe_print("  Test passes on original", chunk_id)

        # 6b: Fails on mutant?
        builds_mut, passes_mut = self.validator.run_tests(
            mutated_file,
            new_test_class,
            temp_repo,
            code_relpath,
            test_relpath,
            venv_python
        )
        if not builds_mut:
            self._thread_safe_print(
                "  Test doesn't build with mutant - DISCARD", chunk_id
            )
            return None
        if passes_mut:
            self._thread_safe_print("  Test doesn't kill mutant - DISCARD", chunk_id)
            return None
        self._thread_safe_print("  Test kills mutant!", chunk_id)

        # STEP 7: LLM as judge - evaluate mutant quality
        self._thread_safe_print("STEP 7: LLM judge evaluation", chunk_id)
        scores_dict = self.llm_orchestrator.llm_judge_mutant(
            original_code=chunk["original_code"],
            mutated_code=mutated_chunk_code,
            original_test=existing_test_class,
            new_test=new_test_class,
            context=context,
            diff=diff
        )

        for score in scores_dict.keys():
            if scores_dict[score] is not None:
                self._thread_safe_print(f" {score} : {scores_dict[score]}", chunk_id)
            else:
                self._thread_safe_print(
                    "score not found", chunk_id
                )

        # Compute final hash with test included
        final_hash_content = f"{chunk_id}|{mutated_chunk_code}|{new_test_class}"
        final_hash = hashlib.sha256(final_hash_content.encode()).hexdigest()[:12]

        # Success! Store mutant info
        result = {
            "chunk_id": chunk["chunk_id"],
            "chunk_type": chunk["chunk_type"],
            "original_chunk": chunk["original_code"],
            "mutated_chunk": mutated_chunk_code,
            "mutated_file": mutated_file,
            "test": new_test_class,
            "scores": scores_dict,
            "hash": final_hash,
        }

        return result
