"""Convert raw legal commands to Traditional Chinese UI labels.

This module only formats already-enumerated legal commands. It does not decide
legality and never changes the command sent back to runtime.
"""

from __future__ import annotations

import re


_MY_SLOT = re.compile(r"^my_slot_(\d+)$")
_OPP_SLOT = re.compile(r"^opponent_slot_(\d+)$")


def build_legal_actions(commands, card_db=None):
    return [label_command(command, card_db=card_db) for command in commands]


def label_command(command, card_db=None):
    parts = str(command).split()
    if not parts:
        return {"command": command, "label": "未知操作", "kind": "unknown"}

    head = parts[0]
    if head == "choose":
        return _choice_action(command, parts)
    if head == "play_card":
        return _play_card_action(command, parts, card_db)
    if head == "pair":
        return _pair_action(command, parts)
    if head == "attack":
        return _attack_action(command, parts)
    if head == "block":
        return _block_action(command, parts)
    if head == "activate_effect":
        return {
            "command": command,
            "label": "發動基地能力",
            "kind": "ability",
        }
    if head == "pass":
        return {
            "command": command,
            "label": "讓過",
            "kind": "pass",
        }
    return {
        "command": command,
        "label": command,
        "kind": "other",
    }


def _choice_action(command, parts):
    choice_id = parts[1] if len(parts) > 1 else ""
    labels = {
        "go_first": "選擇先攻",
        "go_second": "選擇後攻",
        "keep": "保留起手牌",
        "redraw": "重新調度",
        "activate": "發動效果",
        "decline": "不發動效果",
    }
    return {
        "command": command,
        "label": labels.get(choice_id, f"選擇 {choice_id}"),
        "kind": "choice",
        "choice_id": choice_id,
    }


def _play_card_action(command, parts, card_db):
    card_id = parts[1] if len(parts) > 1 else ""
    slot = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else None
    card_type = _card_type(card_db, card_id)
    if slot is not None:
        return {
            "command": command,
            "label": f"部署 {card_id} 到 {slot + 1} 號位",
            "kind": "deploy",
            "card_id": card_id,
            "slot": slot,
        }
    if card_type == "base":
        label = f"部署基地 {card_id}"
        kind = "deploy_base"
    else:
        label = f"使用 {card_id}"
        kind = "use"
    return {
        "command": command,
        "label": label,
        "kind": kind,
        "card_id": card_id,
    }


def _pair_action(command, parts):
    card_id = parts[1] if len(parts) > 1 else ""
    slot = _slot_number(parts[2]) if len(parts) > 2 else None
    label_slot = slot + 1 if slot is not None else "?"
    return {
        "command": command,
        "label": f"將 {card_id} 配對到 {label_slot} 號位",
        "kind": "pair",
        "card_id": card_id,
        "slot": slot,
    }


def _attack_action(command, parts):
    source_slot = _slot_number(parts[1]) if len(parts) > 1 else None
    target = parts[2] if len(parts) > 2 else ""
    label_source = source_slot + 1 if source_slot is not None else "?"
    action = {
        "command": command,
        "kind": "attack",
        "source_slot": source_slot,
    }
    if target == "opponent_base":
        action["label"] = f"以 {label_source} 號位直接攻擊對手"
        action["target"] = "opponent_base"
        return action
    target_slot = _opponent_slot_number(target)
    label_target = target_slot + 1 if target_slot is not None else "?"
    action["label"] = f"以 {label_source} 號位攻擊對手 {label_target} 號位"
    action["target_slot"] = target_slot
    return action


def _block_action(command, parts):
    slot = _slot_number(parts[1]) if len(parts) > 1 else None
    label_slot = slot + 1 if slot is not None else "?"
    return {
        "command": command,
        "label": f"以 {label_slot} 號位阻擋",
        "kind": "block",
        "slot": slot,
    }


def _card_type(card_db, card_id):
    if card_db is None or not card_id:
        return None
    card = card_db.get(card_id)
    if card is None:
        return None
    return card.get("cardType")


def _slot_number(value):
    match = _MY_SLOT.match(str(value))
    return int(match.group(1)) if match else None


def _opponent_slot_number(value):
    match = _OPP_SLOT.match(str(value))
    return int(match.group(1)) if match else None
