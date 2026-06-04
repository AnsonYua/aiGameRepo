#!/usr/bin/env python3
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.absolute()
TOTAL_GAMES = 10

for i in range(1, TOTAL_GAMES + 1):
    print(f"\n{'='*60}")
    print(f"  Game {i} / {TOTAL_GAMES}")
    print(f"{'='*60}")
    result = subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "gcg_simulation.py"), "--p1", "ai", "--p2", "ai"],
        cwd=str(PROJECT_ROOT),
        timeout=900,
    )
    if result.returncode != 0:
        print(f"  Game {i} exited with code {result.returncode}")

print(f"\nDone. {TOTAL_GAMES} games completed.")
print(f"Replays saved in: {PROJECT_ROOT / 'replays'}")
