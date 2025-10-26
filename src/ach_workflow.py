"""Core ACH workflow implementation"""
from src.llm_client import LLMClient
from src.validators import CodeValidator
from prompts.templates import PromptTemplates


class ACHWorkflow:
    def __init__(self, model: str, provider: str):
        self.llm = LLMClient(model, provider)
        self.validator = CodeValidator()
        self.prompts = PromptTemplates()
    
    def run_workflow(self, code_file: str, test_file: str):
        """Run the ACH workflow - ONE attempt per class (matches paper)"""
        print("Starting ACH Workflow (exact paper replication)...")
        print(f"Using model: {self.llm.model}")
        print(f"Processing: {code_file}, {test_file}")
        
        # Read input files

        # TODO: Need to chunk code blocks as opposed to analyzing whole files
        with open(code_file, 'r', encoding='utf-8') as f:
            class_under_test = f.read()
        with open(test_file, 'r', encoding='utf-8') as f:
            existing_test_class = f.read()

        # TODO: customize context + diff based on mutation type
            
        # Context about privacy concerns
        context_about_concern = """Privacy violations in user data handling:
        - Logging personally identifiable information (emails, names, IDs) without sanitization
        - Exposing password hashes, salts, or authentication tokens in responses
        - Missing authorization checks allowing unauthorized data access
        - Storing sensitive data unencrypted or in application logs"""
        
        diff = """Real bug example: User profile endpoint returned 
        password_hash and salt_hex fields in JSON response, exposing sensitive 
        authentication data. Fix removed these fields from public() method."""

        # STEP 1: Generate mutant
        print("\n" + "="*60)
        print("STEP 1: Generate mutant")
        print("="*60)
        mutated_class = self._make_fault(
            context_about_concern, class_under_test, existing_test_class, diff
        )

        # STEP 3: Validate mutant builds and passes
        print("\n" + "="*60)
        print("STEP 3: Validate mutant")
        print("="*60)
        builds, passes = self.validator.run_tests(
            mutated_class, existing_test_class, code_file, test_file
        )
        
        if not builds:
            print("  ✗ Mutant doesn't build - DISCARD")
            return None
        if not passes:
            print("  ✗ Mutant fails existing tests - DISCARD")
            return None
        print("  ✓ Mutant builds and passes")


        # TODO: currently checking syntactic identity for entire file, need to do per method/mutant
        # STEP 2: Remove syntactically identical (Table 2: 25% of mutants)
        print("\n" + "="*60)
        print("STEP 2: Check syntactic identity")
        print("="*60)
        if self.validator.is_syntactically_identical(class_under_test, mutated_class):
            print("  ✗ Syntactically identical - DISCARD")
            return None
        print("  ✓ Syntactically different")
        
        # STEP 4: Equivalence detection
        print("\n" + "="*60)
        print("STEP 4: Equivalence detection")
        print("="*60)
        is_equivalent = self._equivalence_detector(class_under_test, mutated_class)
        
        if is_equivalent:
            print("  ✗ Equivalent mutant - DISCARD")
            return None
        print("  ✓ Non-equivalent")
        
        # STEP 5: Generate test
        print("\n" + "="*60)
        print("STEP 5: Generate test to kill mutant")
        print("="*60)
        new_test_class = self._make_test_to_catch_fault(
            class_under_test, mutated_class, existing_test_class
        )
        
        # STEP 6: Validate test
        print("\n" + "="*60)
        print("STEP 6: Validate generated test")
        print("="*60)
        
        # 6a: Passes on original?
        builds_orig, passes_orig = self.validator.run_tests(
            class_under_test, new_test_class, code_file, test_file
        )
        if not builds_orig or not passes_orig:
            print("  ✗ Test fails on original - DISCARD")
            return None
        print("  ✓ Test passes on original")
        
        # 6b: Fails on mutant?
        builds_mut, passes_mut = self.validator.run_tests(
            mutated_class, new_test_class, code_file, test_file
        )
        if not builds_mut:
            print("  ✗ Test doesn't build with mutant - DISCARD")
            return None
        if passes_mut:
            print("  ✗ Test doesn't kill mutant - DISCARD")
            return None
        print("  ✓ Test kills mutant!")
        
        print("\n" + "="*60)
        print("SUCCESS: Generated valid mutant-killing test")
        print("="*60)
        
        return {
            'mutant': mutated_class,
            'test': new_test_class
        }
    
    def _make_fault(self, context, class_under_test, existing_test_class, diff):
        """Table 1: Make a fault"""
        prompt = self.prompts.make_fault(context, class_under_test, existing_test_class, diff)
        text = self.llm.invoke(prompt)
        return self.llm.extract_code_from_response(text)
    
    def _equivalence_detector(self, class_version1, class_version2):
        """Table 1: Equivalence detector"""
        prompt = self.prompts.equivalence_detector(class_version1, class_version2)
        answer = self.llm.invoke(prompt).strip()
        return answer.lower().startswith('yes')
    
    def _make_test_to_catch_fault(self, original_class, mutated_class, existing_test_class):
        """Table 1: Make a test to catch fault"""
        prompt = self.prompts.make_test_to_catch_fault(original_class, mutated_class, existing_test_class)
        text = self.llm.invoke(prompt)
        return self.llm.extract_code_from_response(text)