# GCG AI Player — Python Implementation Specification

## Overview

This specification defines the `GCGAI` class to be implemented in `gcg_simulation.py` (or a separate `gcg_ai.py` module). The AI makes autonomous decisions at every game phase by reading `game_state.md`, evaluating card data from `card/data/`, applying experience modifiers from `experience/*.yaml`, and outputting a single valid command string per invocation.

---

## 1. Data Structures

### 1.1 GameState (parsed from YAML)

```python
@dataclass
class GameState:
    turn: int
    first_player: str           # "P1" | "P2"
    active_player: str          # "P1" | "P2"
    phase: str                  # "pre-game" | "start" | "draw" | "resource" | "main" | "battle" | "end"
    step: str | None            # battle: "attack"|"block"|"action"|"damage"|"battle_end"; end: "action"|"cleanup"
    current_attacker: int | None
    priority: str | None        # "P1" | "P2" | None
    game_over: bool
    winner: str | None
    battle_log: list[str]
    active_effects: list[dict]
    # Players
    p1: PlayerState
    p2: PlayerState

@dataclass
class PlayerState:
    base: BaseState
    shields: list[dict] | int   # list of {card_id, revealed} or int count
    hand_cards: list[dict]      # [{"card_id": "ST01-005"}, ...] or ["Unknown", ...]
    hand_count: int
    deck_count: int
    resource_deck_count: int
    resources: ResourceState
    battle_area: list[SlotState]
    trash: list[str]
    removal: list[str]
    deck_order: list[str] | None

@dataclass
class BaseState:
    card_id: str
    ap: int
    hp: int
    max_hp: int
    damage: int
    alive: bool
    status: str | None           # "active" | "rested" | None

@dataclass
class ResourceState:
    active: int
    rested: int
    ex: int

@dataclass
class SlotState:
    slot: int
    unit_id: str | None
    pilot_id: str | None
    ap: int
    hp: int
    damage: int
    status: str | None          # "active" | "rested" | None
    keywords: list[str]
    link: bool
    deployed_turn: int | None   # Note: schema calls it `deployed_turn`, not `turns_on_field`
```

**Mapping for `turns_on_field`**: The `deployed_turn` field stores the turn when the unit was deployed. `turns_on_field = current_turn - deployed_turn`. A unit deployed this turn has `turns_on_field = 0`.

### 1.2 CardData (from card/data/st01Card.json + any set)

```python
@dataclass
class CardData:
    id: str                     # e.g. "ST01-005"
    name: str
    card_type: str              # "unit" | "pilot" | "command" | "base"
    color: str
    level: int
    cost: int
    zone: list[str]             # ["Space", "Earth"]
    traits: list[str]
    link: list[str]             # Pilot names this unit can link with
    ap: int
    hp: int
    effects: CardEffects        # parsed from effects.rules[]
    # For dual-purpose [Pilot] cards (Commands with pilot_designation effect):
    pilot_ap: int | None        # AP when deployed as Pilot
    pilot_hp: int | None        # HP when deployed as Pilot
    pilot_name: str | None      # Pilot name if deployable as Pilot

@dataclass
class CardEffects:
    description: list[str]      # Human-readable effect text
    rules: list[EffectRule]     # Structured effect rules
    
@dataclass
class EffectRule:
    effect_id: str
    type: str                   # "triggered" | "continuous" | "activated" | "play" | "special"
    action: str                 # "heal", "damage", "modifyAP", "draw", "rest", "deploy", etc.
    timing: dict                # {eventTrigger, duration, activationWindows, ...}
    target: dict                # {type, scope, filters, count}
    parameters: dict            # {value, cost, ...}
    source_conditions: list | None
    conditions: list | None
    restrictions: list | None   # ["once_per_turn", ...]
    cost: dict | None           # {resource: int, rest: str, oncePerTurn: bool}
```

### 1.3 ExperienceRule (parsed from experience/*.yaml)

```python
@dataclass
class ExperienceRule:
    id: str
    priority: int                # 1-10, higher = more important
    description: str
    condition: dict              # {my_units_min, enemy_units_min, turn_max, ...}
    effect: dict                 # {score_bonus: [...], attack_target: str, desperate_play: bool}
```

---

## 2. AI Class Architecture

```python
class GCGAI:
    """
    Autonomous AI decision engine for GCG.
    
    Usage:
        ai = GCGAI(player_id="P2", first_player="P1")
        ai.load_state(game_state_dict)      # from parsed YAML
        command = ai.decide()              # returns single command string
    """
    
    def __init__(self, player_id: str, first_player: str):
        self.player_id = player_id                    # "P1" | "P2"
        self.first_player = first_player              # "P1" | "P2"
        self.me: str = "p1" if player_id == "P1" else "p2"
        self.opponent: str = "p2" if player_id == "P1" else "p1"
        self.is_first_player: bool = (player_id == first_player)
        self.state: GameState | None = None
        self.card_data: dict[str, CardData] = {}      # Loaded from card/data/*.json
        self.experience_rules: list[ExperienceRule] = []  # Loaded from experience/*.yaml
        self.load_card_data()
        self.load_experience_rules()
    
    def decide(self) -> str:
        """Main entry point: reads current state, returns one command."""
        ...
```

---

## 3. Phase-Level Decision Mapping

### 3.1 Phase Dispatch

```python
def decide(self) -> str:
    phase = self.state.phase
    
    if self.state.game_over:
        return ""  # No command needed
    
    # --- Pre-game ---
    if phase == "pre-game":
        return self._decide_mulligan()
    
    # --- Auto-advance phases (no player choice) ---
    if phase == "start":
        return "pass"
    if phase == "draw":
        return "draw"
    if phase == "resource":
        return "resource"
    
    # --- Main phase ---
    if phase == "main":
        return self._decide_main()
    
    # --- Battle phase ---
    if phase == "battle":
        return self._decide_battle()
    
    # --- End phase ---
    if phase == "end":
        return self._decide_end()
    
    return "pass"
```

### 3.2 Pre-game (Mulligan) — `_decide_mulligan()`

Condition: only called when `self.state.priority == self.player_id`.

```python
def _decide_mulligan(self) -> str:
    """
    Keep or redraw based on hand quality.
    
    Scoring criteria (positive = keep; negative = redraw):
      +15  Have at least 1 unit card with level <= current max level (Lv budget)
      +10  Have at least 1 pilot that matches a unit in hand
      +8   Have at least 1 low-cost unit (cost <= 2)
      +5   Have a mix of unit and command cards
      +3   Have a base card (strategic flexibility)
      -10  No unit cards at all
      -8   All cards are level > (current max resources in 2 turns)
            i.e. level > (expected active by turn 2)
      -5   Only 1 playable card
    
    Threshold:
      score >= 10 → keep
      score < 10 → redraw (except never redraw if hand has 3+ units)
    """
    hand = self._my_hand_ids()
    if not hand:
        return "keep"
    
    # Expected Lv budget = 2 (turn 2 after 2 resources)
    expected_lv_by_t2 = 2
    
    score = 0
    has_unit = any(self.card_data[c].card_type == "unit" for c in hand)
    has_pilot = any(self.card_data[c].card_type == "pilot" for c in hand)
    has_command = any(self.card_data[c].card_type == "command" for c in hand)
    has_base = any(self.card_data[c].card_type == "base" for c in hand)
    
    unit_cards = [c for c in hand if self.card_data[c].card_type == "unit"]
    low_cost_units = [c for c in unit_cards if self.card_data[c].cost <= 2]
    playable_by_t2 = [c for c in hand if self.card_data[c].level <= expected_lv_by_t2]
    
    # Unit presence checks
    if len(unit_cards) >= 3:
        return "keep"  # Never redraw with 3+ units
    if has_unit:
        score += 15
    else:
        score -= 10
    
    # Pilot availability
    if has_pilot:
        # Check if any pilot matches a unit in hand
        for pid in [c for c in hand if self.card_data[c].card_type == "pilot"]:
            pilot_name = self.card_data[pid].name
            for uid in unit_cards:
                if pilot_name in self.card_data[uid].link:
                    score += 10
                    break
    
    # Low cost units
    if low_cost_units:
        score += 8
    
    # Card type diversity
    if has_unit and has_command:
        score += 5
    
    # Base card
    if has_base:
        score += 3
    
    # Curve check
    high_level = [c for c in hand if self.card_data[c].level > expected_lv_by_t2]
    if len(high_level) >= 4:
        score -= 8  # Top-heavy hand
    
    # Only 1 playable card
    if len(playable_by_t2) <= 1:
        score -= 5
    
    return "keep" if score >= 10 else "redraw"
```

