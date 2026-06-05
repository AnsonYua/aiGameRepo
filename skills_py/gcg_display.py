"""
gcg_display.py — 將 game_state 填入模板後輸出純文字。
模板定義在 gcg_display_templates.yaml，修改排版不需動程式碼。

用法:
  python gcg_display.py <state_path> [-o /tmp/out.txt]     # 自動偵測模板
  python gcg_display.py <state_path> error -o /tmp/out.txt # 強制 error 模板
  python gcg_display.py --list                              # 列出所有模板
"""

import sys
from pathlib import Path
from typing import Optional

import yaml

from card_db import build_card_summary, get_card, get_card_keywords
from game_state import BattleSlot, GameState, PlayerState

TEMPLATE_DIR = Path(__file__).parent
TEMPLATE_FILE = TEMPLATE_DIR / "gcg_display_templates.yaml"

STATUS_MAP = {"active": "直立", "rested": "橫置", None: "無", "null": "無"}
PHASE_NAMES = {
    "start": "開始階段", "draw": "抽牌階段", "resource": "資源階段",
    "main": "主要階段", "battle": "戰鬥階段", "end": "結束階段",
}
STEP_LABELS = {
    "attack": "攻擊宣言", "battle_init": "攻擊宣言",
    "action": "動作子步驟", "block": "動作子步驟",
    "damage": "傷害子步驟", "battle_end": "結束",
}

_tpl: dict = {}


def _load_templates():
    global _tpl
    if not _tpl:
        _tpl = yaml.safe_load(TEMPLATE_FILE.read_text())


def _fmt(key: str, **kwargs) -> str:
    """取模板 {key} 並填入 {kwargs}。"""
    _load_templates()
    return _tpl[key].format(**kwargs)


def get_card_name(card_id: str) -> str:
    card = get_card(card_id)
    return card["name"] if card else card_id


# ---------- computed data builders ----------

def _build_card_data(card_id: str) -> dict:
    """將一張卡片的各種欄位計算好，供 card_line 模板使用。"""
    s = build_card_summary(card_id)
    card = get_card(card_id) or {}
    links = card.get("link", [])
    kws = [k for k in get_card_keywords(card_id) if not k.startswith("Link:")]
    return {
        "card_id": card_id,
        "name": s["name"],
        "cardType": s["cardType"],
        "level": s["level"],
        "cost": s["cost"],
        "ap": s["ap"],
        "hp": s["hp"],
        "link_suffix": f" | [Link: {', '.join(links)}]" if links else "",
        "keyword_suffix": f" | [{', '.join(kws)}]" if kws else "",
    }


def _card_line(card_id: str) -> str:
    return _fmt("card_line", **_build_card_data(card_id))


def _check_legality(card_id: str, res: dict) -> str:
    """回傳合法性標記字串：✅ 或 ❌(原因)。"""
    card = get_card(card_id)
    if not card:
        return _fmt("legality_ok")
    level = card.get("level", 0)
    cost = card.get("cost", 0)
    total_lv = res["active"] + res["rested"] + res["ex"]
    if total_lv < level:
        return _fmt("legality_fail_level", total_lv=total_lv, required_lv=level)
    if res["active"] >= cost or res["active"] + res["ex"] >= cost:
        return _fmt("legality_ok")
    return _fmt("legality_fail_cost", active=res["active"], cost=cost)


def _player_resources(player: PlayerState) -> dict:
    return {
        "active": player.resources_active,
        "rested": player.resources_rested,
        "ex": player.resources_ex,
    }


def _battlefield_lines(ba: list[BattleSlot], is_opponent: bool) -> list[str]:
    """戰區格式化。戰鬥區是公開區域，因此雙方單位都顯示明細。"""
    _ = is_opponent
    if all(s.unit_id is None for s in ba):
        return [_fmt("bf_all_empty")]
    lines = []
    for slot in ba:
        if slot.unit_id is None:
            lines.append(_fmt("bf_slot_empty", slot=slot.slot))
            continue
        pilot = f" | {slot.pilot_id}" if slot.pilot_id else ""
        kws = f" | [{', '.join(slot.keywords)}]" if slot.keywords else ""
        d = {
            "slot": slot.slot,
            "unit_id": slot.unit_id,
            "name": get_card_name(slot.unit_id),
            "ap": slot.ap,
            "hp": slot.hp - slot.damage,
            "pilot": pilot,
            "keywords": kws,
            "status": STATUS_MAP.get(slot.status, str(slot.status)),
        }
        lines.append(_fmt("bf_slot_known", **d))
    return lines


