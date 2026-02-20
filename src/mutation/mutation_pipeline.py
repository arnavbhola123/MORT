"""Mutation testing pipeline for MORT workflow"""

from src.mutation.llm_orchestrator import LLMOrchestrator
from src.shared.validators import CodeValidator
from src.mutation.stitcher import FileStitcher
from typing import Dict, Optional, Callable, Set
import hashlib
import os


class MutationPipeline:
    """Handles the mutation testing pipeline for a single chunk"""

    def __init__(
        self,
        llm_orchestrator: LLMOrchestrator,
        validator: CodeValidator,
        stitcher: FileStitcher,
        thread_safe_print: Callable,
        graph_client=None,
        test_type: str = "unit",
    ):
        self.llm_orchestrator = llm_orchestrator
        self.validator = validator
        self.stitcher = stitcher
        self._thread_safe_print = thread_safe_print
        self.graph_client = graph_client
        self.test_type = test_type

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
        concern: str = "privacy",
        repo_path: str = "",
    ) -> Optional[Dict]:
        """Process a single chunk through the MORT workflow"""
        chunk_id = chunk["chunk_id"]

        # Check for duplicates BEFORE doing anything expensive
        if chunk_id in existing_chunk_ids:
            self._thread_safe_print("DUPLICATE CHECK: Chunk already processed - SKIP", chunk_id)
            return {"skipped": True, "chunk_id": chunk_id}

        self._thread_safe_print("DUPLICATE CHECK: New chunk, proceeding", chunk_id)

        # STEP 1: Generate mutant for chunk
        self._thread_safe_print("STEP 1: Generate mutant for chunk", chunk_id)
        mutated_chunk_code = self.llm_orchestrator.make_fault_for_chunk(
            context, chunk, file_data, existing_test_class, diff, concern
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

        # Initialize result fields
        new_test_class = None
        scores_dict = None
        functional_test = None
        functional_test_skipped_reason = None

        # STEPS 5-7: Unit test generation (skip when test_type is "functional")
        if self.test_type in ("unit", "both"):
            # STEP 5: Generate test
            self._thread_safe_print("STEP 5: Generate test to kill mutant", chunk_id)
            new_test_class = self.llm_orchestrator.make_test_to_catch_fault(
                file_data["full_code"], mutated_file, existing_test_class
            )

            if not new_test_class:
                self._thread_safe_print("  Failed to generate test", chunk_id)
                if self.test_type == "unit":
                    return None

            if new_test_class:
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
                    new_test_class = None
                    if self.test_type == "unit":
                        return None
                else:
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
                        new_test_class = None
                        if self.test_type == "unit":
                            return None
                    elif passes_mut:
                        self._thread_safe_print("  Test doesn't kill mutant - DISCARD", chunk_id)
                        new_test_class = None
                        if self.test_type == "unit":
                            return None
                    else:
                        self._thread_safe_print("  Test kills mutant!", chunk_id)

            # STEP 7: LLM as judge - evaluate mutant quality
            if new_test_class:
                self._thread_safe_print("STEP 7: LLM judge evaluation", chunk_id)
                scores_dict = self.llm_orchestrator.llm_judge_mutant(
                    original_code=chunk["original_code"],
                    mutated_code=mutated_chunk_code,
                    original_test=existing_test_class,
                    new_test=new_test_class,
                    context=context,
                    diff=diff,
                    concern=concern,
                )

                if scores_dict:
                    for score in scores_dict.keys():
                        if scores_dict[score] is not None:
                            self._thread_safe_print(f" {score} : {scores_dict[score]}", chunk_id)
                        else:
                            self._thread_safe_print(
                                "score not found", chunk_id
                            )

        # STEP 8: Functional test generation (when test_type is "functional" or "both")
        if self.test_type in ("functional", "both") and self.graph_client is not None:
            self._thread_safe_print("STEP 8: Functional test generation", chunk_id)

            # Extract symbol name from chunk_id (e.g., "ClassName.method_name" -> "method_name")
            symbol_name = chunk_id.split(".")[-1] if "." in chunk_id else chunk_id
            file_suffix = code_relpath

            print(symbol_name)
            print(file_suffix)

            # 8a: Check if functional test is warranted
            self._thread_safe_print("  8a: Checking if functional test is warranted", chunk_id)
            warranted = self.graph_client.check_functional_test_warranted(
                symbol_name, file_suffix
            )

            if warranted is None:
                functional_test_skipped_reason = (
                    f"Functional test not warranted for '{symbol_name}' — "
                    "no importers or isolated symbol"
                )
                self._thread_safe_print(f"  {functional_test_skipped_reason}", chunk_id)
            else:
                # 8b: Get integration context
                self._thread_safe_print("  8b: Querying integration context from knowledge graph", chunk_id)
                integration_context = self.graph_client.get_integration_context(
                    symbol_name, file_suffix
                )

                # 8c: Read source code of direct caller files from disk
                caller_source_code = {}
                if integration_context.get("entry_points"):
                    seen_files = set()
                    for ep in integration_context["entry_points"]:
                        caller_file = ep.get("direct_caller_file")
                        if caller_file and caller_file not in seen_files:
                            seen_files.add(caller_file)
                            abs_path = os.path.join(repo_path, caller_file)
                            if os.path.isfile(abs_path):
                                try:
                                    with open(abs_path, "r", encoding="utf-8") as f:
                                        caller_source_code[caller_file] = f.read()
                                except Exception as e:
                                    self._thread_safe_print(
                                        f"  Warning: Could not read caller file {caller_file}: {e}",
                                        chunk_id,
                                    )
                integration_context["caller_source_code"] = caller_source_code

                # 8d: Generate functional test
                self._thread_safe_print("  8d: Generating functional test via LLM", chunk_id)
                functional_test = self.llm_orchestrator.make_functional_test_to_catch_fault(
                    file_data["full_code"],
                    mutated_file,
                    existing_test_class,
                    integration_context,
                )

                if not functional_test:
                    self._thread_safe_print("  Failed to generate functional test", chunk_id)
                else:
                    # 8e: Validate functional test
                    self._thread_safe_print("  8e: Validating functional test", chunk_id)

                    # Passes on original?
                    builds_orig, passes_orig = self.validator.run_tests(
                        file_data["full_code"],
                        functional_test,
                        temp_repo,
                        code_relpath,
                        test_relpath,
                        venv_python,
                    )
                    if not builds_orig or not passes_orig:
                        self._thread_safe_print(
                            "  Functional test fails on original - DISCARD", chunk_id
                        )
                        functional_test = None
                    else:
                        self._thread_safe_print("  Functional test passes on original", chunk_id)

                        # Fails on mutant?
                        builds_mut, passes_mut = self.validator.run_tests(
                            mutated_file,
                            functional_test,
                            temp_repo,
                            code_relpath,
                            test_relpath,
                            venv_python,
                        )
                        if not builds_mut:
                            self._thread_safe_print(
                                "  Functional test doesn't build with mutant - DISCARD",
                                chunk_id,
                            )
                            functional_test = None
                        elif passes_mut:
                            self._thread_safe_print(
                                "  Functional test doesn't kill mutant - DISCARD", chunk_id
                            )
                            functional_test = None
                        else:
                            self._thread_safe_print("  Functional test kills mutant!", chunk_id)

        # For functional-only mode, run placeholder judge scoring
        if self.test_type == "functional" and scores_dict is None:
            self._thread_safe_print("STEP 7: LLM judge (placeholder for functional mode)", chunk_id)
            scores_dict = {}

        # Determine if we have at least one valid test
        has_unit_test = new_test_class is not None
        has_functional_test = functional_test is not None

        if not has_unit_test and not has_functional_test:
            self._thread_safe_print("  No valid tests generated - DISCARD", chunk_id)
            return None

        # Compute final hash with test included
        hash_parts = chunk_id
        if new_test_class:
            hash_parts += f"|{mutated_chunk_code}|{new_test_class}"
        if functional_test:
            hash_parts += f"|functional|{functional_test}"
        final_hash = hashlib.sha256(hash_parts.encode()).hexdigest()[:12]

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

        if self.test_type in ("functional", "both"):
            result["functional_test"] = functional_test
            if functional_test_skipped_reason:
                result["functional_test_skipped_reason"] = functional_test_skipped_reason

        return result
