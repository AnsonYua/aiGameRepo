"""Command grammar parser（grammar-only，不做合法性檢查）。

V2 command surface（AI 與 runtime 的 contract）：

- ``choose <option_id>``                  回答 pending choice
- ``play_card <card_id> [<slot>]``        部署 Unit（slot）/ 使用 Command 卡（無 slot）
- ``pair <card_id> my_slot_<n>``          配對 Pilot（或 pilot designation command）
- ``activate_effect <source_ref>``        啟動型能力（例如 base 的 [Activate/Main]）
- ``attack my_slot_<n> <target_ref>``     target = opponent_base | opponent_slot_<n>
- ``block my_slot_<n>``                   以 Blocker 阻擋當前攻擊
- ``pass``                                讓過 / 結束主要階段
- ``end turn``                            視為 pass 的別名

輸入可以是兩行格式（CONSIDER: / COMMAND:），parser 會抽出 command 行。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedCommand:
    raw_text: str
    player_id: str
    command_type: str
    consider: str | None = None
    choice_id: str | None = None
    source_ref: str | None = None
    target_ref: str | None = None
    card_id: str | None = None
    args: list[str] = field(default_factory=list)

    def to_dict(self):
        data = {
            "raw_text": self.raw_text,
            "player_id": self.player_id,
            "command_type": self.command_type,
            "action": self.command_type,
            "consider": self.consider,
            "choice_id": self.choice_id,
            "source_ref": self.source_ref,
            "target_ref": self.target_ref,
            "card_id": self.card_id,
            "args": list(self.args),
        }
        return {key: value for key, value in data.items() if value not in (None, [], "")}

    def command_line(self):
        """回傳正規化後的單行指令（不含 CONSIDER）。"""
        parts = [self.command_type if self.command_type != "end_turn" else "pass"]
        if self.command_type == "choose":
            parts.append(self.choice_id)
        elif self.command_type in {"play_card", "pair", "activate_effect", "attack", "block"}:
            if self.source_ref:
                parts.append(self.source_ref)
            if self.target_ref:
                parts.append(self.target_ref)
            parts.extend(self.args)
        return " ".join(str(part) for part in parts if part)


class CommandParser:
    def parse(self, raw_command, player_id):
        if not isinstance(raw_command, str):
            raise ValueError("raw_command must be a string")
        command_text = raw_command.strip()
        if not command_text:
            raise ValueError("raw_command must not be empty")
        if not player_id:
            raise ValueError("player_id is required")

        consider, executable = self._extract_structured_fields(command_text)
        tokens = executable.split()
        head = tokens[0].lower()

        if head == "choose":
            if len(tokens) != 2:
                raise ValueError("choose command must be: choose <option_id>")
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="choose",
                consider=consider,
                choice_id=tokens[1],
            )

        if head == "play_card":
            if len(tokens) < 2:
                raise ValueError("play_card command must be: play_card <card_id> [<slot>]")
            source_ref = tokens[1]
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="play_card",
                consider=consider,
                source_ref=source_ref,
                card_id=source_ref,
                args=tokens[2:],
            )

        if head == "pair":
            if len(tokens) != 3:
                raise ValueError("pair command must be: pair <card_id> my_slot_<n>")
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="pair",
                consider=consider,
                source_ref=tokens[1],
                card_id=tokens[1],
                target_ref=tokens[2],
            )

        if head == "activate_effect":
            if len(tokens) < 2:
                raise ValueError("activate_effect command must be: activate_effect <source_ref>")
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="activate_effect",
                consider=consider,
                source_ref=tokens[1],
                args=tokens[2:],
            )

        if head == "attack":
            if len(tokens) < 3:
                raise ValueError("attack command must be: attack <attacker_ref> <target_ref>")
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="attack",
                consider=consider,
                source_ref=tokens[1],
                target_ref=tokens[2],
                args=tokens[3:],
            )

        if head == "block":
            if len(tokens) < 2:
                raise ValueError("block command must be: block my_slot_<n>")
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="block",
                consider=consider,
                source_ref=tokens[1],
                args=tokens[2:],
            )

        if head == "pass":
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="pass",
                consider=consider,
            )

        if head == "end" and len(tokens) >= 2 and tokens[1].lower() == "turn":
            return ParsedCommand(
                raw_text=command_text,
                player_id=player_id,
                command_type="pass",
                consider=consider,
            )

        raise ValueError(f"unsupported command: {executable}")

    def _extract_structured_fields(self, command_text):
        consider = None
        command = None
        for raw_line in command_text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lowered = line.lower()
            if lowered.startswith("consider:") or lowered.startswith("reason:"):
                consider = line.split(":", 1)[1].strip() or None
            elif lowered.startswith("command:"):
                command = line.split(":", 1)[1].strip() or None
        if command:
            return consider, command
        return consider, command_text


def parse_slot_ref(ref):
    """解析 my_slot_3 / opponent_slot_2 / slot_1 / 3 → int。"""
    if ref is None:
        raise ValueError("缺少欄位參照。")
    raw = str(ref).strip().lower()
    for prefix in ("my_slot_", "opponent_slot_", "slot_"):
        if raw.startswith(prefix):
            raw = raw[len(prefix):]
            break
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"無法解析欄位參照：{ref}") from exc


def parse_attack_target_ref(ref):
    """回傳 (kind, slot)：kind ∈ {base, unit}。"""
    target = str(ref).strip().lower()
    if target in {"opponent_base", "base", "opponent_player", "player"}:
        return "base", None
    return "unit", parse_slot_ref(target)
