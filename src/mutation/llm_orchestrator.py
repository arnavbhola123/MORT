"""LLM interaction orchestrator for MORT workflow"""

from src.shared.llm_client import LLMClient
from prompts.templates import PromptTemplates
from typing import Dict, Optional
import json


class LLMOrchestrator:
    """Handles all LLM interactions for the MORT workflow"""

    def __init__(self, llm_client: LLMClient, prompts: PromptTemplates):
        self.llm = llm_client
        self.prompts = prompts

    def make_fault_for_chunk(
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

        print(f"\n{'='*60}")
        print("LLM CALL: Generate Mutant")
        print(f"{'='*60}")
        print(f"Prompt length: {len(prompt)} chars")
        print(f"Chunk type: {chunk['chunk_type']}")
        print(f"Original code preview: {chunk['original_code']}")

        text = self.llm.invoke(prompt)

        print(f"\nLLM Response (length: {len(text)} chars):")
        print(f"{'-'*60}")
        print(text)
        print(f"{'-'*60}\n")

        extracted = self.llm.extract_code_from_response(text)
        if extracted:
            print(f"Extracted code (length: {len(extracted)} chars)")
        else:
            print(f"Failed to extract code from response")

        return extracted

    def equivalence_detector(self, class_version1: str, class_version2: str) -> bool:
        """Table 1: Equivalence detector"""
        prompt = self.prompts.equivalence_detector(class_version1, class_version2)

        print(f"\n{'='*60}")
        print("LLM CALL: Equivalence Detection")
        print(f"{'='*60}")
        print(f"Prompt length: {len(prompt)} chars")

        answer = self.llm.invoke(prompt).strip()

        print(f"\nLLM Response:")
        print(f"{'-'*60}")
        print(answer[:100])
        print(f"{'-'*60}")
        print(f"Is equivalent: {answer.lower().startswith('yes')}\n")

        return answer.lower().startswith("yes")

    def make_test_to_catch_fault(
        self, original_class: str, mutated_class: str, existing_test_class: str
    ) -> Optional[str]:
        """Table 1: Make a test to catch fault"""
        prompt = self.prompts.make_test_to_catch_fault(
            original_class, mutated_class, existing_test_class
        )

        print(f"\n{'='*60}")
        print("LLM CALL: Generate Test to Kill Mutant")
        print(f"{'='*60}")
        print(f"Prompt length: {len(prompt)} chars")

        text = self.llm.invoke(prompt)

        print(f"\nLLM Response (length: {len(text)} chars):")
        print(f"{'-'*60}")
        print(text[:100])
        print(f"{'-'*60}\n")

        extracted = self.llm.extract_code_from_response(text)
        if extracted:
            print(f"Extracted test code (length: {len(extracted)} chars)")
        else:
            print(f"Failed to extract test code from response")

        return extracted

    def llm_judge_mutant(
        self,
        original_code: str,
        mutated_code: str,
        original_test: str,
        new_test: str,
        context: str,
        diff: str,
    ) -> Optional[Dict]:
        """
        LLM as judge - evaluates the quality and relevance of the generated mutant.

        Args:
            original_code: The original code chunk
            mutated_code: The mutated code chunk
            original_test: The existing test suite
            new_test: The newly generated test
            context: The context about the concern (e.g., privacy violations)

        Returns:
            Dictionary of scores, or None if evaluation fails
        """
        prompt = self.prompts.llm_judge_mutant(
            original_code=original_code,
            mutated_code=mutated_code,
            original_test=original_test,
            new_test=new_test,
            context=context,
            diff=diff
        )

        print(f"\n{'='*60}")
        print("LLM CALL: Judge Mutant Quality")
        print(f"{'='*60}")
        print(f"Prompt length: {len(prompt)} chars")

        try:
            response = self.llm.invoke(prompt)

            print(f"\nLLM Response (length: {len(response)} chars):")
            print(f"{'-'*60}")
            print(response[:100])
            print(f"{'-'*60}\n")

            # Extract JSON from markdown or raw response
            json_str = self.llm.extract_json_from_response(response)
            scores = json.loads(json_str)

            print(f"Parsed scores: {scores}\n")
            return scores

        except json.JSONDecodeError as e:
            print(f"Error parsing JSON from LLM judge: {e}")
            print(f"  Response was: {response}\n")
            return None
        except Exception as e:
            print(f"Error in LLM judge: {e}\n")
            return None
