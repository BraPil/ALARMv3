#!/usr/bin/env bash
# Usage: ./scripts/setup_env.sh
set -euo pipefail

echo "Creating virtualenv and installing project + ML extras..."
python3 -m venv .venv

echo "Activating virtualenv..."
source .venv/bin/activate

echo "Upgrading pip..."
pip install --upgrade pip

echo "Installing base dependencies..."
pip install sentence-transformers chromadb mlflow pytest

echo ""
echo "✓ Environment setup complete!"
echo "To activate the environment, run:"
echo "  source .venv/bin/activate"
