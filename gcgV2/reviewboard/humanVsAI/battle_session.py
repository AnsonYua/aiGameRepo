"""Single local P1 human vs P2 Hermes battle session.

The session is intentionally in-memory and single-game for V1. It wraps the
existing simulator stack but does not call SimulatorRunner.run(); instead it
advances one decision boundary at a time for the mobile UI.
"""

from __future__ import annotations

import copy
import json
import os
import re
import sys
import threading
from pathlib import Path


GCGV2_ROOT = Path(__file__).resolve().parents[2]
if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))

from gcg.engine.command_parser import CommandParser  # noqa: E402
from gcg.sim.bootstrap import build_simulator  # noqa: E402

from .command_labels import build_legal_actions  # noqa: E402


HUMAN_PLAYER = "P1"
AI_PLAYER = "P2"
_CARD_ID_PATTERN = re.compile(r"\bst\d{2}/[A-Z0-9-]+\b")
# AI reasoning markers, e.g. "。 理由：先攻可率先部署…" — the leak vector.
# Everything from the first marker onward is dropped so a hidden card id
# buried in a multiline rationale can never survive into the public message.
_REASONING_MARKERS = ("理由：", "理由:")
_MAX_CHAINED_AUTO_PASSES = 8


def _strip_reasoning(message):
    for marker in _REASONING_MARKERS:
        idx = message.find(marker)
        if idx != -1:
            return message[:idx]
    return message