### 3.3 Draw Phase

Always returns `"draw"`. No decision needed.

### 3.4 Resource Phase

Always returns `"resource"`. No decision needed.

### 3.5 Main Phase — `_decide_main()`

Full decision logic in §4 (Strategy Branches + Card Evaluation).

```python
def _decide_main(self) -> str:
    """
    Main phase decision loop iteration.
    
    Strategy: evaluate board → choose branch → execute branch action.
    Returns a single command (play/deploy/attack/pass/end turn).
    """
    branch = self._evaluate_branch()
    self.current_branch = branch
    
    # Try actions in priority order:
    # 1. Play Command that kills a key threat
    # 2. Deploy Unit/Pilot to empty slot
    # 3. Pair Pilot to unpaired Unit
    # 4. Activate Base/Unit effect
    # 5. Attack (if branch allows)
    # 6. Pass / End turn
    
    action = self._try_command_kill(branch)
    if action: return action
    
    action = self._try_deploy(branch)
    if action: return action
    
    action = self._try_pair(branch)
    if action: return action
    
    action = self._try_activate(branch)
    if action: return action
    
    action = self._try_attack(branch)
    if action: return action
    
    # Nothing to do
    return "pass"
```

### 3.6 Battle Phase — `_decide_battle()`

```python
def _decide_battle(self) -> str:
    step = self.state.step
    active = self.state.active_player
    priority = self.state.priority
    
    # Attack step: active player chooses attacker
    if step == "attack":
        if priority == self.player_id:
            return self._choose_attacker()
        else:
            return "pass"  # Non-active player doesn't attack
    
    # Block step: defending player chooses blocker
    if step == "block":
        if priority == self.player_id:
            return self._choose_blocker()
        else:
            return "pass"  # Attacking player doesn't block
    
    # Action step: either player can play Command or pass
    if step == "action":
        if priority == self.player_id:
            return self._choose_battle_action()
        else:
            return "pass"
    
    # Damage / battle_end: no decision
    return "pass"
```

### 3.7 End Phase — `_decide_end()`

```python
def _decide_end(self) -> str:
    step = self.state.step
    
    # Action step: can play Command or pass
    if step == "action":
        if self.state.priority == self.player_id:
            action = self._try_end_action()
            if action:
                return action
            return "pass"
        return "pass"
    
    # Cleanup step: discard if hand >= 11
    if step == "cleanup":
        return self._decide_discard()
    
    return "pass"
```

### 3.8 Discard — `_decide_discard()`

```python
def _decide_discard(self) -> str:
    """
    End phase cleanup: hand must be ≤ 10.
    Discard lowest-value cards first.
    
    Card value scoring (for discard priority):
      Low value (discard first):
        - Duplicate cards (already have same card on field or in hand)
        - High-level cards unplayable next turn
        - Low-impact cards (low AP/HP, no useful effects)
    """
    hand = self._my_hand_ids()
    hand_size = len(hand)
    
    if hand_size <= 10:
        return "pass"  # No discard needed
    
    need_to_discard = hand_size - 10
    
    # Score cards by keep-value (lowest = discard first)
    scored = [(self._score_card_value(c), c) for c in hand]
    scored.sort()  # ascending by score
    
    discard_ids = [c for _, c in scored[:need_to_discard]]
    
    # Implementation note: The cleanup step currently auto-discards.
    # If the engine supports selective discard, return:
    #   "discard <card_id> [<card_id> ...]"
    # Otherwise return "pass" (let engine handle it).
    return "pass"
```

---

## 4. Strategy Branch Selection

### 4.1 Board Evaluation Metrics

```python
def _evaluate_metrics(self) -> dict:
    """Compute all board metrics for strategy scoring."""
    me = self._me()
    opp = self._opp()
    
    # Defense layers
    my_defense = self._defense_layers(me)
    opp_defense = self._defense_layers(opp)
    defense_diff = my_defense - opp_defense
    
    # Board presence
    my_units = self._unit_count(me)
    opp_units = self._unit_count(opp)
    board_diff = my_units - opp_units
    
    # Attackable units (unrested, meets CR-5.4)
    my_attackable = self._attackable_units(me)
    
    # Resources
    my_total_lv = me.resources.active + me.resources.rested + me.resources.ex
    opp_total_lv = opp.resources.active + opp.resources.rested + opp.resources.ex
    resource_diff = my_total_lv - opp_total_lv
    
    # Hand cards
    my_hand = self._my_hand_count()
    opp_hand = opp.hand_count
    hand_diff = my_hand - opp_hand
    
    # Blocker info
    opp_blockers = self._count_blockers(opp)
    my_blockers = self._count_blockers(me)
    
    # Opponent damaged units
    opp_damaged_units = self._count_damaged_units(opp)
    opp_rested_units = self._count_rested_units(opp)
    
    # My empty slots
    my_empty_slots = self._empty_slot_count(me)
    
    # Has linkable units (unpaired units that can accept a pilot)
    has_unpaired_units = self._has_unpaired_units(me)
    has_link_units = self._has_linkable_pairs(me)
    
    return {
        "defense_diff": defense_diff,
        "board_diff": board_diff,
        "my_units": my_units,
        "opp_units": opp_units,
        "my_attackable": my_attackable,
        "resource_diff": resource_diff,
        "hand_diff": hand_diff,
        "opp_blockers": opp_blockers,
        "my_blockers": my_blockers,
        "opp_damaged_units": opp_damaged_units,
        "opp_rested_units": opp_rested_units,
        "my_empty_slots": my_empty_slots,
        "has_unpaired_units": has_unpaired_units,
        "has_link_units": has_link_units,
        "my_hand_count": my_hand,
        "opp_hand_count": opp_hand,
        "turn": self.state.turn,
        "my_base_hp": me.base.hp - me.base.damage if me.base.alive else 0,
        "opp_base_hp": opp.base.hp - opp.base.damage if opp.base.alive else 0,
        "my_shields": self._shield_count(me),
        "opp_shields": self._shield_count(opp),
    }

def _defense_layers(self, player: PlayerState) -> int:
    """Total defense layers = shields + (base alive ? base remaining HP : 0)"""
    shields = self._shield_count(player)
    if player.base.alive:
        base_hp = player.base.hp - player.base.damage
        return shields + base_hp
    return shields

def _unit_count(self, player: PlayerState) -> int:
    return sum(1 for s in player.battle_area if s.unit_id is not None)

def _attackable_units(self, player: PlayerState) -> int:
    """Units that are upright (status=active) AND eligible per CR-5.4."""
    count = 0
    for s in player.battle_area:
        if s.unit_id is None or s.status != "active":
            continue
        # CR-5.4: turns_on_field >= 1 OR link == true
        turns = self.state.turn - s.deployed_turn if s.deployed_turn else 0
        if turns >= 1 or s.link:
            # Check "can't attack player" restriction (only matters for attacking defense)
            count += 1
    return count

def _count_blockers(self, player: PlayerState) -> int:
    return sum(1 for s in player.battle_area 
               if s.unit_id and s.status == "active" and "Blocker" in s.keywords)

def _count_damaged_units(self, player: PlayerState) -> int:
    return sum(1 for s in player.battle_area if s.unit_id and s.damage > 0)

def _count_rested_units(self, player: PlayerState) -> int:
    return sum(1 for s in player.battle_area if s.unit_id and s.status == "rested")

def _empty_slot_count(self, player: PlayerState) -> int:
    return sum(1 for s in player.battle_area if s.unit_id is None)

def _shield_count(self, player: PlayerState) -> int:
    if isinstance(player.shields, list):
        return len(player.shields)
    return player.shields if isinstance(player.shields, int) else 0

def _has_unpaired_units(self, player: PlayerState) -> bool:
    return any(s.unit_id and not s.pilot_id for s in player.battle_area)

def _has_linkable_pairs(self, player: PlayerState) -> bool:
    """Check if any unit can be paired with a pilot in hand."""
    for s in player.battle_area:
        if s.unit_id and not s.pilot_id:
            unit_data = self.card_data.get(s.unit_id)
            if unit_data and unit_data.link:
                # Check hand for matching pilot
                for cid in self._my_hand_ids():
                    cd = self.card_data.get(cid)
                    if cd and cd.card_type == "pilot" and cd.name in unit_data.link:
                        return True
    return False
```

