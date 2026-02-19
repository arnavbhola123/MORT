# MORT — Mutation-Guided Oracle Refinement Testing

## Project Overview

MORT is an LLM-driven mutation testing and oracle inference framework for automated bug detection. It extends traditional mutation testing by using large language models to generate semantically meaningful mutants targeted at specific concern categories, synthesize tests that kill those mutants, and infer test oracles to detect bugs in original code.

### Core Workflows

- **Mutation Mode** — Generates code mutants (variants with injected bugs) and tests that kill them. A generated test must pass on the original code and fail on the mutant.
- **Oracle Mode** — Analyzes original code to detect existing bugs via oracle inference. Generates multiple mutants, infers what correct behavior should be, then synthesizes tests that fail on buggy original code.

### Concern Categories

Mutations and oracles are targeted at specific fault categories:

| Concern | Description |
|---------|-------------|
| `privacy` | PII logging, sensitive data exposure, missing authorization, information leaks |
| `security` | SQL injection, XSS, authentication bypass, insecure data handling |
| `correctness` | Off-by-one errors, null pointer issues, logic errors, edge case failures |
| `performance` | Inefficient algorithms, memory leaks, N+1 queries, poor resource management |

Each concern has a context description and a real-world bug example (in `constants.py`) that guides LLM mutation generation toward realistic bugs.

---

## Architecture & Design

### System Architecture

```
                           main.py (entry point)
                               │
                               ▼
                         MORTWorkflow                    (src/mort_workflow.py)
                      ┌────────┴────────┐                Unified facade
                      ▼                 ▼
            MutationOrchestrator   OracleOrchestrator
            (mutation mode)        (oracle mode)
                      │                 │
                      ▼                 ▼
            ParallelProcessor      OraclePipeline        (8-step process)
                      │            ┌────┴────┐
                      ▼            │         │
            MutationPipeline    LLMClient  OracleValidator
            (7-step process)       │
            ┌─────┼──────┐        │
            ▼     ▼      ▼        │
    LLMOrchestrator CodeValidator  │
            │       │              │
            ▼       ▼              ▼
         LLMClient  RepoManager   PromptTemplates
```

### Shared Components (`src/shared/`)

| Component | File | Purpose |
|-----------|------|---------|
| `LLMClient` | `llm_client.py` | LangChain wrapper — `invoke()`, `extract_code_from_response()`, `extract_json_from_response()` |
| `CodeChunker` | `chunker.py` | Splits code into logical chunks via LLM or AST. Results cached by MD5 hash in `.chunk_cache/` |
| `CodeValidator` | `validators.py` | Syntactic identity check, syntax validation, test execution (pytest/unittest auto-detected) |
| `RepoManager` | `repo_manager.py` | Two-tier repo copying: master copy (cached, deps installed) → worker copies (per-thread isolation) |

### Repository Isolation Strategy

Tests run in full project context with real dependencies:

```
.temp_testing/
├── {repo}_master_{hash}/     # Created once, deps installed, reused
│   ├── .venv_testing/        # Virtual environment with pip-installed deps
│   └── <full repo copy>
└── {repo}_worker_{id}/       # Fast copy from master, per thread
    └── <repo copy with mutations injected>
```

### Technology Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.12+ |
| LLM framework | LangChain (`init_chat_model`) |
| Default model | `gemini-2.5-flash` via `google_genai` provider |
| Supported providers | Google GenAI, OpenAI, Anthropic |
| Code analysis | Python `ast` module, regex |
| Test frameworks | pytest, unittest (auto-detected) |
| Parallelization | `ThreadPoolExecutor` |
| Configuration | `python-dotenv`, `constants.py` |

---

## Repository Structure

