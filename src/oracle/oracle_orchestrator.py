"""High-level orchestration for oracle inference workflow"""

import json
import os
from pathlib import Path
from typing import Callable, Dict, Optional

import constants
from src.oracle.oracle_pipeline import OraclePipeline
from src.shared.chunker import CodeChunker
from src.shared.repo_manager import RepoManager


class OracleOrchestrator:
    """Orchestrates the oracle inference workflow with full repo context"""

    def __init__(
        self,
        oracle_pipeline: OraclePipeline,
        chunker: CodeChunker,
        repo_manager: RepoManager,
        thread_safe_print: Callable,
        model: str,
        concern: str,
    ):
        self.oracle_pipeline = oracle_pipeline
        self.chunker = chunker
        self.repo_manager = repo_manager
        self._thread_safe_print = thread_safe_print
        self.model = model
        self.concern = concern

    def run_workflow(
        self, code_file: str, repo_path: str, test_file: str
    ) -> Optional[Dict]:
        """
        Execute oracle workflow with full repo context.

        Steps:
        1. Create master repo copy with dependencies
        2. Read code file and chunk it
        3. Read existing test file (required for test generation context)
        4. Filter to function-level chunks only
        5. Process each function through oracle pipeline (sequential)
        6. Use temp repo for all test executions
        7. Aggregate results and generate bug reports
        8. Cleanup repo copies

        Args:
            code_file: Absolute path to code file
            repo_path: Absolute path to repository root
            test_file: Path to existing test file (required)

        Returns:
            Dictionary with workflow results or None if failed
        """
        print("Starting Oracle Inference Workflow...")
        print(f"Using model: {self.model}")
        print(f"Concern: {self.concern}")
        print(f"Processing: {code_file}")

        # Calculate relative paths from repo root
        code_relpath = self.repo_manager.get_relative_path(code_file)
        test_relpath = self.repo_manager.get_relative_path(test_file)

        print(f"Repository: {repo_path}")
        print(f"Code file (relative): {code_relpath}")
        print(f"Test file (relative): {test_relpath}")

        # Create master copy with dependencies installed
        print("\n" + "=" * 80)
        print("CREATING MASTER REPOSITORY COPY")
        print("=" * 80)
        try:
            self.repo_manager.create_master_copy(constants.EXCLUDE_FROM_COPY)
            print(f"  Master copy ready with installed dependencies")
            print(f"  Using Python: {self.repo_manager.venv_python}")
        except Exception as e:
            print(f"  Failed to create master copy: {e}")
            return None

        # Create worker copy for oracle processing (single copy, sequential processing)
        print("\n" + "=" * 80)
        print("CREATING WORKER COPY FOR ORACLE PROCESSING")
        print("=" * 80)
        try:
            temp_repo = self.repo_manager.create_worker_copy("oracle_main")
            print(f"  Worker copy created: {temp_repo}")
        except Exception as e:
            print(f"  Failed to create worker copy: {e}")
            return None

        # Read code file
        with open(code_file, "r", encoding="utf-8") as f:
            code_content = f.read()

        # Read existing test file (required for test generation context)
        print(f"\n  Reading existing test file: {test_file}")
        with open(test_file, "r", encoding="utf-8") as f:
            existing_test_content = f.read()
        print(f"  Loaded {len(existing_test_content)} chars from test file")

        # Context based on concern
        concern_contexts = (
            constants.CONCERN_CONTEXTS
            if hasattr(constants, "CONCERN_CONTEXTS")
            else {
                "privacy": "Privacy violations: logging PII, exposing sensitive data, missing authorization, leaking user information",
                "security": "Security vulnerabilities: SQL injection, XSS, authentication bypass, insecure data handling, missing input validation",
                "performance": "Performance issues: inefficient algorithms, memory leaks, unnecessary computations, poor resource management",
                "correctness": "Correctness bugs: off-by-one errors, null pointer issues, logic errors, edge case failures",
            }
        )
        context = concern_contexts.get(
            self.concern, f"Issues related to {self.concern}"
        )

        # Chunk the code file
        print("\n" + "=" * 80)
        print("STEP 0: Chunking code file")
        print("=" * 80)
        file_data = self.chunker.extract_chunks(code_content, code_file)

        if not file_data:
            print("  Failed to chunk file")
            return None

        # Filter to function-level chunks only (not imports, constants, etc.)
        # For oracle mode, we want functions and methods, not gap chunks
        # TODO: REMOVE LIMITATION AFTER TESTING
        function_chunks = [
            chunk for chunk in file_data["chunks"] if chunk.get("is_mutable", True)
        ][1:2]

        print(f"  Found {len(file_data['chunks'])} chunks")
        print(
            f"  {len(function_chunks)} are functions/methods suitable for oracle inference"
        )

        if not function_chunks:
            print("  No function chunks found for oracle inference")
            return None

        # Process each function chunk sequentially
        results = []
        bugs_found = 0

        print(f"\n{'=' * 80}")
        print(f"PROCESSING {len(function_chunks)} FUNCTIONS SEQUENTIALLY")
        print(f"{'=' * 80}\n")

        for idx, chunk in enumerate(function_chunks, 1):
            print(f"\n{'#' * 80}")
            print(f"FUNCTION {idx}/{len(function_chunks)}: {chunk['chunk_id']}")
            print(f"{'#' * 80}")

            result = self.oracle_pipeline.process_chunk(
                chunk,
                code_content,
                context,
                self.concern,
                temp_repo,
                code_relpath,
                test_relpath,
                self.repo_manager.venv_python,
                existing_test_content,  # Pass test file content for style reference
            )

            if result:
                results.append(result)
                if result.get("bugs_detected"):
                    bugs_found += 1

        # Cleanup worker copy
        print("\n" + "=" * 80)
        print("CLEANING UP WORKER COPIES")
        print("=" * 80)
        try:
            self.repo_manager.cleanup_copies()
            print("  All copies cleaned up")
        except Exception as e:
            print(f"  Cleanup warning: {e}")

        # Save results
        print("\n" + "=" * 80)
        print("SAVING RESULTS")
        print("=" * 80)

        file_name = Path(code_file).stem
        oracle_output_dir = (
            constants.ORACLE_OUTPUT_DIR
            if hasattr(constants, "ORACLE_OUTPUT_DIR")
            else "oracle_outputs"
        )
        output_folder = os.path.join(oracle_output_dir, file_name)
        os.makedirs(output_folder, exist_ok=True)

        # Save metadata
        metadata = {
            "code_file": code_file,
            "concern": self.concern,
            "functions_processed": len(results),
            "bugs_found": bugs_found,
            "results": results,
        }

        metadata_path = os.path.join(output_folder, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print(f"  Metadata saved to: {metadata_path}")

        # Save individual test files
        for result in results:
            chunk_id = result["chunk_id"].replace(".", "_")
            test_file = os.path.join(output_folder, f"test_{chunk_id}.py")

            with open(test_file, "w", encoding="utf-8") as f:
                f.write(result["test_code"])

            print(f"  Test saved: test_{chunk_id}.py")

        # Generate bug report
        self._generate_bug_report(output_folder, metadata)

        # Summary
        print("\n" + "=" * 80)
        print("WORKFLOW COMPLETE")
        print("=" * 80)
        print(f"  Functions processed: {len(results)}")
        print(f"  Bugs detected: {bugs_found}")
        print(f"  Output directory: {output_folder}")

        return metadata

    def _generate_bug_report(self, output_folder: str, metadata: Dict):
        """Generate human-readable bug report"""
        report_path = os.path.join(output_folder, "bug_report.txt")

        with open(report_path, "w", encoding="utf-8") as f:
            f.write("=" * 80 + "\n")
            f.write(f"BUG DETECTION REPORT\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Code File: {metadata['code_file']}\n")
            f.write(f"Concern: {metadata['concern']}\n")
            f.write(f"Functions Processed: {metadata['functions_processed']}\n")
            f.write(f"Bugs Found: {metadata['bugs_found']}\n\n")

            for result in metadata["results"]:
                f.write("-" * 80 + "\n")
                f.write(f"Function: {result['chunk_id']}\n")
                f.write(f"Mutants Generated: {result['mutants_generated']}\n")
                f.write(f"Valid Mutants: {result['valid_mutants']}\n")

                if result["bugs_detected"]:
                    f.write(f"STATUS: [X] BUGS DETECTED\n\n")
                    f.write(f"ORACLE SPECIFICATION:\n")
                    f.write(result["oracle"] + "\n\n")
                    f.write(f"RECOMMENDATION:\n")
                    f.write(
                        f"Review the test file: test_{result['chunk_id'].replace('.', '_')}.py\n"
                    )
                    f.write(
                        f"Run the tests to see specific failures and fix the identified {metadata['concern']} violations.\n"
                    )
                elif result["bugs_detected"] is False:
                    f.write(f"STATUS: [✓] NO BUGS DETECTED\n")
                else:
                    f.write(f"STATUS: [?] TEST BUILD FAILED\n")

                f.write("\n")

        print(f"  Bug report saved: bug_report.txt")