### 4.2 Strategy Branch Scoring

Five branches are scored using the metrics above. The branch with the **highest score** is chosen.

```python
def _score_strategy_suppression(self, m: dict) -> float:
    """压制：Strong defense + Board advantage.
    
    Score contribution:
      Defense diff > 0  → +30
      Board diff > 0    → +25
      My blockers > 0   → +10
      opp_blockers == 0 → +10 (safe to push)
      My attackable > opp_units → +15
      per my_attackable → +5
      
    Anti-conditions:
      My base HP <= 1   → -30 (not really "strong defense")
      opp_units == 0    → -20 (overkill, just go aggro)
    """
    score = 0.0
    if m["defense_diff"] > 0:
        score += 30 + min(m["defense_diff"] * 5, 20)
    if m["board_diff"] > 0:
        score += 25 + min(m["board_diff"] * 8, 25)
    if m["my_blockers"] > 0:
        score += 10
    if m["opp_blockers"] == 0:
        score += 10
    if m["my_attackable"] > m["opp_units"]:
        score += 15
    score += m["my_attackable"] * 5
    
    # Anti-conditions
    if m["my_base_hp"] <= 1:
        score -= 30
    if m["opp_units"] == 0:
        score -= 20
    
    return score

def _score_strategy_development(self, m: dict) -> float:
    """发展：Strong defense + board behind.
    
    Score contribution:
      Defense diff > 0  → +25
      Board diff <= 0   → +30 (we're behind, need to develop)
      My empty slots > 0 → +15 (room to deploy)
      my_hand_count > opp_hand → +10 (resources to develop)
      opp_attackable > 0 → +10 (we need to block)
      
    Anti-conditions:
      My attackable > 0 → -15 (should be attacking if we can)
      opp_units == 0    → -10 (developing when opponent is empty = over-cautious)
    """
    score = 0.0
    if m["defense_diff"] > 0:
        score += 25
    if m["board_diff"] <= 0:
        score += 30
    if m["my_empty_slots"] > 0:
        score += 15
    if m["my_hand_count"] > m["opp_hand_count"]:
        score += 10
    if m["opp_attackable"] > 0:
        score += 10
    
    if m["my_attackable"] > 0:
        score -= 15
    if m["opp_units"] == 0:
        score -= 10
    
    return score

def _score_strategy_aggro(self, m: dict) -> float:
    """抢血：Weak defense + board advantage.
    
    Score contribution:
      defense_diff <= 0 → +25 (weak defense → race!)
      board_diff > 0    → +30 (have board presence)
      opp_shields == 0  → +40 (finish them!)
      opp_base_hp <= 1  → +30 (one more push)
      per my_attackable  → +10 each
      
    Anti-conditions:
      my_units == 0     → -40 (nobody to attack with)
      opp_blockers > 0  → -15 per blocker (they'll block)
    """
    score = 0.0
    if m["defense_diff"] <= 0:
        score += 25
    if m["board_diff"] > 0:
        score += 30
    if m["opp_shields"] == 0:
        score += 40
    if m["opp_base_hp"] <= 1:
        score += 30
    score += m["my_attackable"] * 10
    
    if m["my_units"] == 0:
        score -= 40
    score -= m["opp_blockers"] * 15
    
    return score

def _score_strategy_counterattack(self, m: dict) -> float:
    """反打：Weak overall + many hand cards.
    
    Score contribution:
      defense_diff <= 0 → +20
      board_diff < 0    → +20 (we're behind)
      my_hand_count >= 4 → +25 (can rebuild)
      my_empty_slots > 0 → +10
      has_unpaired_units → +10
      
    Anti-conditions:
      my_hand_count <= 2 → -30 (can't counterattack with empty hand)
      my_units >= 4      → -20 (board is already full, not "counterattack")
    """
    score = 0.0
    if m["defense_diff"] <= 0:
        score += 20
    if m["board_diff"] < 0:
        score += 20
    if m["my_hand_count"] >= 4:
        score += 25
    if m["my_empty_slots"] > 0:
        score += 10
    if m["has_unpaired_units"]:
        score += 10
    
    if m["my_hand_count"] <= 2:
        score -= 30
    if m["my_units"] >= 4:
        score -= 20
    
    return score

def _score_strategy_desperation(self, m: dict) -> float:
    """绝望：Everything weak, go all-in.
    
    Score contribution:
      defense_diff <= -3  → +25 (about to lose)
      board_diff <= -1    → +20 (getting overwhelmed)
      my_hand_count <= 2  → +15 (running out)
      opp_units >= 3      → +20 (they're strong)
      opp_shields == 0    → +15 (last stand)
      
    Anti-conditions:
      my_hand_count >= 4  → -25 (not desperate yet)
      my_units >= 3       → -20 (we have board, use another strat)
      defense_diff > 0    → -20 (defense is fine, don't panic)
    """
    score = 0.0
    if m["defense_diff"] <= -3:
        score += 25
    if m["board_diff"] <= -1:
        score += 20
    if m["my_hand_count"] <= 2:
        score += 15
    if m["opp_units"] >= 3:
        score += 20
    if m["opp_shields"] == 0:
        score += 15
    
    if m["my_hand_count"] >= 4:
        score -= 25
    if m["my_units"] >= 3:
        score -= 20
    if m["defense_diff"] > 0:
        score -= 20
    
    return score
```

### 4.3 Branch Selection

