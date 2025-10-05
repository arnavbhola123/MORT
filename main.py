"""CLI entry point for ACH"""
import sys
import os
from dotenv import load_dotenv
from src.ach_workflow import ACHWorkflow
from constants import (
    MODEL, 
    MODEL_PROVIDER, 
    OUTPUT_DIR, 
    MUTANT_OUTPUT_FILE, 
    TEST_OUTPUT_FILE
)

load_dotenv()

def main():
    """Run ACH with exact prompts from the paper (dynamic filenames)"""
    if len(sys.argv) != 3:
        print("Usage: python main.py <CODE_FILE.py> <TEST_FILE.py>")
        sys.exit(1)
    
    code_file = sys.argv[1]
    test_file = sys.argv[2]

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
    
    ach = ACHWorkflow(model, provider)
    result = ach.run_workflow(code_file, test_file)
    
    if result:
        print("\n" + "="*60)
        print("FINAL RESULTS")
        print("="*60)
        
        # Save results
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        mutant_path = os.path.join(OUTPUT_DIR, MUTANT_OUTPUT_FILE)
        test_path = os.path.join(OUTPUT_DIR, TEST_OUTPUT_FILE)
        
        with open(mutant_path, 'w', encoding='utf-8') as f:
            f.write(result['mutant'])
        with open(test_path, 'w', encoding='utf-8') as f:
            f.write(result['test'])
        print(f" Saved: {mutant_path} and {test_path}")
    else:
        print("\n Workflow did not produce a valid mutant and test pair")


if __name__ == "__main__":
    main()