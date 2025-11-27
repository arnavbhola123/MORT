# Input: Any python code file

# Specify overarching concern for mutations (e.g., security, privacy, performance, correctness) 
# user chooses what methods to mutate
# For each method / piece of functionality in file:
# 1. Generate 10 mutants that violate the concern
# 2. Remove syntactically identical mutants
# 3. Validate mutant builds and passes existing tests
# 4. Equivalence detection
# - return at most 5 mutants
# 5. Generate oracle inference from mutations
# - generate in temp file, user edits
# 6. human-in-the loop validation of oracle inference
# 7. Generate tests to measure oracle inference with user validated input
# 8. Run on code, if tests fail - bug(s) found
# Provided back to user, user will then generate fixes on their own

# new_main.py
"""Enhanced MORT CLI with Oracle Inference for Bug Detection"""
import sys
import os
from typing import List, Dict, Optional, Tuple
from dotenv import load_dotenv
from src.llm_client import LLMClient
from src.validators import CodeValidator
from prompts.templates import PromptTemplates
from constants import MODEL, MODEL_PROVIDER
import ast
import json

load_dotenv()


class EnhancedMORTWorkflow:
    def __init__(self, model: str, provider: str):
        self.llm = LLMClient(model, provider)
        self.validator = CodeValidator()
        self.prompts = PromptTemplates()
    
    def extract_functions(self, code: str) -> List[Dict[str, any]]:
        """Extract all function/method definitions from Python code"""
        try:
            tree = ast.parse(code)
            functions = []
            
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    # Get function source
                    func_lines = code.split('\n')[node.lineno-1:node.end_lineno]
                    func_source = '\n'.join(func_lines)
                    
                    functions.append({
                        'name': node.name,
                        'source': func_source,
                        'lineno': node.lineno,
                        'is_method': self._is_method(node)
                    })
            
            return functions
        except SyntaxError as e:
            print(f"ERROR: Could not parse file: {e}")
            return []
    
    def _is_method(self, node: ast.FunctionDef) -> bool:
        """Check if function is a method (has self parameter)"""
        if node.args.args and len(node.args.args) > 0:
            return node.args.args[0].arg == 'self'
        return False
    
    def generate_multiple_mutants(
        self, 
        context: str, 
        code: str, 
        concern: str,
        num_mutants: int = 10
    ) -> List[str]:
        """Generate multiple mutants for a piece of code"""
        prompt = f"""CONTEXT: {context}

CONCERN: {concern}

INSTRUCTION: Here is a Python code:
'''{code}'''

Generate {num_mutants} DIFFERENT mutated versions of this code. Each mutant should:
1. Introduce a SUBTLE bug related to {concern}
2. Be syntactically different from each other
3. Still be valid Python code
4. Be subtle enough that it might pass casual inspection

For each mutant, wrap the mutated code with delimiters:
// MUTANT START <number>
<mutated code>
// MUTANT END <number>

Generate {num_mutants} distinct mutants."""

        response = self.llm.invoke(prompt)
        return self._extract_multiple_mutants(response, num_mutants)
    
    def _extract_multiple_mutants(self, text: str, expected: int) -> List[str]:
        """Extract multiple mutants from LLM response"""
        import re
        
        # Try to find mutants with markers
        pattern = r'(?://|#)\s*MUTANT\s+START.*?\n(.*?)(?://|#)\s*MUTANT\s+END'
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        
        if matches:
            return [m.strip() for m in matches]
        
        # Fallback: try to extract code blocks
        code_blocks = re.findall(r'```python\n(.*?)```', text, re.DOTALL)
        if code_blocks:
            return [cb.strip() for cb in code_blocks[:expected]]
        
        return []
    
    def generate_oracle_inference(
        self, 
        original_code: str, 
        mutants: List[str],
        concern: str
    ) -> str:
        """Generate oracle inference based on mutants"""
        mutants_text = "\n\n".join([f"MUTANT {i+1}:\n{m}" for i, m in enumerate(mutants)])
        
        prompt = f"""I will show you a piece of code and several BUGGY mutated versions of it.

The mutants introduce various bugs related to {concern}.

IMPORTANT: The original code may ALSO contain bugs. Your task is to infer what 
the CORRECT, secure, and privacy-preserving behavior SHOULD BE by analyzing what 
bugs the mutants introduce.

ORIGINAL CODE:
'''{original_code}'''

BUGGY MUTATED VERSIONS (showing examples of incorrect behavior):
{mutants_text}

TASK: For each mutant, identify what {concern} property it violates.
Then specify what the CORRECT behavior should be.

Analysis approach:
1. For each mutant, ask: "What goes wrong here?"
2. Identify: "What property/invariant does it violate?"
3. Specify: "What should correct code do instead?"

Based on this analysis, provide a specification of CORRECT behavior:

1. INVARIANTS - What properties should ALWAYS be true (that the mutants violate)
2. SAFETY PROPERTIES - What should NEVER happen (that the mutants demonstrate)
3. INPUT-OUTPUT RELATIONSHIPS - What correct outputs should be (not what buggy code produces)
4. ERROR CONDITIONS - What errors should be properly handled

Your oracle should specify behavior that would:
- PASS on correctly implemented code
- FAIL on the buggy mutants shown above
- FAIL on the original code if it contains similar bugs

Provide a clear, testable oracle specification."""

        return self.llm.invoke(prompt)
    
    def validate_oracle_with_user(self, oracle: str) -> Tuple[bool, Optional[str]]:
        """Human-in-the-loop validation of oracle"""
        print("\n" + "="*80)
        print("ORACLE INFERENCE")
        print("="*80)
        print(oracle)
        print("="*80)
        
        while True:
            response = input("\nIs this oracle correct? (y/n/edit): ").lower().strip()
            
            if response == 'y':
                return True, oracle
            elif response == 'n':
                return False, None
            elif response == 'edit':
                print("\nEnter your corrected oracle (type 'END' on a new line when done):")
                lines = []
                while True:
                    line = input()
                    if line == 'END':
                        break
                    lines.append(line)
                return True, '\n'.join(lines)
            else:
                print("Please enter 'y', 'n', or 'edit'")
    
    def generate_test_from_oracle(
        self, 
        original_code: str, 
        oracle: str,
        function_name: str
    ) -> str:
        """Generate test based on validated oracle"""
        prompt = f"""You are generating unittest test cases to detect bugs in code based on an oracle specification.

CRITICAL INSTRUCTIONS:
Your tests must be designed to FAIL on buggy code and PASS on correct code that follows the oracle.
The original code provided below contains bugs. Your tests must catch these bugs.

ORACLE SPECIFICATION (Correct Behavior):
{oracle}

ORIGINAL CODE TO TEST (Might contain bugs):
'''{original_code}'''

TASK: Generate a comprehensive Python unittest.TestCase class that will:

1. DETECT VIOLATIONS of the oracle specification
2. FAIL when run against the buggy original code
3. PASS when run against corrected code that follows the oracle

ASSERTION GUIDELINES:

For SAFETY PROPERTIES (things that should NEVER happen):
- Use assertNotIn when something must NOT be present
- Use assertFalse when something must NOT be true
- Use assertEqual with expected error messages when requests should be denied

Example from oracle "S3: ssn_hash must NEVER be in response":
    self.assertNotIn('ssn_hash', result['data'], "SSN hash must never be shared")
    This will FAIL if ssn_hash IS in the response (catching the bug)

Example from oracle "S6: request_reason must NEVER be logged":
    log_message = self.system.logger.info.call_args[0][0]
    self.assertNotIn('reason=', log_message, "Request reason must not be logged")
    This will FAIL if reason IS logged (catching the bug)

For INVARIANTS (things that must ALWAYS be true):
- Use assertTrue for required conditions
- Use assertEqual for specific expected values
- Use assert_called_once or assert_called_once_with for methods that MUST be invoked

Example from oracle "I3: has_sharing_consent must be checked":
    self.system.has_sharing_consent.assert_called_once_with(user_id)
    This will FAIL if has_sharing_consent is NOT called (catching the bug)

Example from oracle "I6: Rate limit must happen BEFORE data access":
    self.assertEqual(result['error'], 'Rate limit exceeded')
    self.assertFalse(result['approved'])
    self.assertIsNone(result['data'])
    These will FAIL if request is approved despite rate limit (catching the bug)

For INPUT-OUTPUT RELATIONSHIPS:
- Test that correct inputs produce correct outputs per the oracle
- Test that invalid inputs produce specified errors

Example from oracle "IO6: Forbidden field should return error":
    result = system.process_data_access_request(..., requested_fields=['ssn_hash'], ...)
    self.assertFalse(result['approved'], "Request with forbidden field must be denied")
    self.assertEqual(result['error'], 'Forbidden field requested')
    These will FAIL if request is approved (catching the bug)

For ERROR CONDITIONS:
- Verify that errors are handled as specified in the oracle
- Check that proper error messages are returned

WHAT NOT TO DO:
DO NOT write tests that verify buggy behavior exists
DO NOT use assertIn to verify that bugs are present
DO NOT write regression tests that document current buggy behavior

Example of WRONG test (documents bug, doesn't catch it):
    self.assertIn('ssn_hash', result['data'], "BUG: ssn_hash should not be here")
    This PASSES on buggy code - WRONG!

Example of CORRECT test (catches bug):
    self.assertNotIn('ssn_hash', result['data'], "SSN hash must never be shared")
    This FAILS on buggy code - CORRECT!

TEST STRUCTURE REQUIREMENTS:

1. Import all necessary modules:
   - unittest
   - unittest.mock (MagicMock, patch, call)
   - Any other needed imports

2. Create a test class named Test_{function_name}

3. Include setUp method to:
   - Create test instance with mocked dependencies
   - Set up test data
   - Configure default mock behaviors for success case
   - Use patch for uuid and time if needed for deterministic testing

4. Include tearDown method to:
   - Clean up mocks
   - Reset state

5. Write test methods that cover:
   - Each INVARIANT from the oracle
   - Each SAFETY PROPERTY from the oracle
   - Each INPUT-OUTPUT relationship from the oracle
   - Each ERROR CONDITION from the oracle
   - Edge cases and boundary conditions

6. Each test method should:
   - Have a descriptive name indicating what oracle property it tests
   - Set up specific test conditions
   - Execute the function under test
   - Assert expected behavior according to oracle
   - Use assertion messages that explain what SHOULD happen per the oracle

7. Use mocks appropriately:
   - Mock external dependencies (logger, database calls, etc.)
   - Verify mock calls to ensure methods are invoked correctly
   - Check call order when sequence matters (e.g., rate limit before data access)

8. Make tests comprehensive:
   - Test positive cases (correct behavior)
   - Test negative cases (errors handled correctly)
   - Test boundary conditions
   - Test that bugs are caught (tests should FAIL on buggy code)

Now generate the complete unittest test class following all these guidelines.
The tests you generate should FAIL on the buggy original code and PASS on corrected code.
"""

        response = self.llm.invoke(prompt)
        return self.llm.extract_code_from_response(response)
    
    def filter_mutants(
        self, 
        original_code: str, 
        mutants: List[str],
        test_file: Optional[str] = None,
        code_file: str = "temp_code.py"
    ) -> List[str]:
        """Filter mutants through validation pipeline"""
        valid_mutants = []
        
        print(f"\nFiltering {len(mutants)} mutants...")
        
        for i, mutant in enumerate(mutants, 1):
            print(f"\n  Mutant {i}/{len(mutants)}:")
            
            # Step 1: Syntactic identity check
            if self.validator.is_syntactically_identical(original_code, mutant):
                print("    [X] Syntactically identical")
                continue
            
            
            # Step 3: Syntax validation
            is_valid, error = self.validator.validate_syntax(mutant)
            if not is_valid:
                print(f"    [X] Syntax error: {error}")
                continue
            
            # Step 4: If test file exists, check if mutant passes
            if test_file and os.path.exists(test_file):
                builds, passes = self.validator.run_tests(
                    mutant, 
                    open(test_file).read(),
                    code_file,
                    test_file
                )
                if not builds:
                    print("    [X] Doesn't build with tests")
                    continue
                if not passes:
                    print("    [X] Fails existing tests")
                    continue
            
            # Step 5: Equivalence detection
            is_equivalent = self._check_equivalence(original_code, mutant)
            if is_equivalent:
                print("    [X] Equivalent mutant")
                continue
            
            print("    [OK] Valid mutant")
            valid_mutants.append(mutant)
        
        return valid_mutants[:5]  # Return at most 5
    
    def _check_equivalence(self, original: str, mutant: str) -> bool:
        """Check if mutant is equivalent to original"""
        prompt = self.prompts.equivalence_detector(original, mutant)
        answer = self.llm.invoke(prompt).strip()
        return answer.lower().startswith('yes')
    
    def run_bug_detection(
        self,
        original_code: str,
        test_code: str,
        code_file: str,
        function_name: str
    ) -> Tuple[bool, Optional[str]]:
        """Run generated test on original code to detect bugs"""
        print("\n" + "="*80)
        print("RUNNING BUG DETECTION")
        print("="*80)
        
        # Create outputs directory if it doesn't exist
        os.makedirs("outputs", exist_ok=True)
        
        # Create test file in outputs directory
        test_file = os.path.join("outputs", f"test_{function_name}.py")
        with open(test_file, 'w') as f:
            f.write(test_code)
        
        builds, passes = self.validator.run_tests(
            original_code,
            test_code,
            code_file,
            test_file
        )
        
        if not builds:
            return False, "Test doesn't build"
        
        if passes:
            print("[OK] All tests passed - No bugs detected!")
            return True, None
        else:
            print("[BUG] TESTS FAILED - BUGS DETECTED!")
            return False, "Tests revealed bugs in original code"


