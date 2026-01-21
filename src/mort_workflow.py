"""Core workflow implementation"""

from src.shared.llm_client import LLMClient
from src.shared.validators import CodeValidator
from src.shared.chunker import CodeChunker
from src.mutation.stitcher import FileStitcher
from src.shared.repo_manager import RepoManager
from src.mutation.llm_orchestrator import LLMOrchestrator
from src.mutation.mutation_pipeline import MutationPipeline
from src.mutation.parallel_processor import ParallelProcessor
from src.mutation.mutation_orchestrator import MutationOrchestrator
from src.oracle.oracle_validator import OracleValidator
from src.oracle.oracle_pipeline import OraclePipeline
from src.oracle.oracle_orchestrator import OracleOrchestrator
from prompts.templates import PromptTemplates
from typing import Dict, Optional
import threading
import os
import constants


class MORTWorkflow:
    """Unified facade for MORT workflows (mutation or oracle)"""

    def __init__(
        self,
        repo_path: str,
        model: str,
        provider: str,
        max_workers: int = 3,
        chunker_mode: str = "llm",
        mode: str = "mutation",
        concern: str = None,
    ):
        self.repo_path = os.path.abspath(repo_path)
        self.max_workers = max_workers
        self.chunker_mode = chunker_mode.lower()
        self.mode = mode
        self.concern = concern or constants.DEFAULT_CONCERN
        self._print_lock = threading.Lock()

        # Initialize shared dependencies
        llm = LLMClient(model, provider)
        validator = CodeValidator()
        prompts = PromptTemplates()
        chunker = CodeChunker(mode=chunker_mode)
        repo_manager = RepoManager(repo_path, constants.TEMP_TESTING_DIR)

        # Mode-specific initialization
        if mode == "mutation":
            # Build mutation-specific module hierarchy
            stitcher = FileStitcher()
            llm_orchestrator = LLMOrchestrator(llm, prompts)
            mutation_pipeline = MutationPipeline(
                llm_orchestrator, validator, stitcher, self._thread_safe_print
            )
            parallel_processor = ParallelProcessor(
                mutation_pipeline, repo_manager, self._thread_safe_print
            )
            self.workflow_orchestrator = MutationOrchestrator(
                parallel_processor,
                chunker,
                repo_manager,
                max_workers,
                self._thread_safe_print,
                llm.model,
                self.chunker_mode,
                self.concern,
            )
            self.oracle_orchestrator = None

        elif mode == "oracle":
            # Build oracle-specific module hierarchy
            output_dir = os.path.join(constants.ORACLE_OUTPUT_DIR, "temp")
            oracle_validator = OracleValidator(output_dir)
            oracle_pipeline = OraclePipeline(llm, validator, prompts, oracle_validator)
            self.oracle_orchestrator = OracleOrchestrator(
                oracle_pipeline,
                chunker,
                repo_manager,
                self._thread_safe_print,
                llm.model,
                self.concern,
            )
            self.workflow_orchestrator = None

        else:
            raise ValueError(f"Invalid mode: {mode}. Must be 'mutation' or 'oracle'")

    def _thread_safe_print(self, message: str, chunk_id: str = None):
        """Thread-safe printing with optional chunk identification"""
        with self._print_lock:
            if chunk_id:
                print(f"[{chunk_id}] {message}")
            else:
                print(message)

    def run_workflow(self, code_file: str, test_file: str) -> Optional[Dict]:
        """Run mutation workflow (existing)"""
        if self.mode != "mutation":
            raise ValueError("Use run_oracle_workflow() for oracle mode")
        return self.workflow_orchestrator.run_workflow(code_file, test_file)

    def run_oracle_workflow(self, code_file: str, test_file: str = None) -> Optional[Dict]:
        """Run oracle inference workflow (new)"""
        if self.mode != "oracle":
            raise ValueError("Use run_workflow() for mutation mode")
        return self.oracle_orchestrator.run_workflow(code_file, self.repo_path, test_file)