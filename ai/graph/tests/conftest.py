import sys
from pathlib import Path

# Always test this repository's eduagent_kg, even if another copy is installed.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
