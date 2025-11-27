"""File-based oracle validation for human-in-the-loop workflow"""

import os


class OracleValidator:
    """Handle file-based oracle validation workflow"""

    def __init__(self, output_dir: str):
        """
        Initialize oracle validator.

        Args:
            output_dir: Directory where oracle files will be saved
        """
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def save_oracle_for_validation(self, oracle: str, chunk_id: str) -> str:
        """
        Save oracle specification to file for user review.

        Args:
            oracle: Oracle specification text
            chunk_id: Identifier for the chunk/function

        Returns:
            Path to the saved oracle file
        """
        # Sanitize chunk_id for filename
        safe_chunk_id = chunk_id.replace("/", "_").replace("\\", "_")
        oracle_file = os.path.join(self.output_dir, f"{safe_chunk_id}_oracle.txt")

        with open(oracle_file, 'w', encoding='utf-8') as f:
            f.write(oracle)

        return oracle_file

    def wait_for_validation(self, oracle_file: str) -> str:
        """
        Wait for user to validate/edit oracle, then load the validated version.

        User workflow:
        1. Review the oracle file
        2. Edit it if needed
        3. Save edits as *_oracle_validated.txt
        4. Press Enter to continue

        Args:
            oracle_file: Path to the oracle file saved earlier

        Returns:
            Validated oracle text (either user-edited or original)
        """
        validated_file = oracle_file.replace("_oracle.txt", "_oracle_validated.txt")

        print("\n" + "=" * 80)
        print("ORACLE VALIDATION REQUIRED")
        print("=" * 80)
        print(f"\nOracle specification saved to:")
        print(f"  {oracle_file}")
        print(f"\nTo validate:")
        print(f"  1. Review the oracle specification above")
        print(f"  2. If changes needed, edit and save as:")
        print(f"     {validated_file}")
        print(f"  3. Press Enter when ready to continue...")
        print("=" * 80)

        input()

        # Check if user created a validated version
        if os.path.exists(validated_file):
            print(f"✓ Using validated oracle from: {validated_file}")
            with open(validated_file, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            print(f"✓ No edits found, using original oracle")
            with open(oracle_file, 'r', encoding='utf-8') as f:
                return f.read()
