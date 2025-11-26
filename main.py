"""CLI entry point for ACH"""

import sys
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from src.ach_workflow import ACHWorkflow
from constants import MODEL, MODEL_PROVIDER, OUTPUT_DIR, MAX_WORKERS
import time

load_dotenv()


def main():
    """Run ACH with chunk-based mutation"""
    if len(sys.argv) < 4:
        print("Usage: python main.py <repo_path> <code_file> <test_file> [max_workers] [chunker_mode]")
        print()
        print("Arguments:")
        print("  repo_path: Path to repository root (e.g., '.' or '/path/to/repo')")
        print("  code_file: Code file path (relative to repo or absolute)")
        print("  test_file: Test file path (relative to repo or absolute)")
        print("  max_workers: optional, number of parallel workers (default: 3)")
        print("  chunker_mode: optional, 'llm' or 'ast' (default: 'llm')")
        print()
        print("Examples:")
        print("  python main.py . src/validators.py tests/test_validators.py")
        print("  python main.py . examples/simple_example.py examples/simple_example_test.py 5 llm")
        print("  python main.py /path/to/repo src/file.py tests/test_file.py")
        sys.exit(1)

    repo_path = sys.argv[1]
    code_file = sys.argv[2]
    test_file = sys.argv[3]

    # Optional: get max_workers from command line or env
    max_workers = MAX_WORKERS  # default
    if len(sys.argv) > 4:
        try:
            max_workers = int(sys.argv[4])
        except ValueError:
            print(f"Warning: Invalid max_workers '{sys.argv[4]}', using default: 3")

    # Optional: get chunker mode from command line or env
    chunker_mode = "llm"  # default
    if len(sys.argv) > 5:
        chunker_mode = sys.argv[5].lower()
        if chunker_mode not in ["llm", "ast"]:
            print(f"Warning: Invalid chunker_mode '{sys.argv[5]}', using default: 'llm'")
            chunker_mode = "llm"
    else:
        # Allow override from environment variable
        chunker_mode = os.getenv("CHUNKER_MODE", "llm").lower()

    # Convert repo_path to absolute
    repo_path = os.path.abspath(repo_path)

    # Handle both absolute and relative paths for code/test files
    if os.path.isabs(code_file):
        code_file_abs = code_file
    else:
        code_file_abs = os.path.join(repo_path, code_file)

    if os.path.isabs(test_file):
        test_file_abs = test_file
    else:
        test_file_abs = os.path.join(repo_path, test_file)

    # Validate paths
    if not os.path.isdir(repo_path):
        print(f"Error: Repository path not found: {repo_path}")
        sys.exit(2)
    if not os.path.isfile(code_file_abs):
        print(f"Error: Code file not found: {code_file_abs}")
        sys.exit(2)
    if not os.path.isfile(test_file_abs):
        print(f"Error: Test file not found: {test_file_abs}")
        sys.exit(2)

    print(" ACH Workflow Starting")
    print("-" * 60)
    print(f"Chunker mode: {chunker_mode.upper()}")

    # Use constants, but allow .env to override
    model = os.getenv("MODEL", MODEL)
    provider = os.getenv("MODEL_PROVIDER", MODEL_PROVIDER)

    ach = ACHWorkflow(repo_path, model, provider, max_workers=max_workers, chunker_mode=chunker_mode)
    result = ach.run_workflow(code_file_abs, test_file_abs)

    if result:
        print("\n" + "=" * 60)
        print("FINAL RESULTS")
        print("=" * 60)
        print(f"Successfully generated {result['successful_count']} new mutant(s)")
        print(f"Skipped {result.get('skipped_count', 0)} duplicate(s)")

        # Create file-specific output folder
        file_name = Path(code_file_abs).stem
        output_folder = os.path.join(OUTPUT_DIR, file_name)
        os.makedirs(output_folder, exist_ok=True)

        # Load existing metadata
        metadata_path = os.path.join(output_folder, "metadata.json")
        if os.path.exists(metadata_path):
            with open(metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)
        else:
            metadata = {
                "code_file": code_file_abs,
                "total_chunks": result["total_chunks"],
                "mutants": []
            }

        print("\n" + "=" * 60)
        print("SAVING RESULTS")
        print("=" * 60)
        print(f"Output folder: {output_folder}")

        # Save each new mutant
        for mutant_data in result["mutants"]:
            mutant_hash = mutant_data["hash"]
            chunk_id = mutant_data["chunk_id"].replace(".", "_")
            mutant_filename = f"mutant_{chunk_id}_{mutant_hash}.py"
            test_filename = f"test_{chunk_id}_{mutant_hash}.py"

            mutant_path = os.path.join(output_folder, mutant_filename)
            with open(mutant_path, "w", encoding="utf-8") as f:
                f.write(mutant_data["mutated_file"])

            test_path = os.path.join(output_folder, test_filename)
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(mutant_data["test"])

            # Add to metadata
            metadata["mutants"].append({
                "hash": mutant_hash,
                "chunk_id": mutant_data["chunk_id"],
                "chunk_type": mutant_data["chunk_type"],
                "files": {
                    "mutant": mutant_filename,
                    "test": test_filename,
                },
                "scores": mutant_data.get("scores", {}),
            })

            print(f"  [SAVED] {mutant_data['chunk_id']}")
            print(f"          Mutant: {mutant_filename}")
            print(f"          Test:   {test_filename}")
            print(f"          Scores: {mutant_data.get('scores', {})}")

        # Save updated metadata
        metadata["successful_count"] = len(metadata["mutants"])
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print(f"\n  Metadata: {metadata_path}")
        print(f"  Total mutants for this file: {len(metadata['mutants'])}")
    else:
        print("\n Workflow did not produce any valid mutant and test pairs")


if __name__ == "__main__":
    t1 = time.time()
    main()
    t2 = time.time()
    print(f"\n\nFinished in {t2 - t1:.2f} seconds")
    exit(0)
