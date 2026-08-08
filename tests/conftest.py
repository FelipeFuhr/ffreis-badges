"""Make scripts/*.py importable as plain modules from tests/.

scripts/ is not a package (no src/ layout, this repo ships standalone CLI
scripts) so tests import them directly by inserting scripts/ onto sys.path.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
