"""Runtime LLM effect interpreter（對局中即時解讀）。

入口（runtime 呼叫）：

- ``interpret(card_id, timing, context)``：把卡牌文字翻譯成結構化 effect spec。
  - 主動使用（Command Resolver）：timing = MAIN / ACTION / ACTIVATE_MAIN
  - 觸發效果（Trigger Interpreter）：timing = ENTERS_PLAY / DESTROYED / ...

Guardrails：

1. 輸出必須通過 SpecGate（只能用 dictionary 詞彙）。
2. Gate 失敗 → 帶錯誤訊息 re-prompt 一次；再失敗 → InterpretationError。
3. 同一 (card_id, timing) 的 spec 在 process 內快取；
   局面相關部分（目標選擇、條件真假）由 Python 在執行期處理。
"""

from __future__ import annotations

import json
import re

from .spec_gate import SpecGate, SpecGateError, SUPPORTED_CONDITIONS


class InterpretationError(RuntimeError):
    """效果解讀失敗（interpretation problem）。"""


_SYSTEM_PROMPT_TEMPLATE = """你是 GCG 卡牌效果翻譯器。
你的唯一工作：把卡牌效果文字翻譯成結構化 effect spec（JSON）。

絕對規則：
- 只能使用下方 effect dictionary 定義的 primitives、timings、target filter 詞彙。
- 不可發明新 primitive、不可直接改寫遊戲狀態、不可猜測缺少的目標。
- 你只翻譯「指定 timing」對應的效果段落；其他段落忽略。
- 如果該 timing 沒有對應效果，輸出 status=unsupported 並在 unsupported_capabilities 說明。
- 如果效果需要玩家選目標，列在 target_requirements；步驟中以 "$<name>" 引用。
- 條件式效果用 primitive=conditional，condition.type 僅限：{conditions}。
- 只輸出一個 JSON object，不要 markdown、不要解釋文字。

輸出格式：
{{
  "status": "resolved" | "unresolved" | "unsupported",
  "source_card_id": "<card id>",
  "timing": "<指定 timing>",
  "optional": <bool>,                  // 效果是否「可以選擇不發動」
  "once_per_turn": <bool>,
  "cost": {{"resources": <int>, "rest_source": <bool>}},   // 僅啟動型能力需要
  "target_requirements": [
    {{"name": "t1", "controller": "self|opponent|any", "card_type": "unit|...",
      "status": "rested|active", "hp_lte": <int>, "level_lte": <int>, "count": 1}}
  ],
  "primitive_steps": [
    {{"primitive": "damage", "target": "$t1", "amount": 1}},
    {{"primitive": "conditional", "condition": {{"type": "pilot_trait_any", "traits": ["..."]}},
      "steps": [{{"primitive": "draw", "amount": 1}}]}}
  ],
  "unsupported_capabilities": [],
  "notes": ""
}}

step.target 可用值：
- "$<requirement name>"：玩家選出的目標
- "source"：效果來源卡（或其所在 Unit）
- "self_resource"：自己的 1 個資源（資源同質，毋須選擇）
- "self_shield_top"：自己最上面 1 面盾牌
- "self_all_unit" / "self_all_link_unit" / "opponent_all_unit"：範圍目標
- "self_base" / "opponent_base"
- draw / discard 類不需 target，預設作用於效果控制者

重要規則：card_type 永遠不要使用 "shield"。
效果「將盾牌加入手牌」必須使用 target="self_shield_top"，不能使用 target_requirements。

特殊 primitive 約定：
- conditionalTokenDeploy：用 "tokens" 欄位列出
  [{{"unit_count_lte": <int> 或 "unit_count_gte": <int>, "name": "<token名>", "ap": <int>, "hp": <int>}}]
- activate_ability：用 "ability": "main" 表示發動本卡的 [Main] 效果
- modifyAP / modifyHP 若為「本回合」效果，加 "duration": "this_turn"

=== EFFECT DICTIONARY ===
{dictionary}
"""


class EffectInterpreter:
    """Interface。實作：LlmEffectInterpreter（正式）、測試用 fake。"""

    def interpret(self, card, timing, context):
        raise NotImplementedError