def _available_actions(hand_cards: list[str], res: dict) -> list[str]:
    """產生可行指令列表。"""
    lines = []
    for card_id in hand_cards:
        legality = _check_legality(card_id, res)
        card = get_card(card_id) or {}
        d = {
            "card_id": card_id,
            "name": card.get("name", card_id),
            "level": card.get("level", 0),
            "cost": card.get("cost", 0),
            "legality": legality,
        }
        tpl_key = "action_play" if card.get("cardType") == "command" else "action_deploy"
        lines.append(_fmt(tpl_key, **d))
    return lines


def _battle_log_text(logs: list[str]) -> str:
    if not logs:
        return ""
    return "\n".join(_fmt("battle_log_line", message=line) for line in logs[-5:])


def _you_suffix(state: GameState) -> str:
    return "(你)" if state.priority == state.active_player and state.active_player == "P1" else ""


def _turn_owner_text(player_id: str) -> str:
    if player_id == "P1":
        return "你（P1）的回合"
    return f"{player_id} 的回合"


def _can_attack_from_slot(slot: BattleSlot) -> bool:
    if slot.unit_id is None:
        return False
    if slot.status == "rested":
        return False
    if slot.ap <= 0:
        return False
    return slot.link or slot.turns_on_field >= 1


def _is_playable(card_id: str, res: dict) -> bool:
    card = get_card(card_id)
    if not card or card.get("cardType") == "token":
        return False
    level = card.get("level", 0)
    cost = card.get("cost", 0)
    total_lv = res["active"] + res["rested"] + res["ex"]
    return total_lv >= level and res["active"] + res["ex"] >= cost


def _main_phase_summary(state: GameState, res: dict) -> str:
    me = state.p1
    if state.active_player != "P1":
        return ""
    has_play = any(_is_playable(card_id, res) for card_id in me.hand_cards)
    has_attack = any(_can_attack_from_slot(slot) for slot in me.battle_area)
    if has_play or has_attack:
        return ""

    levels = [
        (get_card(card_id) or {}).get("level", 0)
        for card_id in me.hand_cards
        if (get_card(card_id) or {}).get("cardType") != "token"
    ]
    if levels and min(levels) > me.level:
        return f"局勢提示：手牌全部需 Lv{min(levels)}+ 才能部署。唯一行動是 pass（讓過），進入結束階段。\n"
    return "局勢提示：目前沒有可部署或可攻擊的行動。唯一行動是 pass（讓過），進入結束階段。\n"


# ---------- common block ----------

def _build_common_block(state: GameState) -> str:
    """根據 state 計算所有欄位，填入 common_block 模板。"""
    p1, p2 = state.p1, state.p2
    me, opp = p1, p2
    hand_lines = "\n".join(f"- {_card_line(cid)}" for cid in me.hand_cards)
    my_ba = "\n".join(_battlefield_lines(me.battle_area, False))
    opp_ba = "\n".join(_battlefield_lines(opp.battle_area, True))
    phase_label = PHASE_NAMES.get(state.phase, state.phase)
    step_label = ""
    if state.phase == "battle" and state.step:
        step_label = f" — {STEP_LABELS.get(state.step, state.step)}"
    return _fmt("common_block",
        turn=state.turn,
        phase_label=phase_label,
        step_label=step_label,
        turn_owner=_turn_owner_text(state.active_player),
        active=me.resources_active,
        rested=me.resources_rested,
        ex=me.resources_ex,
        level=me.level,
        deck_count=me.deck_count,
        resource_deck_count=me.resource_deck_count,
        hand_count=me.hand_count,
        hand_lines=hand_lines,
        opponent_hand_count=opp.hand_count,
        occupied_slots=me.occupied_slots,
        opponent_occupied_slots=opp.occupied_slots,
        my_battlefield=my_ba,
        opponent_battlefield=opp_ba,
        shields=me.shields,
        opponent_shields=opp.shields,
        base_card_id=me.base.card_id,
        base_hp=me.base.hp - me.base.damage,
        base_max_hp=me.base.hp,
        battle_log=_battle_log_text(state.battle_log),
        priority=state.priority,
        you_suffix=_you_suffix(state),
    )


# ---------- render functions ----------

