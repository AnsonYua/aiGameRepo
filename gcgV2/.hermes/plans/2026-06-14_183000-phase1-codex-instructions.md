# GCG Phase 1 Implementation — HermesPlayerClient

## Overview

Replace `AiPlayerClient` (DeepSeek) with `HermesPlayerClient` (Hermes Agent via `gcg-player` wrapper) in the GCG V2 simulator. Everything else stays the same.

## Files to Touch

| Action | File |
|--------|------|
| **Create** | `gcg/ai/hermes_player_client.py` |
| **Create** | `tests/test_hermes_player_client.py` |
| **Modify** | `gcg/sim/bootstrap.py` |
| **Modify** | `run_simulator.py` |

## Branch First

Before touching any files, create a dedicated branch:

```bash
cd /Users/hello/Desktop/cardAI/gcgV2
git checkout -b feat/hermes-player-client
```

All changes go into this branch. No direct commits to `main`.

## Rules

- Do NOT modify: `prompt_builder.py`, `player_client.py`, `llm_client.py`, `runtime.py`, `command_parser.py`, `action_enumerator.py`, `effect_engine.py`, `state_store.py`, `viewer.py`, `gamelog/*`, `effects/*`
- Do NOT use `shell=True`
- Do NOT use `--profile` flag (use `gcg-player` wrapper directly)

---

## File 1: Create `gcg/ai/hermes_player_client.py`

Complete code below. Paste into this path:
`/Users/hello/Desktop/cardAI/gcgV2/gcg/ai/hermes_player_client.py`

```python
"""Hermes Agent player client — subprocess calls to gcg-player wrapper.

Interface matches AiPlayerClient exactly:
    HermesPlayerClient.decide(game_id, player_id, prompt_payload) -> str
"""

from __future__ import annotations

import json
import logging
import subprocess

logger = logging.getLogger(__name__)

_PROMPT_SIZE_LIMIT = 100_000  # bytes safeguard for argv length


class HermesPlayerClient:
    """Calls gcg-player wrapper for each decision turn.

    Hermes sees only viewer_state + legal_commands from prompt_payload.
    It has zero tools, no memory, no file access.
    """

    def __init__(self, wrapper: str = "gcg-player", timeout: int = 60):
        self.wrapper = wrapper
        self.timeout = timeout

    def decide(self, game_id: str, player_id: str, prompt_payload: dict) -> str:
        """Return 'CONSIDER: ...\\nCOMMAND: ...' string from Hermes."""
        hermes_prompt = self._build_prompt(player_id, prompt_payload)

        prompt_bytes = len(hermes_prompt.encode("utf-8"))
        if prompt_bytes > _PROMPT_SIZE_LIMIT:
            raise RuntimeError(
                f"Hermes prompt too large for CLI adapter "
                f"({prompt_bytes} bytes > {_PROMPT_SIZE_LIMIT}); "
                "use gateway mode later."
            )

        argv = [
            self.wrapper,
            "chat", "-q", hermes_prompt,
            "-t", "none",
            "-s", "gcg-strategy",
            "--max-turns", "1",
            "--source", "gcg-player",
            "-Q",
        ]

        logger.info(
            "hermes_decision game=%s player=%s size=%d",
            game_id, player_id, prompt_bytes,
        )

        try:
            result = subprocess.run(
                argv,
                capture_output=True, text=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"Hermes player {player_id} timed out after {self.timeout}s"
            )
        except FileNotFoundError:
            raise RuntimeError(
                f"Hermes wrapper '{self.wrapper}' not found. "
                "Check PATH or install Hermes."
            )

        if result.returncode != 0:
            tail = (result.stderr or "")[:500]
            raise RuntimeError(
                f"Hermes player {player_id} exit code {result.returncode}: {tail}"
            )

        raw = (result.stdout or "").strip()
        if not raw:
            raise RuntimeError(f"Hermes player {player_id} returned empty output.")

        return self._normalize(raw)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(player_id: str, payload: dict) -> str:
        instruction = (
            f"你是 GCG 玩家 {player_id}。\n"
            "從下方的 `legal_commands` 清單中選一條指令。\n"
            "只輸出兩行：\n"
            "CONSIDER: <繁體中文、public-safe 短理由>\n"
            "COMMAND: <從 legal_commands 逐字複製的指令>\n"
        )
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        return f"{instruction}\n{body}"

    @staticmethod
    def _normalize(raw: str) -> str:
        """Keep only CONSIDER:/REASON:/COMMAND: lines."""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        structured = [
            line for line in lines
            if line.lower().startswith(("consider:", "reason:", "command:"))
        ]
        if any(line.lower().startswith("command:") for line in structured):
            return "\n".join(structured)
        # fallback — runner legal_commands check will catch invalids
        return lines[0] if lines else ""
```

---

## File 2: Create `tests/test_hermes_player_client.py`

Create at:
`/Users/hello/Desktop/cardAI/gcgV2/tests/test_hermes_player_client.py`

