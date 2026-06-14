"""Decision prompt 組裝。

把 viewer state、合法指令清單（Python 枚舉）、卡牌效果文字、規則摘錄與
lessons 組成單一 JSON prompt payload。這層不做合法性判斷、不做策略決定。
"""

from __future__ import annotations

import json
import re

from .lessons import load_experience_summaries, match_summaries, select_summaries

_CARD_ID_PATTERN = re.compile(r"\b(?:st\d+/)?(?:[A-Z]{2}\d{2}-\d{3}|T-\d{3})\b")
_ATTACK_COMMAND_PATTERN = re.compile(r"^attack my_slot_(\d+) (?:opponent_base|opponent_slot_(\d+))$")
_BLOCK_COMMAND_PATTERN = re.compile(r"^block my_slot_(\d+)$")
_PAIR_COMMAND_PATTERN = re.compile(r"^pair (\S+) my_slot_(\d+)$")


_BASE_INSTRUCTIONS = [
    "你必須從 `legal_commands` 清單中逐字複製 1 條作為 `COMMAND:`，不可自行發明指令、card_id、slot 或 target。若想用的指令不在清單中，代表當前規則下無法執行（例如單位剛部署、資源不足、目標不合法等）——不要假設、不要拼湊、不要自己發明。",
    "請只輸出兩行：第一行 `CONSIDER: <公開安全的短理由>`，第二行 `COMMAND: <合法指令>`。",
    "CONSIDER 必須使用繁體中文，只能描述公開安全的局勢、節奏、攻防或交換考量。",
    "CONSIDER 不得提到對手隱藏手牌、牌庫內容、盾牌內容或任何隱藏資訊。",
    "`card_reference` 提供相關卡牌的實際效果文字；評估卡牌價值時必須依照效果文字，不要猜測效果。",
]

_RULE_EXCERPTS = {
    "main": [
        {"cr_id": "CR-2.7", "text": "Main 階段可部署 Unit、配對 Pilot、使用 Command 卡、部署基地與宣告攻擊。"},
        {"cr_id": "CR-3.1", "text": "Level = active + rested + ex 資源總數。"},
        {"cr_id": "CR-5.1", "text": "攻擊目標只能是對手玩家（防禦層）或 rested 的敵方 Unit。"},
        {"cr_id": "CR-4.1", "text": "攻擊防禦層時，傷害順序為 Base → 盾牌 → 玩家。"},
        {"cr_id": "CR-7.4", "text": "Base 破壞不等於敗北；但對手盾牌也為 0 時，攻擊防禦層的傷害會直擊玩家。"},
        {"cr_id": "CR-9.1", "text": "敗北條件：盾牌為 0 且戰鬥傷害直擊玩家時，該玩家立即敗北。"},
        {"cr_id": "CR-5.2", "text": "Unit 部署當回合不能攻擊，除非與對應 Pilot 達成 Link。"},
        {"cr_id": "CR-4.4", "text": "Start 階段：該回合玩家的所有 Unit 恢復 active（橫置→重置）。橫置效果只在施加者的回合內持續；Rest 對手 Unit 後若不在同回合內進攻，該效果就沒有戰術價值。"},
    ],
    "block": [
        {"cr_id": "CR-6.1", "text": "<Blocker>：橫置此 Unit，把攻擊目標改為它。"},
    ],
    "action": [
        {"cr_id": "CR-2.10", "text": "Action Step 雙方輪流取得優先權，連續兩次讓過才推進。"},
    ],
    "mulligan": [
        {"cr_id": "CR-1.8", "text": "調度時可重抽一次：整手洗回牌庫後重抽 5 張。"},
        {"cr_id": "CR-1.2", "text": "後手玩家起始擁有 1 個 EX Resource。"},
    ],
}

