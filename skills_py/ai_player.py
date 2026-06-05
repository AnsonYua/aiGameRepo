import subprocess
from pathlib import Path
from typing import Optional

from .game_engine import save_state
from .game_state import GameState
from .gcg_display import render


PROJECT_ROOT = Path(__file__).parent.parent.absolute()


def _state_path(state: GameState) -> Path:
    return PROJECT_ROOT / "game-states" / state.game_id / "gameState.md"


def ai_decide_command(state: GameState, player_id: str, allowed: Optional[set[str]] = None) -> str:
    save_state(state)
    display_text = render(str(_state_path(state)), viewer=player_id)
    prompt = "\n".join([
        f"player_id: {player_id}",
        f"first_player: {state.first_player}",
        "",
        display_text,
    ])

    try:
        completed = subprocess.run(
            ["opencode", "run", "--agent", "gcg-ai-player", prompt],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("找不到 opencode，無法呼叫 gcg-ai-player 決策。") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("gcg-ai-player 決策逾時。") from exc

    if completed.returncode != 0:
        reason = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        raise RuntimeError(f"gcg-ai-player 決策失敗：{reason}")

    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("gcg-ai-player 沒有回傳指令。")

    cmd = lines[-1]
    action = cmd.split(maxsplit=1)[0].lower()
    if allowed and action not in allowed:
        raise RuntimeError(f"gcg-ai-player 回傳非法指令：{cmd}")
    return cmd