```python
def _evaluate_branch(self) -> str:
    """Evaluate all branches and pick the highest-scoring one."""
    m = self._evaluate_metrics()
    
    scores = {
        "suppression": self._score_strategy_suppression(m),
        "development": self._score_strategy_development(m),
        "aggro": self._score_strategy_aggro(m),
        "counterattack": self._score_strategy_counterattack(m),
        "desperation": self._score_strategy_desperation(m),
    }
    
    # Apply experience YAML modifiers (see §6)
    self._apply_experience_bonus(scores, m)
    
    # Pick highest
    best = max(scores, key=scores.get)
    return best
```

---

## 5. Per-Branch Decision Trees

### 5.1 Suppression (压制)

```python
def _try_attack_suppression(self) -> str | None:
    """
    Priority:
    1. Kill enemy blockers first (trade-advantageous: AP >= HP)
    2. Kill non-blocker enemy units (trade-advantageous, highest AP first)
    3. Attack defense layers (Base first, then shields)
    One attack per call.
    """
    eligible = self._get_attackable_slots()
    if not eligible:
        return None
    
    opp = self._opp()
    
    # Phase 1: Clear blockers with advantageous trades
    blockers = [s for s in opp.battle_area if s.unit_id and "Blocker" in s.keywords and s.status == "active"]
    for blocker in blockers:
        # Find best attacker for this blocker
        attacker = self._best_attacker_for(eligible, blocker)
        if attacker is not None:
            return f"attack {attacker.slot}"
    
    # Phase 2: Kill enemy non-blocker units (trade-advantageous)
    enemy_units = [s for s in opp.battle_area if s.unit_id and "Blocker" not in s.keywords]
    # Priority: lowest HP first (easiest kill), then highest AP
    enemy_units.sort(key=lambda s: (s.hp - s.damage, -s.ap))
    
    for enemy in enemy_units:
        remaining_hp = enemy.hp - enemy.damage
        attacker = self._best_attacker_for(eligible, enemy)
        if attacker is not None:
            return f"attack {attacker.slot}"
    
    # Phase 3: Attack defense layers
    # If opponent has no more units, go for base/shields
    for attacker_slot in sorted([s.slot for s in eligible]):
        return f"attack {attacker_slot}"
    
    return None
```

### 5.2 Development (发展)

```python
def _try_attack_development(self) -> str | None:
    """
    Only attack if guaranteed kill:
    - Enemy unit with remaining HP <= my highest AP
    - Enemy base with 1 HP remaining
    Otherwise, don't attack — just deploy.
    """
    eligible = self._get_attackable_slots()
    if not eligible:
        return None
    
    # Check for sure-kill on enemy unit
    opp = self._opp()
    max_ap = max(s.ap for s in eligible)
    
    for enemy in opp.battle_area:
        if not enemy.unit_id:
            continue
        remaining_hp = enemy.hp - enemy.damage
        if remaining_hp <= max_ap and remaining_hp > 0:
            # Find best attacker
            for att in eligible:
                if att.ap >= remaining_hp:
                    return f"attack {att.slot}"
    
    # Check for base kill
    if opp.base.alive and (opp.base.hp - opp.base.damage) == 1:
        for att in eligible:
            if att.ap >= 1:
                return f"attack {att.slot}"
    
    return None  # Don't attack
```

### 5.3 Aggro (抢血)

```python
def _try_attack_aggro(self) -> str | None:
    """
    All attacks go to defense layers. Only clear blockers if they block our path.
    
    Priority:
    1. Clear exactly 1 blocker if it's blocking our finishing blow (AP > HP)
    2. All other attackers go to defense layers
    """
    eligible = self._get_attackable_slots()
    if not eligible:
        return None
    
    opp = self._opp()
    
    # If opponent has blockers and we need to clear one
    blockers = [s for s in opp.battle_area if s.unit_id and "Blocker" in s.keywords and s.status == "active"]
    if blockers:
        # Only clear if we have enough attackers to both clear and push
        best_blocker = min(blockers, key=lambda s: s.hp - s.damage)
        remaining_hp = best_blocker.hp - best_blocker.damage
        attacker = self._best_attacker_for(eligible, best_blocker)
        if attacker is not None and attacker.ap > remaining_hp:
            return f"attack {attacker.slot}"
    
    # All out on defense layers
    # Sort by highest AP first (to break through base faster)
    eligible.sort(key=lambda s: -s.ap)
    for att in eligible:
        return f"attack {att.slot}"
    
    return None
```

### 5.4 Counterattack (反打)

No attack. Only deploy, pair, and use Command. Return `None` from attack function.

### 5.5 Desperation (绝望)

```python
def _try_attack_desperation(self) -> str | None:
    """
    All attackable units go to defense layers.
    Suicide attacks — don't trade.
    """
    eligible = self._get_attackable_slots()
    if not eligible:
        return None
    
    # Attack defense layers with all
    for att in sorted(eligible, key=lambda s: -s.ap):
        return f"attack {att.slot}"
    
    return None
```

---

## 6. Card Evaluation & Selection

### 6.1 Card Scoring

```python
def _score_card_for_deploy(self, card_id: str, branch: str, metrics: dict) -> float:
    """
    Score a hand card for deployment/play.
    Higher = better choice.
    
    Base scores by card type:
      Unit:   ap + hp + effect_value
      Pilot:  10 + pilot_match_bonus + effect_value
      Command: effect_value + kill_potential
      Base:   15 + shield_return_value
    
    Effect value determined by:
      damage/heal: value * 3
      modifyAP: |value| * 2
      draw: value * 8
      rest: 8
      deploy_token: 12 + token_ap * 2 + token_hp * 2
    
    Strategy-specific modifiers (see §6.3).
    Experience YAML bonus (see §7).
    """
    cd = self.card_data.get(card_id)
    if not cd:
        return -999
    
    base_score = 0.0
    
    if cd.card_type == "unit":
        base_score = cd.ap * 2 + cd.hp * 2
        if cd.link:
            base_score += 10  # Link potential
        # Effect bonus
        base_score += self._effect_value(cd)
        
    elif cd.card_type == "pilot":
        # Base score
        base_score = 10
        # Pairing match with existing units
        match_bonus = self._pilot_match_score(card_id)
        base_score += match_bonus
        # Effect bonus
        base_score += self._effect_value(cd)
        
    elif cd.card_type == "command":
        if cd.pilot_name:
            # Dual-purpose [Pilot] command - score both modes
            as_command = self._effect_value(cd)
            as_pilot = 8 + self._pilot_match_score(card_id)
            base_score = max(as_command, as_pilot)
        else:
            base_score = self._effect_value(cd)
            # Kill potential
            base_score += self._command_kill_potential(cd)
            
    elif cd.card_type == "base":
        base_score = 15
        # Shield return value
        if isinstance(self._me().shields, list) and len(self._me().shields) > 0:
            base_score += 10  # Getting a shield back to hand
        # Effect bonus
        base_score += self._effect_value(cd)
    
    # Cost efficiency: prefer cheaper if scores are similar
    cost_penalty = cd.cost * 3
    base_score -= cost_penalty
    
    # Playability check
    if not self._can_play_card(card_id):
        base_score -= 100
    
    # Strategy-specific modifier
    base_score += self._strategy_card_modifier(cd, branch, metrics)
    
    return base_score

def _can_play_card(self, card_id: str) -> bool:
    """CR-3 check: Level >= card.level and active resources >= card.cost."""
    me = self._me()
    cd = self.card_data.get(card_id)
    if not cd:
        return False
    
    level = me.resources.active + me.resources.rested + me.resources.ex
    if level < cd.level:
        return False
    
    # Can pay cost?
    available = me.resources.active + me.resources.ex
    if available < cd.cost:
        return False
    
    # For unit/pilot: need empty slot
    if cd.card_type in ("unit", "pilot"):
        if self._empty_slot_count(me) == 0:
            return False
    
    return True

def _effect_value(self, cd: CardData) -> float:
    """Compute value of card's effects."""
    value = 0.0
    for rule in cd.effects.rules:
        action = rule.action
        params = rule.parameters
        val = params.get("value", 0)
        
        if action == "damage":
            value += val * 3
        elif action == "heal":
            value += val * 2
        elif action == "modifyAP":
            value += abs(val) * 2
            if val < 0:
                value += 3  # Debuff is slightly more valuable
        elif action == "draw":
            value += val * 8
        elif action == "rest":
            value += 8
        elif action == "deploy" or "conditionalTokenDeploy":
            value += 12
        elif action == "addToHand":
            value += 6
        elif action == "setActive":
            value += 5
        elif action == "redirect_attack":
            value += 10  # Blocker ability
    
    return value

def _command_kill_potential(self, cd: CardData) -> float:
    """How likely is this command to kill something important."""
    opp = self._opp()
    max_kill_value = 0.0
    
    for rule in cd.effects.rules:
        if rule.action == "damage":
            damage_val = rule.parameters.get("value", 0)
            filters = rule.target.get("filters", {})
            
            for slot in opp.battle_area:
                if not slot.unit_id:
                    continue
                remaining_hp = slot.hp - slot.damage
                
                # Check if this command can kill this unit
                can_kill = False
                if damage_val >= remaining_hp:
                    can_kill = True
                # Check status filters
                if "status" in filters:
                    if filters["status"] == "rested" and slot.status != "rested":
                        can_kill = False
                    if filters["status"] == "active" and slot.status != "active":
                        can_kill = False
                
                if can_kill:
                    # Value the kill
                    kill_val = 15
                    if "Blocker" in slot.keywords:
                        kill_val += 10
                    kill_val += slot.ap * 2
                    max_kill_value = max(max_kill_value, kill_val)
    
    return max_kill_value
```