class LlmEffectInterpreter(EffectInterpreter):
    def __init__(self, llm_client, dictionary, trace_writer=None, use_cache=True):
        self.llm_client = llm_client
        self.dictionary = dictionary
        self.spec_gate = SpecGate(dictionary)
        self.trace_writer = trace_writer
        self.use_cache = use_cache
        self._cache = {}
        self._system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            conditions=", ".join(sorted(SUPPORTED_CONDITIONS)),
            dictionary=dictionary.manifest_text(),
        )

    def interpret(self, card, timing, context=None):
        card_id = card["id"]
        cache_key = (card_id, timing)
        if self.use_cache and cache_key in self._cache:
            return self._cache[cache_key]

        user_prompt = self._build_user_prompt(card, timing, context or {})
        raw_reply = self.llm_client.chat(self._system_prompt, user_prompt, temperature=0.0)
        spec, gate_error = self._parse_and_gate(raw_reply, card_id, timing)

        if spec is None:
            # 帶著 gate 錯誤 re-prompt 一次（有上限，不是 retry 洗到過）
            retry_prompt = (
                f"{user_prompt}\n\n你上一次的輸出未通過 schema 驗證：\n{gate_error}\n"
                "請修正後重新輸出一個合法 JSON object。"
            )
            raw_reply_retry = self.llm_client.chat(self._system_prompt, retry_prompt, temperature=0.0)
            spec, gate_error = self._parse_and_gate(raw_reply_retry, card_id, timing)
            self._trace(card_id, timing, context, retry_prompt, raw_reply_retry, spec, gate_error)
            if spec is None:
                raise InterpretationError(
                    f"effect interpretation failed for {card_id}@{timing}: {gate_error}"
                )
        else:
            self._trace(card_id, timing, context, user_prompt, raw_reply, spec, None)

        if self.use_cache:
            self._cache[cache_key] = spec
        return spec

    # ------------------------------------------------------------------

    def _build_user_prompt(self, card, timing, context):
        payload = {
            "request": "interpret_card_effect",
            "timing": timing,
            "card": {
                "id": card.get("id"),
                "name": card.get("name"),
                "cardType": card.get("cardType"),
                "level": card.get("level"),
                "cost": card.get("cost"),
                "ap": card.get("ap"),
                "hp": card.get("hp"),
                "traits": card.get("traits"),
                "link": card.get("link"),
                "effect_text": card.get("effects", {}).get("description", []),
                "structured_rule_hints": card.get("effects", {}).get("rules", []),
            },
            "context": {
                "controller": context.get("controller"),
                "source_zone": context.get("source_zone"),
                "board_summary": context.get("board_summary"),
            },
            "instruction": (
                f"請只翻譯這張卡在 timing={timing} 時的效果。"
                "structured_rule_hints 僅供參考，最終以 effect_text 文字為準。"
            ),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _parse_and_gate(self, raw_reply, card_id, timing):
        try:
            spec = _extract_json_object(raw_reply)
        except ValueError as exc:
            return None, f"JSON 解析失敗：{exc}"
        if isinstance(spec, dict):
            spec.setdefault("source_card_id", card_id)
            spec.setdefault("timing", timing)
            spec.setdefault("target_requirements", [])
        try:
            return self.spec_gate.validate(spec), None
        except SpecGateError as exc:
            return None, str(exc)

    def _trace(self, card_id, timing, context, prompt, raw_reply, spec, gate_error):
        if self.trace_writer is None:
            return
        game_id = (context or {}).get("game_id")
        if game_id is None:
            return
        self.trace_writer.append_trace(
            game_id=game_id,
            player_id=(context or {}).get("controller"),
            request_type=f"effect_interpretation:{card_id}@{timing}",
            system_prompt="<effect interpreter system prompt>",
            prompt=prompt,
            raw_reply=raw_reply,
            normalized_reply=json.dumps(spec, ensure_ascii=False) if spec else f"GATE_ERROR: {gate_error}",
        )


def _extract_json_object(raw_text):
    text = raw_text.strip()
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("回覆中沒有 JSON object")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(str(exc)) from exc