```
MORT/
├── main.py                          # Entry point: interactive wizard + CLI argument parsing
├── constants.py                     # Global config: model, output dirs, concern categories, examples
├── requirements.txt                 # Python dependencies (57 packages)
├── .env.example                     # Template for API key configuration
├── .env                             # API keys (gitignored)
├── README.md                        # Project documentation
│
├── src/                             # Core application
│   ├── mort_workflow.py             # Unified facade for mutation/oracle workflows
│   │
│   ├── mutation/                    # Mutation testing workflow
│   │   ├── mutation_orchestrator.py # High-level orchestration, parallel dispatch, dedup
│   │   ├── mutation_pipeline.py     # 7-step per-chunk mutation process
│   │   ├── llm_orchestrator.py      # LLM calls: mutant gen, equiv check, test gen, scoring
│   │   ├── parallel_processor.py    # ThreadPoolExecutor wrapper, worker copy management
│   │   └── stitcher.py             # Reconstructs full file from chunks + mutated chunk
│   │
│   ├── oracle/                      # Oracle inference workflow
│   │   ├── oracle_orchestrator.py   # High-level oracle orchestration, bug report generation
│   │   ├── oracle_pipeline.py       # 8-step per-function oracle process
│   │   └── oracle_validator.py      # File-based human-in-the-loop oracle validation
│   │
│   ├── shared/                      # Shared utilities
│   │   ├── llm_client.py           # LangChain LLM wrapper (multi-provider)
│   │   ├── chunker.py              # Code chunking (LLM-based or AST-based)
│   │   ├── validators.py           # Syntax checks, test execution, framework detection
│   │   └── repo_manager.py         # Repository copying, venv creation, dep installation
│   │
│   └── neo4j_script.py             # Knowledge graph indexing (experimental, `knowledge-graph` branch)
│
├── prompts/                         # LLM prompt templates
│   └── templates.py                # All prompts: mutation, equivalence, test gen, judge, oracle
│
├── example_test_code/               # Example test subjects
│   ├── simple_example.py           # UserValidator class
│   ├── simple_example_test.py      # Tests for UserValidator
│   ├── new_example.py              # User storage system (signup, auth)
│   └── new_example_tests.py        # Tests for user storage
│
├── outputs/                         # Mutation mode outputs (gitignored except .keep)
│   └── <filename>/<concern>/
│       ├── mutant_<chunk>_<hash>.py
│       ├── test_<chunk>_<hash>.py
│       └── metadata.json
│
├── oracle_outputs/                  # Oracle mode outputs (gitignored except .keep)
│   ├── <filename>/
│   │   ├── bug_report.txt
│   │   └── metadata.json
│   └── temp/                       # Temporary oracle files for human review
│
├── test_data/                       # Evaluation data and analysis
│   ├── validation.json             # Full validation results
│   ├── validation_analysis.csv     # Scoring analysis for evaluated functions
│   ├── oracle_analysis.csv         # Oracle evaluation results
│   └── metadata_analysis.csv       # Metadata statistics
│
├── .chunk_cache/                    # Cached LLM chunking results (by content hash)
└── .temp_testing/                   # Temporary repo copies (auto-cleaned on startup)
```

---

## Usage Guide

### Interactive Mode

```bash
python main.py
```

Prompts for: repository path, code file, test file, chunking strategy, workflow mode, and mode-specific options.

### CLI Mode

#### Mutation Mode

Generate mutants and tests that kill them:

```bash
python main.py [--mode mutation] <repo_path> <code_file> <test_file> [options]
```

| Argument | Description |
|----------|-------------|
| `repo_path` | Repository root directory |
| `code_file` | Path to Python source file to mutate |
| `test_file` | Path to existing test file |
| `--mode` | `mutation` (default) or `oracle` |
| `--max-workers N` | Parallel workers (default: 3) |
| `--chunker-mode` | `llm` (default) or `ast` |
| `--concern` | `privacy` (default), `security`, `correctness`, `performance` |

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

### Chunking Strategies

| Strategy | Description | Best For |
|----------|-------------|----------|
| `llm` | LLM identifies logical code chunks with context awareness | Complex files with interleaved logic |
| `ast` | Python AST parser extracts functions/classes deterministically | Fast, reproducible chunking |

### Output Structure

**Mutation mode** → `outputs/<filename>/<concern>/`:
- `mutant_<chunk_id>_<hash>.py` — Full file with mutated chunk
- `test_<chunk_id>_<hash>.py` — Test that kills the mutant
- `metadata.json` — Chunk info, quality scores, file mappings

**Oracle mode** → `oracle_outputs/<filename>/`:
- `bug_report.txt` — Human-readable bug analysis
- `metadata.json` — Processing results and statistics

---

## Development Workflow

### Adding a New Concern Category

1. Add the concern key to `CONCERN_CONTEXTS` in `constants.py` with a description
2. Add a real-world bug example to `CONCERN_DIFFS` in `constants.py`
3. The prompts in `prompts/templates.py` automatically incorporate the concern context and diff example

### Modifying Prompt Strategies

All prompts are in `prompts/templates.py` as `@staticmethod` methods on the `PromptTemplates` class:

| Method | Purpose |
|--------|---------|
| `make_fault_for_chunk()` | Mutation generation prompt |
| `equivalence_detector()` | Semantic equivalence check (binary yes/no) |
| `make_test_to_catch_fault()` | Test generation to kill a specific mutant |
| `llm_judge_mutant()` | 5-dimension quality scoring with calibration examples |
| `generate_multiple_mutants()` | Batch mutant generation for oracle mode |
| `generate_oracle_inference()` | Oracle specification from mutant analysis |
| `generate_test_from_oracle()` | Test generation from oracle spec |

### Extending the Mutation Pipeline

The 7-step pipeline is in `src/mutation/mutation_pipeline.py` (`MutationPipeline.process_chunk()`). Each step is clearly labeled and can be modified independently. LLM interactions are delegated to `src/mutation/llm_orchestrator.py`.

### Extending the Oracle Pipeline

The 8-step pipeline is in `src/oracle/oracle_pipeline.py` (`OraclePipeline.process_chunk()`). Individual steps are also available as separate methods for flexibility.

### Adding a New Chunking Strategy

1. Add the strategy to `CodeChunker` in `src/shared/chunker.py`
2. Implement an `_extract_chunks_<strategy>()` method
3. Return the same dictionary format: `{"chunks": [...], "full_code": str, "file_path": str}`