_STRATEGY_NOTES = {
    "main": [
        "先檢查斬殺：(a) 若對手盾牌為 0 且沒有基地，任何一次成功的 `attack ... opponent_base` 都會直擊玩家並立即獲勝；此時直擊玩家優先於擊殺單位、清場或部署。(b) 若對手基地仍存在但 HP 極低（≤2），攻擊並摧毀基地移除其防禦層：之後每次攻擊防禦層都固定穿越到盾牌，建立穩定推進。摧毀低 HP 基地的戰略價值遠大於擊殺橫置單位；溢出傷害不會穿透到盾牌仍是值得的。",
        "計算「本回合能否摧毀對手基地」時，不只算場上已有活躍單位的攻擊力。若手牌中有 Link Unit + 對應 Pilot 且資源足夠，部署+配對 Link 後該單位本回合即可攻擊——把這個攻擊力也加入本回合總輸出計算。若總和 ≥ 對手基地剩餘 HP，部署 Link 組合並攻擊基地是最優策略；不要只因為場上沒有活躍單位就放棄斬殺念頭。",
        "部署單位到 slot 前，先比較手牌中所有可部署選項的：AP（攻擊力）、HP、Link 潛力、特殊效果。不要先部署弱單位再用弱單位佔 slot——每個 slot 是有限的資源，先部署最強或最具協同效應的選項（如 Link Unit + Pilot、或 [During Pair] 提供全局增益的單位）。先部署弱單位會排擠更強組合的上場機會，且配對駕駛員給無 Link 單位往往是浪費。",
        "部署 Link Unit 後不要立刻結束主要階段。完整的 In-Turn Link 流程：①部署 Link Unit → ②配對對應的 Link Pilot（`pair` 指令，記得檢查 `pair_annotations`）→ ③Link Unit 本回合即可攻擊 → ④攻擊對手足夠後再結束主要階段。缺少任何一步都會讓該 unit 本回合無法攻擊。若資源足夠，永遠優先完成 Link 組合再考慮結束回合。",
        "前期優先建立場面；對手防禦層薄時優先推進傷害。",
        "若已有可攻擊的單位，不要無限制地只做部署。",
        "若基地壓力高，優先部署有 Blocker 的單位。",
        "手牌管理：不要因為資源（active cards）足夠就把手牌中的威脅一次出完。保留手牌作為後續回合的補充與應變空間；若場上已有足夠場面壓力，保留額外威脅優於全部打出，避免對手清除場面後無後續卡牌可部署。手牌所剩無幾且無法在本回合獲勝時，優先保留手牌備用。",
        "Pilot 配對能提升 AP/HP 並可能達成 Link（部署當回合可攻擊）。配對前先看 `pair_annotations`：同一張 Pilot 通常優先配對到標示為 Link 配對的機體，而不是任意機體。",
        "攻擊目標只能選 rested 的敵方單位或對手防禦層；active 的敵方單位不能被指定，legal_commands 之外的攻擊都不合法。",
        "對手場上有 active 的 <Blocker> 單位時，你的攻擊可能被改向到該 Blocker；宣告攻擊前先評估被阻擋後的交換結果。但 Blocker 每次阻擋需橫置且一次只能改向一隻攻擊者：若你的攻擊力足以擊殺該 Blocker（AP ≥ 其剩餘 HP），即使同歸於盡通常也是有利交換，之後其他攻擊者就能直接打防禦層。",
        "Main 階段若沒有其他有價值的行動（無可部署、無可配對、無可用 Command），讓 active 攻擊者整回合閒置通常劣於攻擊；選 `pass` 前要先確認每一個攻擊選項都真的不利，而不是只因對手有 Blocker 就放棄進攻。",
        "若 legal_commands 中有 `activate_effect base`，那通常是免費價值（例如生成 token），優先評估而不是直接 pass。對手基地已毀時，部署手中基地卡可取得：①新基地吸收傷害保護盾牌；②[Deploy]從盾牌抽1牌；③[Activate]每回合生成 token 增加破盾攻擊次數。",
        "若我方基地已被摧毀且手中有基地卡，部署基地是最優先生存行動，優先於部署任何同費單位。沒有基地時盾牌直接暴露於每次攻擊，傷害先破盾再傷玩家；部署基地提供 HP5 防禦層吸收傷害保護盾牌，[Deploy]抽 1 盾補充手牌，且非 EX-Base 基地每回合可生成 token。不要為了多部署一隻單位而延後基地部署。",
        "使用 [Deploy] 或 Command 效果前，先確認效果能產生的實際戰術利益。橫置(Rest)效果只持續到對手回合的 Start 階段（對手 Unit 會恢復 active），Rest 後若不在同回合內攻擊讓該 Unit 無法阻擋，則 Rest 等同無效。AP 減少效果若寫明「本回合」則只在當前回合有效——你在自己回合讓對手 Unit AP-3，對手 Unit 在你的回合不會攻擊或阻擋，該效果在對手回合開始時消失，完全沒有戰術價值。不要為了觸發效果而觸發：若效果無法在同回合內改變實質戰局（阻擋、攻擊、交換），保留資源優於浪費。",
        "同一張卡同時出現 `pair`（當 Pilot 配對）與 `play_card`（當 Command 使用）時，先比較兩種用法的價值再選：配對提供永久 AP/HP 加成，多半優於一次沒有實際作用的效果。",
        "駕駛員的[When Paired]效果是戰術資產：配對前先看該效果是否能在對手場上找到合法目標（例如 Amuro Ray 需要 ≤5HP 的活躍單位）。若目前沒有目標或目標存活價值低，保留駕駛員等待更好的配對機會（Link 機體或有目標可用的時機）通常優於立即配對到沒有 Link 的單位上。",
        "配對駕駛員前，先評估駕駛員的效果與目標機體的攻擊能力是否 synergy：若駕駛員有 [Attack] 觸發效果（攻擊時獲得某種增益），配對到「不能攻擊玩家」的機體會大幅降低該效果的價值。AP/HP加成雖好，但浪費駕駛員效果得不償失。",
        "優先考慮能攻擊對手的機體部署和保留：若場上唯一的未配對機體有「不能攻擊玩家」限制，慎重將 Pilot 配到其上，尤其當該 Pilot 的價值來自攻擊觸發效果時。",
        "`play_card` 指令的格式依卡牌類型不同：基地卡(Base) → `play_card <card_id>`（無插槽）；單位卡(Unit) → `play_card <card_id> <slot>`（需插槽號碼）；指令卡(Command) → `play_card <card_id>`（無插槽）。同一種 `play_card` 格式不能跨區域使用。若 legal_commands 沒有包含某張 card_id 的 `play_card` 指令，代表當前狀態下無法合法使用該卡。",
    ],
    "block": [
        "若我方盾牌為 0 且沒有基地，被直擊就立即敗北；有可用 Blocker 時必須優先阻擋。",
        "若不阻擋會讓對手直接推進防禦層或擊破關鍵單位，優先考慮阻擋。",
        "盾牌是消耗性資源，Blocker 是可重複使用的防守資產。評估是否阻擋時，先檢查自身盾牌數：",
        "  - 盾牌 ≥3：讓小攻擊（AP≤3）通過，用 1 盾吸收比損失 Blocker 划算。Blocker 留著應付更大的威脅。",
        "  - 盾牌 1-2：評估攻擊者價值。若攻擊者是高費威脅或能決定勝負，Block；否則仍優先保留盾牌。",
        "  - 盾牌 0：有 Blocker 必須擋，除非攻擊者完全無害（AP=0）。",
        "考量成本交換比：用高費 Blocker 去換低費攻擊者是負面交換，即使單位存活也是虧損。不阻擋最多損失 1 面盾牌，阻擋可能損失整個 Blocker 單位。",
    ],
    "action": [
        "若 Action 卡能改變這次戰鬥的交換結果，優先考慮使用。",
        "若 legal_commands 中有 `activate_effect base`，那通常是免費價值，優先評估而不是直接 pass。",
    ],
}


