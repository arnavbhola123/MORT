#!/usr/bin/env python3
"""
ACH (Automated Compliance Hardener) Implementation with Debug Output
Using exact prompts from Table 1 of "Mutation-Guided LLM-based Test Generation at Meta"
"""

import ast
import re
import subprocess
import tempfile
import os
import sys
from google import genai
from dotenv import load_dotenv

load_dotenv()

class ACHWithExactPrompts:
    def __init__(self):
        """Initialize ACH with Gemini API"""
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("Please set GEMINI_API_KEY environment variable")
        self.client = genai.Client(api_key=api_key)
        
    def run_workflow(self, code_file: str, test_file: str, max_attempts: int = 5):
        """Run the ACH workflow with exact prompts from the paper"""
        print("Starting ACH Workflow with exact prompts from paper...")
        print(f"Using model: gemini-2.5-flash")
        print(f"Processing files: {code_file}, {test_file}")
        
        # Read input files
        with open(code_file, 'r') as f:
            class_under_test = f.read()
        with open(test_file, 'r') as f:
            existing_test_class = f.read()
            
        print(f"\n Original class length: {len(class_under_test)} chars")
        print(f" Test class length: {len(existing_test_class)} chars")
            
        # Context about privacy concerns (from paper)
        context_about_concern = """collecting user data without consent, logging sensitive information,
        accessing user data without proper authorization, sharing data with third parties without permission"""
        
        # Example diff (simplified for this implementation)
        diff = "removing user consent checks before data collection"

        for attempt in range(max_attempts):
            # Step 1: Generate mutant using exact "Make a fault" prompt
            print("\n" + "="*60)
            print("STEP 1: Generating mutant with 'Make a fault' prompt...")
            print("="*60)
            mutated_class = self._make_fault(context_about_concern, class_under_test, 
                                            existing_test_class, diff)
            
            print("\n DEBUG - Generated mutant preview (first 500 chars):")
            print("-" * 40)
            print(mutated_class)
            print("-" * 40)
            
            # Step 2: Check if syntactically identical
            print("\n" + "="*60)
            print("STEP 2: Checking syntactic identity...")
            print("="*60)
            if self._is_syntactically_identical(class_under_test, mutated_class):
                print("    Mutant is syntactically identical - discarding")
                return None
            print("   Mutant is syntactically different")
                
            # Step 3: Check if mutant builds and passes
            print("\n" + "="*60)
            print("STEP 3: Validating mutant builds and passes...")
            print("="*60)
            builds, passes = self._validate_mutant(mutated_class, existing_test_class)
            
            if not builds:
                print("    Mutant doesn't build - discarding")
                print("\n DEBUG - Trying to parse mutant for syntax errors:")
                try:
                    ast.parse(mutated_class)
                    print("   Mutant parses as valid Python")
                except SyntaxError as e:
                    print(f"   Syntax Error: {e}")
                    print(f"   At line {e.lineno}: {e.text}")  

                if attempt == max_attempts-1:
                    return None
                continue

            if not passes:
                print("    Mutant fails existing tests - discarding")

                if attempt == max_attempts-1:
                    return None
                continue
            
            print("   ✓ Mutant builds and passes existing tests")

            break
        
        # Step 4: Check equivalence using exact "Equivalence detector" prompt
        print("\n" + "="*60)
        print("STEP 4: Running equivalence detector...")
        print("="*60)
        is_equivalent = self._equivalence_detector(class_under_test, mutated_class)
        
        if is_equivalent:
            print("    Mutant is equivalent - discarding")
            return None
        print("   ✓ Mutant is non-equivalent")
        
        # Step 5: Generate test using exact "Make a test to catch fault" prompt
        print("\n" + "="*60)
        print("STEP 5: Generating test to catch fault...")
        print("="*60)
        new_test_class = self._make_test_to_catch_fault(class_under_test, mutated_class, 
                                                        existing_test_class)
        
        print("\n DEBUG - Generated test preview (first 500 chars):")
        print("-" * 40)
        print(new_test_class[:500] + "..." if len(new_test_class) > 500 else new_test_class)
        print("-" * 40)
        
        print("\nSUCCESS: Generated mutant and killing test!")
        return {
            'mutant': mutated_class,
            'test': new_test_class
        }
    
    def _make_fault(self, context, class_under_test, existing_test_class, diff):
        """Table 1: Make a fault - exact prompt from paper"""