### Project Conventions

- Thread-safe printing via `_thread_safe_print()` callback
- Dependency injection: components receive their dependencies via constructor
- Chunking results are cached by content MD5 hash in `.chunk_cache/`
- Temp directories auto-cleaned on startup in `main.py`
- Mutant code delimited with `# MUTANT START` / `# MUTANT END` comments

---

## Evaluation & Metrics

### LLM-as-Judge Scoring (Mutation Mode)

Each generated mutant+test pair is evaluated on 5 dimensions (0-10 scale):

| Dimension | What It Measures |
|-----------|-----------------|
| **Concern Alignment** | How well the mutation matches the target violation pattern |
| **Business Logic Impact** | Real-world significance of the introduced bug |
| **Mutation Subtlety** | Whether existing tests would miss the bug |
| **Test Effectiveness** | How precisely the generated test catches the mutant |
| **Test Integration** | How well the test fits the existing test suite style |

Scoring guidelines (from `prompts/templates.py`):
- 0-2: Serious problems / completely wrong
- 3-4: Related but poor quality
- 5-6: Decent but imperfect
- 7-8: Good quality with minor issues
- 9-10: Exceptional (should be rare)

### Oracle Mode Metrics

Per-function results tracked in `metadata.json`:
- `mutants_generated` — Total mutants created (target: 10)
- `valid_mutants` — Mutants passing all filters (max: 5)
- `bugs_detected` — Whether oracle-based test found bugs in original code

### Output Metadata Format

`metadata.json` (mutation mode):
```json
{
  "code_file": "path/to/code.py",
  "total_chunks": 5,
  "mutants": [
    {
      "hash": "abc123...",
      "chunk_id": "function_name",
      "chunk_type": "function",
      "files": { "mutant": "mutant_...", "test": "test_..." },
      "scores": {
        "concern_alignment": 8,
        "business_logic_impact": 7,
        "mutation_subtlety": 9,
        "test_effectiveness": 8,
        "test_integration": 7
      }
    }
  ]
}
```

---

## Key Technical Details

### Mutation Pipeline (7 Steps)

Located in `src/mutation/mutation_pipeline.py`:

1. **Generate mutant** — LLM creates a mutated version of the chunk with a subtle bug matching the concern
2. **Syntactic identity check** — Discard if mutated code is textually identical to original
3. **Validate mutant** — Run existing tests on mutant; must build and pass (mutation should be subtle)
4. **Equivalence detection** — LLM checks if mutant is semantically equivalent; discard if yes
5. **Generate killing test** — LLM creates a test that passes on original, fails on mutant
6. **Validate test** — Confirm test passes on original AND fails on mutant (both directions verified)
7. **LLM-as-judge** — Score the mutant+test pair on 5 quality dimensions

### Oracle Pipeline (8 Steps)

Located in `src/oracle/oracle_pipeline.py`:

1. **Generate mutants** — LLM creates 10 mutants for a single function
2. **Remove syntactic duplicates** — Filter identical mutations
3. **Validate syntax** — AST parse check
4. **Equivalence detection** — LLM-based semantic comparison
5. **Generate oracle** — LLM analyzes valid mutants to infer invariants, safety properties, I/O relationships
6. **Human validation** — Oracle saved to file for user review/editing (human-in-the-loop)
7. **Generate test from oracle** — LLM extends existing test file with oracle-based assertions
8. **Bug detection** — Run oracle test on original code; failures indicate real bugs

### Equivalence Detection

Uses exact prompt from the research paper (Table 1). Binary LLM response: the two code versions "always do exactly the same thing" → equivalent (discard) or "not equivalent" with explanation → proceed.

### Human-in-the-Loop (Oracle Mode)

In Step 6 of the oracle pipeline:
1. Oracle specification is saved to `oracle_outputs/temp/{chunk_id}_oracle.txt`
2. User can review and optionally create `{chunk_id}_oracle_validated.txt` with edits
3. System loads validated version if it exists, otherwise uses the original

### Test Framework Detection

`CodeValidator` auto-detects the test framework by examining the test file for patterns:
- `import pytest`, `@pytest.` → pytest
- `class TestCase`, `unittest` → unittest
- Defaults to pytest if unclear

---

## Troubleshooting

### Common Issues

**API key errors:**
- Ensure both `GEMINI_API_KEY` and `GOOGLE_API_KEY` are set in `.env`
- For OpenAI/Anthropic, set corresponding keys and update `MODEL`/`MODEL_PROVIDER` in `constants.py`

**Test execution failures:**
- The target repository must have a `requirements.txt` for `RepoManager` to install dependencies
- Ensure the code file and test file paths are correct relative to the repository root
- Check that the target project's tests pass independently before running MORT

**Chunking issues:**
- If LLM chunking produces poor results, try `--chunker-mode ast` for deterministic function extraction
- LLM chunks are cached in `.chunk_cache/`; delete the cache to force re-chunking

**Temp directory issues:**
- `.temp_testing/` is auto-cleaned on startup
- If a run is interrupted, stale directories may remain; delete `.temp_testing/` manually