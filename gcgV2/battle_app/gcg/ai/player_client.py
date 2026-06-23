"""LLM AI player client.

責任：per-player isolated session、prompt 傳送、輸出正規化、trace 記錄。
不驗證策略、不改 state；合法性由 runtime 把關。
"""

from __future__ import annotations

import json
import os

from .. import config
from .llm_client import LlmClient


def _default_system_prompt(player_id):
    return (
        f"你是 GCG 對戰玩家 {player_id}。\n"
        "你只能根據 public-safe viewer state 做決策。\n"
        "你必須從 user prompt 的 `legal_commands` 清單中逐字複製 1 條指令。\n"
        "請只輸出兩行：\n"
        "CONSIDER: <公開安全的短理由>\n"
        "COMMAND: <從 legal_commands 逐字複製的指令>\n"
        "CONSIDER 必須使用繁體中文，只能描述公開安全的局勢、節奏、攻防或交換考量，\n"
        "不得提到對手隱藏手牌、牌庫內容、盾牌內容或推理鏈。\n"
        "不要輸出 JSON、不要輸出 markdown 區塊、不要輸出多餘段落。\n"
        "\n"
        "決策前依以下順序檢查：\n"
        "1. 斬殺：對手盾牌為 0 且基地不存在 → `attack ... opponent_base` 直擊玩家立即獲勝。\n"
        "2. 防斬殺：己方盾牌 0 且基地不存在，且對手有 active 攻擊者 → 優先部署或保留 Blocker。\n"
        "3. 進攻優先序：攻擊對手防禦層 > 擊殺 rested 威脅 > 清 Blocker > 部署場面。\n"
        "4. 防守優先序：重建基地 > 部署 Blocker > 移除/橫置威脅單位。\n"
        "5. `attack_annotations` 欄位有每個攻擊的計算結果預覽，先看再選。"
    )


class AiPlayerClient:
    def __init__(self, llm_client=None, ai_trace_writer=None, prompt_path=None, temperature=0.2):
        self.llm_client = llm_client or LlmClient()
        self.ai_trace_writer = ai_trace_writer
        self.temperature = temperature
        self.prompt_path = prompt_path or os.getenv("GCG_PLAYER_PROMPT_PATH")
        self._sessions = {}

    def ensure_player_session(self, game_id, player_id):
        key = (game_id, player_id)
        if key in self._sessions:
            return self._sessions[key]
        system_prompt = _default_system_prompt(player_id)
        if self.prompt_path and os.path.exists(self.prompt_path):
            with open(self.prompt_path, "r", encoding="utf-8") as handle:
                system_prompt = f"{system_prompt}\n\n{handle.read().strip()}"
        session = {"system_prompt": system_prompt, "player_id": player_id, "game_id": game_id}
        self._sessions[key] = session
        return session

    def decide(self, game_id, player_id, prompt_payload):
        """傳入 PromptBuilder 的 payload，回傳正規化後的指令文字。"""
        session = self.ensure_player_session(game_id, player_id)
        user_prompt = json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        raw_reply = self.llm_client.chat(
            session["system_prompt"], user_prompt, temperature=self.temperature,
        )
        normalized = self._normalize_command(raw_reply)
        if self.ai_trace_writer is not None:
            self.ai_trace_writer.append_trace(
                game_id=game_id,
                player_id=player_id,
                request_type=prompt_payload.get("request_type"),
                system_prompt=session["system_prompt"],
                prompt=prompt_payload,
                raw_reply=raw_reply,
                normalized_reply=normalized,
            )
        return normalized

    def _normalize_command(self, raw_text):
        if not isinstance(raw_text, str) or not raw_text.strip():
            raise RuntimeError("AI provider returned empty command text.")
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        structured = [
            line for line in lines
            if line.lower().startswith(("consider:", "reason:", "command:"))
        ]
        if any(line.lower().startswith("command:") for line in structured):
            return "\n".join(structured)
        return lines[0]
