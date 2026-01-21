import argparse
import json
import os

# Deletes temp testing on every run
import shutil
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

from constants import MAX_WORKERS, MODEL, MODEL_PROVIDER, ORACLE_OUTPUT_DIR, OUTPUT_DIR
from src.mort_workflow import MORTWorkflow

_temp_testing_dir = os.path.join(os.getcwd(), ".temp_testing")
try:
    if os.path.lexists(_temp_testing_dir):
        if os.path.isdir(_temp_testing_dir) and not os.path.islink(_temp_testing_dir):
            shutil.rmtree(_temp_testing_dir)
        else:
            os.unlink(_temp_testing_dir)
except Exception as e:
    print(f"Warning: Failed to remove '.temp_testing': {e}")


# Monkey-patch argparse to use interactive prompts instead of CLI flags/positionals
def _mort_prompt_nonempty(prompt_text):
    while True:
        try:
            val = input(prompt_text).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(130)
        if val:
            return val
        print("Input cannot be empty. Please try again.\n")


def _mort_prompt_choice(prompt_text, choices_map):
    # choices_map: dict of normalized input -> canonical value
    keys_display = sorted(set(choices_map.values()))
    while True:
        try:
            raw = input(f"{prompt_text} ({'/'.join(keys_display)}): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\nAborted.")
            sys.exit(130)
        if not raw:
            print("Please enter a choice.\n")
            continue
        # allow short forms like first letter or numbers (1/2) for common options
        if raw in choices_map:
            return choices_map[raw]
        # try to match exact canonical value
        for canonical in set(choices_map.values()):
            if raw == canonical:
                return canonical
        print(f"Invalid choice: {raw}. Valid options: {', '.join(keys_display)}\n")


def _mort_interactive_parse_args(self, args=None, namespace=None):
    print("\nMORT Interactive Setup")
    print("-" * 30)

    # Step 1: Repository and file paths
    repo_path = _mort_prompt_nonempty("Enter repository root path: ")
    code_file = _mort_prompt_nonempty(
        "Enter code file path (relative to repo or absolute): "
    )
    test_file = _mort_prompt_nonempty(
        "Enter test file path (relative to repo or absolute): "
    )

    # Step 2: Chunking strategy
    chunker_mode = _mort_prompt_choice(
        "Choose chunking strategy",
        {
            "llm": "llm",
            "ast": "ast",
            "l": "llm",
            "a": "ast",
            "1": "llm",
            "2": "ast",
        },
    )

    # Step 3: Workflow mode
    mode = _mort_prompt_choice(
        "Choose workflow mode",
        {
            "m": "mutation",
            "mutation": "mutation",
            "1": "mutation",
            "o": "oracle",
            "oracle": "oracle",
            "2": "oracle",
        },
    )

    # Step 4: Mode-specific options
    max_workers = MAX_WORKERS  # default
    concern = None

    if mode == "mutation":
        # Ask for number of workers
        while True:
            try:
                workers_input = input(f"Enter number of workers (default {MAX_WORKERS}): ").strip()
                if not workers_input:
                    max_workers = MAX_WORKERS
                    break
                max_workers = int(workers_input)
                if max_workers < 1:
                    print("Number of workers must be at least 1. Please try again.\n")
                    continue
                break
            except ValueError:
                print("Invalid input. Please enter a valid integer.\n")
            except (EOFError, KeyboardInterrupt):
                print("\nAborted.")
                sys.exit(130)
        # Ask for concern (optional, defaults to privacy)
        concern = _mort_prompt_choice(
            "Choose concern (default: privacy)",
            {
                "privacy": "privacy",
                "security": "security",
                "correctness": "correctness",
                "performance": "performance",
                "p": "privacy",
                "s": "security",
                "c": "correctness",
                "perf": "performance",
                "1": "privacy",
                "2": "security",
                "3": "correctness",
                "4": "performance",
                "": "privacy",  # Allow empty input to default to privacy
            },
        )
    elif mode == "oracle":
        concern = _mort_prompt_choice(
            "Choose concern",
            {
                "privacy": "privacy",
                "security": "security",
                "correctness": "correctness",
                "performance": "performance",
                "p": "privacy",
                "s": "security",
                "c": "correctness",
                "perf": "performance",
                "1": "privacy",
                "2": "security",
                "3": "correctness",
                "4": "performance",
            },
        )

    # Provide defaults for options the original parser would set
    ns = argparse.Namespace(
        mode=mode,
        repo_path=repo_path,
        code_file=code_file,
        test_file=test_file,
        max_workers=max_workers,
        chunker_mode=chunker_mode,
        concern=concern,
    )
    return ns


# Apply the patch once
# Use a module-level guard to avoid setting unknown attributes on ArgumentParser
try:
    _MORT_INTERACTIVE_PATCHED  # type: ignore[name-defined]
except NameError:
    _MORT_INTERACTIVE_PATCHED = False  # type: ignore[assignment]

