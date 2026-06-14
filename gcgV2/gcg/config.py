"""Central configuration for gcgV2.

所有路徑都可用環境變數覆寫，預設值對應本機 repo 佈局。
"""

from __future__ import annotations

import os
from pathlib import Path

GCGV2_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = GCGV2_ROOT.parent


def _path_from_env(env_key: str, default: Path) -> Path:
    raw = os.getenv(env_key)
    if raw:
        return Path(raw).expanduser()
    return default


def load_local_env() -> None:
    """Load simple KEY=VALUE pairs from gcgV2/.env when present."""
    for candidate in (Path.cwd() / ".env", GCGV2_ROOT / ".env"):
        if not candidate.exists():
            continue
        for raw_line in candidate.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))
        break


def card_data_root() -> Path:
    return _path_from_env("GCG_CARD_DATA_ROOT", REPO_ROOT / "card" / "data")


def deck_file() -> Path:
    return _path_from_env("GCG_DECK_FILE", REPO_ROOT / "card" / "gcgdecks.json")


def output_root() -> Path:
    return _path_from_env("GCG_V2_OUTPUT_ROOT", GCGV2_ROOT / "out")


def effect_dictionary_path() -> Path:
    return _path_from_env(
        "GCG_EFFECT_DICTIONARY_PATH",
        GCGV2_ROOT / "manifests" / "GCG_V2_EFFECT_DICTIONARY.yaml",
    )


def knowledge_root() -> Path:
    return _path_from_env("GCG_KNOWLEDGE_ROOT", GCGV2_ROOT / "knowledge")


def player_prompt_path() -> Path:
    return _path_from_env("GCG_PLAYER_PROMPT_PATH", knowledge_root() / "gcg-ai-player.md")


def experience_root() -> Path:
    return _path_from_env("GCG_EXPERIENCE_ROOT", knowledge_root() / "experience")


# --- LLM provider settings -------------------------------------------------

def llm_settings() -> dict:
    load_local_env()
    return {
        "api_key": os.getenv("GCG_DEEPSEEK_API_KEY", ""),
        "base_url": os.getenv("GCG_DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        "model": os.getenv("GCG_DEEPSEEK_MODEL", "deepseek-chat"),
        "timeout_seconds": int(os.getenv("GCG_AI_TIMEOUT_SECONDS", "60")),
    }


# --- Game constants --------------------------------------------------------

RESOURCE_DECK_SIZE = 10
SHIELD_COUNT = 6
OPENING_HAND_SIZE = 5
HAND_LIMIT = 10
EX_RESOURCE_CAP = 5
BATTLE_AREA_SLOTS = 6
