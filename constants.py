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