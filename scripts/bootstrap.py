#!/usr/bin/env python3
"""Stable host bootstrap dispatcher; the selected implementation is v1."""
from pathlib import Path
import subprocess
import sys

sys.dont_write_bytecode = True

if __name__ == "__main__":
    try:
        result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name("bootstrap-v1.py")), *sys.argv[1:]])
        raise SystemExit(result.returncode)
    except KeyboardInterrupt:
        print("bootstrap: interrupted", file=sys.stderr)
        raise SystemExit(130)
