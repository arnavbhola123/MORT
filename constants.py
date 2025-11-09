# LLM Configuration
MODEL = "gemini-2.5-flash"
MODEL_PROVIDER = "google_genai"

# Workflow Configuration
MAX_ATTEMPTS = 5
TEST_TIMEOUT = 20

# Output Configuration
OUTPUT_DIR = "outputs"
MUTANT_OUTPUT_FILE = "mutant_output.py"
TEST_OUTPUT_FILE = "test_output.py"

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