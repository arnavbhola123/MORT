"""High-level workflow orchestration for MORT"""

from src.mutation.parallel_processor import ParallelProcessor
from src.shared.chunker import CodeChunker
from src.shared.repo_manager import RepoManager
from typing import Dict, Optional, Callable, Set
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import constants
import os
import json


class WorkflowOrchestrator:
    """Orchestrates the high-level MORT workflow"""

    def __init__(
        self,
        parallel_processor: ParallelProcessor,
        chunker: CodeChunker,
        repo_manager: RepoManager,
        max_workers: int,
        thread_safe_print: Callable,
        model: str,
        chunker_mode: str,
    ):
        self.parallel_processor = parallel_processor
        self.chunker = chunker
        self.repo_manager = repo_manager
        self.max_workers = max_workers
        self._thread_safe_print = thread_safe_print
        self.model = model
        self.chunker_mode = chunker_mode

    def run_workflow(self, code_file: str, test_file: str) -> Optional[Dict]:
        """Run the MORT workflow with chunk-based mutation"""
        print("Starting MORT Workflow (chunk-based mutation)...")
        print(f"Using model: {self.model}")
        print(f"Chunker mode: {self.chunker_mode.upper()}")
        print(f"Processing: {code_file}, {test_file}")
        print(f"Max parallel workers: {self.max_workers}")

        # Load existing metadata for deduplication
        file_name = Path(code_file).stem
        output_folder = os.path.join(constants.OUTPUT_DIR, file_name)
        metadata_path = os.path.join(output_folder, "metadata.json")

        existing_chunk_ids = set()
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, "r", encoding="utf-8") as f:
                    metadata = json.load(f)
                    existing_chunk_ids = {m.get("chunk_id") for m in metadata.get("mutants", [])}
                print(f"Loaded metadata: {len(existing_chunk_ids)} existing mutants found")
            except Exception as e:
                print(f"Warning: Could not load metadata: {e}")

        # Calculate relative paths from repo root
        code_relpath = self.repo_manager.get_relative_path(code_file)
        test_relpath = self.repo_manager.get_relative_path(test_file)

        print(f"Repository: {self.repo_manager.repo_path}")
        print(f"Code file (relative): {code_relpath}")
        print(f"Test file (relative): {test_relpath}")

        # Create master copy with dependencies installed (cached if exists)
        print("\n" + "=" * 60)
        print("CREATING MASTER REPOSITORY COPY")
        print("=" * 60)
        try:
            self.repo_manager.create_master_copy(constants.EXCLUDE_FROM_COPY)
            print(f"  Master copy ready with installed dependencies")
            print(f"  Using Python: {self.repo_manager.venv_python}")
        except Exception as e:
            print(f"  Failed to create master copy: {e}")
            return None

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
            print("  Failed to chunk file")
            return None

        mutable_chunks = self.chunker.get_mutable_chunks(file_data)[:3]
        print(
            f"  Found {len(file_data['chunks'])} chunks ({len(mutable_chunks)} mutable)"
        )

        if not mutable_chunks:
            print("  No mutable chunks found")
            return None

        # Process each mutable chunk in parallel
        successful_mutants = []
        skipped_count = 0
        total_chunks = len(mutable_chunks)

        print(f"\n{'=' * 60}")
        print(f"PROCESSING {total_chunks} CHUNKS IN PARALLEL")
        print(f"{'=' * 60}\n")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all tasks
            future_to_chunk = {
                executor.submit(
                    self.parallel_processor.process_chunk_with_index,
                    idx,
                    chunk,
                    file_data,
                    existing_test_class,
                    context_about_concern,
                    diff,
                    total_chunks,
                    code_relpath,
                    test_relpath,
                    self.repo_manager.venv_python,
                    existing_chunk_ids,
                ): (idx, chunk)
                for idx, chunk in enumerate(mutable_chunks)
            }

            # Process completed tasks as they finish
            for future in as_completed(future_to_chunk):
                idx, chunk = future_to_chunk[future]
                try:
                    result = future.result()
                    if result:
                        if result.get("skipped"):
                            skipped_count += 1
                        else:
                            successful_mutants.append(result)
                except Exception as e:
                    self._thread_safe_print(f"Exception: {e}", chunk["chunk_id"])

        # Cleanup worker copies 
        print("\n" + "=" * 60)
        print("CLEANING UP WORKER COPIES")
        print("=" * 60)
        try:
            self.repo_manager.cleanup_copies()
            print("  All copies cleaned up")
        except Exception as e:
            print(f"  Cleanup warning: {e}")

        # Summary
        print("\n" + "=" * 60)
        print(
            f"WORKFLOW COMPLETE: {len(successful_mutants)} new, {skipped_count} skipped, {len(mutable_chunks)} total chunks"
        )
        print("=" * 60)

        if successful_mutants:
            return {
                "file_data": file_data,
                "mutants": successful_mutants,
                "total_chunks": len(mutable_chunks),
                "successful_count": len(successful_mutants),
                "skipped_count": skipped_count,
            }

        return None
