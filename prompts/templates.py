class PromptTemplates:
    @staticmethod
    def make_fault_for_chunk(
        context: str,
        chunk_code: str,
        chunk_type: str,
        parent_class: str,
        full_class_context: str,
        existing_test_class: str,
        diff: str,
        concern: str = "privacy",
    ) -> str:
        """Generate fault for a specific code chunk (method/function)"""

        # Build context information
        if parent_class and chunk_type == "method":
            location_info = f"This is a method from the '{parent_class}' class."
            context_section = f"""
FULL CLASS CONTEXT (for understanding dependencies):
'''{full_class_context}'''
"""
        else:
            location_info = f"This is a standalone {chunk_type}."
            context_section = ""

        return f"""CONTEXT: {context}

{location_info}

CODE TO MUTATE:
'''{chunk_code}'''
{context_section}
EXISTING TESTS:
'''{existing_test_class}'''

INSTRUCTION: Write a mutated version of the code above that introduces a SUBTLE bug representing a {concern} issue similar to: {diff}

Requirements:
1. The bug should be SUBTLE enough that all existing tests still pass
2. Do not completely remove functionality - introduce edge cases or partial failures
3. The mutation should be realistic (something that could happen in real code)
4. Preserve the function/method signature and overall structure
5. Delimit ONLY the mutated lines using the comment-pair '# MUTANT START' and '# MUTANT END'

Return the COMPLETE mutated function/method code (not just the changed lines)."""

    @staticmethod
    def equivalence_detector(class_version1: str, class_version2: str) -> str:
        """Table 1: Equivalence detector - EXACT prompt"""
        return f"""I'm going to show you two slightly different versions of a Python class. Here is the first version of the Python class:'''{class_version1}'''.
Here is the second version of the Python class:'''{class_version2}'''. INSTRUCTION: If the first version of the class will always do exactly
the same thing as the second version of the class, just respond with 'yes'. However, if the two versions of the class are not equivalent,
respond with 'no', and give an explanation of how execution of the first version can produce a different behaviour to execution of the
second version."""

    @staticmethod
    def make_test_to_catch_fault(
        original_class: str, mutated_class: str, existing_test_class: str
    ) -> str:
        """Table 1: Make a test to catch fault - EXACT prompt"""
        return f"""What follows is two versions of a Python class under test. An original correct class and a mutated version of that class that contains one
mutant per method, each of which represents a bug. Each bug is delimited by the comment-pair '# MUTANT START' and '# MUTANT END'. The
original class and its mutant are followed by a test class that contains unit tests for the original correct class under test. This is the
original version of the class under test:'''{original_class}'''. This is the mutated version of the class under test:'''{mutated_class}'''.
Here is the existing test class:'''{existing_test_class}'''. 

CRITICAL REQUIREMENTS:
1. Add EXACTLY ONE new test method OR modify ONE existing test method to catch the mutant
2. The new/modified test MUST pass on the original correct version
3. The new/modified test MUST fail on the mutated version

Write an extended version of the test class that adds exactly one test case to catch the mutant."""
    
    @staticmethod
    def llm_judge_mutant(
        original_code: str,
        mutated_code: str,
        original_test: str,
        new_test: str,
        context: str,
        diff: str,
        concern: str = "privacy",
    ) -> str:
        """Prompt for LLM to judge mutant quality"""
        return f"""
You are an expert security and testing reviewer evaluating AI-generated mutations and tests for {concern}/business-logic concerns.

{concern.upper()} CONCERN CONTEXT:
{context}

TARGET VIOLATION PATTERN:
{diff}

ORIGINAL CODE:
```python
{original_code}
```

MUTATED CODE (with bug):
```python
{mutated_code}
```

ORIGINAL TEST SUITE:
```python
{original_test}
```

NEW/EXTENDED TESTS (designed to catch the mutant):
```python
{new_test}
```

---

EVALUATION CRITERIA:

1. CONCERN ALIGNMENT (0-10):
   How well does the mutation represent the TARGET VIOLATION PATTERN?
   - 0-2: Completely different type of bug (e.g., null pointer when pattern is data leakage)
   - 3-4: Related domain but wrong mechanism (e.g., logs wrong field for privacy violation)
   - 5-6: Similar bug class but misses nuance (e.g., leaks data but not in the same way)
   - 7-8: Closely matches pattern with minor deviations
   - 9-10: Perfect instantiation of the violation pattern in this code context

2. BUSINESS LOGIC IMPACT (0-10):
   How significantly does this mutation affect real-world system behavior?
   - 0-2: Trivial changes (variable rename, comment change, cosmetic)
   - 3-4: Affects implementation details but not observable behavior
   - 5-6: Changes behavior in edge cases only
   - 7-8: Impacts common execution paths or data handling
   - 9-10: Critical business logic flaw with serious consequences

3. MUTATION SUBTLETY (0-10):
   Would existing tests miss this? Is it realistic?
   - 0-2: Obvious bug that existing tests should catch (syntax error, crashes immediately)
   - 3-4: Breaks obvious contracts or invariants
   - 5-6: Plausible but careful code review would catch it
   - 7-8: Subtle enough to slip through review, realistic developer mistake
   - 9-10: Insidious bug that mimics correct behavior in most cases

4. TEST EFFECTIVENESS (0-10):
   Does the new test actually catch the mutant with precision?
   - 0-2: Test doesn't fail on mutant OR is trivial/unrelated
   - 3-4: Test attempts to catch mutant but assertions are weak or wrong
   - 5-6: Catches mutant but with overly broad assertions (brittle/false positives)
   - 7-8: Precisely targets the mutation with specific, relevant assertions
   - 9-10: Exceptional test that verifies the privacy/security property thoroughly

5. TEST INTEGRATION (0-10):
   How well does the test fit the existing test suite?
   - 0-2: Completely different style, duplicates existing tests, or breaks conventions
   - 3-4: Poor structure, doesn't follow patterns, hard to maintain
   - 5-6: Functional but inconsistent with existing test organization
   - 7-8: Follows most conventions, integrates cleanly with minor issues
   - 9-10: Seamlessly extends test suite, follows all patterns and naming

---

CRITICAL DISQUALIFIERS (any of these = automatic 0 for relevant metric):

- Mutation introduces syntax errors → concern_alignment=0, mutation_subtlety=0
- Mutation is completely unrelated to the privacy concern → concern_alignment=0
- Test just checks unrelated functionality → test_effectiveness=0

---

CALIBRATION EXAMPLES:

EXAMPLE 1 - EXCELLENT (scores: 9, 9, 8, 9, 8)
Concern: "User data leaked in logs"
Pattern: "Logging PII in debug statements"
Mutation: Changed `logger.debug(f"Processing order order_id")` to `logger.debug(f"Processing order order_id for user.email")`
Test: Mocks logger, triggers code path, asserts email NOT in any log calls
Why high: Perfect match to pattern, realistic logging mistake, test precisely verifies no PII in logs

EXAMPLE 2 - POOR (scores: 3, 5, 2, 3, 4)
Concern: "Insufficient access control checks"
Pattern: "Missing permission verification before data access"
Mutation: Changed variable name `user_data` to `usr_data`
Test: Checks that method returns correct data type
Why low: Cosmetic change unrelated to access control, no security impact, test doesn't verify permissions

EXAMPLE 3 - MEDIUM (scores: 7, 6, 7, 5, 6)
Concern: "Race condition in shared resource access"
Pattern: "Missing lock acquisition"
Mutation: Removed `with self.lock:` wrapper around cache update
Test: Calls method multiple times, checks final state is correct
Why medium: Good concern match, realistic bug, but test doesn't actually verify thread-safety (no concurrent execution)

EXAMPLE 4 - SUBTLE ISSUE (scores: 8, 8, 9, 4, 7)
Concern: "Data retention policy violation"
Pattern: "Not deleting user data after retention period"
Mutation: Changed `if days_old > RETENTION_DAYS: delete_user_data()` to `if days_old >= RETENTION_DAYS: delete_user_data()`
Test: Checks that data exists after exactly RETENTION_DAYS
Why: Perfect boundary condition bug (concern_alignment=8), but test assertions are inverted - should verify data is DELETED, not that it exists (test_effectiveness=4)

---

IMPORTANT SCORING GUIDELINES:

- Your scores should follow a realistic distribution
- Most mutations should score 4-7 (decent but imperfect)
- Scores of 9-10 should be RARE (truly exceptional alignment and execution)
- Scores of 0-3 should flag serious problems
- Be critical: if you're unsure between two scores, choose the lower one
- A mutation can match the concern pattern well but still have low subtlety or poor test quality

---

PROVIDE YOUR EVALUATION:

Return ONLY valid JSON with no additional text:
{{
    "concern_alignment": <int 0-10>,
    "concern_alignment_reasoning": "<one sentence explaining score>",
    "business_logic_impact": <int 0-10>,
    "business_logic_impact_reasoning": "<one sentence>",
    "mutation_subtlety": <int 0-10>,
    "mutation_subtlety_reasoning": "<one sentence>",
    "test_effectiveness": <int 0-10>,
    "test_effectiveness_reasoning": "<one sentence>",
    "test_integration": <int 0-10>,
    "test_integration_reasoning": "<one sentence>"
}}
"""

    # ===== Oracle Mode Prompts =====

    @staticmethod
    def generate_multiple_mutants(context: str, code: str, concern: str, num_mutants: int = 10) -> str:
        """Generate multiple mutants for oracle inference"""
        return f"""CONTEXT: {context}

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

    @staticmethod
    def generate_oracle_inference(original_code: str, mutants: list, concern: str) -> str:
        """Generate oracle specification from analyzing mutants"""
        mutants_text = "\n\n".join([f"MUTANT {i+1}:\n{m}" for i, m in enumerate(mutants)])

        return f"""I will show you a piece of code and several BUGGY mutated versions of it.

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

    @staticmethod
    def generate_test_from_oracle(original_code: str, oracle: str, chunk_id: str, existing_test_file: str) -> str:
        """Generate extended test from oracle specification by adding to existing test file"""

        return f"""You are extending an existing test file by adding new test methods to detect bugs based on an oracle specification.

EXISTING TEST FILE (extend this with new test methods):
```python
{existing_test_file}
```

ORACLE SPECIFICATION (Correct Behavior to Verify):
{oracle}

ORIGINAL CODE TO TEST (Might contain bugs):
```python
{original_code}
```

TASK: Extend the existing test class by adding new test methods that will:

1. DETECT VIOLATIONS of the oracle specification
2. FAIL when run against the buggy original code
3. PASS when run against corrected code that follows the oracle
4. Follow the SAME structure, imports, and style as the existing test file

CRITICAL REQUIREMENTS:
- Add test methods to the EXISTING test class structure shown above
- Use the SAME imports and test framework (pytest or unittest) as the existing tests
- Match the naming conventions and coding style of existing tests
- Return the COMPLETE extended test file (existing tests + new tests)
- Do NOT remove or modify existing test methods

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
DO NOT remove or modify existing test methods

Example of WRONG test (documents bug, doesn't catch it):
    self.assertIn('ssn_hash', result['data'], "BUG: ssn_hash should not be here")
    This PASSES on buggy code - WRONG!

Example of CORRECT test (catches bug):
    self.assertNotIn('ssn_hash', result['data'], "SSN hash must never be shared")
    This FAILS on buggy code - CORRECT!

EXTENDING THE EXISTING TEST FILE:

1. Keep ALL existing imports, test classes, and test methods unchanged

2. Add new test methods to the existing test class that verify the oracle specification:
   - Each INVARIANT from the oracle gets a test method
   - Each SAFETY PROPERTY from the oracle gets a test method
   - Each INPUT-OUTPUT relationship from the oracle gets a test method
   - Each ERROR CONDITION from the oracle gets a test method
   - Edge cases and boundary conditions

3. Each new test method should:
   - Follow the naming convention of existing tests
   - Have a descriptive name indicating what oracle property it tests
   - Set up test conditions (using setUp patterns from existing tests if present)
   - Execute the function under test
   - Assert expected behavior according to oracle
   - Use assertion messages that explain what SHOULD happen per the oracle

4. Use the same mocking patterns as existing tests:
   - Mock external dependencies consistently
   - Verify mock calls to ensure methods are invoked correctly
   - Check call order when sequence matters

5. Match the style and structure of existing tests:
   - Same assertion style (self.assertEqual vs self.assert_equal, etc.)
   - Same mock setup patterns
   - Same test data creation patterns
   - Same helper function usage

Now generate the COMPLETE extended test file following all these guidelines.
Include ALL existing tests unchanged, plus your new test methods.
The new tests you add should FAIL on the buggy original code and PASS on corrected code.
Return the full Python test file.
"""

    # ===== Indexer Prompts =====

    @staticmethod
    def module_summary(file_path: str, source_code: str) -> str:
        """Generate a one-paragraph summary of a Python module"""
        return f"""Analyze the following Python module and provide a ONE PARAGRAPH summary describing its purpose, main responsibilities, and key classes or functions it contains.

FILE PATH: {file_path}

SOURCE CODE:
'''{source_code}'''

Provide ONLY the summary paragraph, no headers or bullet points."""