if not _MORT_INTERACTIVE_PATCHED:
    _MORT_INTERACTIVE_PATCHED = True  # type: ignore[assignment]
    _MORT_ORIGINAL_PARSE_ARGS = argparse.ArgumentParser.parse_args  # type: ignore[assignment]

    def _mort_parse_args_wrapper(self, args=None, namespace=None):
        # If CLI args are provided, use the original parser; otherwise, launch interactive setup.
        if args not in (None, []) or len(sys.argv) > 1:
            return _MORT_ORIGINAL_PARSE_ARGS(self, args, namespace)
        return _mort_interactive_parse_args(self, args, namespace)

    argparse.ArgumentParser.parse_args = _mort_parse_args_wrapper  # type: ignore[method-assign]

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
  python main.py --mode oracle . src/user_service.py tests/test_user_service.py --concern privacy
  python main.py --mode oracle . examples/calculator.py tests/test_calculator.py --concern correctness
        """,
    )

    # Mode selection (optional, defaults to mutation for backward compatibility)
    parser.add_argument(
        "--mode",
        choices=["mutation", "oracle"],
        default="mutation",
        help="Workflow mode (default: mutation)",
    )

    # Required arguments (common)
    parser.add_argument("repo_path", help="Repository root path")
    parser.add_argument(
        "code_file", help="Code file path (relative to repo or absolute)"
    )

    # Test file required for both modes
    parser.add_argument(
        "test_file",
        nargs="?",  # Made optional in argparse but validated in validate_args
        help="Test file path (required for both mutation and oracle modes)",
    )

    # Common options
    parser.add_argument(
        "--max-workers",
        type=int,
        default=MAX_WORKERS,
        help=f"Number of parallel workers for mutation mode (default: {MAX_WORKERS})",
    )
    parser.add_argument(
        "--chunker-mode",
        choices=["llm", "ast"],
        default="llm",
        help="Chunking strategy (default: llm)",
    )

    # Concern option (required for oracle, optional for mutation)
    parser.add_argument(
        "--concern",
        choices=["privacy", "security", "correctness", "performance"],
        help="Concern category (required for oracle mode, optional for mutation mode - defaults to privacy)",
    )

    return parser


def validate_args(args):
    """Validate mode-specific requirements"""
    if args.mode == "mutation":
        if not args.test_file:
            print("Error: test_file is required for mutation mode")
            print("Usage: python main.py <repo_path> <code_file> <test_file>")
            sys.exit(1)
    elif args.mode == "oracle":
        if not args.concern:
            print("Error: --concern is required for oracle mode")
            print(
                "Usage: python main.py --mode oracle <repo_path> <code_file> <test_file> --concern {privacy|security|correctness|performance}"
            )
            sys.exit(1)
        if not args.test_file:
            print("Error: test_file is required for oracle mode")
            print(
                "Usage: python main.py --mode oracle <repo_path> <code_file> <test_file> --concern {privacy|security|correctness|performance}"
            )
            sys.exit(1)


def run_mutation_mode(args, repo_path, code_file_abs, test_file_abs):
    """Run mutation testing workflow"""
    # Default concern to privacy if not specified
    concern = args.concern or "privacy"

    print(" MORT MUTATION TESTING WORKFLOW")
    print("-" * 80)
    print(f"Concern: {concern.upper()}")
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
        mode="mutation",
        concern=concern,
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
                "mutants": [],
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
            metadata["mutants"].append(
                {
                    "hash": mutant_hash,
                    "chunk_id": mutant_data["chunk_id"],
                    "chunk_type": mutant_data["chunk_type"],
                    "files": {
                        "mutant": mutant_filename,
                        "test": test_filename,
                    },
                    "scores": mutant_data.get("scores", {}),
                }
            )

            print(f"  [SAVED] {mutant_data['chunk_id']}")
            print(f"          Mutant: {mutant_filename}")
            print(f"          Test:   {test_filename}")
            print(f"          Scores: {mutant_data.get('scores', {})}")

        # Save updated metadata
        metadata['total_chunks'] = result['total_chunks']
        metadata["successful_count"] = len(metadata["mutants"])
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        print(f"\n  Metadata: {metadata_path}")
        print(f"  Total mutants for this file: {len(metadata['mutants'])}")
    else:
        print("\n Workflow did not produce any valid mutant and test pairs")


def run_oracle_mode(args, repo_path, code_file_abs, test_file_abs):
    """Run oracle inference workflow"""
    print(" MORT ORACLE INFERENCE WORKFLOW")
    print("-" * 80)
    print(f"Concern: {args.concern.upper()}")
    print(f"Chunker mode: {args.chunker_mode.upper()}")
    print(f"Test file: {test_file_abs}")
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
        mode="oracle",
        concern=args.concern,
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

    # Handle test file (required for both modes)
    test_file_abs = None
    if args.test_file:
        if os.path.isabs(args.test_file):
            test_file_abs = args.test_file
        else:
            test_file_abs = os.path.join(repo_path, args.test_file)

        # Test file must exist for both mutation and oracle modes
        if not os.path.isfile(test_file_abs):
            print(f"Error: Test file not found: {test_file_abs}")
            sys.exit(2)

    if args.mode == "mutation":
        run_mutation_mode(args, repo_path, code_file_abs, test_file_abs)
    else:
        run_oracle_mode(args, repo_path, code_file_abs, test_file_abs)


if __name__ == "__main__":
    t1 = time.time()
    main()
    t2 = time.time()
    print(f"\n\nFinished in {t2 - t1:.2f} seconds")
    exit(0)