### 6.2 Strategy-Specific Card Modifiers

```python
def _strategy_card_modifier(self, cd: CardData, branch: str, metrics: dict) -> float:
    """
    Branch-specific bonuses for card types.
    """
    modifier = 0.0
    
    if branch == "suppression":
        if cd.card_type == "command":
            modifier += 8  # Removal is key
        elif cd.card_type == "unit" and cd.hp >= 4:
            modifier += 10  # Tanky units
    
    elif branch == "development":
        if cd.card_type == "unit":
            modifier += 12  # Building board
            if cd.hp >= 4:
                modifier += 8  # Sticky units
        elif cd.card_type == "pilot":
            modifier += 10  # Pairing value
    
    elif branch == "aggro":
        if cd.card_type == "unit":
            modifier += cd.ap * 3  # High AP prioritized
        elif cd.card_type == "command" and self._command_kill_potential(cd) > 0:
            modifier += 5  # Only if it kills
    
    elif branch == "counterattack":
        if cd.card_type == "unit":
            modifier += 15  # Need bodies
        elif cd.card_type == "command":
            modifier += 10  # Need removal
    
    elif branch == "desperation":
        if cd.card_type == "unit":
            modifier += 20  # Everything on board
        elif cd.card_type == "command" and self._command_kill_potential(cd) > 0:
            modifier += 15  # Remove biggest threat
    
    return modifier
```

### 6.3 Pilot Match Scoring

```python
def _pilot_match_score(self, pilot_card_id: str) -> float:
    """
    How well does this pilot match existing unpaired units?
    Returns bonus per matching unpaired unit.
    """
    cd = self.card_data.get(pilot_card_id)
    if not cd or cd.card_type != "pilot":
        return 0.0
    
    me = self._me()
    score = 0.0
    
    for slot in me.battle_area:
        if not slot.unit_id or slot.pilot_id:
            continue
        unit_data = self.card_data.get(slot.unit_id)
        if unit_data and cd.name in unit_data.link:
            # Direct match!
            score += 25
        elif unit_data and any(t in unit_data.link for t in cd.traits):
            # Trait match (e.g., "White Base Team" pilot with "White Base Team" unit)
            score += 15
    
    return score
```

---

## 7. Experience YAML Influence

### 7.1 Loading YAML

```python
def load_experience_rules(self):
    """Load all YAML files from experience/ directory."""
    import yaml
    from pathlib import Path
    
    exp_dir = Path(__file__).parent / "experience"
    self.experience_rules = []
    
    if not exp_dir.exists():
        return
    
    for yaml_file in sorted(exp_dir.glob("*.yaml")):
        try:
            with open(yaml_file) as f:
                data = yaml.safe_load(f)
            rule = ExperienceRule(
                id=data.get("id"),
                priority=data.get("priority", 5),
                description=data.get("description", ""),
                condition=data.get("condition", {}),
                effect=data.get("effect", {})
            )
            self.experience_rules.append(rule)
        except Exception as e:
            print(f"  ⚠ Failed to load {yaml_file}: {e}")
    
    # Sort by priority descending (highest first)
    self.experience_rules.sort(key=lambda r: -r.priority)
```

### 7.2 Applying Experience to Strategy Scores

```python
def _apply_experience_bonus(self, scores: dict[str, float], metrics: dict):
    """
    Check each experience rule; if its condition matches current state,
    apply the effect to strategy branch scores.
    
    Effects can:
    - Add score_bonus to specific card types (see §6)
    - Modify attack_target preference (suppression/aggro)
    - Force desperate_play flag
    """
    for rule in self.experience_rules:
        if not self._check_experience_condition(rule.condition, metrics):
            continue
        
        effect = rule.effect
        
        # attack_target overrides (highest priority rule wins)
        if "attack_target" in effect:
            attack_target = effect["attack_target"]
            if attack_target == "base":
                # Push aggro score up
                scores["aggro"] += 15
            elif attack_target == "kill":
                # Push suppression score up
                scores["suppression"] += 15
        
        # desperate_play flag
        if effect.get("desperate_play"):
            scores["desperation"] += 10
        
        # score_bonus is handled during card scoring (not strategy scoring)
        self._active_experience_bonuses[rule.id] = effect.get("score_bonus", [])

def _check_experience_condition(self, condition: dict, metrics: dict) -> bool:
    """Check if an experience rule's conditions match current state."""
    # Turn range
    if "turn_min" in condition and metrics["turn"] < condition["turn_min"]:
        return False
    if "turn_max" in condition and metrics["turn"] > condition["turn_max"]:
        return False
    
    # Unit counts
    if "my_units_min" in condition and metrics["my_units"] < condition["my_units_min"]:
        return False
    if "my_units_max" in condition and metrics["my_units"] > condition["my_units_max"]:
        return False
    if "enemy_units_min" in condition and metrics["opp_units"] < condition["enemy_units_min"]:
        return False
    
    # Empty slots
    if "my_empty_slots_min" in condition and metrics["my_empty_slots"] < condition["my_empty_slots_min"]:
        return False
    if "my_empty_slots_max" in condition and metrics["my_empty_slots"] > condition["my_empty_slots_max"]:
        return False
    
    # Damaged/rested units
    if "enemy_damaged_units_min" in condition and metrics["opp_damaged_units"] < condition["enemy_damaged_units_min"]:
        return False
    if "enemy_rested_units_min" in condition and metrics["opp_rested_units"] < condition["enemy_rested_units_min"]:
        return False
    
    # Link/Unpaired
    if condition.get("has_link_units") and not metrics["has_link_units"]:
        return False
    if condition.get("has_unpaired_units") and not metrics["has_unpaired_units"]:
        return False
    
    # Base HP
    if "my_base_hp_max" in condition and metrics["my_base_hp"] > condition["my_base_hp_max"]:
        return False
    
    return True
```

