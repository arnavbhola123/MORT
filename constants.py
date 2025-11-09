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