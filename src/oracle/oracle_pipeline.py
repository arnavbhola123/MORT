"""Oracle inference pipeline for bug detection"""

from src.shared.llm_client import LLMClient
from src.shared.validators import CodeValidator
from src.oracle.oracle_validator import OracleValidator
from prompts.templates import PromptTemplates
from typing import Dict, List, Optional
import re


class OraclePipeline:
    """8-step oracle inference workflow for a single code chunk"""

    def __init__(
        self,
        llm_client: LLMClient,
        validator: CodeValidator,
        prompts: PromptTemplates,
        oracle_validator: OracleValidator,
    ):
        self.llm = llm_client
        self.validator = validator
        self.prompts = prompts
        self.oracle_validator = oracle_validator

    def generate_mutants(
        self, chunk_code: str, context: str, concern: str, num_mutants: int = 10
    ) -> List[str]:
        """
        Step 1: Generate multiple mutants for oracle inference.

        Args:
            chunk_code: The code chunk to mutate
            context: Context about the concern
            concern: The concern category (privacy, security, etc.)
            num_mutants: Number of mutants to generate

        Returns:
            List of mutated code strings
        """
        print(f"\n  Step 1: Generating {num_mutants} mutants...")

        prompt = self.prompts.generate_multiple_mutants(
            context, chunk_code, concern, num_mutants
        )
        response = self.llm.invoke(prompt)

        mutants = self._extract_multiple_mutants(response, num_mutants)
        print(f"    Generated {len(mutants)} mutants")

        return mutants

    def _extract_multiple_mutants(self, text: str, expected: int) -> List[str]:
        """Extract multiple mutants from LLM response"""
        # Try to find mutants with markers
        pattern = r'(?://|#)\s*MUTANT\s+START.*?\n(.*?)(?://|#)\s*MUTANT\s+END'
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)

        if matches:
            return [m.strip() for m in matches]

        # Fallback: try to extract code blocks
        code_blocks = re.findall(r'```python\n(.*?)```', text, re.DOTALL)
        if code_blocks:
            return [cb.strip() for cb in code_blocks[:expected]]

        return []

    def filter_mutants(
        self,
        original_code: str,
        mutants: List[str],
        temp_repo: str,
        code_relpath: str,
        test_relpath: str,
        venv_python: str,
    ) -> List[str]:
        """
        Steps 2-4: Filter mutants through validation pipeline.

        - Step 2: Remove syntactically identical mutants
        - Step 3: Validate syntax
        - Step 4: Check equivalence

        Args:
            original_code: Original code chunk
            mutants: List of mutant code strings
            temp_repo: Path to temporary repository copy
            code_relpath: Relative path to code file
            test_relpath: Relative path to test file (not used for oracle, but needed for validator)
            venv_python: Path to Python executable in venv

        Returns:
            List of valid mutants (max 5)
        """
        print(f"\n  Steps 2-4: Filtering {len(mutants)} mutants...")
        valid_mutants = []

        for i, mutant in enumerate(mutants, 1):
            print(f"    Mutant {i}/{len(mutants)}: ", end="")

            # Step 2: Syntactic identity check
            if self.validator.is_syntactically_identical(original_code, mutant):
                print("[X] Syntactically identical")
                continue

            # Step 3: Syntax validation
            is_valid, error = self.validator.validate_syntax(mutant)
            if not is_valid:
                print(f"[X] Syntax error: {error[:50]}")
                continue

            # Step 4: Equivalence detection
            is_equivalent = self._check_equivalence(original_code, mutant)
            if is_equivalent:
                print("[X] Equivalent mutant")
                continue

            print("[OK] Valid mutant")
            valid_mutants.append(mutant)

            # Return at most 5 valid mutants
            if len(valid_mutants) >= 5:
                break

        print(f"    Retained {len(valid_mutants)} valid mutants")
        return valid_mutants

    def _check_equivalence(self, original: str, mutant: str) -> bool:
        """Check if mutant is equivalent to original using LLM"""
        prompt = self.prompts.equivalence_detector(original, mutant)
        answer = self.llm.invoke(prompt).strip()
        return answer.lower().startswith('yes')

    def generate_oracle(
        self, chunk_code: str, mutants: List[str], concern: str
    ) -> str:
        """
        Step 5: Generate oracle specification from mutants.

        Args:
            chunk_code: Original code chunk
            mutants: List of valid mutants
            concern: Concern category

        Returns:
            Oracle specification text
        """
        print(f"\n  Step 5: Generating oracle specification...")

        prompt = self.prompts.generate_oracle_inference(chunk_code, mutants, concern)
        oracle = self.llm.invoke(prompt)

        print(f"    Oracle generated ({len(oracle)} chars)")
        return oracle

    def validate_oracle_with_user(
        self, oracle: str, chunk_id: str
    ) -> str:
        """
        Step 6: Human-in-the-loop validation of oracle.

        Saves oracle to file, waits for user to review/edit,
        then loads the validated version.

        Args:
            oracle: Generated oracle specification
            chunk_id: Identifier for the chunk

        Returns:
            Validated oracle specification
        """
        print(f"\n  Step 6: Oracle validation (file-based)...")

        # Save oracle for user review
        oracle_file = self.oracle_validator.save_oracle_for_validation(
            oracle, chunk_id
        )

        # Wait for user validation
        validated_oracle = self.oracle_validator.wait_for_validation(oracle_file)

        return validated_oracle

    def generate_test(
        self, chunk_code: str, oracle: str, chunk_id: str, existing_test_file: str
    ) -> Optional[str]:
        """
        Step 7: Generate test from validated oracle.

        Args:
            chunk_code: Original code chunk
            oracle: Validated oracle specification
            chunk_id: Identifier for the chunk/function
            existing_test_file: Existing test file content (required)

        Returns:
            Generated test code or None if generation failed
        """
        print(f"\n  Step 7: Extending existing test file based on oracle...")

        if not existing_test_file:
            print(f"    ERROR: existing_test_file is required but not provided")
            return None

        print(f"    Using existing test file as base ({len(existing_test_file)} chars)")

        prompt = self.prompts.generate_test_from_oracle(chunk_code, oracle, chunk_id, existing_test_file)
        response = self.llm.invoke(prompt)

        test_code = self.llm.extract_code_from_response(response)
        if test_code:
            print(f"    Test generated ({len(test_code)} chars)")
        else:
            print(f"    Failed to extract test code")

        return test_code

    def detect_bugs(
        self,
        original_code: str,
        test_code: str,
        temp_repo: str,
        code_relpath: str,
        test_relpath: str,
        venv_python: str,
    ) -> Dict:
        """
        Step 8: Run test on original code to detect bugs.

        Args:
            original_code: Original code (full file)
            test_code: Generated test code
            temp_repo: Path to temporary repository copy
            code_relpath: Relative path to code file
            test_relpath: Relative path to test file
            venv_python: Path to Python executable in venv

        Returns:
            Dictionary with test results
        """
        print(f"\n  Step 8: Running bug detection...")

        builds, passes = self.validator.run_tests(
            original_code,
            test_code,
            temp_repo,
            code_relpath,
            test_relpath,
            venv_python,
        )

        if not builds:
            print("    [!] Test doesn't build")
            return {"builds": False, "passes": False, "bugs_detected": None}

        if passes:
            print("    [✓] All tests passed - No bugs detected!")
            return {"builds": True, "passes": True, "bugs_detected": False}
        else:
            print("    [X] TESTS FAILED - BUGS DETECTED!")
            return {"builds": True, "passes": False, "bugs_detected": True}

    def process_chunk(
        self,
        chunk: Dict,
        full_code: str,
        context: str,
        concern: str,
        temp_repo: str,
        code_relpath: str,
        test_relpath: str,
        venv_python: str,
        existing_test_file: str,
    ) -> Optional[Dict]:
        """
        Process a single chunk through the complete 8-step oracle pipeline.

        Args:
            chunk: Chunk dictionary from CodeChunker
            full_code: Full original code file content
            context: Context about the concern
            concern: Concern category
            temp_repo: Path to temporary repository copy
            code_relpath: Relative path to code file
            test_relpath: Relative path to test file
            venv_python: Path to Python executable in venv
            existing_test_file: Existing test file content (required)

        Returns:
            Dictionary with results or None if pipeline failed
        """
        chunk_id = chunk["chunk_id"]
        chunk_code = chunk["original_code"]

        print(f"\n{'='*80}")
        print(f"PROCESSING CHUNK: {chunk_id}")
        print(f"{'='*80}")

        # Step 1: Generate mutants
        mutants = self.generate_mutants(chunk_code, context, concern, num_mutants=10)
        if not mutants:
            print("  WARNING: No mutants generated")
            return None

        # Steps 2-4: Filter mutants
        valid_mutants = self.filter_mutants(
            chunk_code, mutants, temp_repo, code_relpath, test_relpath, venv_python
        )
        if not valid_mutants:
            print("  WARNING: No valid mutants after filtering")
            return None

        # Step 5: Generate oracle
        oracle = self.generate_oracle(chunk_code, valid_mutants, concern)

        # Step 6: Human validation
        validated_oracle = self.validate_oracle_with_user(oracle, chunk_id)

        # Step 7: Generate test (with optional test file context)
        test_code = self.generate_test(chunk_code, validated_oracle, chunk_id, existing_test_file)
        if not test_code:
            print("  WARNING: Failed to generate test")
            return None

        # Step 8: Detect bugs
        bug_results = self.detect_bugs(
            full_code, test_code, temp_repo, code_relpath, test_relpath, venv_python
        )

        # Return complete results
        return {
            "chunk_id": chunk_id,
            "chunk_type": chunk.get("chunk_type", "unknown"),
            "mutants_generated": len(mutants),
            "valid_mutants": len(valid_mutants),
            "oracle": validated_oracle,
            "test_code": test_code,
            "bug_results": bug_results,
            "bugs_detected": bug_results.get("bugs_detected", None),
        }
