"""Core ACH workflow implementation"""
from src.llm_client import LLMClient
from src.validators import CodeValidator
from prompts.templates import PromptTemplates


class ACHWorkflow:
    def __init__(self, model: str, provider: str):
        self.llm = LLMClient(model, provider)
        self.validator = CodeValidator()
        self.prompts = PromptTemplates()
    
    def run_workflow(self, code_file: str, test_file: str, max_attempts: int = 5):
        """Run the ACH workflow with exact prompts from the paper"""
        print("Starting ACH Workflow with exact prompts from paper...")
        print(f"Using model: {self.llm.model}")
        print(f"Processing files: {code_file}, {test_file}")
        
        # Read input files
        with open(code_file, 'r', encoding='utf-8') as f:
            class_under_test = f.read()
        with open(test_file, 'r', encoding='utf-8') as f:
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
            print(mutated_class[:500] + ("..." if len(mutated_class) > 500 else ""))
            print("-" * 40)
            
            # Step 2: Check if syntactically identical
            print("\n" + "="*60)
            print("STEP 2: Checking syntactic identity...")
            print("="*60)
            if self.validator.is_syntactically_identical(class_under_test, mutated_class):
                print("    Mutant is syntactically identical - discarding")
                return None
            print("   Mutant is syntactically different")
                
            # Step 3: Check if mutant builds and passes
            print("\n" + "="*60)
            print("STEP 3: Validating mutant builds and passes...")
            print("="*60)
            builds, passes = self.validator.run_tests(
                mutated_class,
                existing_test_class,
                code_filename=code_file,
                test_filename=test_file,
            )
            
            if not builds:
                print("    Mutant doesn't build - discarding")
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
        print(new_test_class[:500] + ("..." if len(new_test_class) > 500 else ""))
        print("-" * 40)
        
        print("\nSUCCESS: Generated mutant and killing test!")
        return {
            'mutant': mutated_class,
            'test': new_test_class
        }
    
    def _make_fault(self, context, class_under_test, existing_test_class, diff):
        """Table 1: Make a fault - exact prompt from paper"""
        prompt = self.prompts.make_fault(context, class_under_test, existing_test_class, diff)
        
        print("\n Sending prompt to model (prompt length: {} chars)".format(len(prompt)))
        
        text = self.llm.invoke(prompt)
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
        extracted = self.llm.extract_code_from_response(text)
        return extracted
    
    def _equivalence_detector(self, class_version1, class_version2):
        """Table 1: Equivalence detector - exact prompt from paper"""
        prompt = self.prompts.equivalence_detector(class_version1, class_version2)
        
        print(f"\n Checking equivalence (prompt length: {len(prompt)} chars)")
        
        answer = self.llm.invoke(prompt).strip()
        print(f" Equivalence check response: {answer[:100]}...")
        
        is_yes = answer.lower().startswith('yes')
        print(f"   Interpreted as: {'Equivalent' if is_yes else 'Non-equivalent'}")
        
        return is_yes
    
    def _make_test_to_catch_fault(self, original_class, mutated_class, existing_test_class):
        """Table 1: Make a test to catch fault - exact prompt from paper"""
        prompt = self.prompts.make_test_to_catch_fault(original_class, mutated_class, existing_test_class)

        print(f"\n Generating test (prompt length: {len(prompt)} chars)")
        
        text = self.llm.invoke(prompt)
        print(f" Received test response (length: {len(text)} chars)")
        
        # Extract code from response
        extracted = self.llm.extract_code_from_response(text)
        return extracted