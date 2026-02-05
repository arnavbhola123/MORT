"""LLM-powered module summary generation"""

from typing import Dict, List

from src.shared.llm_client import LLMClient
from prompts.templates import PromptTemplates

from constants import INDEXER_MAX_SOURCE_CHARS


class ModuleSummarizer:
    """Generate one-paragraph summaries of Python modules using the LLM"""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    def summarize_file(
        self, file_path: str, source_code: str,
        function_count: int, class_count: int,
    ) -> Dict:
        """
        Generate a summary for a single Python file.

        Args:
            file_path: Relative path to the file
            source_code: Full source code of the file
            function_count: Number of functions found in this file
            class_count: Number of classes found in this file

        Returns:
            Module summary dict
        """
        try:
            # Truncate long source to stay within LLM context
            truncated = source_code[:INDEXER_MAX_SOURCE_CHARS]
            if len(source_code) > INDEXER_MAX_SOURCE_CHARS:
                truncated += "\n# ... (truncated)"

            prompt = PromptTemplates.module_summary(file_path, truncated)
            response = self._llm.invoke(prompt)

            return {
                "file_path": file_path,
                "summary": response.strip(),
                "function_count": function_count,
                "class_count": class_count,
            }
        except Exception as e:
            print(f"WARNING: Failed to summarize {file_path}: {e}")
            return {
                "file_path": file_path,
                "summary": "Summary generation failed",
                "function_count": function_count,
                "class_count": class_count,
            }

    def summarize_files(self, files: List[Dict]) -> List[Dict]:
        """
        Generate summaries for multiple files sequentially.

        Args:
            files: List of dicts with keys: file_path, source_code, function_count, class_count

        Returns:
            List of module summary dicts
        """
        summaries = []
        total = len(files)
        for i, file_data in enumerate(files, 1):
            print(f"  Summarizing [{i}/{total}] {file_data['file_path']}...")
            summary = self.summarize_file(
                file_data["file_path"],
                file_data["source_code"],
                file_data["function_count"],
                file_data["class_count"],
            )
            summaries.append(summary)
        return summaries