### 7.3 Applying Experience to Card Scores

```python
def _apply_experience_card_bonus(self, card_id: str, card_type: str) -> float:
    """
    Sum up score bonuses from all currently active experience rules
    that match this card's type.
    """
    bonus = 0.0
    for rule_id, bonuses in self._active_experience_bonuses.items():
        if not isinstance(bonuses, list):
            bonuses = [bonuses]
        for b in bonuses:
            if isinstance(b, dict) and b.get("card_type") == card_type:
                bonus += b.get("bonus", 0)
            elif isinstance(b, dict) and b.get("card_type") == "pilot" and card_type == "pilot":
                bonus += b.get("bonus", 0)
    return bonus
```

---

## 8. Legality Self-Check (Command Output Filter)

### 8.1 Universal Legality Check

```python
def verify_legality(self, command: str) -> tuple[bool, str]:
    """
    Verify a command passes all legality checks before returning it.
    Returns (is_valid, reason_if_invalid).
    
    Called before returning ANY play/deploy/pair/attack/block command.
    """
    parts = command.split()
    cmd = parts[0]
    
    if cmd in ("pass", "end turn", "draw", "resource", "keep", "redraw", "concede"):
        return True, ""
    
    if cmd in ("play", "deploy"):
        return self._verify_play_deploy(parts)
    
    if cmd == "pair":
        return self._verify_pair(parts)
    
    if cmd == "attack":
        return self._verify_attack(parts)
    
    if cmd == "block":
        return self._verify_block(parts)
    
    if cmd == "activate":
        return self._verify_activate(parts)
    
    return False, f"Unknown command: {cmd}"
```

### 8.2 play/deploy Verification

```python
def _verify_play_deploy(self, parts: list[str]) -> tuple[bool, str]:
    """CR-3, CR-5.11 verification for play/deploy."""
    if len(parts) < 2:
        return False, "Missing card_id"
    
    cmd = parts[0]  # "play" or "deploy"
    card_id = parts[1]
    
    # Phase check
    if self.state.phase not in ("main", "end"):
        return False, f"Wrong phase: {self.state.phase}"
    if self.state.phase == "end" and self.state.step not in ("action", None):
        return False, f"Wrong end step: {self.state.step}"
    
    # Card exists in hand
    me = self._me()
    hand_ids = self._my_hand_ids()
    if card_id not in hand_ids:
        return False, f"Card {card_id} not in hand"
    
    # Card data exists
    cd = self.card_data.get(card_id)
    if not cd:
        return False, f"No card data for {card_id}"
    
    # Level check (CR-3.1, CR-3.2)
    level = me.resources.active + me.resources.rested + me.resources.ex
    if level < cd.level:
        return False, f"Level {level} < required {cd.level}"
    
    # Cost check (CR-3.3)
    available = me.resources.active + me.resources.ex
    if available < cd.cost:
        return False, f"Available {available} < cost {cd.cost}"
    
    # Card type checks
    if cd.card_type in ("unit", "pilot"):
        if cmd != "deploy":
            return False, f"{cd.card_type} must be deployed (not played)"
        # Battle area space check (CR-5.11)
        if self._empty_slot_count(me) == 0:
            # Could trash, but for AI: refuse unless desperation
            return False, "Battle area full"
        # Token can't be deployed from hand (CR-6.7)
        if cd.level == 0 and cd.color == "Token":
            return False, "Token cannot be deployed from hand"
    
    elif cd.card_type == "command":
        if cmd not in ("play", "deploy"):
            return False, f"Command must be played (not deployed)"
        # If it's a dual-purpose [Pilot], both play/deploy work
        # "play" = use as Command, "deploy" = deploy as Pilot
        if cmd == "deploy" and not cd.pilot_name:
            # Only deploy as pilot if it has pilot designation
            has_pilot_effect = any(
                r.action == "designate_pilot" for r in cd.effects.rules
            )
            if not has_pilot_effect:
                return False, f"Cannot deploy {card_id} - not a Pilot"
    
    elif cd.card_type == "base":
        if cmd != "deploy":
            return False, "Base must be deployed"
        # Base deployment replaces current base (CR-7.3)
        # Always allowed as long as we have the slot (which we do - Base is card_id)
    
    return True, ""
```

### 8.3 Attack Verification

```python
def _verify_attack(self, parts: list[str]) -> tuple[bool, str]:
    """CR-5.4 attack eligibility check."""
    if len(parts) < 2:
        return False, "Missing slot number"
    
    try:
        slot_num = int(parts[1])
    except ValueError:
        return False, f"Invalid slot: {parts[1]}"
    
    me = self._me()
    
    # Slot exists and has a unit
    if slot_num < 0 or slot_num >= len(me.battle_area):
        return False, f"Slot {slot_num} out of range"
    
    slot = me.battle_area[slot_num]
    if not slot.unit_id:
        return False, f"Slot {slot_num} is empty"
    
    # Unit must be active (not rested)
    if slot.status != "active":
        return False, f"Unit in slot {slot_num} is {slot.status}, not active"
    
    # CR-5.4: turns_on_field >= 1 OR link == true
    turns = self.state.turn - slot.deployed_turn if slot.deployed_turn else 0
    if turns < 1 and not slot.link:
        return False, f"Unit in slot {slot_num} deployed this turn and not a Link Unit"
    
    # Check "can't attack player" restriction
    if "不可攻擊玩家" in slot.keywords:
        return False, f"Unit in slot {slot_num} cannot attack player"
    # Also check English keyword
    attack_restriction = any(
        "disallow" in str(r) and "player" in str(r)
        for r in (self.card_data.get(slot.unit_id).effects.rules if self.card_data.get(slot.unit_id) else [])
    )
    if attack_restriction:
        return False, f"Unit in slot {slot_num} has attack restriction"
    
    # Phase must be battle(attack) or main
    if self.state.phase == "battle" and self.state.step != "attack":
        return False, f"Not attack step"
    
    return True, ""
```

### 8.4 Block Verification

```python
def _verify_block(self, parts: list[str]) -> tuple[bool, str]:
    """CR-5.8 blocker eligibility check."""
    if len(parts) < 2:
        return False, "Missing slot number"
    
    try:
        slot_num = int(parts[1])
    except ValueError:
        return False, f"Invalid slot: {parts[1]}"
    
    me = self._me()
    
    if slot_num < 0 or slot_num >= len(me.battle_area):
        return False, f"Slot {slot_num} out of range"
    
    slot = me.battle_area[slot_num]
    if not slot.unit_id:
        return False, f"Slot {slot_num} has no unit"
    
    # Must have Blocker keyword (CR-6.1)
    if "Blocker" not in slot.keywords:
        return False, f"Unit in slot {slot_num} lacks Blocker"
    
    # Must be active (not rested)
    if slot.status != "active":
        return False, f"Unit in slot {slot_num} is {slot.status}, not active"
    
    # Phase must be battle(block)
    if self.state.phase != "battle" or self.state.step != "block":
        return False, f"Not block step"
    
    return True, ""
```

---

## 9. Battle Decision Logic

### 9.1 Choosing an Attacker

