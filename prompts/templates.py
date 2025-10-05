"""Prompt templates from the Meta paper (Table 1)"""


class PromptTemplates:
    @staticmethod
    def make_fault(context: str, class_under_test: str, 
                   existing_test_class: str, diff: str) -> str:
        """Table 1: Make a fault - exact prompt from paper"""
        return f"""CONTEXT: {context} INSTRUCTION: Here is a Python class and a test class with some unit tests for the class under test
'''{class_under_test}'''. '''{existing_test_class}'''. Write a new version of the class under test in which each method is replaced by a new
version of that method that contains a typical bug that introduces a privacy violation similar to {diff}. The bug should be SUBTLE enough that
all existing tests still pass. Do not completely remove functionality - introduce edge cases or partial failures. Delimit the mutated part using the
comment-pair '# MUTANT START' and '# MUTANT END'"""
    
    @staticmethod
    def equivalence_detector(class_version1: str, class_version2: str) -> str:
        """Table 1: Equivalence detector - exact prompt from paper"""
        return f"""I'm going to show you two slightly different versions of a Python class. Here is the first version of the Python class:'''{class_version1}'''.
Here is the second version of the Python class:'''{class_version2}'''. INSTRUCTION: If the first version of the class will always do exactly
the same thing as the second version of the class, just respond with 'yes'. However, if the two versions of the class are not equivalent,
respond with 'no', and give an explanation of how execution of the first version can produce a different behaviour to execution of the
second version."""
    
    @staticmethod
    def make_test_to_catch_fault(original_class: str, mutated_class: str, 
                                 existing_test_class: str) -> str:
        """Table 1: Make a test to catch fault - exact prompt from paper"""
        return f"""What follows is two versions of a Python class under test. An original correct class and a mutated version of that class that contains one
mutant per method, each of which represents a bug. Each bug is delimited by the comment-pair '# MUTANT START' and '# MUTANT END'. The
original class and its mutant are followed by a test class that contains unit tests for the original correct class under test. This is the
original version of the class under test:'''{original_class}'''. This is the mutated version of the class under test:'''{mutated_class}'''.
Here is the existing test class:'''{existing_test_class}'''. Write an extended version of the test class that contains extra test cases that
will fail on the mutant version of the class, but would pass on the correct version."""