class HumanVsAiBattleSession:
    def __init__(
        self,
        players_mode=None,
        interpreter_mode=None,
        ai_timeout_seconds=None,
        max_ai_invalid_attempts=2,
        auto_pass_ai_no_move=False,
        reveal_card_names=False,
    ):
        self.players_mode = players_mode or os.getenv("GCG_BATTLE_AI_MODE", "hermes")
        self.interpreter_mode = interpreter_mode or os.getenv("GCG_BATTLE_INTERPRETER", "llm")
        self.ai_timeout_seconds = int(ai_timeout_seconds or os.getenv("GCG_HERMES_TIMEOUT_SECONDS", "60"))
        self.max_ai_invalid_attempts = max(1, int(max_ai_invalid_attempts))
        self.auto_pass_ai_no_move = bool(auto_pass_ai_no_move)
        # When True (V3), public event messages show card names instead of the
        # opaque "卡牌" token and strip the AI free-text 理由 (reasoning), which
        # is the only vector that could leak a hidden hand card. Board/own cards
        # are already public via viewer_state, so naming them is safe.
        self.reveal_card_names = bool(reveal_card_names)

        self._lock = threading.RLock()
        self._generation = 0
        self._worker = None
        self._runner = None
        self._status = "not_started"
        self._error = None
        self._last_message = "尚未開始對戰。"

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    def start(self):
        with self._lock:
            self._generation += 1
            self._runner = self._build_runner()
            self._status = "waiting_human"
            self._error = None
            self._last_message = "對戰開始，請選擇先攻或後攻。"
            self._runner.start_game(decision_player=self._human_player_locked())
            self._advance_and_update_status_locked()
            self._start_ai_worker_if_needed_locked()
            return self._response_locked()

    def state(self):
        with self._lock:
            return self._response_locked()

    def reset(self):
        with self._lock:
            self._generation += 1
            self._runner = None
            self._status = "not_started"
            self._error = None
            self._last_message = "已重置對戰。"
            return self._response_locked()

    def submit_command(self, raw_command):
        if not isinstance(raw_command, str) or not raw_command.strip():
            return self._error_response("缺少 command。")

        with self._lock:
            if self._runner is None or self._status == "not_started":
                return self._error_response_locked("對戰尚未開始。")
            if self._status == "waiting_ai":
                return self._error_response_locked("對手正在思考中，請稍候。")
            if self._status == "game_over":
                return self._error_response_locked("對局已結束。")
            if self._status == "error":
                return self._response_locked()

            self._advance_and_update_status_locked()
            human_player = self._human_player_locked()
            actor, legal_commands, pending_choice = self._current_decision_locked()
            if actor != human_player:
                return self._error_response_locked(f"目前不是 {human_player} 的決策時機。")

            try:
                parsed = CommandParser().parse(raw_command, human_player)
                normalized = parsed.command_line()
                if normalized not in set(legal_commands):
                    raise ValueError(f"指令不在合法清單中：{normalized}")
                if pending_choice is not None:
                    self._runner.runtime.resolve_pending_choice(parsed, pending_choice)
                else:
                    self._runner.runtime.resolve_command(parsed)
            except Exception as exc:  # noqa: BLE001 - API should return JSON error
                self._runner.gameplay_logger.log_invalid_command(
                    game_id=self._runner.game_id,
                    player_id=human_player,
                    raw_command=raw_command,
                    reason=str(exc),
                )
                return self._error_response_locked(f"指令執行失敗：{exc}")

            self._last_message = f"{human_player} 已執行操作。"
            self._advance_and_update_status_locked()
            self._start_ai_worker_if_needed_locked()
            return self._response_locked()

    # ------------------------------------------------------------------
    # setup
    # ------------------------------------------------------------------

    def _build_runner(self):
        runner = build_simulator(
            players=self.players_mode,
            interpreter=self.interpreter_mode,
        )
        if self.players_mode == "hermes" and AI_PLAYER in runner.players:
            runner.players[AI_PLAYER].timeout = self.ai_timeout_seconds
        return runner

    # ------------------------------------------------------------------
    # state / response
    # ------------------------------------------------------------------

    def _response_locked(self):
        if self._runner is None:
            return {
                "ok": self._status != "error",
                "status": self._status,
                "game_id": None,
                "viewer_state": None,
                "legal_commands": [],
                "legal_actions": [],
                "events": [],
                "message": self._last_message,
                "decision_type": "not_started",
                "game_over": False,
                "winner": None,
                "error": self._error,
            }

        human_player = self._human_player_locked()
        viewer_bundle = self._runner.viewer_builder.build_for_player(
            self._runner.state, human_player,
        )
        viewer_state = viewer_bundle["viewer_state"]
        legal_commands = []
        if self._status == "waiting_human":
            actor, legal_commands, _pending_choice = self._current_decision_locked()
            if actor != human_player:
                legal_commands = []

        decision_type = viewer_state.get("decision_type")
        if self._status == "waiting_ai":
            decision_type = "wait"
        elif self._status == "error":
            decision_type = "error"
        elif self._status == "game_over":
            decision_type = "game_over"

        return {
            "ok": self._status != "error",
            "status": self._status,
            "game_id": self._runner.game_id,
            "viewer_state": viewer_state,
            "legal_commands": list(legal_commands),
            "legal_actions": build_legal_actions(
                legal_commands,
                card_db=self._runner.prompt_builder.card_db,
            ),
            "events": self._public_events_locked(),
            "message": self._message_locked(viewer_state),
            "decision_type": decision_type,
            "game_over": self._runner.runtime.is_game_over(),
            "winner": self._runner.runtime.get_winner(),
            "error": self._error,
        }

    def _message_locked(self, viewer_state):
        if self._status == "waiting_ai":
            return "對手思考中..."
        if self._status == "error":
            return self._error or "AI 決策失敗，請重新開始。"
        if self._status == "game_over":
            winner = self._runner.runtime.get_winner()
            return f"對局結束，勝者：{winner}。"
        pending = viewer_state.get("pending_choice") or {}
        if pending.get("visible") and pending.get("message"):
            return pending["message"]
        return self._last_message

    def _public_events_locked(self, limit=16):
        writer = self._runner.gameplay_logger.yaml_writer
        document = writer.get_document(self._runner.game_id)
        events = document.get("events") or []
        public = []
        for event in events[-limit:]:
            public.append({
                "seq": event.get("seq"),
                "turn": event.get("turn"),
                "phase": event.get("phase"),
                "step": event.get("step"),
                "actor": event.get("actor"),
                "event_type": event.get("event_type"),
                "message": self._public_message(event),
                "ok": (event.get("result") or {}).get("ok"),
            })
        return public

    def _public_message(self, event):
        actor = event.get("actor")
        event_type = event.get("event_type")
        if actor == AI_PLAYER and event_type == "command_rejected":
            return "AI 輸出不合法指令，正在重新決策。"
        message = str(event.get("message") or "")
        if self.reveal_card_names:
            # Drop the AI reasoning tail first — it is the only place a hidden
            # hand card id can appear. Then map every remaining (public) card id
            # to its name so the log reads "Demi Trainer 攻擊 Gundam" not
            # "卡牌 attacked 卡牌".
            message = _strip_reasoning(message).strip()
            return _CARD_ID_PATTERN.sub(self._public_card_replacer(event), message)
        return _CARD_ID_PATTERN.sub("卡牌", message)

    def _public_card_replacer(self, event):
        payload = ((event.get("result") or {}).get("payload") or {})
        hidden_card_ids = set(payload.get("hidden_card_ids") or [])

        def replace(match):
            card_id = match.group(0)
            if card_id in hidden_card_ids:
                return "卡牌"
            return self._card_name_replacer(match)

        return replace

    def _card_name_replacer(self, match):
        card_id = match.group(0)
        card_db = self._runner.prompt_builder.card_db if self._runner else None
        if card_db is not None:
            card = card_db.get(card_id)
            name = card.get("name") if card else None
            if name:
                return name
        return card_id

    def card_detail(self, card_id):
        """Public card metadata for the V3 detail sheet. Returns None if the
        card id is unknown. Only exposes display fields, never rules engine
        internals."""
        if self._runner is None or not card_id:
            return None
        card = self._runner.prompt_builder.card_db.get(card_id)
        if card is None:
            return None
        return {
            "id": card.get("id"),
            "name": card.get("name"),
            "cardType": card.get("cardType"),
            "color": card.get("color"),
            "level": card.get("level", 0),
            "cost": card.get("cost", 0),
            "ap": card.get("ap", 0),
            "hp": card.get("hp", 0),
            "zone": list(card.get("zone", [])),
            "traits": list(card.get("traits", [])),
            "link": list(card.get("link", [])),
            "descriptions": list(card.get("effects", {}).get("description", [])),
        }

    def _error_response(self, message):
        with self._lock:
            return self._error_response_locked(message)

    def _error_response_locked(self, message):
        payload = self._response_locked()
        payload["ok"] = False
        payload["error"] = message
        payload["message"] = message
        return payload

    # ------------------------------------------------------------------
    # decision boundaries
    # ------------------------------------------------------------------

    def _advance_and_update_status_locked(self):
        if self._runner is None or self._status == "error":
            return
        self._runner.runtime.advance_until_decision_or_stable()
        if self._runner.runtime.is_game_over():
            self._status = "game_over"
            return
        actor, legal_commands, _pending_choice = self._current_decision_locked()
        if actor == self._human_player_locked():
            self._status = "waiting_human"
        elif actor == AI_PLAYER and legal_commands:
            self._status = "waiting_ai"
        else:
            self._status = "error"
            self._error = "Runtime 無法找到下一個合法決策點。"

    def _current_decision_locked(self):
        if self._runner is None or self._runner.runtime.is_game_over():
            return None, [], None
        pending_choice = self._runner.state.peek_pending_choice()
        if pending_choice is not None:
            actor = pending_choice.get("player_id")
            legal_commands = self._runner.enumerator.pending_choice_commands(pending_choice)
            return actor, legal_commands, pending_choice
        if self._runner.state.needs_action_window():
            actor = self._runner.state.get_priority_player()
            legal_commands = self._runner.enumerator.legal_commands(actor)
            return actor, legal_commands, None
        return None, [], None

    def _human_player_locked(self):
        return HUMAN_PLAYER

    # ------------------------------------------------------------------
    # AI worker
    # ------------------------------------------------------------------

    def _start_ai_worker_if_needed_locked(self):
        if self._status != "waiting_ai":
            return
        if self._worker is not None and self._worker.is_alive():
            return
        generation = self._generation
        self._worker = threading.Thread(
            target=self._ai_worker,
            args=(generation,),
            name="gcg-human-vs-ai-p2",
            daemon=True,
        )
        self._worker.start()

    def _ai_worker(self, generation):
        while True:
            with self._lock:
                task = self._build_ai_task_locked(generation)
            if task is None:
                return

            runner, player, game_id, prompt_payload, legal_commands = task
            resolved = False
            retry_note = None

            for attempt in range(self.max_ai_invalid_attempts):
                payload = copy.deepcopy(prompt_payload)
                if retry_note:
                    payload["error_feedback"] = retry_note

                try:
                    raw_command = player.decide(game_id, AI_PLAYER, payload)
                except Exception as exc:  # noqa: BLE001 - surfaced to UI
                    with self._lock:
                        self._set_ai_error_locked(generation, f"AI 決策失敗，請重新開始：{exc}")
                    return

                with self._lock:
                    validation_error = self._resolve_ai_command_locked(
                        generation, runner, raw_command, legal_commands,
                    )
                    if validation_error is None:
                        resolved = True
                        break

                    if generation != self._generation:
                        return
                    retry_note = (
                        f"你上一個指令不合法：{validation_error}。"
                        "請從 legal_commands 重新選擇。"
                    )

            if not resolved:
                with self._lock:
                    self._set_ai_error_locked(
                        generation,
                        "AI 連續輸出不合法指令，請重新開始。",
                    )
                return

    def _build_ai_task_locked(self, generation):
        auto_passes = 0
        while True:
            if generation != self._generation:
                return None
            if self._runner is None or self._status in {"error", "game_over", "not_started"}:
                return None

            self._advance_and_update_status_locked()
            if self._status != "waiting_ai":
                return None

            actor, legal_commands, pending_choice = self._current_decision_locked()
            if actor != AI_PLAYER or not legal_commands:
                return None

            if (
                self.auto_pass_ai_no_move
                and self.players_mode == "hermes"
                and pending_choice is None
                and legal_commands == ["pass"]
            ):
                if auto_passes >= _MAX_CHAINED_AUTO_PASSES:
                    self._set_ai_error_locked(
                        generation,
                        "AI 自動讓過次數過多，請重新開始。",
                    )
                    return None
                before = self._decision_snapshot_locked()
                try:
                    parsed = CommandParser().parse("pass", AI_PLAYER)
                    self._runner.runtime.resolve_command(parsed)
                except Exception as exc:  # noqa: BLE001 - surfaced to UI
                    self._set_ai_error_locked(generation, f"AI 自動讓過失敗，請重新開始：{exc}")
                    return None
                auto_passes += 1
                self._runner.gameplay_logger.log_system_event(
                    self._runner.game_id,
                    "auto_progress",
                    {"message": "P2 自動讓過（沒有可用操作）。"},
                )
                self._last_message = "P2 沒有可用操作，自動讓過。"
                after = self._decision_snapshot_locked()
                if after == before:
                    self._set_ai_error_locked(
                        generation,
                        "AI 自動讓過未推進對局，請重新開始。",
                    )
                    return None
                continue

            viewer_bundle = self._runner.viewer_builder.build_for_player(
                self._runner.state, AI_PLAYER,
            )
            prompt_payload = self._runner.prompt_builder.build(viewer_bundle, legal_commands)
            return (
                self._runner,
                self._runner.players[AI_PLAYER],
                self._runner.game_id,
                prompt_payload,
                list(legal_commands),
            )

    def _decision_snapshot_locked(self):
        if self._runner is None:
            return None
        raw_state = self._runner.state.get_state()
        action_window = raw_state.get("action_window") or {}
        return (
            raw_state.get("turn"),
            raw_state.get("phase"),
            raw_state.get("step"),
            raw_state.get("active_player"),
            raw_state.get("priority_player"),
            json.dumps(action_window, sort_keys=True, ensure_ascii=False),
        )

    def _resolve_ai_command_locked(self, generation, runner, raw_command, legal_commands):
        if generation != self._generation:
            return None
        if self._runner is None or self._runner is not runner:
            return "對局不存在。"

        actor, current_legal, pending_choice = self._current_decision_locked()
        if actor != AI_PLAYER:
            return "目前不是 P2 的決策時機。"
        if set(current_legal) != set(legal_commands):
            return "AI 決策期間合法指令清單已變更。"

        try:
            parsed = CommandParser().parse(raw_command, AI_PLAYER)
            normalized = parsed.command_line()
            if normalized not in set(legal_commands):
                return "指令不在合法清單中。"
            if pending_choice is not None:
                self._runner.runtime.resolve_pending_choice(parsed, pending_choice)
            else:
                self._runner.runtime.resolve_command(parsed)
        except Exception as exc:  # noqa: BLE001 - retry/error path
            return str(exc)

        self._last_message = "P2 已完成決策。"
        self._advance_and_update_status_locked()
        if self._status == "waiting_ai":
            return None
        return None

    def _set_ai_error_locked(self, generation, message):
        if generation != self._generation:
            return
        self._status = "error"
        self._error = message
        self._last_message = message


class ManualBattleSession(HumanVsAiBattleSession):
    """Dev/test session where both players are manually controlled."""

    def _human_player_locked(self):
        if self._runner is None or self._runner.state.get_state() is None:
            return HUMAN_PLAYER
        actor, _legal_commands, _pending_choice = self._current_decision_locked()
        return actor if actor in {"P1", "P2"} else HUMAN_PLAYER

    def _start_ai_worker_if_needed_locked(self):
        return
