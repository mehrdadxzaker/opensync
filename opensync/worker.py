"""Absolute-path timer entry point; does not rely on a working directory."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from opensync.cli import main
if __name__ == "__main__":
    raise SystemExit(main())
