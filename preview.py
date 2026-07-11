#!/usr/bin/env python3
"""Dev-only helper: build with sample data, then copy the dark dashboard to
preview.svg so it can be rasterized locally (e.g. `qlmanage -t preview.svg`)."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
subprocess.run([sys.executable, "update.py", "--sample"], cwd=ROOT, check=True)
shutil.copy(ROOT / "assets" / "dashboard-dark.svg", ROOT / "preview.svg")
print("wrote preview.svg (copy of dashboard-dark.svg)")