```python
def _get_attackable_slots(self) -> list[SlotState]:
    """Get all slots that can attack this turn (CR-5.4 check)."""
    me = self._me()
    eligible = []
    
    for slot in me.battle_area:
        if not slot.unit_id or slot.status != "active":
            continue
        turns = self.state.turn - slot.deployed_turn if slot.deployed_turn else 0
        if turns >= 1 or slot.link:
            # Check attack restriction
            cd = self.card_data.get(slot.unit_id)
            if cd:
                restricted = any(
                    r.get("action") == "restrict_attack" and 
                    r.get("parameters", {}).get("disallow") == "player"
                    for r in cd.effects.rules
                )
                if restricted:
                    continue
            eligible.append(slot)
    
    # Sort by attack priority (CR-5.5): First Strike first, then highest AP
    eligible.sort(key=lambda s: (
        0 if "First Strike" in s.keywords else 1,
        -s.ap
    ))
    
    return eligible

def _choose_attacker(self) -> str:
    """
    Delegate to active strategy branch.
    Returns "attack <slot>" or "pass" if no eligible attacker.
    """
    eligible = self._get_attackable_slots()
    if not eligible:
        return "pass"
    
    branch = self.current_branch
    
    if branch == "suppression":
        return self._choose_attacker_suppression(eligible)
    elif branch == "development":
        return self._choose_attacker_development(eligible)
    elif branch == "aggro":
        return self._choose_attacker_aggro(eligible)
    elif branch == "counterattack":
        return "pass"  # No attack in counterattack
    elif branch == "desperation":
        return self._choose_attacker_desperation(eligible)
    
    # Fallback: attack with first eligible
    return f"attack {eligible[0].slot}"
```

### 9.2 Choosing a Blocker

```python
def _choose_blocker(self) -> str:
    """
    Decide whether to block an incoming attack.
    
    Logic:
    1. Fatal (CR-4.9): shields=0 + base dead → block at any cost
    2. Non-fatal:
       a. blocker HP > attacker AP → block (safe block)
       b. blocker HP == attacker AP → block (trade, only if valuable)
       c. blocker HP < attacker AP → don't block (unless protecting high-value)
    3. Protection priority: Link Unit > high AP (4+) > undamaged
    """
    me = self._me()
    attacker = self._get_current_attacker_from_state()
    if not attacker:
        return "pass"
    
    # Check if fatal
    shields = self._shield_count(me)
    base_alive = me.base.alive
    is_fatal = shields == 0 and not base_alive
    
    # Find available blockers
    blockers = [s for s in me.battle_area 
                if s.unit_id and s.status == "active" and "Blocker" in s.keywords]
    
    if not blockers:
        return "pass"
    
    if is_fatal:
        # Block at any cost — use the blocker with highest HP
        best = max(blockers, key=lambda s: s.hp - s.damage)
        return f"block {best.slot}"
    
    # Non-fatal: trade evaluation
    attacker_ap = attacker.ap
    
    for blocker in blockers:
        blocker_hp = blocker.hp - blocker.damage
        
        if blocker_hp > attacker_ap:
            # Safe block
            return f"block {blocker.slot}"
        elif blocker_hp == attacker_ap:
            # Trade — only block if attacker is high value
            attacker_val = self._unit_value(attacker)
            blocker_val = self._unit_value(blocker)
            if attacker_val > blocker_val:
                return f"block {blocker.slot}"
        else:
            # Blocker dies — only block if attacker is much more valuable
            attacker_val = self._unit_value(attacker)
            blocker_val = self._unit_value(blocker)
            if attacker_val >= blocker_val * 2:
                return f"block {blocker.slot}"
    
    return "pass"

def _unit_value(self, slot: SlotState) -> float:
    """Estimate a unit's strategic value."""
    if not slot.unit_id:
        return 0
    
    value = slot.ap * 2 + (slot.hp - slot.damage) * 1.5
    
    if slot.link:
        value += 10
    if "Blocker" in slot.keywords:
        value += 8
    if "First Strike" in slot.keywords:
        value += 5
    if slot.pilot_id:
        value += 8  # Pilot attached = extra value
    
    return value

def _best_attacker_for(self, eligible: list[SlotState], target: SlotState) -> SlotState | None:
    """
    Find the best attacker to kill a target unit.
    Best = AP closest to (but >=) target's remaining HP, minimizing overkill.
    """
    target_hp = target.hp - target.damage
    
    # Filter: can kill the target
    candidates = [s for s in eligible if s.ap >= target_hp]
    if not candidates:
        return None
    
    # Sort by overkill (least overkill first), then by lowest AP
    candidates.sort(key=lambda s: (s.ap - target_hp, s.ap))
    return candidates[0]
```

### 9.3 Battle Action Step

```python
def _choose_battle_action(self) -> str:
    """
    During battle action step, consider playing a Command.
    Priority:
    1. Kill a damaged/rested enemy unit (especially Blocker or high AP)
    2. Debuff a threatening attacker
    3. Heal an important friendly unit
    """
    # Try to play a kill command
    cmd = self._find_best_battle_command()
    if cmd:
        return cmd
    
    return "pass"

def _find_best_battle_command(self) -> str | None:
    """Find the best Command to play during battle action step."""
    hand = self._my_hand_ids()
    opp = self._opp()
    me = self._me()
    
    best_card = None
    best_score = -999
    
    for card_id in hand:
        cd = self.card_data.get(card_id)
        if not cd or cd.card_type != "command":
            continue
        if not self._can_play_card(card_id):
            continue
        
        score = 0.0
        
        # Evaluate effects
        for rule in cd.effects.rules:
            if rule.action == "damage":
                dmg = rule.parameters.get("value", 0)
                # Can it kill any enemy?
                for slot in opp.battle_area:
                    if not slot.unit_id:
                        continue
                    remaining = slot.hp - slot.damage
                    if dmg >= remaining:
                        kill_score = 20
                        if "Blocker" in slot.keywords:
                            kill_score += 10
                        # Heavily damaged = easier kill (less overkill needed)
                        if remaining <= 2:
                            kill_score += 5
                        score = max(score, kill_score)
            
            elif rule.action == "modifyAP":
                ap_change = rule.parameters.get("value", 0)
                if ap_change < 0:
                    # Debuff — valuable if attacker exists
                    for slot in opp.battle_area:
                        if slot.unit_id and slot.status == "active":
                            score += 8
            
            elif rule.action == "heal":
                heal_val = rule.parameters.get("value", 0)
                # Check if any friendly unit is damaged
                for slot in me.battle_area:
                    if slot.unit_id and slot.damage > 0 and slot.damage <= heal_val:
                        score += 6
        
        if score > best_score:
            best_score = score
            best_card = card_id
    
    if best_card and best_score > 0:
        return f"play {best_card}"
    
    return None
```

---

## 10. Surrender / Concede Logic

```python
def _should_concede(self) -> bool:
    """
    CR-8.4 surrender conditions.
    ALL conditions must be true to concede:
    1. Opponent has 3+ units on board
    2. My battle area is empty
    3. My hand size <= 1
    4. My deck <= 3 cards
    5. My shields = 0
    6. No Command in hand that can remove a threat
    """
    me = self._me()
    opp = self._opp()
    
    # Condition 1: Opponent has 3+ units
    opp_units = self._unit_count(opp)
    if opp_units < 3:
        return False
    
    # Condition 2: My battle area empty
    my_units = self._unit_count(me)
    if my_units > 0:
        return False
    
    # Condition 3: My hand <= 1
    hand_count = self._my_hand_count()
    if hand_count > 1:
        return False
    
    # Condition 4: My deck <= 3
    if me.deck_count > 3:
        return False
    
    # Condition 5: My shields == 0
    if self._shield_count(me) > 0:
        return False
    
    # Condition 6: No removal Command in hand
    has_removal = False
    for cid in self._my_hand_ids():
        cd = self.card_data.get(cid)
        if cd and cd.card_type == "command":
            for rule in cd.effects.rules:
                if rule.action in ("damage", "modifyAP"):
                    has_removal = True
                    break
            if has_removal:
                break
    
    if has_removal:
        return False  # Still have hope
    
    return True
```