def main():
    """Enhanced CLI for MORT with Oracle Inference"""
    if len(sys.argv) < 2:
        print("Usage: python new_main.py <CODE_FILE.py> [concern]")
        print("\nExamples:")
        print("  python new_main.py user_service.py security")
        print("  python new_main.py calculator.py correctness")
        sys.exit(1)
    
    code_file = sys.argv[1]
    concern = sys.argv[2] if len(sys.argv) > 2 else "correctness"
    
    if not os.path.isfile(code_file):
        print(f"ERROR: code file not found: {code_file}")
        sys.exit(2)
    
    # Read original code
    with open(code_file, 'r', encoding='utf-8') as f:
        original_code = f.read()
    
    print("Enhanced MORT Workflow with Oracle Inference")
    print("="*80)
    print(f"File: {code_file}")
    print(f"Concern: {concern}")
    print("="*80)
    
    # Define concern contexts
    concern_contexts = {
        "security": "Security vulnerabilities: SQL injection, XSS, authentication bypass, insecure data handling, missing input validation",
        "privacy": "Privacy violations: logging PII, exposing sensitive data, missing authorization, leaking user information",
        "performance": "Performance issues: inefficient algorithms, memory leaks, unnecessary computations, poor resource management",
        "correctness": "Correctness bugs: off-by-one errors, null pointer issues, logic errors, edge case failures"
    }
    
    context = concern_contexts.get(concern.lower(), f"Issues related to {concern}")
    
    # Initialize workflow
    model = os.getenv("MODEL", MODEL)
    provider = os.getenv("MODEL_PROVIDER", MODEL_PROVIDER)
    workflow = EnhancedMORTWorkflow(model, provider)
    
    # Extract functions
    print("\nExtracting functions...")
    functions = workflow.extract_functions(original_code)

    if not functions:
        print("ERROR: No functions found in file")
        sys.exit(3)
    
    print(f"Found {len(functions)} function(s)")
    for func in functions:
        print(f"  - {func['name']} (line {func['lineno']})")
    
    # Process each function
    all_results = []
    
    for func_idx, func in enumerate(functions, 1):
        print("\n" + "="*80)
        print(f"PROCESSING FUNCTION {func_idx}/{len(functions)}: {func['name']}")
        print("="*80)
        
        func_code = func['source']
        
        # Step 1: Generate 10 mutants
        print("\nStep 1: Generating 10 mutants...")
        mutants = workflow.generate_multiple_mutants(
            context, 
            func_code, 
            concern,
            num_mutants=10
        )
        print(f"  Generated {len(mutants)} mutants")
        
        if not mutants:
            print("  WARNING: No mutants generated, skipping function")
            continue
        
        # Step 2-4: Filter mutants
        # TODO: Why give original code not func code
        print("\nSteps 2-4: Filtering mutants...")
        valid_mutants = workflow.filter_mutants(original_code, mutants, code_file=code_file)
        
        print(f"\nRetained {len(valid_mutants)} valid mutants (max 5)")
        
        if not valid_mutants:
            print("  WARNING: No valid mutants, skipping function")
            continue
        
        # Step 5: Generate oracle inference
        print("\nStep 5: Generating oracle inference...")
        oracle = workflow.generate_oracle_inference(func_code, valid_mutants, concern)
        
        # Step 6: Human-in-the-loop validation
        print("\nStep 6: Human validation of oracle...")
        oracle_valid, validated_oracle = workflow.validate_oracle_with_user(oracle)
        
        if not oracle_valid:
            print("  WARNING: Oracle rejected, skipping function")
            continue
        
        # Step 7: Generate test from oracle
        print("\nStep 7: Generating test from validated oracle...")
        test_code = workflow.generate_test_from_oracle(
            func_code,
            validated_oracle,
            func['name']
        )
        
        print(f"\nGenerated test code ({len(test_code)} chars)")
        print("\nTest preview:")
        print("-" * 40)
        print(test_code[:500] + "..." if len(test_code) > 500 else test_code)
        print("-" * 40)
        
        # Step 8: Run test to detect bugs
        print("\nStep 8: Running bug detection...")
        success, error = workflow.run_bug_detection(
            original_code,
            test_code,
            code_file,
            func['name']
        )
        
        result = {
            'function': func['name'],
            'mutants_generated': len(mutants),
            'valid_mutants': len(valid_mutants),
            'oracle': validated_oracle,
            'test_code': test_code,
            'bugs_found': not success,
            'error': error
        }
        
        all_results.append(result)
    
    # Final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)
    
    for result in all_results:
        print(f"\nFunction: {result['function']}")
        print(f"  Mutants generated: {result['mutants_generated']}")
        print(f"  Valid mutants: {result['valid_mutants']}")
        print(f"  Bugs found: {'YES' if result['bugs_found'] else 'NO'}")
        if result['bugs_found']:
            print(f"  Error: {result['error']}")
    
    # Save results
    output_file = f"ach_results_{os.path.basename(code_file)}.json"
    with open(output_file, 'w') as f:
        json.dump(all_results, f, indent=2)
    
    print(f"\nResults saved to: {output_file}")
    print("\nEnhanced MORT workflow complete!")


if __name__ == "__main__":
    main()