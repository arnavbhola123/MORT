"""Core workflow implementation"""

from src.shared.llm_client import LLMClient
from src.shared.validators import CodeValidator
from src.shared.chunker import CodeChunker
from src.mutation.stitcher import FileStitcher
from src.shared.repo_manager import RepoManager
from src.mutation.llm_orchestrator import LLMOrchestrator
from src.mutation.mutation_pipeline import MutationPipeline
from src.mutation.parallel_processor import ParallelProcessor
from src.mutation.workflow_orchestrator import WorkflowOrchestrator
from prompts.templates import PromptTemplates
from typing import Dict, Optional
import threading
import os
import constants


class ACHWorkflow:
    """Facade for the ACH workflow - delegates to specialized modules"""

    def __init__(self, repo_path: str, model: str, provider: str, max_workers: int = 3, chunker_mode: str = "llm"):
        self.repo_path = os.path.abspath(repo_path)
        self.max_workers = max_workers
        self.chunker_mode = chunker_mode.lower()
        self._print_lock = threading.Lock()

        # Initialize dependencies
        llm = LLMClient(model, provider)
        validator = CodeValidator()
        prompts = PromptTemplates()
        chunker = CodeChunker(mode=chunker_mode)
        stitcher = FileStitcher()
        repo_manager = RepoManager(repo_path, constants.TEMP_TESTING_DIR)

        # Build the module hierarchy
        llm_orchestrator = LLMOrchestrator(llm, prompts)
        mutation_pipeline = MutationPipeline(
            llm_orchestrator, validator, stitcher, self._thread_safe_print
        )
        parallel_processor = ParallelProcessor(
            mutation_pipeline, repo_manager, self._thread_safe_print
        )
        self.workflow_orchestrator = WorkflowOrchestrator(
            parallel_processor,
            chunker,
            repo_manager,
            max_workers,
            self._thread_safe_print,
            llm.model,
            self.chunker_mode,
        )

    def _thread_safe_print(self, message: str, chunk_id: str = None):
        """Thread-safe printing with optional chunk identification"""
        with self._print_lock:
            if chunk_id:
                print(f"[{chunk_id}] {message}")
            else:
                print(message)

    def run_workflow(self, code_file: str, test_file: str) -> Optional[Dict]:
        """Run the ACH workflow with chunk-based mutation"""
        return self.workflow_orchestrator.run_workflow(code_file, test_file)