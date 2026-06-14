"""Canonical gamePlay.yaml event logger.

- features 來自 state_store 的 gameplay snapshot（public snapshot + 雙方手牌明細，
  供 review/debug 用；此檔不可餵給 AI prompt）
- seq 單調遞增
- close_game 會 finalize summary（status / winner / win_reason）
"""

from __future__ import annotations

from datetime import datetime


class GameplayLogger:
    def __init__(self, yaml_writer, state_store):
        self.yaml_writer = yaml_writer
        self.state_store = state_store
        self.current_game_id = None
        self.seq = 0

    def open_game(self, game_id):
        self.current_game_id = game_id
        self.seq = 0
        self.yaml_writer.create_gameplay_log(game_id=game_id, schema_version="2.0")

    def close_game(self, game_id, status, winner=None, win_reason=None):
        self.yaml_writer.finalize(
            game_id=game_id, status=status, winner=winner, win_reason=win_reason,
        )

    def log_system_event(self, game_id, event_type, payload):
        event = self._build_event(
            game_id=game_id,
            event_type=event_type,
            actor="system",
            message=payload.get("message", event_type),
            result={"ok": True, "reason": "", "payload": {
                key: value for key, value in payload.items() if key != "message"
            }},
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_command_event(self, game_id, parsed_command, message):
        event = self._build_event(
            game_id=game_id,
            event_type="command_resolved",
            actor=parsed_command.player_id,
            message=message,
            command={"raw": parsed_command.raw_text, "parsed": parsed_command.to_dict()},
            result={"ok": True, "reason": "", "consider": parsed_command.consider},
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_invalid_command(self, game_id, player_id, raw_command, reason):
        event = self._build_event(
            game_id=game_id,
            event_type="command_rejected",
            actor=player_id,
            message=f"指令不合法：{reason}",
            command={"raw": raw_command},
            result={"ok": False, "reason": reason},
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_pending_choice(self, game_id, choice):
        public_choice = {
            "type": choice.get("type"),
            "player_id": choice.get("player_id"),
            "message": choice.get("message"),
        }
        if not choice.get("hidden_options"):
            public_choice["options"] = [
                {"id": option.get("id"), "label": option.get("label")}
                for option in choice.get("options", [])
            ]
        event = self._build_event(
            game_id=game_id,
            event_type="pending_choice_created",
            actor="system",
            message=choice.get("message", "等待玩家選擇"),
            result={"ok": True, "reason": "", "created_pending_choice": public_choice},
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_trigger_skipped(self, game_id, trigger_context, reason):
        public_context = {
            key: trigger_context.get(key)
            for key in ("timing", "controller", "card_id", "source_slot", "source_zone")
        }
        event = self._build_event(
            game_id=game_id,
            event_type="trigger_skipped",
            actor="system",
            message=f"Trigger 未解決：{reason}",
            result={"ok": False, "reason": reason},
            trigger={"context": public_context},
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def get_path(self, game_id):
        return self.yaml_writer.get_gameplay_path(game_id)

    def _build_event(
        self,
        game_id,
        event_type,
        actor,
        message,
        result,
        command=None,
        trigger=None,
    ):
        features = self.state_store.build_gameplay_snapshot()
        self.seq += 1
        event = {
            "seq": self.seq,
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "turn": features.get("turn"),
            "phase": features.get("phase"),
            "step": features.get("step"),
            "actor": actor,
            "event_type": event_type,
            "public": True,
            "message": message,
            "result": result,
            "features": features,
        }
        if command is not None:
            event["command"] = command
        if trigger is not None:
            event["trigger"] = trigger
        return event