#         prompt = f"""CONTEXT: {context} INSTRUCTION: Here is a Python class and a test class with some unit tests for the class under test
# '''{class_under_test}'''. '''{existing_test_class}'''. Write a new version of the class under test in which each method is replaced by a new
# version of that method that contains a typical bug that introduces a privacy violation similar to {diff}. Delimit the mutated part using the
# comment-pair '# MUTANT START' and '# MUTANT END'"""
        prompt = f"""CONTEXT: {context} INSTRUCTION: Here is a Python class and a test class with some unit tests for the class under test
'''{class_under_test}'''. '''{existing_test_class}'''. Write a new version of the class under test in which each method is replaced by a new
version of that method that contains a typical bug that introduces a privacy violation similar to {diff}. The bug should be SUBTLE enough that
all existing tests still pass. Do not completely remove functionality - introduce edge cases or partial failures. Delimit the mutated part using the
comment-pair '# MUTANT START' and '# MUTANT END'"""

        print("\n Sending prompt to Gemini (prompt length: {} chars)".format(len(prompt)))
        
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        text = response.text
        print(f" Received response (length: {len(text)} chars)")
        
        # Debug: show raw response structure
        print("\nDEBUG - Checking response format:")
        if "```python" in text:
            print("   Found Python code block")
        if "# MUTANT START" in text or "# MUTANT END" in text:
            print("   Found MUTANT markers")
        elif "// MUTANT" in text:
            print("   Found // style MUTANT markers (will convert to #)")
            
        # Extract code from response
        code_match = re.search(r'```python\n(.*?)```', text, re.DOTALL)
        if code_match:
            extracted = code_match.group(1)
            print(f"   Extracted code from markdown block ({len(extracted)} chars)")
            # Convert // comments to # for Python
            extracted = extracted.replace("// MUTANT", "# MUTANT")
            return extracted
        else:
            print("   No markdown code block found, returning raw response")
            # Convert // comments to # for Python
            return text.replace("// MUTANT", "# MUTANT")
    
    def _equivalence_detector(self, class_version1, class_version2):
        """Table 1: Equivalence detector - exact prompt from paper"""
        prompt = f"""I'm going to show you two slightly different versions of a Python class. Here is the first version of the Python class:'''class_version1'''.
Here is the second version of the Python class:'''class_version2'''. INSTRUCTION: If the first version of the class will always do exactly
the same thing as the second version of the class, just respond with 'yes'. However, if the two versions of the class are not equivalent,
respond with 'no', and give an explanation of how execution of the first version can produce a different behaviour to execution of the
second version."""
        
        # Replace placeholders
        prompt = prompt.replace("class_version1", class_version1)
        prompt = prompt.replace("class_version2", class_version2)
        
        print(f"\n Checking equivalence (prompt length: {len(prompt)} chars)")
        
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        answer = response.text.strip()
        print(f" Equivalence check response: {answer[:100]}...")
        
        is_yes = answer.lower().startswith('yes')
        print(f"   Interpreted as: {'Equivalent' if is_yes else 'Non-equivalent'}")
        
        return is_yes
    
    def _make_test_to_catch_fault(self, original_class, mutated_class, existing_test_class):
        """Table 1: Make a test to catch fault - exact prompt from paper"""
        prompt = f"""What follows is two versions of a Python class under test. An original correct class and a mutated version of that class that contains one
mutant per method, each of which represents a bug. Each bug is delimited by the comment-pair '# MUTANT START' and '# MUTANT END'. The
original class and its mutant are followed by a test class that contains unit tests for the original correct class under test. This is the
original version of the class under test:'''{original_class}'''. This is the mutated version of the class under test:'''{mutated_class}'''.
Here is the existing test class:'''{existing_test_class}'''. Write an extended version of the test class that contains extra test cases that
will fail on the mutant version of the class, but would pass on the correct version."""

        print(f"\n Generating test (prompt length: {len(prompt)} chars)")
        
        response = self.client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        
        text = response.text
        print(f" Received test response (length: {len(text)} chars)")
        
        # Extract code from response
        code_match = re.search(r'```python\n(.*?)```', text, re.DOTALL)
        if code_match:
            extracted = code_match.group(1)
            print(f"   Extracted test code from markdown block ({len(extracted)} chars)")
            return extracted
        else:
            print("   No markdown block found, returning raw response")
            return text
    
    def _validate_mutant(self, mutated_code, test_code):
        """Check if mutant builds and passes existing tests"""
        print("\n Validating mutant...")
        
        # Check syntax
        try:
            ast.parse(mutated_code)
            print("   Mutant syntax is valid")
        except SyntaxError as e:
            print(f"    Syntax error: {e}")
            print(f"      Line {e.lineno}: {e.text}")
            return False, False
            
        # Run tests against mutant
        with tempfile.TemporaryDirectory() as tmpdir:
            print(f"   Created temp directory: {tmpdir}")
            
            # Save mutated code
            code_path = os.path.join(tmpdir, "user_service.py")
            with open(code_path, 'w') as f:
                f.write(mutated_code)
            print(f"    Saved mutant to {code_path}")
            
            # Save test file
            test_path = os.path.join(tmpdir, "test_user_service.py")
            with open(test_path, 'w') as f:
                f.write(test_code)
            print(f"    Saved tests to {test_path}")
            
            # Run tests
            print("   Running tests...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", "test_user_service", "-v"],
                    capture_output=True,
                    text=True,
                    cwd=tmpdir,
                    timeout=10
                )
                
                if result.returncode == 0:
                    print("   All tests pass")
                else:
                    print("    Some tests failed")
                    print("   STDERR:", result.stderr[:500])
                    
                return True, result.returncode == 0
            except subprocess.TimeoutExpired:
                print("    Tests timed out")
                return True, False
            except Exception as e:
                print(f"    Error running tests: {e}")
                return True, False
    
    def _is_syntactically_identical(self, original, mutated):
        """Check if code is syntactically identical after removing mutation markers"""
        def clean(code):
            # Remove both // and # style mutation markers and the mutated code between them
            code = re.sub(r'(//|#)\s*MUTANT\s*START.*?(//|#)\s*MUTANT\s*END', '', code, flags=re.DOTALL)
            # Also remove standalone markers
            code = re.sub(r'(//|#)\s*MUTANT\s*(START|END).*\n', '', code)
            try:
                tree = ast.parse(code)
                return ast.unparse(tree)
            except:
                return code.strip()
        
        original_clean = clean(original)
        mutated_clean = clean(mutated)
        
        is_same = original_clean == mutated_clean
        
        if is_same:
            print("   Cleaned versions are identical")
        else:
            print("   Cleaned versions differ")
            print(f"   Original (cleaned) length: {len(original_clean)}")
            print(f"   Mutated (cleaned) length: {len(mutated_clean)}")
            
        return is_same


def main():
    """Run ACH with exact prompts from the paper"""
    if len(sys.argv) != 3:
        print("Usage: python ach_debug.py user_service.py test_user_service.py")
        sys.exit(1)
    
    print(" ACH Workflow Starting")
    print("-" * 60)
    
    ach = ACHWithExactPrompts()
    result = ach.run_workflow(sys.argv[1], sys.argv[2])
    
    if result:
        print("\n" + "="*60)
        print("FINAL RESULTS")
        print("="*60)
        
        # Save results
        with open("mutant_output.py", 'w') as f:
            f.write(result['mutant'])
        with open("test_output.py", 'w') as f:
            f.write(result['test'])
        print(" Saved: mutant_output.py and test_output.py")
    else:
        print("\n Workflow did not produce a valid mutant and test pair")


if __name__ == "__main__":
    main()