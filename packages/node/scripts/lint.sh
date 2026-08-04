#!/bin/bash
set -e

# Change directory to the repository root
cd "$(dirname "$0")/.."

echo "=== Running Ruff Check ==="
ruff check .

echo "=== Running Ruff Format Check ==="
ruff format --check .

echo "=== Running MyPy Static Type Check ==="
mypy src

echo "=== Linting & Type Checking Passed Successfully ==="
