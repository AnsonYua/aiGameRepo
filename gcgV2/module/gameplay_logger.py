"""
Lean pseudo class for the V2 gameplay logger.

This file is intentionally simple.
It shows how gamePlay.yaml should be written.
"""

from datetime import datetime


class GameplayLogger:
    """
    Writer for canonical gamePlay.yaml events.

    Responsibilities:
    - open one game log
    - append structured events
    - keep seq increasing
    - include message, result, and features snapshot

    Non-responsibilities:
    - do not mutate game state
    - do not decide rules
    - do not dump hidden raw state
    """

    def __init__(self, yaml_writer, state_store):
        self.yaml_writer = yaml_writer
        self.state_store = state_store

        self.current_game_id = None
        self.seq = 0

    def open_game(self, game_id):
        """
        Create a new gamePlay.yaml document.
        """
        self.current_game_id = game_id
        self.seq = 0
        self.yaml_writer.create_gameplay_log(
            game_id=game_id,
            schema_version="2.0",
        )

    def log_system_event(self, game_id, event_type, payload):
        """
        Append a generic system event.

        Example:
        - game_started
        - phase_changed
        - agent_server_init
        """
        features = payload.get("features")
        if features is None:
            features = self.state_store.build_snapshot()

        event = self._build_event(
            game_id=game_id,
            event_type=event_type,
            actor="system",
            viewer="P1",
            message=payload.get("message", event_type),
            result={
                "ok": True,
                "reason": "",
                "payload": payload,
            },
            features=features,
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_command_resolved(self, game_id, parsed_command, resolved_intent):
        """
        Append one resolved player command event.

        Example:
        - P1 plays GD01-008
        - chooses p2_slot_1
        - deals 1 damage
        """
        event = self._build_event(
            game_id=game_id,
            event_type="command_resolved",
            actor=parsed_command.player_id,
            viewer=parsed_command.player_id,
            message=resolved_intent.public_message,
            command={
                "raw": parsed_command.raw_text,
                "parsed": parsed_command.to_dict(),
            },
            intent=resolved_intent.to_dict(),
            result={
                "ok": True,
                "reason": "",
                "state_changes": resolved_intent.state_changes,
            },
            features=self.state_store.build_snapshot(),
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_invalid_command(self, game_id, parsed_command, reason):
        """
        Append one invalid command event.
        """
        event = self._build_event(
            game_id=game_id,
            event_type="command_rejected",
            actor=parsed_command.player_id,
            viewer=parsed_command.player_id,
            message=f"指令不合法：{reason}",
            command={
                "raw": parsed_command.raw_text,
                "parsed": parsed_command.to_dict(),
            },
            result={
                "ok": False,
                "reason": reason,
            },
            features=self.state_store.build_snapshot(),
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_pending_choice(self, game_id, choice):
        """
        Append one pending choice event.

        Example:
        - choose 1 rested enemy Unit
        - choose order of 2 triggers
        - choose whether to use optional effect
        """
        event = self._build_event(
            game_id=game_id,
            event_type="pending_choice_created",
            actor="system",
            viewer=choice["player_id"],
            message=choice["message"],
            result={
                "ok": True,
                "reason": "",
                "created_pending_choice": choice,
            },
            features=self.state_store.build_snapshot(),
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_trigger_resolved(self, game_id, trigger_context, trigger_spec):
        """
        Append one resolved trigger event.
        """
        event = self._build_event(
            game_id=game_id,
            event_type="trigger_resolved",
            actor="system",
            viewer="P1",
            message=trigger_spec.public_message,
            result={
                "ok": True,
                "reason": "",
                "state_changes": trigger_spec.state_changes,
            },
            trigger={
                "context": trigger_context,
                "spec": trigger_spec.to_dict(),
            },
            features=self.state_store.build_snapshot(),
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_trigger_skipped(self, game_id, trigger_context, reason):
        """
        Append one skipped trigger event.
        """
        event = self._build_event(
            game_id=game_id,
            event_type="trigger_skipped",
            actor="system",
            viewer="P1",
            message=f"Trigger 未解決：{reason}",
            result={
                "ok": False,
                "reason": reason,
            },
            trigger={
                "context": trigger_context,
            },
            features=self.state_store.build_snapshot(),
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def log_rule_event(self, game_id, rule_event):
        """
        Append one automatic rule event.

        Example:
        - damaged Unit is destroyed
        - shield breaks
        - game over is detected
        """
        event = self._build_event(
            game_id=game_id,
            event_type="rule_event",
            actor="system",
            viewer="P1",
            message=rule_event["message"],
            result={
                "ok": True,
                "reason": "",
                "state_changes": rule_event["state_changes"],
            },
            features=self.state_store.build_snapshot(),
        )
        self.yaml_writer.append_event(game_id=game_id, event=event)

    def get_path(self, game_id):
        """
        Return the gamePlay.yaml path for one game.
        """
        return self.yaml_writer.get_gameplay_path(game_id)

    def _build_event(
        self,
        game_id,
        event_type,
        actor,
        viewer,
        message,
        result,
        features,
        command=None,
        intent=None,
        trigger=None,
    ):
        """
        Build one structured event record.
        """
        self.seq += 1
        event = {
            "seq": self.seq,
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "turn": features.get("turn"),
            "phase": features.get("phase"),
            "step": features.get("step"),
            "actor": actor,
            "viewer": viewer,
            "event_type": event_type,
            "public": True,
            "message": message,
            "result": result,
            "features": features,
        }
        if command is not None:
            event["command"] = command
        if intent is not None:
            event["intent"] = intent
        if trigger is not None:
            event["trigger"] = trigger
        return event


if __name__ == "__main__":
    # Pseudo bootstrap only.
    # Real wiring should provide concrete implementations.
    yaml_writer = None
    state_store = None

    gameplay_logger = GameplayLogger(
        yaml_writer=yaml_writer,
        state_store=state_store,
    )

    # Example:
    # gameplay_logger.open_game("game_20260608_021028_537485")
    # print(gameplay_logger.get_path("game_20260608_021028_537485"))