def _render_mulligan(state: GameState) -> str:
    """調度模板
    輸出示例:
      調度 — P1 為後手
      你的手牌：
      - st01/ST01-009 | Zowort | unit | Lv2 | Cost:2 | AP:3/HP:2 | [Blocker]
      - st01/ST01-008 | Demi Trainer | unit | Lv1 | Cost:1 | AP:1/HP:1 | [Blocker]
      ...
      請輸入 redraw 或 keep
    """
    p1 = state.p1
    first = "先手" if state.first_player == "P1" else "後手"
    hand_lines = "\n".join(f"- {_card_line(cid)}" for cid in p1.hand_cards)
    return _fmt("mulligan", player="P1", first_or_second=first, hand_lines=hand_lines)


def _render_main_phase(state: GameState) -> str:
    """主要階段模板 — 含出牌合法性檢查
    輸出示例:
      回合 9 | 主要階段 | P2 的回合
      資源：直立=0 橫置=4 EX=0 | 牌庫：33 | 資源牌庫：6

      你的手牌（4）：
      - st01/ST01-006 | Gundam Aerial (Permet Score Six) | unit | Lv5 | Cost:4 | AP:4/HP:4 | [Link: Suletta Mercury]
      ...

      對手手牌：2 張

      你地場上（4/6）：
      - 欄位0：[st01/ST01-008] Demi Trainer | AP:1/HP:1 | [Blocker] | 橫置
      ...

      對手的場上（6/6）：
      - 欄位0：[st01/ST01-008] Demi Trainer | AP:1/HP:1 | [Blocker] | 橫置
      ...

      盾牌：0 剩餘 | 基地：st01/ST01-016 | HP：0/5
      對手盾牌：3 剩餘

      • P2 plays/deploys st01/ST01-004
      ...

      優先權：P2

      可行指令（依出牌合法性 ✅/❌ 計算）：
        - 部署 st01/ST01-006 — Gundam Aerial (Permet Score Six)（Lv5/Cost:4）❌ (Lv不足: 4/5)
        - 使用 st01/ST01-014 — Unforeseen Incident（Lv3/Cost:1）❌ (費用不足: active=0/cost=1)
        ...
      - 攻擊 <欄位>（若單位符合條件：直立 +（出場回合≥1 或 link=true）[CR-5.4]）
      - 讓過 — 進入結束階段
      - 投降
    """
    me = state.p1
    res = _player_resources(me)
    actions = _available_actions(me.hand_cards, res)
    action_block = "\n".join(actions)
    return _fmt("main_phase",
        common_block=_build_common_block(state),
        main_summary=_main_phase_summary(state, res),
        action_lines=action_block,
    )


def _render_start_phase(state: GameState) -> str:
    """開始階段模板
    輸出示例:
      回合 1 | 開始階段 | P1 的回合
      資源：直立=0 橫置=0 EX=0 | 牌庫：39 | 資源牌庫：10

      你的手牌（5）：
      - st01/ST01-009 | Zowort | unit | Lv2 | Cost:2 | AP:3/HP:2 | [Blocker]
      ...

      對手手牌：5 張

      你地場上（0/6）：
      - 全部空格

      對手的場上（0/6）：
      - 全部空格

      盾牌：6 剩餘 | 基地：EX-BASE | HP：3/3
      對手盾牌：6 剩餘

      優先權：P1

      可行指令：
      - 讓過 — 進入抽牌階段
    """
    return _fmt("start_phase", common_block=_build_common_block(state))


def _render_draw_phase(state: GameState) -> str:
    """抽牌階段模板
    輸出示例:
      回合 1 | 抽牌階段 — 自動抽牌 | P1 的回合
      ...

      可行指令：
      - 讓過 — 抽牌完成，進入資源階段
    """
    return _fmt("draw_phase", common_block=_build_common_block(state))


def _render_resource_phase(state: GameState) -> str:
    """資源階段模板
    輸出示例:
      回合 1 | 資源階段 — 自動部署資源 | P1 的回合
      ...

      可行指令：
      - 讓過 — 部署資源完成，進入主要階段
    """
    return _fmt("resource_phase", common_block=_build_common_block(state))


def _render_battle_attack(state: GameState) -> str:
    """戰鬥階段 — 攻擊宣言模板
    輸出示例:
      回合 2 | 戰鬥階段 — 攻擊宣言 | P1 的回合
      ...

      可行指令：
      - 攻擊 <欄位>（若單位符合攻擊條件）
      - 讓過 — 跳過攻擊，進入結束階段
      - 投降
    """
    return _fmt("battle_attack", common_block=_build_common_block(state))


