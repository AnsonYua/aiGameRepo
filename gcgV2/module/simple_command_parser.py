"""
Minimal command parser for GCG V2 bootstrap flow and common action grammar.

This parser intentionally stays grammar-only:
- opening choices such as `choose go_first`
- common action forms such as `play_card`, `activate_effect`, `attack`, `block`
- utility forms such as `pass`, `order_triggers`, `decline_optional`

It returns a stable parsed object shape that runtime_core can inspect.
"""

from dataclasses import dataclass, field


@dataclass
class ParsedCommand:
    raw_text: str
    player_id: str
    command_type: str
    choice_id: str | None = None
    source_ref: str | None = None
    target_ref: str | None = None
    target_refs: list[str] = field(default_factory=list)
    card_id: str | None = None
    trigger_refs: list[str] = field(default_factory=list)
    optional_ref: str | None = None
    args: list[str] = field(default_factory=list)

    def to_dict(self):
        data = {
            "raw_text": self.raw_text,
            "player_id": self.player_id,
            "command_type": self.command_type,
            "action": self.command_type,
            "choice_id": self.choice_id,
            "source_ref": self.source_ref,
            "target_ref": self.target_ref,
            "target_refs": list(self.target_refs),
            "card_id": self.card_id,
            "trigger_refs": list(self.trigger_refs),
            "optional_ref": self.optional_ref,
            "args": list(self.args),
        }
        return {key: value for key, value in data.items() if value not in (None, [], "")}


class SimpleCommandParser:
    """
    Small parser for bootstrap-safe and common action grammar.
    """

    def parse(self, raw_command, viewer_bundle):
        if not isinstance(raw_command, str):
            raise ValueError("raw_command must be a string")

        command_text = raw_command.strip()
        if not command_text:
            raise ValueError("raw_command must not be empty")

        viewer_state = viewer_bundle.get("viewer_state", {})
        player_id = viewer_state.get("viewer_player")
        if not player_id:
            raise ValueError("viewer_bundle missing viewer_state.viewer_player")

        tokens = command_text.split()
        head = tokens[0].lower()

        if head == "choose":
            if len(tokens) != 2:
                raise ValueError("choose command must be: choose <option_id>")
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="choose",
                choice_id=tokens[1],
            )

        if head == "play_card":
            return self._parse_source_and_targets(
                command_text=command_text,
                player_id=player_id,
                command_type="play_card",
                tokens=tokens,
            )

        if head == "activate_effect":
            return self._parse_source_and_targets(
                command_text=command_text,
                player_id=player_id,
                command_type="activate_effect",
                tokens=tokens,
            )

        if head == "attack":
            if len(tokens) < 3:
                raise ValueError("attack command must be: attack <attacker_ref> <target_ref>")
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="attack",
                source_ref=tokens[1],
                target_ref=tokens[2],
                target_refs=tokens[2:3],
                args=tokens[3:],
            )

        if head == "block":
            if len(tokens) < 3:
                raise ValueError("block command must be: block <blocker_ref> <attacker_ref>")
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="block",
                source_ref=tokens[1],
                target_ref=tokens[2],
                target_refs=tokens[2:3],
                args=tokens[3:],
            )

        if head == "pass":
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="pass",
            )

        if head == "order_triggers":
            if len(tokens) < 2:
                raise ValueError(
                    "order_triggers command must be: order_triggers <trigger_ref> [more_refs...]"
                )
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="order_triggers",
                trigger_refs=tokens[1:],
            )

        if head == "decline_optional":
            optional_ref = tokens[1] if len(tokens) > 1 else None
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="decline_optional",
                optional_ref=optional_ref,
                args=tokens[2:] if len(tokens) > 2 else [],
            )

        raise ValueError(f"unsupported command for SimpleCommandParser: {command_text}")

    def _parse_source_and_targets(self, command_text, player_id, command_type, tokens):
        if len(tokens) < 2:
            raise ValueError(f"{command_type} command must include a source ref")

        source_ref = tokens[1]
        card_id = source_ref if "/" in source_ref else None
        target_refs = []
        args = []
        index = 2

        while index < len(tokens):
            token = tokens[index]
            if token == "target":
                index += 1
                if index >= len(tokens):
                    raise ValueError(
                        f"{command_type} command has 'target' without a following target ref"
                    )
                while index < len(tokens) and tokens[index] != "target":
                    target_refs.append(tokens[index])
                    index += 1
                continue

            args.append(token)
            index += 1

        return ParsedCommand(
            raw_text=command_text,
            player_id=player_id,
            command_type=command_type,
            source_ref=source_ref,
            target_ref=target_refs[0] if target_refs else None,
            target_refs=target_refs,
            card_id=card_id,
            args=args,
        )
