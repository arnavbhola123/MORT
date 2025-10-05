"""Code validation utilities"""
import ast
import re
import subprocess
import tempfile
import os
import sys


class CodeValidator:
    @staticmethod
    def is_syntactically_identical(original: str, mutated: str) -> bool:
        """Check if code is syntactically identical after removing mutation markers"""
        def clean(code):
            # Remove both // and # style mutation markers and the mutated code between them
            code = re.sub(r'(//|#)\s*MUTANT\s*START.*?(//|#)\s*MUTANT\s*END', '', code, flags=re.DOTALL)
            # Also remove standalone markers
            code = re.sub(r'(//|#)\s*MUTANT\s*(START|END).*\n', '', code)
            try:
                tree = ast.parse(code)
                return ast.unparse(tree)
            except Exception:
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
    
    @staticmethod
    def validate_syntax(code: str) -> tuple:
        """Check if code has valid syntax"""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Syntax Error at line {e.lineno}: {e.text}"
    
    @staticmethod
    def run_tests(mutated_code: str, test_code: str, 
                  code_filename: str, test_filename: str,
                  timeout: int = 20) -> tuple:
        """
        Check if mutant builds and passes existing tests.

        Saves files using the SAME BASENAMES as the originals so imports keep working.
        Then runs: python -m unittest <test_module_basename> -v
        """
        print("\n Validating mutant...")
        
        # Check syntax of the mutant first
        is_valid, error = CodeValidator.validate_syntax(mutated_code)
        if not is_valid:
            print(f"    {error}")
            return False, False
        print("   Mutant syntax is valid")
            
        with tempfile.TemporaryDirectory() as tmpdir:
            print(f"   Created temp directory: {tmpdir}")

            # Determine basenames and module name
            code_base = os.path.basename(code_filename)
            test_base = os.path.basename(test_filename)
            test_module = os.path.splitext(test_base)[0]

            # Save mutated code under SAME name as provided code file
            code_path = os.path.join(tmpdir, code_base)
            with open(code_path, 'w', encoding='utf-8') as f:
                f.write(mutated_code)
            print(f"    Saved mutant to {code_path}")

            # Save tests under SAME name as provided test file
            test_path = os.path.join(tmpdir, test_base)
            with open(test_path, 'w', encoding='utf-8') as f:
                f.write(test_code)
            print(f"    Saved tests to {test_path}")
            
            # Run tests
            print(f"   Running tests as module: {test_module}")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", test_module, "-v"],
                    capture_output=True,
                    text=True,
                    cwd=tmpdir,
                    timeout=timeout
                )
                # Show a concise preview of output
                out_preview = (result.stdout or "")[:800]
                err_preview = (result.stderr or "")[:400]
                print("   --- unittest STDOUT (truncated) ---")
                print(out_preview)
                if result.returncode != 0:
                    print("   --- unittest STDERR (truncated) ---")
                    print(err_preview)

                if result.returncode == 0:
                    print("   All tests pass")
                else:
                    print("    Some tests failed (return code {})".format(result.returncode))
                    
                return True, result.returncode == 0
            except subprocess.TimeoutExpired:
                print("    Tests timed out")
                return True, False
            except Exception as e:
                print(f"    Error running tests: {e}")
                return True, False