```python
"""Tests for HermesPlayerClient (mocked subprocess)."""

import pytest
from gcg.ai.hermes_player_client import HermesPlayerClient

MOCK_PAYLOAD = {
    "request_type": "gcg_main_decision",
    "player_id": "P1",
    "legal_commands": ["pass", "play_card st01/ST01-008 0"],
    "viewer_state": {"phase": "main"},
}


def test_decide_does_not_crash():
    """echo wrapper returns input as stdout — normalize extracts nothing
    structured, but the function shouldn't raise."""
    client = HermesPlayerClient(wrapper="echo")
    result = client.decide("g001", "P1", MOCK_PAYLOAD)
    assert isinstance(result, str)


def test_decide_raises_on_empty_output():
    client = HermesPlayerClient(wrapper="true")  # true → empty stdout
    with pytest.raises(RuntimeError, match="empty output"):
        client.decide("g001", "P1", MOCK_PAYLOAD)


def test_decide_timeout():
    client = HermesPlayerClient(wrapper="sleep", timeout=1)
    with pytest.raises(RuntimeError, match="timed out"):
        client.decide("g001", "P1", MOCK_PAYLOAD)


def test_decide_wrapper_not_found():
    client = HermesPlayerClient(wrapper="/nonexistent/xyz")
    with pytest.raises(RuntimeError, match="not found"):
        client.decide("g001", "P1", MOCK_PAYLOAD)
```

---

## File 3: Modify `gcg/sim/bootstrap.py`

Path: `/Users/hello/Desktop/cardAI/gcgV2/gcg/sim/bootstrap.py`

**Import addition** (after line 6, with other imports):

```python
from ..ai.hermes_player_client import HermesPlayerClient
```

**Logic addition** — in `build_simulator()`, add a new branch after the `players == "scripted"` block (around line 83):

```python
    elif players == "hermes":
        player_map = {
            "P1": HermesPlayerClient(timeout=60),
            "P2": HermesPlayerClient(timeout=60),
        }
```

Make sure the `elif` chain looks like:

```python
    if players == "llm":
        ...
    elif players == "scripted":
        ...
    elif players == "hermes":          # ← add this
        player_map = {
            "P1": HermesPlayerClient(timeout=60),
            "P2": HermesPlayerClient(timeout=60),
        }
    else:
        raise ValueError(f"unknown players mode: {players}")
```

---

## File 4: Modify `run_simulator.py`

Path: `/Users/hello/Desktop/cardAI/gcgV2/run_simulator.py`

Change the `--players` argument choices (line ~30):

```python
    parser.add_argument(
        "--players",
        choices=("llm", "scripted", "hermes"),   # add "hermes"
        default="llm",
    )
```

---

## Verification Order

Execute these steps **in order**. Stop and report if any step fails.

### Step 1: Compile check

```bash
cd /Users/hello/Desktop/cardAI/gcgV2
python3 -m py_compile gcg/ai/hermes_player_client.py
python3 -m py_compile gcg/sim/bootstrap.py
python3 -m py_compile run_simulator.py
```

### Step 2: Unit tests

```bash
python3 -m pytest tests/test_hermes_player_client.py -v
```

Expected: all 4 tests PASS.

### Step 3: Hermes CLI smoke test

```bash
gcg-player chat -q '只輸出兩行：CONSIDER: 測試。 COMMAND: pass' \
  -Q -t none -s gcg-strategy --max-turns 1 --source gcg-player
```

Expected output (exact format):
```
CONSIDER: 測試。
COMMAND: pass
```

If this fails → API key is not configured. Run:
```bash
export OPENROUTER_API_KEY="sk-or-..."
gcg-player config set model.provider openrouter
gcg-player config set model.default deepseek/deepseek-chat
```
Then retry.

### Step 4: Regression — scripted game still works

```bash
python3 run_simulator.py --players scripted --interpreter reference --seed 42
```

Expected: game finishes with status `finished` (printed as JSON).

### Step 5: Hermes player + reference interpreter

```bash
python3 run_simulator.py --players hermes --interpreter reference --seed 42
```

Expected: game runs. Hermes makes decisions each turn. Check `out/game_*/` for artifact files.

### Step 6: Hermes player + LLM interpreter (optional, needs API key)

```bash
python3 run_simulator.py --players hermes --interpreter llm --seed 42
```

---

## Design Constraints (don't violate)

1. **No shell=True** — use list-form argv with `subprocess.run()`
2. **No `--profile` flag** — call `gcg-player` directly (it's already the profile wrapper)
3. **Memory is off** — `config.yaml` already sets `memory.memory_enabled: false`
4. **Zero tools** — `-t none` in every invocation
5. **Hermes never sees raw state** — only the JSON prompt_payload from PromptBuilder
6. **Don't touch these files**: `player_client.py`, `llm_client.py`, `prompt_builder.py`, `runtime.py`, `command_parser.py`, `action_enumerator.py`, `effect_engine.py`, `state_store.py`, `viewer.py`, `gamelog/*`, `effects/*`
