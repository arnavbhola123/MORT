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

### Mutation Mode

Generate mutants and tests that kill them:
```bash
python main.py <repo_path> <code_file> <test_file>
```

Example:
```bash
python main.py . src/validators.py tests/test_validators.py --max-workers 3 --chunker-mode llm
```

### Oracle Mode

Detect bugs in original code via oracle inference:
```bash
python main.py --mode oracle <repo_path> <code_file> --concern <concern>
```

Example:
```bash
python main.py --mode oracle . src/user_service.py --concern privacy
```

Concerns: `privacy`, `security`, `correctness`, `performance`

Optionally provide test file for style reference:
```bash
python main.py --mode oracle . src/user_service.py tests/test_user_service.py --concern security
```

## Output

- **Mutation Mode**: `outputs/<filename>/` - generated mutants and tests
- **Oracle Mode**: `oracle_outputs/<filename>/` - bug reports and test files