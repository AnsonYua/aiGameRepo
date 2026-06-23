"""Scripted player（測試 / 離線 harness 專用，不是 AI 智慧路徑）。

依固定優先序從 legal_commands 選擇，讓 engine 測試可重現。
正式 AI vs AI 模擬請使用 LLM player。
"""

from __future__ import annotations


class ScriptedPlayer:
    """Deterministic test policy：攻擊 > 配對 > 部署 > 其他 > pass。"""

    def __init__(self, prefer_block=True):
        self.prefer_block = prefer_block

    def decide(self, game_id, player_id, prompt_payload):
        legal_commands = list(prompt_payload.get("legal_commands") or [])
        if not legal_commands:
            raise RuntimeError("scripted player got empty legal_commands")
        command = self._pick(legal_commands)
        return f"CONSIDER: 測試腳本依固定優先序選擇。\nCOMMAND: {command}"

    def _pick(self, legal_commands):
        choose_options = [cmd for cmd in legal_commands if cmd.startswith("choose ")]
        if choose_options:
            for preferred in ("choose go_first", "choose keep", "choose activate"):
                if preferred in choose_options:
                    return preferred
            return choose_options[0]

        for prefix in ("attack ", "pair ", "play_card ", "activate_effect"):
            for command in legal_commands:
                if command.startswith(prefix):
                    return command
        if self.prefer_block:
            for command in legal_commands:
                if command.startswith("block "):
                    return command
        return "pass" if "pass" in legal_commands else legal_commands[0]
