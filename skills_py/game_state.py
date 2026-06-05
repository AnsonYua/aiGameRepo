import random
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BaseState:
    card_id: str = "EX-BASE"
    ap: int = 0
    hp: int = 3
    damage: int = 0
    alive: bool = True
    status: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "card_id": self.card_id, "ap": self.ap, "hp": self.hp,
            "damage": self.damage, "alive": self.alive, "status": self.status
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BaseState":
        return cls(**{k: d.get(k, v) for k, v in cls().to_dict().items()})


@dataclass
class BattleSlot:
    slot: int
    unit_id: Optional[str] = None
    pilot_id: Optional[str] = None
    ap: int = 0
    hp: int = 0
    damage: int = 0
    status: Optional[str] = None
    keywords: list = field(default_factory=list)
    link: bool = False
    turns_on_field: int = 0

    def to_dict(self) -> dict:
        return {
            "slot": self.slot, "unit_id": self.unit_id, "pilot_id": self.pilot_id,
            "ap": self.ap, "hp": self.hp, "damage": self.damage,
            "status": self.status, "keywords": list(self.keywords),
            "link": self.link, "turns_on_field": self.turns_on_field
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BattleSlot":
        return cls(
            slot=d.get("slot", 0), unit_id=d.get("unit_id"), pilot_id=d.get("pilot_id"),
            ap=d.get("ap", 0), hp=d.get("hp", 0), damage=d.get("damage", 0),
            status=d.get("status"), keywords=d.get("keywords", []),
            link=d.get("link", False), turns_on_field=d.get("turns_on_field", 0)
        )


@dataclass
class PlayerState:
    player_id: str
    base: BaseState = field(default_factory=BaseState)
    shields: int = 0
    shield_cards: list = field(default_factory=list)
    hand_cards: list = field(default_factory=list)
    deck_cards: list = field(default_factory=list)
    deck_count: int = 45
    resource_deck_count: int = 10
    resources_active: int = 0
    resources_rested: int = 0
    resources_ex: int = 0
    battle_area: list = field(default_factory=lambda: [
        BattleSlot(slot=i) for i in range(6)
    ])
    trash: list = field(default_factory=list)
    removal: list = field(default_factory=list)

    @property
    def level(self) -> int:
        return self.resources_active + self.resources_rested + self.resources_ex

    @property
    def occupied_slots(self) -> int:
        return sum(1 for s in self.battle_area if s.unit_id is not None)

    @property
    def hand_count(self) -> int:
        return len(self.hand_cards)

    def to_dict(self, hide_hand: bool = False, include_private: bool = False):
        return {
            "base": self.base.to_dict(),
            "shields": self.shields,
            "shield_cards": list(self.shield_cards) if include_private else ["Unknown"] * len(self.shield_cards),
            "hand_count": len(self.hand_cards),
            "hand_cards": (["Unknown"] * len(self.hand_cards)) if hide_hand else list(self.hand_cards),
            "deck_cards": list(self.deck_cards),
            "deck_count": len(self.deck_cards) if self.deck_cards else self.deck_count,
            "resource_deck_count": self.resource_deck_count,
            "resources": {
                "active": self.resources_active,
                "rested": self.resources_rested,
                "ex": self.resources_ex
            },
            "battle_area": [s.to_dict() for s in self.battle_area],
            "trash": list(self.trash),
            "removal": list(self.removal)
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PlayerState":
        p = cls(player_id="")
        ba = d.get("battle_area", [])
        p.battle_area = [BattleSlot.from_dict(s) for s in ba] if ba else [BattleSlot(slot=i) for i in range(6)]
        res = d.get("resources", {})
        p.resources_active = res.get("active", 0)
        p.resources_rested = res.get("rested", 0)
        p.resources_ex = res.get("ex", 0)
        p.hand_cards = d.get("hand_cards", [])
        p.deck_cards = d.get("deck_cards", [])
        p.deck_count = d.get("deck_count", 0)
        p.resource_deck_count = d.get("resource_deck_count", 0)
        p.shields = d.get("shields", 0)
        p.shield_cards = d.get("shield_cards", [])
        p.trash = d.get("trash", [])
        p.removal = d.get("removal", [])
        p.base = BaseState.from_dict(d.get("base", {}))
        return p


@dataclass
class GameState:
    game_id: str = ""
    turn: int = 0
    first_player: str = ""
    active_player: str = ""
    phase: str = "pre-game"
    step: Optional[str] = None
    current_attacker: Optional[int] = None
    priority: Optional[str] = None
    p1: PlayerState = field(default_factory=lambda: PlayerState(player_id="P1"))
    p2: PlayerState = field(default_factory=lambda: PlayerState(player_id="P2"))
    active_effects: list = field(default_factory=list)
    battle_log: list = field(default_factory=list)
    game_over: bool = False
    winner: Optional[str] = None

    def get_player(self, pid: str) -> PlayerState:
        return self.p1 if pid == "P1" else self.p2

    def get_opponent(self, pid: str) -> PlayerState:
        return self.p2 if pid == "P1" else self.p1

    def get_active(self) -> PlayerState:
        return self.get_player(self.active_player)

    def to_dict(self, viewer: str = "P1") -> dict:
        hide_p1 = viewer == "P2"
        hide_p2 = viewer == "P1"
        include_private = viewer == "none"
        return {
            "game_id": self.game_id,
            "turn": self.turn,
            "first_player": self.first_player,
            "active_player": self.active_player,
            "phase": self.phase,
            "step": self.step,
            "current_attacker": self.current_attacker,
            "priority": self.priority,
            "p1": self.p1.to_dict(hide_hand=hide_p1, include_private=include_private),
            "p2": self.p2.to_dict(hide_hand=hide_p2, include_private=include_private),
            "active_effects": list(self.active_effects),
            "battle_log": list(self.battle_log),
            "game_over": self.game_over,
            "winner": self.winner
        }

    def to_yaml_lines(self, viewer: str = "P1") -> list[str]:
        d = self.to_dict(viewer)
        import yaml
        return yaml.dump(d, allow_unicode=True, default_flow_style=False).split("\n")

    @classmethod
    def from_dict(cls, d: dict) -> "GameState":
        gs = cls()
        gs.game_id = d.get("game_id", "")
        gs.turn = d.get("turn", 0)
        gs.first_player = d.get("first_player", "")
        gs.active_player = d.get("active_player", "")
        gs.phase = d.get("phase", "pre-game")
        gs.step = d.get("step")
        gs.current_attacker = d.get("current_attacker")
        gs.priority = d.get("priority")
        gs.p1 = PlayerState.from_dict(d.get("p1", {}))
        gs.p1.player_id = "P1"
        gs.p2 = PlayerState.from_dict(d.get("p2", {}))
        gs.p2.player_id = "P2"
        gs.active_effects = d.get("active_effects", [])
        gs.battle_log = d.get("battle_log", [])
        gs.game_over = d.get("game_over", False)
        gs.winner = d.get("winner")
        return gs
