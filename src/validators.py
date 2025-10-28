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
        """Table 2: Remove syntactically identical mutants (25%)"""
        def normalize(code):
            # Remove comments
            code = re.sub(r'#.*$', '', code, flags=re.MULTILINE)
            # Normalize whitespace
            code = re.sub(r'\s+', ' ', code)
            return code.strip()
        
        return normalize(original) == normalize(mutated)
    
    @staticmethod
    def validate_syntax(code: str) -> tuple:
        """Check if code has valid syntax"""
        try:
            ast.parse(code)
            return True, ""
        except SyntaxError as e:
            return False, f"Syntax Error: {e}"
    
    # TODO: FIX for chunks
    @staticmethod
    def run_tests(mutated_code: str, test_code: str, 
                  code_filename: str, test_filename: str,
                  timeout: int = 20) -> tuple:
        """
        Returns: (builds: bool, passes: bool)
        """
        # Syntax check first
        is_valid, error = CodeValidator.validate_syntax(mutated_code)
        if not is_valid:
            print(f"    Syntax error: {error}")
            return False, False
            
        with tempfile.TemporaryDirectory() as tmpdir:
            code_base = os.path.basename(code_filename)
            test_base = os.path.basename(test_filename)
            test_module = os.path.splitext(test_base)[0]

            # Save files
            code_path = os.path.join(tmpdir, code_base)
            with open(code_path, 'w') as f:
                f.write(mutated_code)

            test_path = os.path.join(tmpdir, test_base)
            with open(test_path, 'w') as f:
                f.write(test_code)
            
            # Run tests
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "unittest", test_module, "-v"],
                    capture_output=True,
                    text=True,
                    cwd=tmpdir,
                    timeout=timeout
                )
                
                passed = result.returncode == 0
                if not passed:
                    print(f"    Test output:\n{result.stdout}")
                    print(f"    Test errors:\n{result.stderr}")
                return True, passed
                
            except subprocess.TimeoutExpired:
                return True, False
            except Exception as e:
                print(f"    Error: {e}")
                return True, False