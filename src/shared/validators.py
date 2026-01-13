"""Code validation utilities"""
import ast
import re
import subprocess
import os
import shutil
import time

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
    
    @staticmethod
    def _detect_test_framework(test_code: str) -> str:
        """
        Detect whether tests use pytest or unittest.

        Args:
            test_code: Content of test file

        Returns:
            "pytest" or "unittest"
        """
        # Check for pytest-specific patterns
        pytest_indicators = [
            'import pytest',
            'from pytest import',
            '@pytest.',
            'def test_',  # pytest style functions (no class)
        ]

        # Check for unittest-specific patterns
        unittest_indicators = [
            'import unittest',
            'from unittest import',
            'unittest.TestCase',
            'class Test',  # Common unittest pattern
        ]

        pytest_count = sum(1 for indicator in pytest_indicators if indicator in test_code)
        unittest_count = sum(1 for indicator in unittest_indicators if indicator in test_code)

        # If both are present or unclear, prefer pytest (more common, more flexible)
        if pytest_count > unittest_count:
            return "pytest"
        elif unittest_count > 0:
            return "unittest"
        else:
            # Default to pytest if no clear indicators
            return "pytest"

    @staticmethod
    def run_tests(mutated_code: str, test_code: str,
                temp_repo: str, code_relpath: str, test_relpath: str,
                venv_python: str,
                timeout: int = 20) -> tuple:
        """
        Run tests in full repository context with proper dependencies.
        Automatically detects and uses either pytest or unittest.

        Args:
            mutated_code: Content of mutated code
            test_code: Content of test file
            temp_repo: Path to temporary repository copy
            code_relpath: Relative path of code file from repo root
            test_relpath: Relative path of test file from repo root
            venv_python: Path to Python executable in virtual environment
            timeout: Test timeout in seconds

        Returns: (builds: bool, passes: bool)
        """
        # Syntax check first
        is_valid, error = CodeValidator.validate_syntax(mutated_code)
        if not is_valid:
            print(f"    Syntax error: {error}")
            return False, False

        print("validated")

        try:
            # Replace code file in temp repo
            code_path = os.path.join(temp_repo, code_relpath)
            print(f"    Writing mutated code to: {code_path}")
            print(f"    Mutated code length: {len(mutated_code)} bytes")
            os.makedirs(os.path.dirname(code_path), exist_ok=True)
            with open(code_path, 'w', encoding='utf-8') as f:
                f.write(mutated_code)
                f.flush()
                os.fsync(f.fileno())
            print(f"    Code file written successfully")

            # Verify it was written
            if os.path.exists(code_path):
                actual_size = os.path.getsize(code_path)
                print(f"    Verified: file exists, size={actual_size} bytes")

            # Replace/add test file in temp repo
            test_path = os.path.join(temp_repo, test_relpath)
            print(f"    Writing test code to: {test_path}")
            print(f"    Test code length: {len(test_code)} bytes")
            print(f"    Test code preview (first 200 chars):\n{test_code[:200]}")
            os.makedirs(os.path.dirname(test_path), exist_ok=True)
            with open(test_path, 'w', encoding='utf-8') as f:
                f.write(test_code)
                f.flush()
                os.fsync(f.fileno())
            print(f"    Test file written successfully")

            # Verify it was written
            if os.path.exists(test_path):
                actual_size = os.path.getsize(test_path)
                print(f"    Verified: file exists, size={actual_size} bytes")
                # Read it back to confirm
                with open(test_path, 'r', encoding='utf-8') as f:
                    readback = f.read()
                    if readback == test_code:
                        print(f"    Verified: content matches what was written")
                    else:
                        print(f"    WARNING: Content doesn't match!")
                        print(f"      Expected length: {len(test_code)}")
                        print(f"      Actual length: {len(readback)}")
            else:
                print(f"    WARNING: Test file doesn't exist after writing!")

            # Detect test framework
            test_framework = CodeValidator._detect_test_framework(test_code)
            print(f"    Detected test framework: {test_framework}")

            # Run tests based on detected framework
            if test_framework == "pytest":
                # Run with pytest, disabling cache
                result = subprocess.run(
                    [venv_python, "-m", "pytest", test_path, "-v"], 
                    capture_output=True,
                    text=True,
                    cwd=temp_repo,
                    timeout=timeout,
                    # env=test_env
                )
            else:
                # Run with unittest
                # Convert test file path to module name
                # e.g., "tests/test_validators.py" -> "tests.test_validators"
                test_module = test_relpath.replace('/', '.').replace('\\', '.').replace('.py', '')
                result = subprocess.run(
                    [venv_python, "-m", "unittest", test_module, "-v"],
                    capture_output=True,
                    text=True,
                    cwd=temp_repo,
                    timeout=timeout,
                    # env=test_env
                )

            passed = result.returncode == 0

            # Always print output for debugging
            print(f"    Test framework: {test_framework}")
            print(f"    Test return code: {result.returncode}")
            print(f"    Test result: {'PASSED' if passed else 'FAILED'}")
            print(f"    Test output (first 100 chars):\n{result.stdout[:100]}")
            if result.stderr:
                print(f"    Test errors:\n{result.stderr}")

            # Check if tests errored out (import errors, syntax errors, etc.)
            # vs actually running and failing/passing
            if "ImportError" in result.stderr or "ModuleNotFoundError" in result.stderr:
                print(f"    Test has import errors - doesn't build properly")
                return False, False
            elif "SyntaxError" in result.stderr or "IndentationError" in result.stderr:
                print(f"    Test has syntax errors - doesn't build properly")
                return False, False
            elif "ERROR" in result.stderr and "FAILED" not in result.stdout:
                # Test errored but didn't actually run
                print(f"    Test errored without running - doesn't build properly")
                return False, False

            # Tests built and ran, return whether they passed
            return True, passed

        except subprocess.TimeoutExpired:
            print(f"    Test execution timeout")
            return True, False
        except Exception as e:
            print(f"    Error running tests: {e}")
            return True, False