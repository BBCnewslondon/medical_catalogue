#!/usr/bin/env bash
set -euo pipefail

echo "=================================================="
echo " Running CCE Code Guidelines & Verification Suite"
echo "=================================================="

# 1. Ruff Linting
echo "--> 1. Running Ruff Lint..."
.venv/bin/ruff check .

# 2. Ruff Formatting Check
echo "--> 2. Running Ruff Format Check..."
.venv/bin/ruff format --check .

# 3. Mypy Static Type Checking
echo "--> 3. Running Mypy Static Type Checking..."
.venv/bin/mypy

# 4. Pytest & Coverage
echo "--> 4. Running Pytest Suite with Coverage..."
.venv/bin/pytest --cov=cce --cov-report=term-missing

echo "=================================================="
echo " All Code Guidelines & Tests Successfully Passed!"
echo "=================================================="

