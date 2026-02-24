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

MUTATION APPROACH:
The goal is to introduce a realistic {concern} violation — NOT a simple operator swap or off-by-one error. Think about how a developer could plausibly introduce a {concern} flaw through:
- Removing or weakening a security/validation check that exists in the code
- Changing the order of operations so a side effect happens before a guard
- Removing an error handler so sensitive state leaks through exceptions
- Changing a condition so a code path that should be restricted becomes accessible
- Replacing a safe default with an unsafe one
- Removing a cleanup/reset operation so state persists when it shouldn't
- Changing what data gets included in a return value or passed to another function
- Short-circuiting a loop or validation early so not all cases are checked

HARD CONSTRAINTS:
1. Only use variables, attributes, methods, and logic structures that ALREADY EXIST in the original code — do NOT invent new ones
2. The mutated code must be syntactically valid Python
3. All existing tests must still pass on the mutated version
4. Preserve the function/method signature exactly
5. Delimit mutated lines with '# MUTANT START' and '# MUTANT END'

BAD MUTATIONS (do NOT do these):
- Inventing new attributes like `o.sensitive_metadata_size` that don't exist in the code
- Adding new if-blocks that check for conditions not in the original
- Adding logging, print statements, or new function calls
- Adding new try/except blocks not in the original
- Simple operator swaps like > to >= (too shallow, not a business logic concern)

GOOD MUTATIONS for reference:
- Removing a `warnings.warn()` call so users aren't notified of unsafe behavior
- Deleting `o.seek(current_position or 0)` so file pointer isn't restored (corrupts subsequent reads)
- Changing an error handler's fallback value so it exposes internal state instead of safe default
- Removing a `if "b" not in o.mode:` check so text-mode files are silently accepted
- Swapping which branch of an existing if/else runs (e.g., error path vs success path)

Return the COMPLETE mutated function/method code (not just the changed lines)."""

    @staticmethod
    def equivalence_detector(class_version1: str, class_version2: str) -> str:
        """Table 1: Equivalence detector"""
        return f"""I'm going to show you two slightly different versions of a Python class.

First version:
'''{class_version1}'''

Second version:
'''{class_version2}'''

INSTRUCTION: If the first version will ALWAYS produce exactly the same observable behavior as the second version for ALL possible inputs, respond with 'yes'.

If they are NOT equivalent, respond with 'no' and give:
1. A specific input or scenario where they differ
2. What the first version produces
3. What the second version produces"""

    @staticmethod
    def make_test_to_catch_fault(
        original_class: str, mutated_class: str, existing_test_class: str
    ) -> str:
        """Generate a unit test that catches a mutation by calling the target directly"""
        return f"""Two versions of a Python class: the original and a mutated version containing a bug delimited by '# MUTANT START' and '# MUTANT END'.

ORIGINAL:
'''{original_class}'''

MUTATED:
'''{mutated_class}'''

EXISTING TESTS:
'''{existing_test_class}'''

TASK: Add EXACTLY ONE new test method to catch the mutant.

REQUIREMENTS:
1. The test MUST pass on the original code
2. The test MUST fail on the mutated code
3. Call the mutated function/method DIRECTLY with inputs that expose the difference
4. Use SPECIFIC assertions — assertEqual with exact expected values, not broad checks like assertTrue(result)
5. Target the EXACT lines between '# MUTANT START' and '# MUTANT END' — design an input that forces execution through that code path
6. Follow the naming conventions and style of the existing test class

STRATEGY:
- Read the mutation carefully — what specific behavior changed?
- Find an input where the original and mutant produce DIFFERENT outputs
- Assert the ORIGINAL's output — this will pass on original, fail on mutant

Write the extended test class with all existing tests unchanged plus your one new test method."""

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
        return f"""You are an expert security and testing reviewer evaluating AI-generated mutations and tests for {concern}/business-logic concerns.

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
   - 0-3: Unrelated bug type or invents non-existent attributes/logic
   - 4-6: Related domain but wrong mechanism or too heavy-handed
   - 7-8: Closely matches pattern with minor deviations
   - 9-10: Perfect instantiation of the violation pattern