def _render_battle_action(state: GameState) -> str:
    """戰鬥階段 — 動作子步驟模板
    輸出示例:
      回合 2 | 戰鬥階段 — 動作子步驟 | P1 的回合
      ...

      可行指令：
      - 阻擋 <欄位>（若單位有 Blocker 關鍵字）
      - 讓過 — 不阻擋
    """
    return _fmt("battle_action", common_block=_build_common_block(state))


def _render_battle_end(state: GameState) -> str:
    """戰鬥階段 — 結束步驟模板
    輸出示例:
      回合 2 | 戰鬥階段 — 結束 | P1 的回合
      ...

      可行指令：
      - 讓過 — 戰鬥結束，進入結束階段
      - 投降
    """
    return _fmt("battle_end", common_block=_build_common_block(state))


def _render_end_phase(state: GameState) -> str:
    """結束階段模板
    輸出示例:
      回合 1 | 結束階段 | P1 的回合
      ...

      可行指令：
      - 讓過 — 結束回合
      - 投降
    """
    return _fmt("end_phase", common_block=_build_common_block(state))


def _render_error(reason: str = "") -> str:
    """錯誤模板
    輸出示例:
      非法指令：費用不足
    """
    return _fmt("error", reason=reason or "未知錯誤")


# ---------- routing ----------

RENDER_MAP = {
    "mulligan": _render_mulligan,
    "main_phase": _render_main_phase,
    "start_phase": _render_start_phase,
    "draw_phase": _render_draw_phase,
    "resource_phase": _render_resource_phase,
    "battle_attack": _render_battle_attack,
    "battle_action": _render_battle_action,
    "battle_end": _render_battle_end,
    "end_phase": _render_end_phase,
    "error": lambda s: _render_error("階段不匹配"),
}


def resolve_template(state: GameState) -> str:
    _load_templates()
    if state.phase == "battle":
        return _tpl["battle_step_map"].get(state.step, "battle_end")
    return _tpl["phase_table"].get(state.phase, "error")


def render(state_path: str, template_name: Optional[str] = None) -> str:
    state = GameState.from_dict(yaml.safe_load(Path(state_path).read_text()))
    if template_name is None:
        template_name = resolve_template(state)
    render_fn = RENDER_MAP.get(template_name)
    if render_fn is None:
        return _render_error(f"未知模板: {template_name}")
    return render_fn(state)


def main():
    r"""
    用法:
      # 自動偵測階段，輸出到終端
      python gcg_display.py game-states/game_20250605_120000/gameState.md

      # 輸出到檔案（正常流程）
      python gcg_display.py <state_path> -o /tmp/gcg_output.txt

      # Judge reject（強制 error 模板）
      python gcg_display.py <state_path> error -o /tmp/gcg_output.txt

      # 列出所有可用模板名稱
      python gcg_display.py --list
    """
    import argparse
    ap = argparse.ArgumentParser(
        description="GCG Display — 將 game_state 填入 YAML 模板後輸出純文字",
        epilog="模板定義在 skills_py/gcg_display_templates.yaml",
    )
    ap.add_argument(
        "state_path", nargs="?", default=None,
        help="gameState.md 路徑（YAML 格式）。若省略 template 則自動從 phase/step 選取對應模板",
    )
    ap.add_argument(
        "template", nargs="?", default=None,
        help="手動指定模板名稱，如 mulligan / main_phase / battle_attack 等。省略時自動偵測",
    )
    ap.add_argument(
        "-o", "--output",
        help="將輸出寫入指定檔案（預設輸出到 stdout）。orchestrator 用此寫入 /tmp/gcg_output.txt",
    )
    ap.add_argument(
        "--list", action="store_true",
        help="列出 gcg_display_templates.yaml 中所有可用模板名稱後退出",
    )
    args = ap.parse_args()

    if args.list:
        _load_templates()
        keys = [k for k in _tpl if k != "phase_table" and k != "battle_step_map"]
        print("可用模板:", ", ".join(keys))
        return

    if not args.state_path:
        ap.error("state_path is required unless --list")
        return

    try:
        text = render(args.state_path, args.template)
    except Exception as e:
        text = _render_error(str(e))

    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text)
        print(f"Wrote {len(text)} chars → {args.output}", file=sys.stderr)
    else:
        print(text)


if __name__ == "__main__":
    main()
