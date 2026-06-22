"""Manual test scenario loading for the local battle app."""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

from gcg import config


BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT.parent
DEFAULT_SCENARIO_ROOT = GCGV2_ROOT / "scenarios" / "manual"
_SCENARIO_INDEX_CACHE = {}


class ScenarioError(ValueError):
    pass


def load_scenario(scenario_id, root=None):
    if not isinstance(scenario_id, str) or not scenario_id.strip():
        raise ScenarioError("缺少 scenario_id。")
    scenario_id = scenario_id.strip()
    index = _scenario_index(Path(root or DEFAULT_SCENARIO_ROOT).resolve())
    if scenario_id in index:
        return copy.deepcopy(index[scenario_id])
    raise ScenarioError(f"找不到測試場景：{scenario_id}")


def _scenario_index(root):
    files = sorted(root.rglob("*.yaml"))
    signature = tuple(
        (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        for path in files
    )
    cached = _SCENARIO_INDEX_CACHE.get(root)
    if cached and cached["signature"] == signature:
        return cached["index"]

    index = {}
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        scenario_id = data.get("scenario_id")
        if not scenario_id:
            continue
        if scenario_id in index:
            raise ScenarioError(f"scenario_id 重複：{scenario_id}")
        _validate_scenario(data)
        index[scenario_id] = data
    _SCENARIO_INDEX_CACHE[root] = {"signature": signature, "index": index}
    return index


def apply_scenario(runner, scenario):
    state = runner.state
    game_id = state.create_game_shell()
    runner.game_id = game_id
    runner.step_count = 0
    runner.status = "in_progress"
    runner.gameplay_logger.open_game(game_id)

    setup = scenario.get("setup") or {}
    raw_state = state.get_state()
    raw_state["turn"] = int(setup.get("turn", 1))
    raw_state["phase"] = setup.get("phase", "main")
    raw_state["step"] = setup.get("step")
    raw_state["active_player"] = setup.get("active_player", "P1")
    raw_state["priority_player"] = setup.get("priority_player", "P1")
    raw_state["battle_context"] = None
    raw_state["pending_choice"] = []
    raw_state["trigger_queue"] = []
    raw_state["once_per_turn_used"] = []
    raw_state["game_over"] = False
    raw_state["winner"] = None
    raw_state["win_reason"] = None
    raw_state["opening"] = {
        "decision_player": None,
        "first_player": setup.get("first_player", "P1"),
        "second_player": "P2" if setup.get("first_player", "P1") == "P1" else "P1",
        "mulligan_done": {"P1": True, "P2": True},
    }
    raw_state["action_window"] = {
        "active": True,
        "origin": setup.get("action_window_origin", raw_state["phase"]),
        "consecutive_passes": 0,
        "last_action_player": None,
    }

    for player_id in ("P1", "P2"):
        _apply_player(runner, player_id, (scenario.get("players") or {}).get(player_id) or {})

    runner.gameplay_logger.log_system_event(
        game_id,
        "scenario_loaded",
        {
            "message": f"已載入測試場景：{scenario['scenario_id']}",
            "scenario_id": scenario["scenario_id"],
            "target_card": scenario.get("target_card"),
        },
    )
    state.save_snapshot()
    return game_id


def start_session_from_scenario(session, scenario):
    with session._lock:
        session._generation += 1
        session._runner = session._build_runner()
        session._status = "waiting_human"
        session._error = None
        session._last_message = f"已載入測試場景：{scenario['scenario_id']}"
        game_id = apply_scenario(session._runner, scenario)
        session._advance_and_update_status_locked()
        session._start_ai_worker_if_needed_locked()
        response = session._response_locked()
    return game_id, response


def _apply_player(runner, player_id, spec):
    player = runner.state.get_player_state(player_id)
    player["hand"] = _card_list(spec.get("hand", []))
    player["deck"] = _filler_cards(spec.get("deck_count", 30))
    player["shield"] = _filler_cards(spec.get("shields", 6))
    player["trash"] = _card_list(spec.get("trash", []))
    player["removal"] = _card_list(spec.get("removal", []))
    player["resource_deck_count"] = int(spec.get("resource_deck_count", 10))
    resources = spec.get("resources") or {}
    player["resources"] = {
        "active": int(resources.get("active", 0)),
        "rested": int(resources.get("rested", 0)),
        "ex": int(resources.get("ex", 0)),
    }
    player["base"] = None
    base = spec.get("base", "EX-BASE")
    if base == "EX-BASE":
        runner.state.deploy_ex_base(player_id)
    elif base:
        card = runner.state.card_database.get(base)
        if card is None:
            raise ScenarioError(f"{player_id} base 不存在：{base}")
        runner.state.deploy_base(player_id, base, card.get("ap", 0), card.get("hp", 0))

    player["battle_area"] = [
        runner.state._build_empty_slot(slot)  # Existing StateStore owns slot shape.
        for slot in range(config.BATTLE_AREA_SLOTS)
    ]
    for unit in spec.get("board") or []:
        card_id = unit["unit"]
        slot_index = int(unit.get("slot", 0))
        keywords = unit.get("keywords")
        if keywords is None:
            keywords = runner.runtime.rules_index.keywords(card_id)
        runner.state._place_unit(player_id, card_id, slot_index, keywords=keywords)
        slot = runner.state.get_slot(player_id, slot_index)
        slot["status"] = unit.get("status", "active")
        slot["damage"] = int(unit.get("damage", 0))
        slot["turns_on_field"] = int(unit.get("turns_on_field", 1))
        runner.state.recompute_slot_stats(slot)


def _validate_scenario(data):
    if data.get("schema_version") != 1:
        raise ScenarioError("scenario schema_version 必須是 1。")
    target = data.get("target_card")
    if not _known_card(target):
        raise ScenarioError(f"target_card 不存在：{target}")
    normalized = target.split("/")[-1]
    if not normalized.startswith(("ST01-", "ST02-", "ST03-", "ST04-")):
        raise ScenarioError("target_card 必須屬於 ST01-ST04。")
    setup = data.get("setup") or {}
    if setup.get("priority_player", "P1") not in {"P1", "P2"}:
        raise ScenarioError("priority_player 必須是 P1 或 P2。")
    players = data.get("players") or {}
    for player_id in ("P1", "P2"):
        if player_id not in players:
            raise ScenarioError(f"缺少玩家設定：{player_id}")
        _validate_player(players[player_id], player_id)


def _validate_player(spec, player_id):
    base = spec.get("base", "EX-BASE")
    if base and base != "EX-BASE":
        card = _known_card(base)
        if not card or card.get("cardType") != "base":
            raise ScenarioError(f"{player_id} base 不合法：{base}")
    for card_id in _card_list(spec.get("hand", [])) + _card_list(spec.get("trash", [])):
        if not _known_card(card_id):
            raise ScenarioError(f"{player_id} 包含未知卡牌：{card_id}")
    seen_slots = set()
    for unit in spec.get("board") or []:
        slot = int(unit.get("slot", 0))
        if slot < 0 or slot >= config.BATTLE_AREA_SLOTS or slot in seen_slots:
            raise ScenarioError(f"{player_id} board slot 不合法：{slot}")
        seen_slots.add(slot)
        card_id = unit.get("unit")
        card = _known_card(card_id)
        if not card or card.get("cardType") != "unit":
            raise ScenarioError(f"{player_id} board unit 不合法：{card_id}")


def _known_card(card_id):
    from gcg.cards import CardDatabase

    return CardDatabase().get(card_id)


def _card_list(value):
    if value is None:
        return []
    if not isinstance(value, list):
        raise ScenarioError("card list 欄位必須是 list。")
    return [str(item) for item in value]


def _filler_cards(count):
    count = max(0, int(count or 0))
    return ["st01/ST01-009" for _ in range(count)]
