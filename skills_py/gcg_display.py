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

try:
    from .card_db import build_card_summary, get_card, get_card_keywords
    from .game_engine import can_attack, can_attack_unit, can_block, can_play_card
    from .game_state import BattleSlot, GameState, PlayerState
except ImportError:
    PROJECT_ROOT = Path(__file__).parent.parent.absolute()
    if str(PROJECT_ROOT) not in sys.path:
        sys.path.insert(0, str(PROJECT_ROOT))
    from skills_py.card_db import build_card_summary, get_card, get_card_keywords
    from skills_py.game_engine import can_attack, can_attack_unit, can_block, can_play_card
    from skills_py.game_state import BattleSlot, GameState, PlayerState

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


def _check_legality(card_id: str, state: GameState, viewer: str, has_unit: bool = True) -> str:
    """回傳合法性標記字串：✅ 或 ❌(原因)。"""
    card = get_card(card_id)
    if not card:
        return _fmt("legality_ok")
    if card.get("cardType") == "pilot" and not has_unit:
        return _fmt("legality_fail_pair")
    ok, reason = can_play_card(state, viewer, card_id)
    if ok:
        return _fmt("legality_ok")
    if reason.startswith("insufficient Level"):
        return _fmt("legality_fail_level", total_lv=state.get_player(viewer).level, required_lv=card.get("level", 0))
    if reason.startswith("insufficient resources"):
        return _fmt("legality_fail_cost", active=state.get_player(viewer).resources_active, cost=card.get("cost", 0))
    return f"❌ ({reason})"


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


def _available_actions(state: GameState, viewer: str, battle_area: list[BattleSlot]) -> list[str]:
    """產生可行指令列表。"""
    lines = []
    hand_cards = state.get_player(viewer).hand_cards
    has_unit = any(slot.unit_id is not None for slot in battle_area)
    for card_id in hand_cards:
        legality = _check_legality(card_id, state, viewer, has_unit)
        card = get_card(card_id) or {}
        card_type = card.get("cardType")
        d = {
            "card_id": card_id,
            "name": card.get("name", card_id),
            "level": card.get("level", 0),
            "cost": card.get("cost", 0),
            "legality": legality,
        }
        if card_type == "command":
            tpl_key = "action_play"
        elif card_type == "pilot":
            tpl_key = "action_pair"
        else:
            tpl_key = "action_deploy"
        lines.append(_fmt(tpl_key, **d))
    return lines


def _combat_reason(reason: str) -> str:
    reason_map = {
        "can only attack in main phase": "只能在主要階段攻擊",
        "invalid slot": "欄位不存在",
        "no unit in that slot": "該欄位沒有 Unit",
        "unit is rested": "該 Unit 已橫置",
        "unit cannot attack this turn (summoning sickness)": "剛部署的 Unit 本回合不能攻擊",
        "unit has 0 AP": "AP 為 0，不能攻擊",
        "invalid target slot": "目標欄位不存在",
        "no enemy unit in target slot": "目標欄位沒有敵方 Unit",
        "enemy unit must be rested to attack": "只能攻擊已橫置的敵方 Unit",
        "can only block during attack step": "只能在攻擊/阻擋窗口阻擋",
        "unit is not a Blocker": "該 Unit 沒有 Blocker",
    }
    return reason_map.get(reason, reason)


def _attack_action_lines(state: GameState, viewer: str) -> list[str]:
    if state.phase != "main" or state.priority != viewer or state.active_player != viewer:
        return ["  - 攻擊：目前不是你的攻擊時機"]

    player = state.get_player(viewer)
    opponent = state.get_opponent(viewer)
    lines: list[str] = []
    legal_count = 0
    for slot in player.battle_area:
        if slot.unit_id is None:
            continue
        ok, reason = can_attack(state, viewer, slot.slot)
        if not ok:
            lines.append(f"  - 欄位{slot.slot} 不能攻擊：{_combat_reason(reason)}")
            continue
        legal_count += 1
        lines.append(f"  - 攻擊 {slot.slot} — 攻擊對手防禦層✅")
        for target in opponent.battle_area:
            if target.unit_id is None:
                continue
            target_ok, target_reason = can_attack_unit(state, viewer, slot.slot, target.slot)
            if target_ok:
                lines.append(f"  - 攻擊 {slot.slot} unit {target.slot} — 攻擊敵方欄位{target.slot}✅")
            elif target.status == "rested":
                lines.append(f"  - 欄位{slot.slot} 不能攻擊敵方欄位{target.slot}：{_combat_reason(target_reason)}")
    if legal_count == 0:
        lines.append("  - 攻擊：目前沒有合法攻擊者")
    return lines


