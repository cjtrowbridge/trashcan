#!/usr/bin/env bash
set -euo pipefail

trap 'printf "%s\n" "benchmark: interrupted" >&2; exit 130' INT

if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' 'benchmark: python3 is unavailable. Install Python 3, then retry.' >&2
  exit 1
fi

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
benchmark="$script_dir/llm_benchmark/benchmark.py"
if [[ ! -f $benchmark ]]; then
  printf '%s\n' 'benchmark: llm_benchmark submodule is unavailable. Run git submodule update --init --recursive.' >&2
  exit 1
fi

printf '%s\n' 'benchmark: prerequisites ready; starting interactive Ollama benchmark'
exec python3 "$benchmark" "$@"
