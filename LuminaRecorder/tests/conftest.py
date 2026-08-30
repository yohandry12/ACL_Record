"""Configuration pytest : rend src/ importable comme le fait main.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))
