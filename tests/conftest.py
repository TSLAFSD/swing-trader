"""Make the repo root importable (config/, src/) regardless of pytest cwd."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
