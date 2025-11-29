# MORT - Mutation-Guided Oracle Refinement Testing

LLM-driven mutation testing and oracle inference for automated bug detection.

Reference: https://arxiv.org/pdf/2501.12862

## Overview

MORT provides two complementary workflows for code analysis:

**Mutation Mode**: Generate mutants and tests that kill them (tests pass on original, fail on mutant)
**Oracle Mode**: Generate oracle specifications to detect bugs in original code (tests fail on buggy original)

## Setup

1. Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate  # macOS/Linux
```

2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Configure API keys in `.env`:

```
GEMINI_API_KEY=your_key
GOOGLE_API_KEY=your_key
```

## Usage

Assume the file structure is as follows:

```
.
|  .gitignore
|  requirements.txt
|  README.md
├── src
│   ├── code.py
│   └── code2.py
│
└── tests
    └── test.py
```

### Mutation Mode

Generate mutants and tests that kill them:

```bash
# Code file and test file should be relative to the repo path you already specified
python main.py <repo_path> <code_file> <test_file>
```

Example:

```bash
python main.py . src/code.py tests/test.py --max-workers 3 --chunker-mode llm
```

### Oracle Mode

Detect bugs in original code via oracle inference:

```bash
# Code file and test file should be relative to the repo path you already specified
python main.py --mode oracle <repo_path> <code_file> <test_file> --concern <concern>
```

Concerns: `privacy`, `security`, `correctness`, `performance`

Example:

```bash
python main.py --mode oracle . src/code.py tests/test.py --concern privacy
```

## Output

- **Mutation Mode**: `outputs/<filename>/` - generated mutants and tests
- **Oracle Mode**: `oracle_outputs/<filename>/` - bug reports and test files
