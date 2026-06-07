import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import ai_adapters
from .card_db import get_card_name
from .game_engine import save_state
from .game_state import GameState
from .gcg_display import render


PROJECT_ROOT = Path(__file__).parent.parent.absolute()


@dataclass
class AIDecision:
    command: str
    consideration: str = ""
    raw_output: str = ""
    elapsed_seconds: float = 0.0
    provider: str = ""


def _state_path(state: GameState) -> Path:
    return PROJECT_ROOT / "game-states" / state.game_id / "gameState.md"


def _parse_ai_output(output: str) -> AIDecision:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    command = ""
    consideration = ""
    for line in lines:
        lower = line.lower()
        if lower.startswith("consider:") or line.startswith("考量：") or line.startswith("考量:"):
            consideration = line.split(":", 1)[1].strip() if ":" in line else line.split("：", 1)[1].strip()
        elif lower.startswith("command:") or line.startswith("指令：") or line.startswith("指令:"):
            command = line.split(":", 1)[1].strip() if ":" in line else line.split("：", 1)[1].strip()
    if not command and lines:
        command = lines[-1]
    if not command:
        raise RuntimeError("AI provider 沒有回傳指令。")
    return AIDecision(command=_clean_command(command), consideration=consideration, raw_output=output)


def _clean_command(command: str) -> str:
    cleaned = command.strip()
    for separator in (" — ", " – ", "—", "–"):
        if separator in cleaned:
            cleaned = cleaned.split(separator, 1)[0].strip()
    return cleaned


def _action_name(command: str) -> str:
    return command.split(maxsplit=1)[0].lower() if command.strip() else ""


def _timeout_seconds() -> float:
    raw = os.environ.get("GCG_AI_TIMEOUT_SECONDS", "60")
    try:
        timeout = float(raw)
    except ValueError:
        timeout = 60.0
    return max(1.0, timeout)


def _public_safe_consideration(state: GameState, player_id: str, text: str) -> str:
    if not text:
        return ""
    if state.phase == "pre-game" or any(term in text for term in ("手牌", "hand", "曲線")):
        return "依調度階段的隱藏資訊評估後選擇此指令，細節不寫入公開 replay。"
    player = state.get_player(player_id)
    hidden_terms = set(player.hand_cards + player.shield_cards + player.deck_cards)
    for card_id in player.hand_cards:
        name = get_card_name(card_id)
        if name:
            hidden_terms.add(name)
    if any(term and term in text for term in hidden_terms):
        return "依公開場面、防禦層與優先權評估後選擇此指令。"
    return text


def ai_decide(state: GameState, player_id: str, allowed: Optional[set[str]] = None) -> AIDecision:
    save_state(state, set_active=False)
    display_text = render(str(_state_path(state)), viewer=player_id)
    legal_hint = ", ".join(sorted(allowed)) if allowed else "依目前顯示的可行指令"
    base_prompt = "\n".join([
        f"game_id: {state.game_id}",
        f"player_id: {player_id}",
        f"first_player: {state.first_player}",
        f"legal_actions: {legal_hint}",
        "",
        display_text,
    ])

    last_decision: Optional[AIDecision] = None
    timeout_seconds = _timeout_seconds()
    adapter = ai_adapters.get_ai_adapter()
    # One contract-repair reprompt is allowed when the provider returns an
    # action outside the runtime-provided allowed set. This is not a strategy
    # fallback; runtime legality still decides whether COMMAND applies.
    for attempt in range(2):
        prompt = base_prompt
        if attempt and last_decision:
            prompt = "\n".join([
                base_prompt,
                "",
                f"上一個 COMMAND 不合法：{last_decision.command}",
                f"請重新輸出，COMMAND 第一個字必須是：{legal_hint}",
            ])
        try:
            completed = adapter.run(prompt, timeout_seconds)
        except TimeoutError as exc:
            raise RuntimeError(f"{adapter.provider} AI 決策逾時（timeout={timeout_seconds:g}s）。") from exc

        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip() or f"exit code {completed.returncode}"
            raise RuntimeError(f"{completed.provider or adapter.provider} AI provider 執行失敗：{detail}")

        decision = _parse_ai_output(completed.stdout)
        decision.elapsed_seconds = completed.elapsed_seconds
        decision.provider = completed.provider or adapter.provider
        action = _action_name(decision.command)
        if allowed and action not in allowed:
            last_decision = decision
            continue
        decision.consideration = _public_safe_consideration(state, player_id, decision.consideration)
        return decision
    raise RuntimeError(f"{adapter.provider} AI provider 回傳不允許的指令：{last_decision.command if last_decision else ''}；允許：{legal_hint}")


def ai_decide_command(state: GameState, player_id: str, allowed: Optional[set[str]] = None) -> str:
    return ai_decide(state, player_id, allowed).command