2. BUSINESS LOGIC IMPACT (0-10):
   How significantly does this mutation affect real-world system behavior?
   - 0-3: Cosmetic or no observable behavioral change
   - 4-6: Changes behavior in edge cases only
   - 7-8: Impacts common execution paths
   - 9-10: Critical business logic flaw

3. MUTATION SUBTLETY (0-10):
   Would existing tests miss this? Is it realistic?
   - 0-3: Invents attributes/logic not in original code, crashes immediately, or syntax error
   - 4-6: Plausible but detectable — removes an obvious guard or changes a clear default
   - 7-8: Subtle — weakens a validation, reorders operations, or changes error handling in a way that looks intentional
   - 9-10: Insidious — correct behavior in most cases, only fails under specific conditions

4. TEST EFFECTIVENESS (0-10):
   Does the new test actually catch the mutant with precision?
   - 0-3: Doesn't fail on mutant, or uses wrong assertions
   - 4-6: Catches mutant but assertions are broad or brittle
   - 7-8: Precisely targets the mutation with specific assertions
   - 9-10: Thorough verification of the affected property

5. TEST INTEGRATION (0-10):
   How well does the test fit the existing test suite?
   - 0-3: Different style, breaks conventions, duplicates tests
   - 4-6: Functional but inconsistent with existing patterns
   - 7-8: Follows conventions, integrates cleanly
   - 9-10: Seamlessly extends suite

---

AUTOMATIC DISQUALIFIERS:
- Mutation adds attributes/logic not in original code → mutation_subtlety=0
- Mutation introduces syntax errors → concern_alignment=0, mutation_subtlety=0
- Test doesn't fail on mutant → test_effectiveness=0

SCORING GUIDELINES:
- Most mutations should score 4-7
- Scores of 9-10 should be RARE
- If unsure between two scores, choose the lower one

