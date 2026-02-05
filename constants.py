# LLM Configuration
MODEL = "gemini-2.5-flash"
MODEL_PROVIDER = "google_genai"

# Output Configuration
OUTPUT_DIR = "outputs"

# Temporary Testing Configuration
TEMP_TESTING_DIR = ".temp_testing"
EXCLUDE_FROM_COPY = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".pytest_cache",
    ".venv",
    ".venv_testing",
    "venv",
    "env",
    "node_modules",
    ".chunk_cache",
    "outputs",
    ".temp_testing",
    ".DS_Store",
    "*.egg-info",
    ".tox",
    "htmlcov",
    "*.so",
    "*.dylib",
    "*.dll",
]

# Parallel Processing Configuration
MAX_WORKERS = 3

# Oracle Mode Configuration
ORACLE_OUTPUT_DIR = "oracle_outputs"
NUM_MUTANTS_PER_FUNCTION = 10
MAX_VALID_MUTANTS = 5
DEFAULT_CONCERN = "privacy"

CONCERN_CONTEXTS = {
    "security": "Security vulnerabilities: SQL injection, XSS, authentication bypass, insecure data handling, missing input validation",
    "privacy": "Privacy violations: logging PII, exposing sensitive data, missing authorization, leaking user information",
    "performance": "Performance issues: inefficient algorithms, memory leaks, unnecessary computations, poor resource management",
    "correctness": "Correctness bugs: off-by-one errors, null pointer issues, logic errors, edge case failures"
}

# Indexer Configuration
INDEXER_OUTPUT_FILE = "codebase_index.json"
INDEXER_MAX_SOURCE_CHARS = 4000
INDEXER_EXCLUDE_PATTERNS = [
    "test_", "_test.py", "tests/", "test/",
    ".git", "__pycache__", ".pytest_cache",
    ".venv", "venv", "env", "node_modules",
    ".DS_Store", ".egg-info", "conftest.py",
]

# Context Assembler Configuration
CONTEXT_DEFAULT_MAX_CALLERS = 5
CONTEXT_DEFAULT_MAX_CALLEES = 5
CONTEXT_DEFAULT_CALLER_DEPTH = 1
CONTEXT_DEFAULT_CALLEE_DEPTH = 1

CONCERN_DIFFS = {
    "privacy": """Real bug example: User profile endpoint returned password_hash and salt_hex fields
in JSON response, exposing sensitive authentication data. Fix removed these fields from public() method.""",
    "security": """Real bug example: SQL query used string concatenation instead of parameterized queries,
allowing SQL injection via user input. Fix replaced f-string with cursor.execute(query, params).""",
    "correctness": """Real bug example: Loop used < instead of <= causing off-by-one error that skipped
the last element in the array. Fix changed range(len(arr)-1) to range(len(arr)).""",
    "performance": """Real bug example: Function called database query inside a loop, causing N+1 query
problem. Fix moved query outside loop and used batch fetching with a single query."""
}