"""Parallel processing manager for ACH workflow"""

from src.mutation.mutation_pipeline import MutationPipeline
from src.shared.repo_manager import RepoManager
from typing import Dict, Optional, Callable, Set
import threading


class ParallelProcessor:
    """Handles parallel chunk processing with thread-safe worker management"""

    def __init__(
        self,
        mutation_pipeline: MutationPipeline,
        repo_manager: RepoManager,
        thread_safe_print: Callable,
    ):
        self.mutation_pipeline = mutation_pipeline
        self.repo_manager = repo_manager
        self._thread_safe_print = thread_safe_print
        self._worker_copies = {}

    def process_chunk_with_index(
        self,
        idx: int,
        chunk: Dict,
        file_data: Dict,
        existing_test_class: str,
        context: str,
        diff: str,
        total_chunks: int,
        code_relpath: str,
        test_relpath: str,
        venv_python: str,
        existing_chunk_ids: Set[str],
    ) -> Optional[Dict]:
        """Process a single chunk with its index (for parallel execution)"""
        chunk_id = chunk["chunk_id"]

        self._thread_safe_print(
            f"{'=' * 50}\nStarting chunk {idx + 1}/{total_chunks}\n{'=' * 50}", chunk_id
        )

        # Get or create worker copy for this thread
        worker_id = threading.current_thread().ident
        if worker_id not in self._worker_copies:
            try:
                temp_repo = self.repo_manager.create_worker_copy(str(worker_id))
                self._worker_copies[worker_id] = temp_repo
                self._thread_safe_print(f"Created worker copy: {temp_repo}", chunk_id)
            except Exception as e:
                self._thread_safe_print(f"Failed to create worker copy: {e}", chunk_id)
                return None

        temp_repo = self._worker_copies[worker_id]

        result = self.mutation_pipeline.process_chunk(
            chunk,
            file_data,
            existing_test_class,
            context,
            diff,
            temp_repo,
            code_relpath,
            test_relpath,
            venv_python,
            existing_chunk_ids,
        )

        if result:
            if result.get("skipped"):
                self._thread_safe_print(f"Skipped (already exists)", chunk_id)
            else:
                self._thread_safe_print(f"Successfully generated mutant and test", chunk_id)
            return result
        else:
            self._thread_safe_print(f"Failed to generate valid mutant", chunk_id)
            return None
