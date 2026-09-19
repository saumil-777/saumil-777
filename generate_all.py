#!/usr/bin/env python3
"""
generate_all.py — Run every generator in order and verify outputs.

Usage:
    python generate_all.py [photo_path]

    photo_path defaults to the value of the PHOTO env var, or the hard-coded
    path below.  Pass STATIC=1 to preview frozen frames.

Run this locally whenever you update your photo or the card content.
The GitHub Action only needs to run gen_heatmap.py (the only file that
changes daily).
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT       = Path(__file__).parent
SCRIPTS    = ROOT / "scripts"
PHOTO_DEFAULT = r"C:\Users\singh\Downloads\MY photo.pdf"


def run(cmd: list[str], env: dict | None = None) -> None:
    print(f"\n{'─' * 62}")
    print("$", " ".join(str(c) for c in cmd))
    print('─' * 62)
    merged = {**os.environ, **(env or {})}
    result = subprocess.run(cmd, cwd=ROOT, env=merged)
    if result.returncode != 0:
        print(f"\nFAILED (exit {result.returncode}): {cmd[0]}")
        sys.exit(result.returncode)


def main() -> None:
    photo = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PHOTO", PHOTO_DEFAULT)
    static_env = {"STATIC": os.environ.get("STATIC", "0")}

    py = sys.executable

    run([py, str(SCRIPTS / "gen_portrait.py"), photo, "ascii-portrait.svg"], env=static_env)
    run([py, str(SCRIPTS / "gen_card.py"),              "info-card.svg"],      env=static_env)
    run([py, str(SCRIPTS / "gen_heatmap.py"),           "contrib-heatmap.svg"],env=static_env)
    run([py, str(SCRIPTS / "gen_readme.py")])

    print(f"\n{'═' * 62}")
    print("✓  All files generated:")
    for f in ["ascii-portrait.svg", "info-card.svg", "contrib-heatmap.svg", "README.md"]:
        p = ROOT / f
        size = p.stat().st_size if p.exists() else 0
        print(f"   {f:<28}  {size:>8,} bytes")
    print('═' * 62)


if __name__ == "__main__":
    main()
