"""Local environment loading for battle_app.

Vercel injects environment variables at runtime. This loader is only for local
development so running battle_app directly can use app-local defaults.
"""

from __future__ import annotations

import os
from pathlib import Path


BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT


def load_battle_app_env() -> None:
    """Load simple KEY=VALUE env files without overriding real env vars."""
    for path in (
        BATTLE_APP_ROOT / ".env.local",
        BATTLE_APP_ROOT / ".env",
        GCGV2_ROOT / ".env.local",
        GCGV2_ROOT / ".env",
    ):
        _load_env_file(path)


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
