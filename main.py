"""CLI entry point for ACH"""

import sys
import os
import json
from dotenv import load_dotenv
from src.ach_workflow import ACHWorkflow
from constants import MODEL, MODEL_PROVIDER, OUTPUT_DIR
import time

load_dotenv()


def main():
    """Run ACH with chunk-based mutation"""
    if len(sys.argv) < 3:
        print("Usage: python main.py <CODE_FILE.py> <TEST_FILE.py> [max_workers]")
        print("  max_workers: optional, number of parallel workers (default: 4)")
        sys.exit(1)

    code_file = sys.argv[1]
    test_file = sys.argv[2]

    # Optional: get max_workers from command line or env
    max_workers = 3  # default
    if len(sys.argv) > 3:
        try:
            max_workers = int(sys.argv[3])
        except ValueError:
            print(f"Warning: Invalid max_workers '{sys.argv[3]}', using default: 3")
    else:
        # Allow override from environment variable
        max_workers = int(os.getenv("MAX_WORKERS", "4"))

    if not os.path.isfile(code_file):
        print(f"Error: code file not found: {code_file}")
        sys.exit(2)
    if not os.path.isfile(test_file):
        print(f"Error: test file not found: {test_file}")
        sys.exit(2)

    print(" ACH Workflow Starting")
    print("-" * 60)

    # Use constants, but allow .env to override
    model = os.getenv("MODEL", MODEL)
    provider = os.getenv("MODEL_PROVIDER", MODEL_PROVIDER)

    ach = ACHWorkflow(model, provider, max_workers=max_workers)
    result = ach.run_workflow(code_file, test_file)

    if result:
        print("\n" + "=" * 60)
        print("FINAL RESULTS")
        print("=" * 60)
        print(f"Successfully generated {result['successful_count']} mutant(s)")

        # Save results
        os.makedirs(OUTPUT_DIR, exist_ok=True)

        # Save each mutant and test
        for idx, mutant_data in enumerate(result["mutants"]):
            chunk_id = mutant_data["chunk_id"].replace(".", "_")

            # Save mutated file
            mutant_path = os.path.join(OUTPUT_DIR, f"mutant_{chunk_id}.py")
            with open(mutant_path, "w", encoding="utf-8") as f:
                f.write(mutant_data["mutated_file"])

            # Save test
            test_path = os.path.join(OUTPUT_DIR, f"test_{chunk_id}.py")
            with open(test_path, "w", encoding="utf-8") as f:
                f.write(mutant_data["test"])

            print(f"  [{idx + 1}] {mutant_data['chunk_id']}")
            print(f"      Mutant: {mutant_path}")
            print(f"      Test:   {test_path}")
            print(f"      ✨🏆 LLM JUDGE SCORE: {mutant_data['llm_judge_score']} 🏆✨")

        # Save metadata
        metadata = {
            "total_chunks": result["total_chunks"],
            "successful_count": result["successful_count"],
            "mutants": [
                {
                    "chunk_id": m["chunk_id"],
                    "chunk_type": m["chunk_type"],
                    "files": {
                        "mutant": f"mutant_{m['chunk_id'].replace('.', '_')}.py",
                        "test": f"test_{m['chunk_id'].replace('.', '_')}.py",
                    },
                }
                for m in result["mutants"]
            ],
        }
        metadata_path = os.path.join(OUTPUT_DIR, "metadata.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print(f"\n  Metadata: {metadata_path}")
    else:
        print("\n Workflow did not produce any valid mutant and test pairs")


if __name__ == "__main__":
    t1 = time.time()
    main()
    t2 = time.time()
    print(f"\n\n⏰ Finished in {t2 - t1:.2f} seconds")
    exit(0)