class PromptBuilder:
    def __init__(self, experience_root=None, card_db=None, rules_index=None):
        self.experience_summaries = load_experience_summaries(experience_root)
        self.card_db = card_db
        self.rules_index = rules_index

    def build(self, viewer_bundle, legal_commands, request_type=None):
        viewer_state = viewer_bundle["viewer_state"]
        decision_type = viewer_state.get("decision_type")
        pending_choice = viewer_state.get("pending_choice") or {}
        kind = self._decision_kind(viewer_state, pending_choice)

        payload = {
            "request_type": request_type or f"gcg_{kind}_decision",
            "game_id": viewer_state.get("game_id"),
            "player_id": viewer_state.get("viewer_player"),
            "decision_type": decision_type,
            "instructions": list(_BASE_INSTRUCTIONS) + self._kind_instructions(kind, pending_choice),
            "legal_commands": list(legal_commands),
            "viewer_state": viewer_state,
            "viewer_markdown": viewer_bundle.get("markdown", ""),
            "output_contract": {
                "format": "two_line_consider_and_command",
                "examples": self._examples(kind, legal_commands),
            },
        }
        card_reference = self._card_reference(viewer_state, pending_choice, legal_commands)
        if card_reference:
            payload["card_reference"] = card_reference
        rule_excerpts = _RULE_EXCERPTS.get(kind)
        if rule_excerpts:
            payload["rule_excerpts"] = rule_excerpts
        strategy_notes = _STRATEGY_NOTES.get(kind)
        if strategy_notes:
            payload["strategy_notes"] = strategy_notes
        attack_annotations = self._annotate_attacks(legal_commands, viewer_state)
        if attack_annotations:
            payload["attack_annotations"] = attack_annotations
        block_annotations = self._annotate_blocks(legal_commands, viewer_state)
        if block_annotations:
            payload["block_annotations"] = block_annotations
        pair_annotations = self._annotate_pairs(legal_commands, viewer_state)
        if pair_annotations:
            payload["pair_annotations"] = pair_annotations
        if attack_annotations or block_annotations or pair_annotations:
            payload["instructions"].append(
                "`attack_annotations` / `block_annotations` / `pair_annotations` 是 runtime "
                "依規則計算的結果預覽，內容是事實；評估攻擊、阻擋或配對時以它為準，不要自行心算或猜測 Link 名單。"
            )
        lessons = self._lessons_for_decision(kind, viewer_state)
        if lessons:
            payload["experience_summaries"] = lessons
        return payload

    def _decision_kind(self, viewer_state, pending_choice):
        if pending_choice.get("visible"):
            choice_type = pending_choice.get("type")
            if choice_type == "mulligan":
                return "mulligan"
            if choice_type == "choose_turn_order":
                return "turn_order"
            return "pending_choice"
        phase = viewer_state.get("phase")
        step = viewer_state.get("step")
        if phase == "main":
            return "main"
        if phase == "battle" and step == "block":
            return "block"
        return "action"

    def _kind_instructions(self, kind, pending_choice):
        if kind == "turn_order":
            return ["你正在決定先攻或後攻。"]
        if kind == "mulligan":
            return [
                "你正在決定是否保留起手牌。",
                "若起手缺乏前期可部署的 Unit，傾向重抽。",
            ]
        if kind == "pending_choice":
            return [
                f"你正在回應一個選擇：{pending_choice.get('message') or pending_choice.get('type')}",
                "請從 options 中選 1 個，輸出 `choose <option_id>`。",
                "效果來源卡的實際效果文字在 `card_reference`，請依實際效果選擇目標。",
            ]
        if kind == "main":
            return [
                "你正在 Main 階段做 1 個行動決策。",
                "`legal_commands` 內的指令是完整的可執行清單：不在其中的攻擊、部署、配對或使用都無法執行。即使某單位狀態為 active，若其 `attack` 指令不在清單中，代表該單位本回合無法攻擊（可能剛部署、不是 Link、或被其他效果限制）。若想用的指令不在清單中，選其他合法指令或 `pass`。",
                "`pass` 代表結束主要階段。",
            ]
        if kind == "block":
            return ["你正在阻擋步驟，決定是否以 Blocker 阻擋這次攻擊。"]
        return ["你正在 Action Step，可使用 [Action] 卡或讓過。"]

    def _examples(self, kind, legal_commands):
        first_command = legal_commands[0] if legal_commands else "pass"
        examples = {
            "turn_order": [
                "CONSIDER: 先攻較能主動建立節奏。\nCOMMAND: choose go_first",
            ],
            "mulligan": [
                "CONSIDER: 起手節奏穩定，保留前期發展空間。\nCOMMAND: choose keep",
                "CONSIDER: 起手偏慢且前期展開不足，選擇重抽。\nCOMMAND: choose redraw",
            ],
            "main": [
                "CONSIDER: 前期先補上場面，讓下回合有攻擊者可用。\nCOMMAND: play_card st01/ST01-008 0",
                "CONSIDER: 推進對手防禦層，壓低盾牌數。\nCOMMAND: attack my_slot_0 opponent_base",
                "CONSIDER: 對手防禦層已空，直擊玩家立即獲勝。\nCOMMAND: attack my_slot_0 opponent_base",
                "CONSIDER: 暫時沒有更高價值的合法行動。\nCOMMAND: pass",
            ],
            "block": [
                "CONSIDER: 阻擋能保住防禦層，先用 Blocker 接戰。\nCOMMAND: block my_slot_1",
                "CONSIDER: 沒有值得阻擋的理由，讓攻擊通過。\nCOMMAND: pass",
            ],
        }
        return examples.get(kind, [f"CONSIDER: 選擇目前最有利的選項。\nCOMMAND: {first_command}"])

    def _card_reference(self, viewer_state, pending_choice, legal_commands):
        """收集本次決策相關的 public-safe 卡牌效果文字。

        範圍：自己的手牌、雙方場上單位/Pilot/基地、pending choice 與
        legal_commands 中出現的 card id。不包含對手隱藏區域。
        """
        if self.card_db is None:
            return {}
        card_ids = []

        def add(card_id):
            if card_id and card_id not in card_ids:
                card_ids.append(card_id)

        players = viewer_state.get("players") or {}
        viewer_player = viewer_state.get("viewer_player")
        for player_id, player in players.items():
            if player_id == viewer_player:
                for card_id in player.get("hand") or []:
                    add(card_id)
            for slot in player.get("battle_area") or []:
                if slot and not slot.get("empty"):
                    add(slot.get("unit_id"))
                    add(slot.get("pilot_id"))
            base = player.get("base") or {}
            if base.get("present"):
                add(base.get("card_id"))
        scan_blob = json.dumps(
            [pending_choice, list(legal_commands)], ensure_ascii=False, default=str
        )
        for match in _CARD_ID_PATTERN.findall(scan_blob):
            add(match)

        reference = {}
        for card_id in card_ids:
            card = self.card_db.get(card_id)
            if card is None:
                continue
            reference[card_id] = {
                "name": card.get("name"),
                "type": card.get("cardType"),
                "level": card.get("level"),
                "cost": card.get("cost"),
                "ap": card.get("ap"),
                "hp": card.get("hp"),
                "link": card.get("link") or [],
                "effects": card.get("effects", {}).get("description") or [],
            }
        return reference

    # ------------------------------------------------------------------
    # 攻擊 / 阻擋結果預覽（純規則計算的事實，不做策略評價）
    # ------------------------------------------------------------------

    def _annotate_attacks(self, legal_commands, viewer_state):
        """為每條 attack 指令附上 runtime 規則計算的結果預覽。

        只輸出事實（誰被擊破、盾牌/基地變化、是否直擊獲勝），
        不輸出「有利/不利」等策略評價；判斷仍交給 LLM。
        """
        players = viewer_state.get("players") or {}
        my_block = players.get(viewer_state.get("viewer_player")) or {}
        opp_block = players.get(viewer_state.get("opponent_player")) or {}
        if not my_block or not opp_block:
            return {}

        annotations = {}
        for command in legal_commands:
            match = _ATTACK_COMMAND_PATTERN.match(command)
            if not match:
                continue
            attacker = self._slot_by_index(my_block, int(match.group(1)))
            if attacker is None:
                continue
            target_slot_text = match.group(2)
            if target_slot_text is None:
                unblocked = self._preview_defense_hit(attacker, opp_block)
            else:
                defender = self._slot_by_index(opp_block, int(target_slot_text))
                if defender is None:
                    continue
                unblocked = self._preview_unit_fight(attacker, defender)
            entry = {"if_unblocked": unblocked}
            blocked_lines = [
                self._preview_block_redirect(attacker, blocker)
                for blocker in self._active_blockers(opp_block)
            ]
            if blocked_lines:
                entry["if_blocked"] = blocked_lines
            annotations[command] = entry
        return annotations

    def _annotate_blocks(self, legal_commands, viewer_state):
        """阻擋決策時，為每條 block 指令附上互相傷害的計算結果。"""
        battle_context = viewer_state.get("battle_context") or {}
        attacker_slot_index = battle_context.get("attacker_slot")
        if attacker_slot_index is None:
            return {}
        players = viewer_state.get("players") or {}
        my_block = players.get(viewer_state.get("viewer_player")) or {}
        opp_block = players.get(viewer_state.get("opponent_player")) or {}
        attacker = self._slot_by_index(opp_block, attacker_slot_index)
        if attacker is None:
            return {}

        annotations = {}
        for command in legal_commands:
            match = _BLOCK_COMMAND_PATTERN.match(command)
            if not match:
                continue
            blocker = self._slot_by_index(my_block, int(match.group(1)))
            if blocker is None:
                continue
            blocker_ap = blocker.get("ap", 0)
            blocker_hp = blocker.get("remaining_hp", 0)
            attacker_ap = attacker.get("ap", 0)
            attacker_hp = attacker.get("remaining_hp", 0)
            blocker_text = (
                "被擊破" if attacker_ap >= blocker_hp else f"存活（剩 {blocker_hp - attacker_ap} HP）"
            )
            attacker_text = "被擊破" if blocker_ap >= attacker_hp else "存活"
            annotations[command] = (
                f"我方 {blocker['slot']} 號位（{blocker_ap}/{blocker_hp}）"
                f"與對手攻擊者 {attacker['slot']} 號位（{attacker_ap}/{attacker_hp}）互相造成傷害："
                f"我方 Blocker {blocker_text}；對手攻擊者 {attacker_text}"
            )
        return annotations

    def _preview_defense_hit(self, attacker, opp_block):
        ap = attacker.get("ap", 0)
        if ap <= 0:
            return "AP 0：無法對防禦層造成傷害（CR-4.8）"
        base = opp_block.get("base") or {}
        if base.get("present"):
            remaining = base.get("remaining_hp", 0)
            if ap >= remaining:
                return "摧毀對手基地（溢出傷害不會穿透到盾牌）"
            return f"對手基地受 {ap} 傷害（剩 {remaining - ap} HP）"
        shields = opp_block.get("shield_count", 0)
        if shields > 0:
            return f"破壞對手 1 張盾牌（剩 {shields - 1} 張）"
        return "直擊玩家：立即獲勝"

    def _preview_unit_fight(self, attacker, defender):
        my_ap = attacker.get("ap", 0)
        my_hp = attacker.get("remaining_hp", 0)
        def_ap = defender.get("ap", 0)
        def_hp = defender.get("remaining_hp", 0)
        defender_dies = my_ap >= def_hp
        attacker_dies = def_ap >= my_hp
        defender_text = "被擊破" if defender_dies else f"存活（剩 {def_hp - my_ap} HP）"
        attacker_text = "被擊破" if attacker_dies else f"存活（剩 {my_hp - def_ap} HP）"
        return (
            f"互相造成傷害：對手 {defender['slot']} 號位 {defender_text}；"
            f"我方 {attacker['slot']} 號位 {attacker_text}"
        )

    def _annotate_pairs(self, legal_commands, viewer_state):
        """為每條 pair 指令標注是否形成 Link（名字比對是規則事實）與加成數值。"""
        if self.card_db is None:
            return {}
        players = viewer_state.get("players") or {}
        my_block = players.get(viewer_state.get("viewer_player")) or {}

        annotations = {}
        for command in legal_commands:
            match = _PAIR_COMMAND_PATTERN.match(command)
            if not match:
                continue
            pilot = self._pilot_info(match.group(1))
            if pilot is None:
                continue
            slot = self._slot_by_index(my_block, int(match.group(2)))
            if slot is None:
                continue
            unit_card = self.card_db.get(slot.get("unit_id"))
            link_names = list((unit_card or {}).get("link") or [])
            bonus_text = f"AP+{pilot['ap']}/HP+{pilot['hp']}"
            if pilot["name"] in link_names:
                annotations[command] = (
                    f"配對到 {slot.get('unit_id')}：Link 配對（{pilot['name']} 在該機體 Link 名單中），"
                    f"{bonus_text}，Link 單位部署當回合即可攻擊"
                )
            else:
                link_text = "、".join(link_names) if link_names else "無"
                annotations[command] = (
                    f"配對到 {slot.get('unit_id')}：非 Link 配對（該機體 Link 名單：{link_text}），{bonus_text}"
                )
        return annotations

    def _pilot_info(self, card_id):
        card = self.card_db.get(card_id)
        if card is None:
            return None
        if card.get("cardType") == "pilot":
            return {
                "name": card.get("name"),
                "ap": card.get("ap") or 0,
                "hp": card.get("hp") or 0,
            }
        if self.rules_index is not None:
            designation = self.rules_index.pilot_designation(card_id)
            if designation:
                return {
                    "name": designation.get("name"),
                    "ap": designation.get("ap") or 0,
                    "hp": designation.get("hp") or 0,
                }
        return None

    def _preview_block_redirect(self, attacker, blocker):
        fight = self._preview_unit_fight(attacker, blocker)
        return (
            f"對手 {blocker['slot']} 號位（{blocker.get('ap', 0)}/{blocker.get('remaining_hp', 0)}, Blocker）"
            f"可阻擋並改向：{fight}"
        )

    def _active_blockers(self, opp_block):
        return [
            slot for slot in opp_block.get("battle_area") or []
            if slot
            and not slot.get("empty")
            and slot.get("status") == "active"
            and "Blocker" in (slot.get("keywords") or [])
        ]

    def _slot_by_index(self, player_block, slot_index):
        for slot in player_block.get("battle_area") or []:
            if slot and slot.get("slot") == slot_index and not slot.get("empty"):
                return slot
        return None

    def _lessons_for_decision(self, kind, viewer_state):
        """mulligan 用固定清單（盤面尚未成形）；main/block 依 lesson 宣告的
        condition 與 public 盤面特徵做檢索匹配，取 priority 最高的數條。"""
        if kind == "mulligan":
            return select_summaries(
                self.experience_summaries,
                ("early-game-no-play", "early-game-rush", "pilot-over-command"),
            )
        if kind not in {"main", "block"}:
            return []
        features = self._lesson_features(viewer_state)
        return match_summaries(self.experience_summaries, features)

    def _lesson_features(self, viewer_state):
        players = viewer_state.get("players") or {}
        my_block = players.get(viewer_state.get("viewer_player")) or {}
        opp_block = players.get(viewer_state.get("opponent_player")) or {}
        my_slots = [
            slot for slot in my_block.get("battle_area") or []
            if slot and not slot.get("empty")
        ]
        opp_slots = [
            slot for slot in opp_block.get("battle_area") or []
            if slot and not slot.get("empty")
        ]
        my_base = my_block.get("base") or {}
        opp_base = opp_block.get("base") or {}
        return {
            "turn": viewer_state.get("turn") or 0,
            "my_units": len(my_slots),
            "my_active_units": sum(1 for slot in my_slots if slot.get("status") == "active"),
            "my_empty_slots": len(my_block.get("battle_area") or []) - len(my_slots),
            "enemy_units": len(opp_slots),
            "enemy_rested_units": sum(1 for slot in opp_slots if slot.get("status") == "rested"),
            "enemy_damaged_units": sum(1 for slot in opp_slots if slot.get("damage", 0) > 0),
            "my_base_hp": my_base.get("remaining_hp", 0) if my_base.get("present") else 0,
            "my_base_present": bool(my_base.get("present")),
            "my_shields": my_block.get("shield_count", 0),
            "enemy_base_present": bool(opp_base.get("present")),
            "enemy_base_hp": opp_base.get("remaining_hp", 0) if opp_base.get("present") else 0,
            "enemy_shields": opp_block.get("shield_count", 0),
            "has_link_units": any(self._unit_has_link_names(slot) for slot in my_slots),
            "has_unpaired_units": any(slot.get("pilot_id") is None for slot in my_slots),
            "has_temp_debuff_in_hand": self._has_temp_debuff_in_hand(my_block.get("hand") or []),
            "has_matching_pilot_in_hand": self._has_matching_pilot_in_hand(
                my_block.get("hand") or [], my_slots
            ),
            "enemy_active_units": sum(1 for slot in opp_slots if slot.get("status") == "active"),
            "has_pilot_in_hand": self._has_pilot_in_hand(my_block.get("hand") or []),
            "has_attack_restricted_unit": self._has_attack_restricted_unit(my_slots),
            "has_pairable_in_hand": self._has_pairable_in_hand(my_block.get("hand") or []),
            "has_base_in_hand": self._has_base_in_hand(my_block.get("hand") or []),
            "my_blocker_count": sum(
                1 for slot in my_slots
                if slot.get("status") == "active"
                and "Blocker" in (slot.get("keywords") or [])
            ),
        }

    def _has_temp_debuff_in_hand(self, hand_ids):
        if self.card_db is None:
            return False
        for card_id in hand_ids:
            card = self.card_db.get(card_id)
            if card is None:
                continue
            for rule in (card.get("effects") or {}).get("rules") or []:
                params = rule.get("parameters") or {}
                dur = ((rule.get("timing") or {}).get("duration") or "")
                if (rule.get("action") == "modifyAP"
                        and params.get("value", 0) < 0
                        and dur == "UNTIL_END_OF_TURN"):
                    return True
        return False

    def _has_matching_pilot_in_hand(self, hand_ids, my_slots):
        if self.card_db is None:
            return False
        target_link_names = set()
        for slot in my_slots:
            if slot.get("pilot_id") is not None or slot.get("is_link"):
                continue
            card = self.card_db.get(slot.get("unit_id"))
            if card and card.get("link"):
                target_link_names.update(card["link"])
        if not target_link_names:
            return False
        for card_id in hand_ids:
            card = self.card_db.get(card_id)
            if card is None or card.get("cardType") != "pilot":
                continue
            if card.get("name") in target_link_names:
                return True
        return False

    def _has_pilot_in_hand(self, hand_ids):
        if self.card_db is None:
            return False
        for card_id in hand_ids:
            card = self.card_db.get(card_id)
            if card and card.get("cardType") == "pilot":
                return True
        return False

    def _has_attack_restricted_unit(self, my_slots):
        if self.card_db is None:
            return False
        for slot in my_slots:
            if slot.get("pilot_id") is not None:
                continue
            card = self.card_db.get(slot.get("unit_id"))
            if card is None:
                continue
            for rule in (card.get("effects") or {}).get("rules") or []:
                if (rule.get("action") == "restrict_attack"
                        and (rule.get("parameters") or {}).get("disallow") == "player"):
                    return True
        return False

    def _has_base_in_hand(self, hand_ids):
        if self.card_db is None:
            return False
        for card_id in hand_ids:
            card = self.card_db.get(card_id)
            if card and card.get("cardType") == "base":
                return True
        return False

    def _has_pairable_in_hand(self, hand_ids):
        if self.card_db is None:
            return False
        for card_id in hand_ids:
            card = self.card_db.get(card_id)
            if card is None:
                continue
            if card.get("cardType") == "pilot":
                return True
            if self.rules_index is not None and self.rules_index.pilot_designation(card_id):
                return True
            for desc in (card.get("effects") or {}).get("description") or []:
                if "[Pilot]" in desc:
                    return True
        return False

    def _unit_has_link_names(self, slot):
        if slot.get("is_link"):
            return False
        if self.card_db is None:
            return False
        card = self.card_db.get(slot.get("unit_id"))
        if card is None:
            return False
        return bool(card.get("link"))