def _block_action_lines(state: GameState, viewer: str) -> list[str]:
    if state.phase != "battle" or state.step not in ("attack", "block") or state.priority != viewer:
        return ["  - 阻擋：目前不是你的阻擋窗口"]

    player = state.get_player(viewer)
    lines: list[str] = []
    legal_count = 0
    for slot in player.battle_area:
        if slot.unit_id is None:
            continue
        ok, reason = can_block(state, viewer, slot.slot)
        if ok:
            legal_count += 1
            lines.append(f"  - 阻擋 {slot.slot} — 使用欄位{slot.slot} 阻擋✅")
        else:
            lines.append(f"  - 欄位{slot.slot} 不能阻擋：{_combat_reason(reason)}")
    if legal_count == 0:
        lines.append("  - 阻擋：目前沒有合法阻擋者")
    return lines


def _battle_log_text(logs: list[str]) -> str:
    if not logs:
        return ""
    return "\n".join(_fmt("battle_log_line", message=line) for line in logs[-5:])


def _you_suffix(state: GameState, viewer: str) -> str:
    return "(你)" if state.priority == viewer else ""


def _base_status_text(base) -> str:
    if not base.alive:
        return "無"
    return f"有（{base.card_id} | AP|HP：{base.ap}|{base.hp - base.damage}）"


def _turn_owner_text(player_id: str, viewer: str) -> str:
    if player_id == viewer:
        return f"你（{viewer}）的回合"
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


def _main_phase_summary(state: GameState, viewer: str, res: dict) -> str:
    me = state.get_player(viewer)
    if state.priority != viewer:
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

def _build_common_block(state: GameState, viewer: str = "P1") -> str:
    """根據 state 計算所有欄位，填入 common_block 模板。"""
    me = state.get_player(viewer)
    opp = state.get_opponent(viewer)
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
        turn_owner=_turn_owner_text(state.active_player, viewer),
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
        base_ap=me.base.ap,
        base_hp=me.base.hp - me.base.damage,
        opponent_base_status=_base_status_text(opp.base),
        battle_log=_battle_log_text(state.battle_log),
        priority=state.priority,
        you_suffix=_you_suffix(state, viewer),
    )


# ---------- render functions ----------

def _render_mulligan(state: GameState, viewer: str = "P1") -> str:
    """調度模板
    輸出示例:
      調度 — P1 為後手
      你的手牌：
      - st01/ST01-009 | Zowort | unit | Lv2 | Cost:2 | AP:3/HP:2 | [Blocker]
      - st01/ST01-008 | Demi Trainer | unit | Lv1 | Cost:1 | AP:1/HP:1 | [Blocker]
      ...
      請輸入 redraw 或 keep
    """
    me = state.get_player(viewer)
    first = "先手" if state.first_player == viewer else "後手"
    hand_lines = "\n".join(f"- {_card_line(cid)}" for cid in me.hand_cards)
    return _fmt("mulligan", player=viewer, first_or_second=first, hand_lines=hand_lines)


def _render_main_phase(state: GameState, viewer: str = "P1") -> str:
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
    if state.priority != viewer:
        return _fmt("main_phase_waiting",
            common_block=_build_common_block(state, viewer),
            priority=state.priority,
        )

    me = state.get_player(viewer)
    res = _player_resources(me)
    actions = _available_actions(state, viewer, me.battle_area)
    action_block = "\n".join(actions)
    return _fmt("main_phase",
        common_block=_build_common_block(state, viewer),
        main_summary=_main_phase_summary(state, viewer, res),
        action_lines=action_block,
        attack_lines="\n".join(_attack_action_lines(state, viewer)),
    )


