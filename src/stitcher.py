"""File reconstruction utilities - simple chunk joining"""
from typing import Dict, Optional


class FileStitcher:
    """Reconstruct Python files from chunks with mutations"""

    def stitch_file(self, file_data: Dict, mutated_chunk_id: Optional[str] = None,
                   mutated_code: Optional[str] = None) -> str:
        """
        Reconstruct a full Python file from chunks.
        Simply joins all chunks in order, replacing one if mutated.

        Args:
            file_data: Dictionary from CodeChunker.extract_chunks()
            mutated_chunk_id: ID of chunk to replace with mutated version
            mutated_code: The mutated code to use for that chunk

        Returns:
            Complete Python file as string
        """
        if not file_data or 'chunks' not in file_data:
            return ""

        parts = []
        for chunk in file_data['chunks']:
            if mutated_chunk_id and chunk['chunk_id'] == mutated_chunk_id and mutated_code:
                # Use mutated version
                parts.append(mutated_code)
            else:
                # Use original
                parts.append(chunk['original_code'])

        return ''.join(parts)

    def create_mutant_file(self, file_data: Dict, chunk: Dict,
                          mutated_chunk_code: str) -> str:
        """
        Convenience method to create a full file with one mutated chunk.

        Args:
            file_data: Original file data
            chunk: The chunk being mutated
            mutated_chunk_code: The mutated version of the chunk

        Returns:
            Complete file with mutation
        """
        return self.stitch_file(file_data, chunk['chunk_id'], mutated_chunk_code)
