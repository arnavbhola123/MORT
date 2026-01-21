# MORT - Mutation-Guided Oracle Refinement Testing

LLM-driven mutation testing and oracle inference for automated bug detection.

Reference: https://arxiv.org/pdf/2501.12862

## Overview

MORT provides two complementary workflows for code analysis:

- **Mutation Mode**: Generates mutants (code variants with injected bugs) and tests that kill them (tests pass on original code, fail on mutant)
- **Oracle Mode**: Analyzes original code to detect existing bugs via oracle inference (generates tests that fail on buggy original)

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
GOOGLE_API_KEY=your_key  # same as GEMINI_API_KEY
```

## Usage

MORT supports two usage modes: **Interactive** and **CLI**.

### Interactive Mode

Run without arguments to launch the interactive setup wizard:

```bash
python main.py
```

The wizard will prompt you for:
1. Repository root path
2. Code file path (relative or absolute)
3. Test file path (relative or absolute)
4. Chunking strategy (`llm` or `ast`)
5. Workflow mode (`mutation` or `oracle`)
6. Mode-specific options (workers, concern category)

### CLI Mode

Pass arguments directly for scripted/automated usage.

#### Mutation Mode

Generate mutants and tests that kill them:

```bash
python main.py [--mode mutation] <repo_path> <code_file> <test_file> [options]
```

Options:
- `--max-workers N` - Number of parallel workers (default: 3)
- `--chunker-mode {llm,ast}` - Code chunking strategy (default: llm)
- `--concern {privacy,security,correctness,performance}` - Bug category to focus on (default: privacy)

Example:

```bash
python main.py . src/validators.py tests/test_validators.py --max-workers 5 --concern security
```

#### Oracle Mode

Detect bugs in original code via oracle inference:

```bash
python main.py --mode oracle <repo_path> <code_file> <test_file> --concern <concern>
```

The `--concern` flag is **required** for oracle mode.

Example:

```bash
python main.py --mode oracle . src/user_service.py tests/test_user_service.py --concern privacy
```

### Concern Categories

| Concern | Description |
|---------|-------------|
| `privacy` | PII logging, sensitive data exposure, missing authorization, information leaks |
| `security` | SQL injection, XSS, authentication bypass, insecure data handling |
| `correctness` | Off-by-one errors, null pointer issues, logic errors, edge case failures |
| `performance` | Inefficient algorithms, memory leaks, N+1 queries, poor resource management |

### Chunking Strategies

| Strategy | Description |
|----------|-------------|
| `llm` | Uses LLM to intelligently identify logical code chunks |
| `ast` | Uses AST parsing to extract functions/classes as chunks |

## Output

- **Mutation Mode**: `outputs/<filename>/`
  - `mutant_<chunk>_<hash>.py` - Generated mutant files
  - `test_<chunk>_<hash>.py` - Tests that kill each mutant
  - `metadata.json` - Chunk info, scores, and file mappings

- **Oracle Mode**: `oracle_outputs/<filename>/`
  - `bug_report.txt` - Detailed bug analysis
  - `metadata.json` - Processing results and statistics
