# llm-mutation-guided-testing

LLM-driven mutant generation and automated test-case generation to kill mutants.

Reference: https://arxiv.org/pdf/2501.12862

## Description

This repository contains tooling to generate subtle mutants of a Python class using an LLM and then generate test cases that expose those mutants.

## Prerequisites

- Python 3.8+
- Environment with `GEMINI_API_KEY` and `GOOGLE_API_KEY` configured

## Setup

Create and activate a virtual environment, then install the required packages:

    python -m venv .venv
    source .venv/bin/activate  # macOS/Linux
    .\.venv\Scripts\activate  # Windows (PowerShell)

Install the dependencies:

    pip install -r requirements.txt

## Usage


Run the main script with the target module and its existing tests:

Example usage:
    python main.py examples/user_service.py examples/test_user_service.py