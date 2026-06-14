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
        return lines[0] if lines else ""
