"""Run Skriveflyt from a terminal with: py -3 main.py"""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from app import main  # noqa: E402


if __name__ == "__main__":
    main()

