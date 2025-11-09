"""
Repository Manager for creating and managing temporary repository copies.

This module handles the creation of isolated repository copies for testing,
allowing workers to run tests with mutated files in full project context.

Uses a two-tier copy strategy:
1. Master copy: Cached copy with installed dependencies
2. Worker copies: Fast copies from master for each worker
"""

import os
import sys
import shutil
import subprocess
import hashlib
import uuid
from typing import Optional


class RepoManager:
    """Manage temporary repository copies for isolated testing"""

    def __init__(self, repo_path: str, temp_base_dir: str = ".temp_testing"):
        """
        Initialize RepoManager.

        Args:
            repo_path: Path to the original repository
            temp_base_dir: Base directory for temporary copies
        """
        self.repo_path = os.path.abspath(repo_path)
        self.repo_name = os.path.basename(self.repo_path)
        # Make temp_base_dir absolute - relative to current working directory
        self.temp_base_dir = os.path.abspath(temp_base_dir)
        self.master_copy_path = None
        self.venv_python = None

    def create_master_copy(self, exclude_patterns: list) -> str:
        """
        Create a master copy of the repository with installed dependencies.
        This copy is cached and reused across workers.

        Args:
            exclude_patterns: List of patterns to exclude when copying

        Returns:
            Path to the master copy
        """
        # Create unique identifier for this repo based on path
        repo_hash = hashlib.md5(self.repo_path.encode()).hexdigest()[:8]
        master_dir_name = f"{self.repo_name}_master_{repo_hash}"
        master_dir_path = os.path.join(self.temp_base_dir, master_dir_name)

        # Check if master copy already exists and is valid (has working venv)
        if os.path.exists(master_dir_path):
            shutil.rmtree(master_dir_path)

        print(f"Creating master copy of repository...")

        # Create temp base directory if it doesn't exist
        os.makedirs(self.temp_base_dir, exist_ok=True)

        try:
            # Copy entire repository excluding specified patterns
            shutil.copytree(
                self.repo_path,
                master_dir_path,
                ignore=shutil.ignore_patterns(*exclude_patterns)
            )

            # Create virtual environment and install dependencies
            self._setup_venv(master_dir_path)

            self.master_copy_path = master_dir_path
            return master_dir_path
        except Exception:
            # Clean up on failure
            if os.path.exists(master_dir_path):
                shutil.rmtree(master_dir_path)
            raise

    def _setup_venv(self, repo_copy_path: str) -> None:
        """
        Create a virtual environment and install dependencies.

        Args:
            repo_copy_path: Path to repository copy
        """
        # Use unique venv name to avoid conflicts with user's .venv
        venv_path = os.path.join(repo_copy_path, ".venv_testing")

        print(f"Creating virtual environment in master copy...")
        print(f"  Using Python: {sys.executable}")
        print(f"  Target venv path: {venv_path}")

        # Create virtual environment using the current Python interpreter
        result = subprocess.run(
            [sys.executable, "-m", "venv", venv_path],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            print(f"  VENV CREATION FAILED!")
            print(f"  stdout: {result.stdout}")
            print(f"  stderr: {result.stderr}")
            raise RuntimeError(f"Failed to create venv: {result.stderr}")

        print(f"  ✓ Venv created successfully")

        # Get Python path from venv (use python, not pip directly)
        python_executable = self._get_venv_python_path(venv_path)
        print(f"  Expected Python at: {python_executable}")

        if not os.path.exists(python_executable):
            # List what's actually in the venv
            if os.path.exists(venv_path):
                print(f"  Venv directory exists, contents:")
                for item in os.listdir(venv_path):
                    print(f"    - {item}")
                bin_dir = os.path.join(venv_path, "bin")
                if os.path.exists(bin_dir):
                    print(f"  bin/ directory contents:")
                    for item in os.listdir(bin_dir):
                        print(f"    - {item}")
            raise RuntimeError(f"Venv Python not found at: {python_executable}")

        # Detect and install dependencies
        requirements_file = os.path.join(repo_copy_path, "requirements.txt")
        pyproject_file = os.path.join(repo_copy_path, "pyproject.toml")

        if os.path.exists(requirements_file):
            print(f"Installing dependencies from requirements.txt...")
            result = subprocess.run(
                [python_executable, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=repo_copy_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to install dependencies: {result.stderr}")
        elif os.path.exists(pyproject_file):
            print(f"Installing dependencies from pyproject.toml...")
            result = subprocess.run(
                [python_executable, "-m", "pip", "install", "."],
                cwd=repo_copy_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to install project: {result.stderr}")
        else:
            print("No requirements.txt or pyproject.toml found, skipping dependency installation")

        # Store venv Python path
        self.venv_python = python_executable

    def _get_venv_python_path(self, venv_path: str) -> str:
        """
        Get the Python executable path from the virtual environment directory.

        Args:
            venv_path: Path to virtual environment directory

        Returns:
            Path to Python executable
        """
        if os.name == "nt":  # Windows
            return os.path.join(venv_path, "Scripts", "python.exe")
        else:  # Unix/Mac
            return os.path.join(venv_path, "bin", "python")

    def _get_venv_python(self, repo_path: str) -> str:
        """
        Get the Python executable path from the virtual environment in repo.

        Args:
            repo_path: Path to repository with .venv_testing

        Returns:
            Path to Python executable
        """
        venv_path = os.path.join(repo_path, ".venv_testing")
        python_path = self._get_venv_python_path(venv_path)
        return python_path if os.path.exists(python_path) else "python"

    def create_worker_copy(self, worker_id: str) -> str:
        """
        Create a worker copy from the master copy.
        This is fast since it copies from the already-prepared master.

        Args:
            worker_id: Unique identifier for the worker thread

        Returns:
            Path to the worker's repository copy
        """
        if not self.master_copy_path:
            raise RuntimeError("Master copy not created. Call create_master_copy() first.")

        # Create unique temp directory name for worker
        temp_dir_name = f"{self.repo_name}_worker_{worker_id}_{uuid.uuid4().hex[:8]}"
        temp_dir_path = os.path.join(self.temp_base_dir, temp_dir_name)

        # Copy from master copy (includes venv)
        shutil.copytree(self.master_copy_path, temp_dir_path)

        return temp_dir_path


    def cleanup_worker_copies(self) -> None:
        """
        Remove all worker copies but preserve the master copy (cache).
        """
        if not os.path.exists(self.temp_base_dir):
            return

        # Remove all directories except master copy
        for item in os.listdir(self.temp_base_dir):
            item_path = os.path.join(self.temp_base_dir, item)
            # Only remove worker copies (not master)
            if os.path.isdir(item_path) and "_worker_" in item:
                shutil.rmtree(item_path)

    def get_relative_path(self, file_path: str) -> str:
        """
        Convert absolute or relative path to relative from repo root.

        Args:
            file_path: File path (absolute or relative)

        Returns:
            Relative path from repository root
        """
        if os.path.isabs(file_path):
            return os.path.relpath(file_path, self.repo_path)
        return file_path