---

## 11. Integration into gcg_simulation.py

### 11.1 GCGAI Usage in the Simulation Loop

```python
class GCGSimulation:
    # ... existing fields ...
    
    def __init__(self, p1_mode="human", p2_mode="ai", game_state_path=None):
        # ... existing init ...
        if p1_mode == "ai":
            self.p1_ai = GCGAI(player_id="P1", first_player="P1")
        if p2_mode == "ai":
            self.p2_ai = GCGAI(player_id="P2", first_player="P1")  # first_player from state
    
    def next_command(self):
        """Modified to use AI when applicable."""
        s = self.state
        if not s:
            return None
        
        phase = s.get("phase")
        priority = s.get("priority")
        game_over = s.get("game_over", False)
        
        if game_over:
            return None
        
        # Determine which AI is active
        ai_player = None
        if priority == "P1" and self.p1_mode == "ai":
            ai_player = self.p1_ai
        elif priority == "P2" and self.p2_mode == "ai":
            ai_player = self.p2_ai
        
        if ai_player:
            # Update AI state from current game state
            ai_player.load_state(s)
            
            # Set first_player if not set (only on first call)
            if ai_player.first_player is None:
                ai_player.first_player = s.get("first_player", "P1")
            
            # Get AI decision
            return ai_player.decide()
        
        # ... existing human routing ...
```

### 11.2 Complete Command Flow

```
Simulation reads game_state.md
  → routes to next_command()
    → calls GCGAI.decide()
      → phase dispatch
        → branch evaluation (scoring 5 strategies)
        → experience YAML influence
        → card scoring & selection
        → legality self-check
        → return command string
    → returns command to orchestrator
  → orchestrator executes, writes new state
  → loop
```

---

## 12. Card Data Loading

```python
def load_card_data(self):
    """Load all card data from card/data/*.json files."""
    import json
    from pathlib import Path
    
    data_dir = Path(__file__).parent / "card" / "data"
    if not data_dir.exists():
        return
    
    for json_file in data_dir.glob("*.json"):
        try:
            with open(json_file) as f:
                raw_data = json.load(f)
            
            # Handle different JSON structures
            cards = raw_data.get("cards", raw_data)
            
            for card_id, card_info in cards.items():
                cd = self._parse_card(card_id, card_info)
                self.card_data[card_id] = cd
        
        except Exception as e:
            print(f"  ⚠ Failed to load {json_file}: {e}")

def _parse_card(self, card_id: str, info: dict) -> CardData:
    """Parse raw card JSON into CardData dataclass."""
    rules = info.get("effects", {}).get("rules", [])
    
    # Check for pilot designation (dual-purpose Command)
    pilot_name = None
    pilot_ap = None
    pilot_hp = None
    for rule in rules:
        if rule.get("action") == "designate_pilot":
            params = rule.get("parameters", {})
            pilot_name = params.get("pilotName")
            pilot_ap = params.get("AP")
            pilot_hp = params.get("HP")
            break
    
    return CardData(
        id=card_id,
        name=info.get("name", ""),
        card_type=info.get("cardType", "").lower(),
        color=info.get("color", ""),
        level=info.get("level", 0),
        cost=info.get("cost", 0),
        zone=info.get("zone", []),
        traits=info.get("traits", []),
        link=info.get("link", []),
        ap=info.get("ap", 0),
        hp=info.get("hp", 0),
        effects=CardEffects(
            description=info.get("effects", {}).get("description", []),
            rules=rules
        ),
        pilot_ap=pilot_ap,
        pilot_hp=pilot_hp,
        pilot_name=pilot_name,
    )
```

---

## 13. Helper Methods

```python
def _me(self) -> PlayerState:
    return getattr(self.state, self.me)

def _opp(self) -> PlayerState:
    return getattr(self.state, self.opponent)

def _my_hand_ids(self) -> list[str]:
    """Get actual card IDs from hand (not 'Unknown')."""
    hand = self._me().hand_cards
    result = []
    for h in hand:
        if isinstance(h, dict):
            cid = h.get("card_id")
            if cid and cid != "Unknown":
                result.append(cid)
        elif isinstance(h, str) and h != "Unknown":
            result.append(h)
    return result

def _my_hand_count(self) -> int:
    """Reliable hand count."""
    return self._me().hand_count or len(self._my_hand_ids())

def _get_current_attacker_from_state(self) -> SlotState | None:
    """
    Get the current attacking unit during battle(block) step.
    The attacker is identified by current_attacker slot number.
    """
    attacker_slot = self.state.current_attacker
    if attacker_slot is None:
        return None
    
    opp = self._opp()
    if 0 <= attacker_slot < len(opp.battle_area):
        return opp.battle_area[attacker_slot]
    return None
```

---

## 14. Implementation Roadmap

### Phase 1: Foundation
1. Define all dataclasses (`GameState`, `PlayerState`, `CardData`, `ExperienceRule`, etc.)
2. Implement YAML/JSON parsing for state, card data, and experience rules
3. Implement phase dispatch skeleton (all phases → "pass")

### Phase 2: Core Decision Engine
4. Implement board evaluation metrics (`_evaluate_metrics()`)
5. Implement 5 strategy branch scoring functions
6. Implement branch selection with experience YAML influence

### Phase 3: Main Phase Actions
7. Card scoring and selection (`_score_card_for_deploy()`)
8. Deploy logic (`_try_deploy()`)
9. Pair logic (`_try_pair()`)
10. Command play logic (`_try_command_kill()`)
11. Attack logic per branch

### Phase 4: Battle Phase
12. Attacker selection per branch
13. Blocker selection logic
14. Battle action step (Command usage)

### Phase 5: Legality & Integration
15. All legality self-check functions
16. Integration into `gcg_simulation.py`
17. Surrender logic
18. Discard logic

---

## 15. Complete Data Flow Diagram

```
game_state.md 
  │  (YAML parsed)
  ▼
GCGAI.load_state()
  │
  ▼
GCGAI.decide()
  │
  ├── Phase == "pre-game"  → _decide_mulligan()
  ├── Phase == "start"     → "pass"
  ├── Phase == "draw"      → "draw"  
  ├── Phase == "resource"  → "resource"
  ├── Phase == "main"      → _decide_main()
  │     │
  │     ├── _evaluate_metrics()
  │     ├── _evaluate_branch()  ← _apply_experience_bonus()
  │     ├── _try_command_kill()
  │     ├── _try_deploy()       ← _score_card_for_deploy() ← _apply_experience_card_bonus()
  │     ├── _try_pair()
  │     ├── _try_attack()       ← per-branch logic
  │     └── "pass"
  │
  ├── Phase == "battle"    → _decide_battle()
  │     ├── step=="attack" → _choose_attacker()
  │     ├── step=="block"  → _choose_blocker()
  │     ├── step=="action" → _choose_battle_action()
  │     └── else           → "pass"
  │
  └── Phase == "end"       → _decide_end()
        ├── step=="action"  → _try_end_action()
        └── step=="cleanup" → _decide_discard()
  │
  ▼
verify_legality()  ← final filter before output
  │
  ▼
Return command string
```
