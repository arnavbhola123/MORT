"""CLI entry point for MORT - Mutation-Guided Oracle Refinement Testing"""

import argparse
import sys
import os
import json
from pathlib import Path
from dotenv import load_dotenv
from src.mort_workflow import MORTWorkflow
from constants import MODEL, MODEL_PROVIDER, OUTPUT_DIR, MAX_WORKERS, ORACLE_OUTPUT_DIR
import time

load_dotenv()


def create_parser():
    """Create argument parser with mode selection"""
    parser = argparse.ArgumentParser(
        description="MORT - Mutation-Guided Oracle Refinement Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Mutation mode (default)
  python main.py . src/validators.py tests/test_validators.py
  python main.py --mode mutation . src/validators.py tests/test_validators.py --max-workers 5

  # Oracle mode
  python main.py --mode oracle . src/user_service.py --concern privacy
  python main.py --mode oracle . examples/calculator.py --concern correctness
        """
    )

    # Mode selection (optional, defaults to mutation for backward compatibility)
    parser.add_argument(
        '--mode',
        choices=['mutation', 'oracle'],
        default='mutation',
        help='Workflow mode (default: mutation)'
    )

    # Required arguments (common)
    parser.add_argument('repo_path', help='Repository root path')
    parser.add_argument('code_file', help='Code file path (relative to repo or absolute)')

    # Mutation mode requires test_file
    parser.add_argument(
        'test_file',
        nargs='?',  # Optional for oracle mode
        help='Test file path (required for mutation mode, not used in oracle mode)'
    )

    # Common options
    parser.add_argument(
        '--max-workers',
        type=int,
        default=MAX_WORKERS,
        help=f'Number of parallel workers for mutation mode (default: {MAX_WORKERS})'
    )
    parser.add_argument(
        '--chunker-mode',
        choices=['llm', 'ast'],
        default='llm',
        help='Chunking strategy (default: llm)'
    )

    # Oracle-specific options
    parser.add_argument(
        '--concern',
        choices=['privacy', 'security', 'correctness', 'performance'],
        help='Concern category for oracle mode (required for oracle mode)'
    )

    return parser


def validate_args(args):
    """Validate mode-specific requirements"""
    if args.mode == 'mutation':
        if not args.test_file:
            print("Error: test_file is required for mutation mode")
            print("Usage: python main.py <repo_path> <code_file> <test_file>")
            sys.exit(1)
    elif args.mode == 'oracle':
        if not args.concern:
            print("Error: --concern is required for oracle mode")
            print("Usage: python main.py --mode oracle <repo_path> <code_file> --concern {privacy|security|correctness|performance}")
            sys.exit(1)


def run_mutation_mode(args, repo_path, code_file_abs, test_file_abs):
    """Run mutation testing workflow"""
    print(" MORT MUTATION TESTING WORKFLOW")
    print("-" * 80)
    print(f"Chunker mode: {args.chunker_mode.upper()}")
    print(f"Max workers: {args.max_workers}")
    print("-" * 80)

    # Get model configuration
    model = os.getenv("MODEL", MODEL)
    provider = os.getenv("MODEL_PROVIDER", MODEL_PROVIDER)

    # Initialize and run mutation workflow
    mort = MORTWorkflow(
        repo_path,
        model,
        provider,
        max_workers=args.max_workers,
        chunker_mode=args.chunker_mode,
        mode='mutation'
    )
    result = mort.run_workflow(code_file_abs, test_file_abs)

    if result:
        print("\n" + "=" * 80)
        print("FINAL RESULTS")
        print("=" * 80)
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

        print("\n" + "=" * 80)
        print("SAVING RESULTS")
        print("=" * 80)
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


def run_oracle_mode(args, repo_path, code_file_abs, test_file_abs=None):
    """Run oracle inference workflow"""
    print(" MORT ORACLE INFERENCE WORKFLOW")
    print("-" * 80)
    print(f"Concern: {args.concern.upper()}")
    print(f"Chunker mode: {args.chunker_mode.upper()}")
    if test_file_abs:
        print(f"Test file (for style reference): {test_file_abs}")
    print("-" * 80)

    # Get model configuration
    model = os.getenv("MODEL", MODEL)
    provider = os.getenv("MODEL_PROVIDER", MODEL_PROVIDER)

    # Initialize and run oracle workflow
    mort = MORTWorkflow(
        repo_path,
        model,
        provider,
        chunker_mode=args.chunker_mode,
        mode='oracle',
        concern=args.concern
    )
    result = mort.run_oracle_workflow(code_file_abs, test_file_abs)

    if result:
        print("\n" + "=" * 80)
        print("ORACLE WORKFLOW COMPLETE")
        print("=" * 80)
        print(f"Functions processed: {result['functions_processed']}")
        print(f"Bugs detected: {result['bugs_found']}")
        print("\nFor detailed results, see:")
        file_name = Path(code_file_abs).stem
        output_folder = os.path.join(ORACLE_OUTPUT_DIR, file_name)
        print(f"  Output folder: {output_folder}")
        print(f"  Bug report: {output_folder}/bug_report.txt")
        print(f"  Metadata: {output_folder}/metadata.json")
    else:
        print("\n Oracle workflow failed or produced no results")


def main():
    """Main entry point"""
    parser = create_parser()
    args = parser.parse_args()

    # Validate mode-specific requirements
    validate_args(args)

    # Convert repo_path to absolute
    repo_path = os.path.abspath(args.repo_path)

    # Handle both absolute and relative paths for code file
    if os.path.isabs(args.code_file):
        code_file_abs = args.code_file
    else:
        code_file_abs = os.path.join(repo_path, args.code_file)

    # Validate paths
    if not os.path.isdir(repo_path):
        print(f"Error: Repository path not found: {repo_path}")
        sys.exit(2)
    if not os.path.isfile(code_file_abs):
        print(f"Error: Code file not found: {code_file_abs}")
        sys.exit(2)

    # Handle test file based on mode
    test_file_abs = None
    if args.test_file:
        if os.path.isabs(args.test_file):
            test_file_abs = args.test_file
        else:
            test_file_abs = os.path.join(repo_path, args.test_file)

        # For mutation mode, test file is required and must exist
        if args.mode == 'mutation':
            if not os.path.isfile(test_file_abs):
                print(f"Error: Test file not found: {test_file_abs}")
                sys.exit(2)
        # For oracle mode, test file is optional (just for style reference)
        else:
            if not os.path.isfile(test_file_abs):
                print(f"Warning: Test file not found: {test_file_abs}")
                print("  Proceeding without test file style reference...")
                test_file_abs = None

    if args.mode == 'mutation':
        run_mutation_mode(args, repo_path, code_file_abs, test_file_abs)
    else:
        run_oracle_mode(args, repo_path, code_file_abs, test_file_abs)


if __name__ == "__main__":
    t1 = time.time()
    main()
    t2 = time.time()
    print(f"\n\nFinished in {t2 - t1:.2f} seconds")
    exit(0)
