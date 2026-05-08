#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/.."
export PYTHONPATH="$PWD"
.venv/bin/python scripts/run_2560_analysis.py "$@"
