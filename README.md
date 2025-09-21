# llm-mutation-guided-testing

A small testbench for LLM-driven mutant generation and automated test-case generation to kill mutants.

Reference: https://arxiv.org/pdf/2501.12862

## Description

This repository contains tooling to generate subtle mutants of a Python class using an LLM and then generate test cases that expose those mutants. The implementation in this directory follows the prompts and workflow described in the paper linked above.

## Prerequisites

- Python 3.8+
- A Gemini API key set in the environment as `GEMINI_API_KEY`
- Recommended packages (install via pip):
  - google-genai
  - python-dotenv

## Usage

Run the main script with the target module and its existing tests:

    python test_script.py user_service.py test_user_service.py

## Notes

- The code uses exact prompts from the referenced paper and writes outputs to `mutant_output.py` and `test_output.py` when a valid mutant and killing test are produced.
- Ensure the environment variable `GEMINI_API_KEY` is set before running.