def _render_start_phase(state: GameState, viewer: str = "P1") -> str:
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
    return _fmt("start_phase", common_block=_build_common_block(state, viewer))


def _render_draw_phase(state: GameState, viewer: str = "P1") -> str:
    """抽牌階段模板
    輸出示例:
      回合 1 | 抽牌階段 — 自動抽牌 | P1 的回合
      ...

      可行指令：
      - 讓過 — 抽牌完成，進入資源階段
    """
    return _fmt("draw_phase", common_block=_build_common_block(state, viewer))


def _render_resource_phase(state: GameState, viewer: str = "P1") -> str:
    """資源階段模板
    輸出示例:
      回合 1 | 資源階段 — 自動部署資源 | P1 的回合
      ...

      可行指令：
      - 讓過 — 部署資源完成，進入主要階段
    """
    return _fmt("resource_phase", common_block=_build_common_block(state, viewer))


def _render_battle_attack(state: GameState, viewer: str = "P1") -> str:
    """戰鬥階段 — 攻擊宣言模板
    輸出示例:
      回合 2 | 戰鬥階段 — 攻擊宣言 | P1 的回合
      ...

      可行指令：
      - 攻擊 <欄位>（若單位符合攻擊條件）
      - 讓過 — 跳過攻擊，進入結束階段
      - 投降
    """
    return _fmt(
        "battle_attack",
        common_block=_build_common_block(state, viewer),
        attack_lines="\n".join(_attack_action_lines(state, viewer)),
    )


def _render_battle_action(state: GameState, viewer: str = "P1") -> str:
    """戰鬥階段 — 動作子步驟模板
    輸出示例:
      回合 2 | 戰鬥階段 — 動作子步驟 | P1 的回合
      ...

      可行指令：
      - 阻擋 <欄位>（若單位有 Blocker 關鍵字）
      - 讓過 — 不阻擋
    """
    return _fmt(
        "battle_action",
        common_block=_build_common_block(state, viewer),
        block_lines="\n".join(_block_action_lines(state, viewer)),
    )


def _render_battle_end(state: GameState, viewer: str = "P1") -> str:
    """戰鬥階段 — 結束步驟模板
    輸出示例:
      回合 2 | 戰鬥階段 — 結束 | P1 的回合
      ...

      可行指令：
      - 讓過 — 戰鬥結束，進入結束階段
      - 投降
    """
    return _fmt("battle_end", common_block=_build_common_block(state, viewer))


def _render_end_phase(state: GameState, viewer: str = "P1") -> str:
    """結束階段模板
    輸出示例:
      回合 1 | 結束階段 | P1 的回合
      ...

      可行指令：
      - 讓過 — 結束回合
      - 投降
    """
    return _fmt("end_phase", common_block=_build_common_block(state, viewer))


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
    "error": lambda s, viewer="P1": _render_error("階段不匹配"),
}


def resolve_template(state: GameState) -> str:
    _load_templates()
    if state.phase == "battle":
        return _tpl["battle_step_map"].get(state.step, "battle_end")
    return _tpl["phase_table"].get(state.phase, "error")


def render(state_path: str, template_name: Optional[str] = None, viewer: str = "P1") -> str:
    state = GameState.from_dict(yaml.safe_load(Path(state_path).read_text()))
    if template_name is None:
        template_name = resolve_template(state)
    render_fn = RENDER_MAP.get(template_name)
    if render_fn is None:
        return _render_error(f"未知模板: {template_name}")
    return render_fn(state, viewer)


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
        "--viewer", choices=("P1", "P2"), default="P1",
        help="指定顯示視角。玩家/AI 決策時必須使用該玩家視角的完整可見狀態",
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
        text = render(args.state_path, args.template, viewer=args.viewer)
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
