#!/usr/bin/env python3
"""Run the bundled OpenSync without pip installation or network access."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from opensync.cli import main
if __name__ == '__main__':
    raise SystemExit(main())