Return ONLY valid JSON:
{{
    "concern_alignment": <int 0-10>,
    "concern_alignment_reasoning": "<one sentence>",
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

CODE:
'''{code}'''

Generate {num_mutants} DIFFERENT mutated versions of this code.

Each mutant should introduce a realistic {concern} violation by:
- Removing or weakening a validation/security check
- Changing operation order so a side effect happens before a guard
- Removing error handling so internal state leaks
- Changing a condition so a restricted path becomes accessible
- Replacing a safe default with an unsafe one
- Removing cleanup so state persists when it shouldn't
- Changing what data a return value or function call includes
- Short-circuiting a validation loop early

HARD CONSTRAINTS for every mutant:
1. Only use variables, attributes, and logic that ALREADY EXIST in the original — do NOT invent new ones
2. Must be syntactically valid Python
3. Each mutant must be different from every other
4. Do NOT do simple operator swaps (> to >=) — these are too shallow for business logic concerns
5. Do NOT add new attributes, if-blocks, try/except, logging, or function calls not in the original

For each mutant, wrap the mutated code with delimiters:
// MUTANT START <number>
<complete mutated function>
// MUTANT END <number>

Generate {num_mutants} distinct mutants."""

    @staticmethod
    def generate_oracle_inference(original_code: str, mutants: list, concern: str, integration_context: dict = None) -> str:
        """Generate oracle specification from analyzing mutants"""
        mutants_text = "\n\n".join([f"MUTANT {i+1}:\n{m}" for i, m in enumerate(mutants)])

        # Format integration context from knowledge graph if available
        integration_section = ""
        if integration_context:
            parts = []

            if integration_context.get("entry_points"):
                lines = []
                seen = set()
                for ep in integration_context["entry_points"]:
                    key = (ep.get("direct_caller"), ep.get("direct_caller_file"))
                    if key not in seen:
                        seen.add(key)
                        line = f"  - {ep.get('direct_caller')} in {ep.get('direct_caller_file')}"
                        if ep.get("top_level_entry"):
                            line += f" (called by {ep.get('top_level_entry')} in {ep.get('top_entry_file')})"
                        lines.append(line)
                parts.append("CALLERS THAT USE THIS FUNCTION:\n" + "\n".join(lines))

            if integration_context.get("class_interface"):
                ci = integration_context["class_interface"][0]
                method_lines = []
                for m in ci.get("public_methods", []):
                    params = ", ".join(m.get("params", [])) if m.get("params") else ""
                    method_lines.append(f"  - {m.get('name')}({params})")
                parts.append(
                    f"CLASS INTERFACE for {ci.get('class_name')}:\n"
                    f"  Bases: {ci.get('bases', [])}\n"
                    f"  Public methods:\n" + "\n".join(method_lines)
                )

            if integration_context.get("import_chain"):
                ic = integration_context["import_chain"][0]
                parts.append(
                    f"IMPORT CHAIN:\n"
                    f"  Target file: {ic.get('target_file')}\n"
                    f"  Direct importers: {ic.get('direct_importers', [])}\n"
                    f"  Second-hop importers: {ic.get('second_hop_importers', [])}"
                )

            if integration_context.get("caller_source_code"):
                caller_parts = []
                for path, code in integration_context["caller_source_code"].items():
                    caller_parts.append(f"--- {path} ---\n{code}")
                parts.append("SOURCE CODE OF CALLERS:\n" + "\n\n".join(caller_parts))

            if parts:
                integration_section = (
                    "\nINTEGRATION CONTEXT (how this function is used across the codebase):\n"
                    + "\n\n".join(parts)
                    + "\n\nUse this integration context to infer CROSS-MODULE invariants — "
                    "properties that callers depend on, contracts between this function and its consumers, "
                    "and integration-level safety properties that would break downstream behavior.\n"
                )

        return f"""I will show you code and several BUGGY mutated versions of it.

ORIGINAL CODE:
'''{original_code}'''

BUGGY MUTANTS (each has a subtle bug related to {concern}):
{mutants_text}
{integration_section}
TASK: Infer what CORRECT behavior should be by analyzing what each mutant breaks.

For each mutant:
1. What specific line changed?
2. What behavior does the change break?
3. What property/invariant does it violate?

Then produce a TESTABLE oracle specification:

INVARIANTS: Properties that must ALWAYS hold (that mutants violate)
SAFETY PROPERTIES: Things that must NEVER happen (that mutants cause)
INPUT-OUTPUT RELATIONSHIPS: Correct outputs for given inputs
ERROR CONDITIONS: How errors must be handled
INTEGRATION CONTRACTS: Properties that callers depend on (if integration context was provided)

Each specification item must be concrete enough to write an assertion for.

BAD: "The function should handle errors properly"
GOOD: "When input is None, the function must return 0, not raise TypeError"

BAD: "Data should be secure"
GOOD: "The response dict must never contain the key 'ssn_hash'"

BAD: "Callers expect correct results"
GOOD: "When prepare_request() calls super_len(data), the returned value must match len(data.read()) for file-like objects"
"""

    @staticmethod
    def generate_test_from_oracle(original_code: str, oracle: str, chunk_id: str, existing_test_file: str) -> str:
        """Generate extended test from oracle specification"""

        return f"""Extend the existing test file with new test methods based on an oracle specification.

EXISTING TEST FILE:
```python
{existing_test_file}
```

ORACLE SPECIFICATION:
{oracle}

CODE UNDER TEST:
```python
{original_code}
```

TASK: Add new test methods that verify the oracle specification.

RULES:
1. Keep ALL existing imports, classes, and test methods unchanged
2. Add new test methods to the existing test class
3. Match the naming conventions, assertion style, and mock patterns of existing tests
4. Each oracle property (invariant, safety property, I/O relationship, error condition) gets one test method

ASSERTION GUIDE:

For SAFETY PROPERTIES ("X must NEVER happen"):
    self.assertNotIn('ssn_hash', result['data'])    # FAILS if bug leaks ssn_hash
    self.assertFalse(result['approved'])              # FAILS if bug approves incorrectly

For INVARIANTS ("X must ALWAYS be true"):
    self.assertTrue(result['validated'])              # FAILS if bug skips validation
    mock_fn.assert_called_once_with(expected_arg)     # FAILS if bug skips the call

For INPUT-OUTPUT ("Given X, output must be Y"):
    self.assertEqual(result, expected_value)           # FAILS if bug changes output
    self.assertIsNone(result['data'])                  # FAILS if bug leaks data

COMMON MISTAKE — do NOT write tests that verify bugs exist:
    WRONG: self.assertIn('ssn_hash', result)          # passes on buggy code
    RIGHT: self.assertNotIn('ssn_hash', result)       # fails on buggy code

Return the COMPLETE test file: all existing tests unchanged plus new test methods.
New tests should FAIL on buggy code and PASS on corrected code."""

    # ===== Functional Test Prompts =====

    @staticmethod
    def make_functional_test_to_catch_fault(
        original_class: str,
        mutated_class: str,
        existing_test_class: str,
        integration_context: dict,
    ) -> str:
        """Generate a functional test that catches a mutation through a realistic usage path."""

        # Format entry points
        entry_points_text = ""
        if integration_context.get("entry_points"):
            lines = []
            seen = set()
            for ep in integration_context["entry_points"]:
                key = (ep.get("direct_caller"), ep.get("direct_caller_file"))
                if key not in seen:
                    seen.add(key)
                    lines.append(
                        f"  - {ep.get('direct_caller')} in {ep.get('direct_caller_file')}"
                        + (f" (called by {ep.get('top_level_entry')} in {ep.get('top_entry_file')})"
                           if ep.get("top_level_entry") else "")
                    )
            entry_points_text = "CALLERS THAT USE THE MUTATION TARGET:\n" + "\n".join(lines)

        # Format class interface
        class_interface_text = ""
        if integration_context.get("class_interface"):
            ci = integration_context["class_interface"][0]
            methods = ci.get("public_methods", [])
            method_lines = []
            for m in methods:
                params = ", ".join(m.get("params", [])) if m.get("params") else ""
                method_lines.append(f"  - {m.get('name')}({params})")
            class_interface_text = (
                f"CLASS INTERFACE for {ci.get('class_name')}:\n"
                f"  Bases: {ci.get('bases', [])}\n"
                f"  Public methods:\n" + "\n".join(method_lines)
            )

        # Format import chain
        import_chain_text = ""
        if integration_context.get("import_chain"):
            ic = integration_context["import_chain"][0]
            import_chain_text = (
                f"IMPORT CHAIN:\n"
                f"  Target file: {ic.get('target_file')}\n"
                f"  Direct importers: {ic.get('direct_importers', [])}\n"
                f"  Second-hop importers: {ic.get('second_hop_importers', [])}"
            )

        # Format caller source code
        caller_source_text = ""
        if integration_context.get("caller_source_code"):
            parts = []
            for path, code in integration_context["caller_source_code"].items():
                parts.append(f"--- {path} ---\n{code}")
            caller_source_text = "SOURCE CODE OF CALLERS (use these to understand the integration path):\n" + "\n\n".join(parts)

        return f"""Two versions of Python code: original and mutated. The bug is between '# MUTANT START' and '# MUTANT END'.

ORIGINAL:
'''{original_class}'''

MUTATED:
'''{mutated_class}'''

EXISTING TESTS:
'''{existing_test_class}'''

INTEGRATION CONTEXT FROM KNOWLEDGE GRAPH:

{entry_points_text}

{class_interface_text}

{import_chain_text}

{caller_source_text}

TASK: Write a FUNCTIONAL TEST that catches the mutation through a CALLER, not by calling the mutated function directly.

HOW A FUNCTIONAL TEST WORKS:
- The mutation is in function X
- Function Y calls X (listed in the callers above)
- Your test calls Y and asserts on Y's output
- The mutation in X causes Y to produce wrong results
- Your assertion catches the difference

REQUIREMENTS:
1. Add EXACTLY ONE new test method
2. The test MUST pass on the original code
3. The test MUST fail on the mutated code
4. DO NOT import or call the mutation target function directly
5. Instead, import and call one of the CALLERS listed in the integration context
6. Assert on the observable outcome at the caller level

CHOOSING THE RIGHT CALLER:
- Pick the caller closest to the mutation target (direct caller, not second-hop)
- If the caller is a method, instantiate its class and call the method
- If the caller source code is provided above, read it to understand what inputs to provide
- Set up realistic preconditions that the caller expects

WHAT MAKES THIS DIFFERENT FROM A UNIT TEST:
- Unit test: `result = super_len(my_object)` then assert result
- Functional test: `prepared = Request('POST', url, data=my_object).prepare()` then assert `prepared.headers['Content-Length']`

The functional test verifies the mutation is caught through the REAL usage path in the codebase.

Write the extended test class with all existing tests unchanged plus your one new functional test."""