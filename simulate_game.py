#!/usr/bin/env python3
"""GCG Full Game Simulation — two AI players, full rule engine + Command effects + Link."""

import json, random, copy, os, yaml
from dataclasses import dataclass, field
from typing import Optional

# ── Card data ──────────────────────────────────────────────────────
with open("card/data/st01Card.json") as f:
    RAW = json.load(f)["cards"]

CARD_CACHE = {}
for cid_str, c in RAW.items():
    cid = f"st01/{cid_str}"
    CARD_CACHE[cid] = {
        "id": cid, "name": c["name"], "cardType": c["cardType"],
        "level": c["level"], "cost": c["cost"], "ap": c["ap"], "hp": c["hp"],
        "link": c.get("link", []), "traits": c.get("traits", []),
        "color": c.get("color", ""), "keywords": [],
        "pilot_for": None, "command_pilot": False, "pilot_ap": 0, "pilot_hp": 0,
        "raw_rules": c.get("effects", {}).get("rules", []),
    }

for cid_str, c in RAW.items():
    cid = f"st01/{cid_str}"
    entry = CARD_CACHE[cid]
    desc = c.get("effects", {}).get("description", [])
    for d in desc:
        if "<Blocker>" in d: entry["keywords"].append("Blocker")
        if "不可攻擊玩家" in d or "can't choose the enemy player" in d:
            entry["keywords"].append("不可攻擊玩家")
        if "<First Strike>" in d: entry["keywords"].append("First Strike")
        if "<Breach" in d:
            import re
            m = re.search(r'<Breach\s*(\d+)>', d)
            if m: entry["keywords"].append(f"Breach {m.group(1)}")
            else: entry["keywords"].append("Breach 1")
    for d in desc:
        if "[Pilot]" in d: entry["command_pilot"] = True
    for rule in c.get("effects", {}).get("rules", []):
        if rule.get("action") == "designate_pilot":
            p = rule["parameters"]
            entry["pilot_for"] = p.get("pilotName")
            entry["pilot_ap"] = p.get("AP", 0)
            entry["pilot_hp"] = p.get("HP", 0)

def card_info(card_id):
    return CARD_CACHE.get(card_id)

def interpret_effects(card_id):
    """Convert raw JSON effects.rules to standardized format per skill_card_db.md.
    Returns list of dicts with keys: trigger, cost, action, target, value, duration, condition, oncePerTurn, summary.
    """
    info = card_info(card_id)
    if not info: return []
    rules = info.get("raw_rules", [])
    results = []
    for rule in rules:
        eid = rule.get("effectId", "")
        rt = rule.get("type", "")
        timing = rule.get("timing", {})
        params = rule.get("parameters", {})
        target = rule.get("target", {})
        action = rule.get("action", "")
        cost_raw = rule.get("cost", {})
        val = params.get("value", 1)

        # Determine trigger
        evt = timing.get("eventTrigger", "")
        if evt == "ENTERS_PLAY": trigger = "on_deploy"
        elif evt == "PAIRING_COMPLETE": trigger = "on_pair"
        elif evt == "END_OF_TURN": trigger = "end_of_turn"
        elif evt == "ATTACK_PHASE": trigger = "on_attack"
        elif evt == "BURST_CONDITION": trigger = "on_burst"
        elif evt == "ATTACK_REDIRECT": trigger = "on_block"
        elif rt == "play": trigger = "on_play"
        elif rt == "activated": trigger = "manual_activate"
        elif rt == "continuous": trigger = "continuous"
        elif rt == "special": trigger = "special"
        elif evt: trigger = evt.lower()
        else: trigger = "on_play"

        # Determine cost
        if not cost_raw: cost = "none"
        elif isinstance(cost_raw, dict):
            if cost_raw.get("resource"):
                c = f"resource({cost_raw['resource']})"
                if cost_raw.get("oncePerTurn"): c += "+once"
                cost = c
            elif cost_raw.get("rest") == "self": cost = "rest_self"
            else: cost = "none"
        else: cost = "none"

        # Determine action
        if action == "heal": std_action = f"heal({val})"
        elif action == "damage": std_action = f"damage({val})"
        elif action == "draw": std_action = f"draw({val})"
        elif action == "modifyAP":
            std_action = f"ap_boost({val})" if val > 0 else f"ap_reduce({-val})"
        elif action == "rest": std_action = "rest_target"
        elif action == "setActive": std_action = "activate_resource"
        elif action == "redirect_attack": std_action = "block"
        elif action == "restrict_attack": std_action = "no_player_attack"
        elif action == "addToHand":
            scope = target.get("scope", "")
            std_action = "shield_to_hand(1)" if scope == "self_shield" else "return_to_hand"
        elif action == "deploy": std_action = "deploy_self"
        elif action == "conditionalTokenDeploy": std_action = f"deploy_token({val})"
        elif action == "activate_ability": std_action = "activate_ability"
        elif action == "designate_pilot": std_action = "pilot_dual"
        else: std_action = action

        # Determine target
        tscope = target.get("scope", "source")
        ttype = target.get("type", "unit")
        if tscope == "source": std_target = "self"
        elif tscope == "self" and ttype == "unit": std_target = "self_unit(1)"
        elif tscope == "self_all_unit": std_target = "self_all_units"
        elif tscope == "opponent": std_target = "opponent_unit(1)"
        elif tscope == "self_resource": std_target = "self_resource(1)"
        elif tscope == "self_shield": std_target = "self_shield(1)"
        elif tscope == "self" and ttype == "card": std_target = "self_hand"
        else: std_target = tscope

        # Duration
        dur = timing.get("duration", "instant")
        duration_map = {"UNTIL_END_OF_TURN": "until_end_of_turn", "YOUR_TURN": "your_turn", "continuous": "continuous"}
        std_duration = duration_map.get(dur, "instant")

        # Condition
        cond = None
        if target.get("filters", {}).get("linkStatus") == "linked": cond = "paired"
        if target.get("filters", {}).get("HP"): cond = f"HP<={target['filters']['HP']}"

        results.append({
            "effectId": eid, "trigger": trigger, "cost": cost,
            "action": std_action, "target": std_target,
            "value": val, "duration": std_duration,
            "condition": cond,
            "oncePerTurn": timing.get("oncePerTurn", False),
            "summary": f"{trigger}: {std_action} on {std_target}"
        })
    return results

# ── Deck ───────────────────────────────────────────────────────────
with open("card/gcgdecks.json") as f:
    DECK_CFG = json.load(f)
DECK_CARDS = DECK_CFG["decks"]["deck001"]["cards"]

TOKEN_CACHE = {}
for tid, tinfo in DECK_CFG.get("extraCard", {}).items():
    cid = f"st01/{tid}"
    TOKEN_CACHE[cid] = {
        "id": cid, "name": tinfo.get("name", tid), "cardType": "unit",
        "level": 0, "cost": 0, "ap": tinfo.get("ap", 0), "hp": tinfo.get("hp", 0),
        "link": [], "traits": tinfo.get("traits", []), "color": "Token",
        "keywords": ["Token"], "pilot_for": None, "command_pilot": False,
        "pilot_ap": 0, "pilot_hp": 0, "raw_rules": [],
    }

# ── State ──────────────────────────────────────────────────────────
@dataclass
class Slot:
    unit_id: Optional[str] = None
    pilot_id: Optional[str] = None
    unit_name: Optional[str] = None
    pilot_name: Optional[str] = None
    ap: int = 0
    hp: int = 0
    damage: int = 0
    status: Optional[str] = "active"
    keywords: list = field(default_factory=list)
    turns_on_field: int = 0

@dataclass
class Player:
    deck: list
    resource_deck: list
    hand: list
    trash: list
    removal: list
    active: int
    rested: int
    ex: int
    shields: list
    base_id: str
    base_hp: int
    base_damage: int
    base_alive: bool
    base_status: Optional[str]
    battle_area: list
    base_ap: int = 0
    turn_count: int = 0

    @property
    def level(self):
        return self.active + self.rested + self.ex

@dataclass
class Game:
    turn: int
    active_player: int
    first_player: int
    phase: str
    step: Optional[str]
    current_attacker: Optional[int]
    p: list
    battle_log: list
    game_over: bool
    winner: Optional[int]
    turn_played: list
    active_effects: list
    priority: Optional[int] = None

    def active(self): return self.p[self.active_player]
    def opponent(self): return self.p[1 - self.active_player]

    @property
    def priority_player(self):
        return f"P{self.priority + 1}" if self.priority is not None else None

    def to_dict(self):
        """Serialize Game to dict matching game_state.md format."""
        def player_dict(pi, p):
            return {
                "base": {"card_id": p.base_id, "ap": p.base_ap, "hp": p.base_hp,
                    "damage": p.base_damage, "alive": p.base_alive, "status": p.base_status},
                "shields": len(p.shields),
                "hand_count": len(p.hand),
                "hand_cards": list(p.hand),
                "deck_count": len(p.deck),
                "resource_deck_count": len(p.resource_deck),
                "resources": {"active": p.active, "rested": p.rested, "ex": p.ex},
                "battle_area": [{"slot": i, "unit_id": s.unit_id, "pilot_id": s.pilot_id,
                    "ap": s.ap, "hp": s.hp, "damage": s.damage, "status": s.status,
                    "keywords": list(s.keywords), "link": "Link" in s.keywords}
                    for i, s in enumerate(p.battle_area)],
                "trash": list(p.trash),
                "removal": list(p.removal),
            }
        return {
            "turn": self.turn,
            "first_player": f"P{self.first_player + 1}",
            "active_player": f"P{self.active_player + 1}",
            "phase": self.phase,
            "step": self.step,
            "current_attacker": self.current_attacker,
            "priority": self.priority,
            "p1": player_dict(0, self.p[0]),
            "p2": player_dict(1, self.p[1]),
            "active_effects": [],
            "battle_log": list(self.battle_log),
            "game_over": self.game_over,
            "winner": f"P{self.winner + 1}" if self.winner is not None else None,
        }

    def write_state(self, path="game_state.md"):
        """Write current game state to game_state.md in YAML format."""
        with open(path, "w") as f:
            yaml.dump(self.to_dict(), f, default_flow_style=None, allow_unicode=True, sort_keys=False)

    @classmethod
    def from_dict(cls, d, seed=42):
        """Deserialize game_state.md dict back to Game. Rebuilds cards from cache."""
        random.seed(seed)
        def parse_p(pd, deck_cards, rd_cards):
            bd = pd["base"]
            p = Player(
                deck=list(deck_cards), resource_deck=list(rd_cards),
                hand=list(pd.get("hand_cards", [])),
                trash=list(pd.get("trash", [])),
                removal=list(pd.get("removal", [])),
                active=pd["resources"]["active"],
                rested=pd["resources"]["rested"],
                ex=pd["resources"]["ex"],
                shields=[None] * pd["shields"],
                base_id=bd["card_id"], base_ap=bd.get("ap", 0),
                base_hp=bd["hp"], base_damage=bd["damage"],
                base_alive=bd["alive"], base_status=bd.get("status"),
                battle_area=[Slot() for _ in range(6)],
            )
            for ba in pd.get("battle_area", []):
                si = ba["slot"]
                s = p.battle_area[si]
                s.unit_id = ba["unit_id"]; s.pilot_id = ba.get("pilot_id")
                s.ap = ba["ap"]; s.hp = ba["hp"]; s.damage = ba["damage"]
                s.status = ba["status"]
                s.keywords = list(ba.get("keywords", []))
                if ba.get("link") and "Link" not in s.keywords:
                    s.keywords.append("Link")
            return p
        first = 0 if d["first_player"] == "P1" else 1
        active = 0 if d["active_player"] == "P1" else 1
        deck1 = copy.deepcopy(DECK_CARDS); deck2 = copy.deepcopy(DECK_CARDS)
        random.shuffle(deck1); random.shuffle(deck2)
        rd1 = copy.deepcopy(DECK_CARDS[:10]); rd2 = copy.deepcopy(DECK_CARDS[:10])
        random.shuffle(rd1); random.shuffle(rd2)
        g = Game(
            turn=d["turn"], active_player=active, first_player=first,
            phase=d["phase"], step=d.get("step"), current_attacker=d.get("current_attacker"),
            priority=d.get("priority"),
            p=[parse_p(d["p1"], deck1, rd1), parse_p(d["p2"], deck2, rd2)],
            battle_log=list(d.get("battle_log", [])),
            game_over=d.get("game_over", False),
            winner=None if d.get("winner") is None else (0 if d["winner"] == "P1" else 1),
            turn_played=[[], []], active_effects=[],
        )
        return g

# ── Game Init ──────────────────────────────────────────────────────
def init_game(seed=42):
    random.seed(seed)
    p1_deck, p2_deck = copy.deepcopy(DECK_CARDS), copy.deepcopy(DECK_CARDS)
    random.shuffle(p1_deck); random.shuffle(p2_deck)
    rd1 = copy.deepcopy(DECK_CARDS[:10])
    rd2 = copy.deepcopy(DECK_CARDS[:10])
    random.shuffle(rd1); random.shuffle(rd2)

    def mk_p(deck, rd):
        return Player(deck=deck, resource_deck=rd, hand=[], trash=[], removal=[],
            active=0, rested=0, ex=0, shields=[], base_id="EX-BASE",
            base_ap=0, base_hp=3, base_damage=0, base_alive=True, base_status=None,
            battle_area=[Slot() for _ in range(6)])

    first = random.randint(0, 1)
    g = Game(turn=0, active_player=first, first_player=first,
        phase="pre-game", step=None, current_attacker=None,
        priority=None,
        p=[mk_p(p1_deck, rd1), mk_p(p2_deck, rd2)], battle_log=[],
        game_over=False, winner=None, turn_played=[[], []],
        active_effects=[])

    for i in range(2):
        g.p[i].hand = g.p[i].deck[:5]
        g.p[i].deck = g.p[i].deck[5:]
        g.p[i].resource_deck = g.p[i].resource_deck[:10]
        log(g, f"P{i+1} starting hand (5 cards)")

    if first == 0:
        g.p[1].ex = 1; log(g, "P2 gets 1 EX Resource (second player) [CR-1.2]")
    else:
        g.p[0].ex = 1; log(g, "P1 gets 1 EX Resource (second player) [CR-1.2]")

    log(g, f"P1: {len(g.p[0].deck)} deck, {len(g.p[0].shields)} shields")
    log(g, f"P2: {len(g.p[1].deck)} deck, {len(g.p[1].shields)} shields")
    return g

def setup_shields(g):
    """Set up 6 shields per player from deck top (CR-1.3, CR-1.5). Called after mulligan."""
    for i in range(2):
        g.p[i].shields = g.p[i].deck[:6]
        g.p[i].deck = g.p[i].deck[6:]
    log(g, "Shields set: 6 each [CR-1.3]")

def log(g, msg):
    g.battle_log.append(msg)
    print(f"  {msg}")

def log_action(g, template, **kwargs):
    """Log using ui_templates.md §12 format."""
    g.battle_log.append(template.format(**kwargs))

def trigger_events(g, event, player_idx, context=None):
    """Fire effects matching a trigger event. event: on_deploy, on_pair, on_attack, end_of_turn, on_burst."""
    p = g.p[player_idx]
    op = g.opponent()
    if event == "end_of_turn":
        for i, slot in enumerate(p.battle_area):
            if not slot.unit_id: continue
            cid = slot.unit_id
            for eff in interpret_effects(cid):
                if eff["trigger"] == "end_of_turn":
                    act = eff["action"]
                    if act.startswith("heal"):
                        import re
                        m = re.search(r'heal\((\d+)\)', act)
                        val = int(m.group(1)) if m else 2
                        slot.damage = max(0, slot.damage - val)
                        log(g, f"  [End of Turn] {slot.unit_name} heals {val} HP (→{slot.hp - slot.damage}/{slot.hp})")
    elif event == "on_deploy":
        if context and context.get("card_id"):
            cid = context["card_id"]
            for eff in interpret_effects(cid):
                if eff["trigger"] == "on_deploy":
                    act = eff["action"]
                    if act == "rest_target":
                        candidates = [(i, s) for i, s in enumerate(op.battle_area) if s.unit_id and s.status == "active"]
                        if candidates:
                            candidates.sort(key=lambda x: x[1].hp - x[1].damage)
                            si, slot = candidates[0]
                            slot.status = "rested"
                            log(g, f"  [Deploy] Rested {slot.unit_name} (slot {si})")
                    elif act == "shield_to_hand(1)":
                        if len(p.shields) > 0:
                            ret = p.shields.pop(0)
                            p.hand.append(ret)
                            log(g, f"  [Deploy] Top shield returned to hand")

def phase_log(g, msg):
    g.battle_log.append(msg)
    print(f"\n=== {msg} ===")

# ── Slot helpers ───────────────────────────────────────────────────
def clear_slot(slot):
    slot.unit_id = slot.pilot_id = slot.unit_name = slot.pilot_name = None
    slot.ap = slot.hp = slot.damage = 0
    slot.status = None; slot.keywords = []

def slot_empty(slot):
    return slot.unit_id is None

def count_units(p):
    return sum(1 for s in p.battle_area if s.unit_id)

def get_effective_ap(g, player_idx, slot_idx):
    """Compute effective AP for a unit including active effects."""
    slot = g.p[player_idx].battle_area[slot_idx]
    if not slot.unit_id:
        return 0
    total = slot.ap
    for eff in g.active_effects:
        params = eff["parameters"]
        if params.get("player_idx") == player_idx and params.get("slot_idx") == slot_idx and params.get("stat") == "ap":
            total += params.get("value", 0)
    return max(0, total)

def register_effect(g, effectId, source, timing, parameters):
    """Register an active effect on the game."""
    eff = {
        "effectId": effectId,
        "source": source,
        "timing": timing,
        "parameters": parameters,
        "used_this_turn": False,
    }
    g.active_effects.append(eff)
    return eff

def clear_timed_effects(g, timing="UNTIL_END_OF_TURN"):
    """Remove all active effects with the given timing."""
    g.active_effects = [e for e in g.active_effects if e["timing"] != timing]

# ── Phase Transitions ──────────────────────────────────────────────
def do_start_phase(g):
    clear_timed_effects(g, "UNTIL_END_OF_TURN")
    i = g.active_player  # only active player untaps (CR-2.4)
    total = g.p[i].active + g.p[i].rested
    g.p[i].active = total; g.p[i].rested = 0
    for slot in g.p[i].battle_area:
        if slot.unit_id and slot.status == "rested": slot.status = "active"
        slot.turns_on_field += 1
    if g.p[i].base_alive and g.p[i].base_status: g.p[i].base_status = "active"
    g.turn_played = [[], []]
    phase_log(g, f"Start Phase — P{i+1} reset all rested")

def do_draw_phase(g):
    p = g.active()
    if len(p.deck) == 0:
        g.game_over = True; g.winner = 1 - g.active_player
        log(g, f"P{g.active_player+1} deck empty → lose! [CR-8.2]")
        return
    drawn = p.deck.pop(0)
    p.hand.append(drawn)
    log(g, f"P{g.active_player+1} draws a card")

def do_resource_phase(g):
    p = g.active()
    if len(p.resource_deck) == 0:
        log(g, "Resource deck empty — skip [CR-8.3]"); return
    p.resource_deck.pop(0); p.active += 1
    log(g, f"P{g.active_player+1} deploys a resource")

def advance_to_main(g):
    g.phase = "main"; g.step = None
    phase_log(g, f"Turn {g.turn} | Main Phase | P{g.active_player+1}'s turn")

def advance_turn(g):
    if g.game_over: return
    do_start_phase(g); do_draw_phase(g)
    if g.game_over: return
    do_resource_phase(g); advance_to_main(g)

# ── Combat ─────────────────────────────────────────────────────────
def resolve_combat(g, attacker_slot):
    """Declare an attack. Phase → battle(attack). Block and damage handled in game loop."""
    ap = g.active()
    atk = ap.battle_area[attacker_slot]
    if not atk.unit_id: log(g, "No unit in slot!"); return

    g.phase = "battle"
    g.step = "attack"
    g.current_attacker = attacker_slot
    g.priority = g.active_player  # active player has priority after attack
    atk_ap = get_effective_ap(g, g.active_player, attacker_slot)
    atk.status = "rested"
    log(g, f"P{g.active_player+1} attacks with slot {attacker_slot}")
    trigger_events(g, "on_attack", g.active_player, {"slot": attacker_slot})

def execute_block(g, player_idx, slot):
    """Execute a block. Rest blocker, advance to action step."""
    p = g.p[player_idx]
    if slot < 0 or slot >= 6:
        log(g, f"Invalid block slot {slot}"); return False
    bslot = p.battle_area[slot]
    if not bslot.unit_id:
        log(g, f"No unit in slot {slot} to block"); return False
    if bslot.status != "active":
        log(g, f"Unit in slot {slot} is not active (can't block)"); return False
    if "Blocker" not in bslot.keywords:
        log(g, f"Unit in slot {slot} does not have Blocker"); return False
    bslot.status = "rested"
    g.step = "action"
    log(g, f"P{player_idx+1} blocks with slot {slot}")
    return True

def resolve_damage(g):
    """Resolve combat damage after action step. Handles blocked and unblocked attacks."""
    ap = g.active()
    op = g.opponent()
    attacker_slot = g.current_attacker
    if attacker_slot is None: return
    atk = ap.battle_area[attacker_slot]
    if not atk.unit_id: return
    atk_ap = get_effective_ap(g, g.active_player, attacker_slot)

    # Check if blocked: look for a rested non-active unit (blocker)
    blocker_slot = None
    for i, slot in enumerate(op.battle_area):
        if slot.unit_id and slot.status == "rested" and "Blocker" in getattr(slot, 'keywords', []):
            blocker_slot = i
            break

    if blocker_slot is not None:
        bslot = op.battle_area[blocker_slot]

        # Check for First Strike (CR-5.7)
        atk_has_fs = "First Strike" in atk.keywords
        def_has_fs = "First Strike" in bslot.keywords

        if atk_has_fs and not def_has_fs:
            # Attacker deals damage first
            bslot.damage += atk_ap
            log(g, f"  [FS] {atk.unit_name} strikes first! {bslot.unit_name} takes {atk_ap} dmg")
            if bslot.damage >= bslot.hp:
                log(g, f"  {bslot.unit_name} destroyed — no counterattack!")
                pname = bslot.pilot_name
                if pname: log(g, f"  Pilot {pname} also trashed"); op.trash.append(bslot.pilot_id)
                op.trash.append(bslot.unit_id); clear_slot(bslot)
            else:
                # Blocker counterattacks
                if bslot.ap > 0:
                    atk.damage += bslot.ap
                    log(g, f"  Counter: {atk.unit_name} takes {bslot.ap} dmg")
                    if atk.damage >= atk.hp:
                        log(g, f"  {atk.unit_name} destroyed!")
                        pname = atk.pilot_name
                        if pname: log(g, f"  Pilot {pname} also trashed"); ap.trash.append(atk.pilot_id)
                        ap.trash.append(atk.unit_id); clear_slot(atk)
        elif def_has_fs and not atk_has_fs:
            # Blocker strikes first
            atk.damage += bslot.ap
            log(g, f"  [FS] {bslot.unit_name} strikes first! {atk.unit_name} takes {bslot.ap} dmg")
            if atk.damage >= atk.hp:
                log(g, f"  {atk.unit_name} destroyed — no counterattack!")
                pname = atk.pilot_name
                if pname: log(g, f"  Pilot {pname} also trashed"); ap.trash.append(atk.pilot_id)
                ap.trash.append(atk.unit_id); clear_slot(atk)
            elif atk_ap > 0:
                bslot.damage += atk_ap
                log(g, f"  Counter: {bslot.unit_name} takes {atk_ap} dmg")
                if bslot.damage >= bslot.hp:
                    log(g, f"  {bslot.unit_name} destroyed!")
                    pname = bslot.pilot_name
                    if pname: log(g, f"  Pilot {pname} also trashed"); op.trash.append(bslot.pilot_id)
                    op.trash.append(bslot.unit_id); clear_slot(bslot)
        else:
            # No FS or both have FS — simultaneous damage (original logic)
            bslot.damage += atk_ap
            log(g, f"  {atk.unit_name} deals {atk_ap} damage to {bslot.unit_name}")
            if bslot.damage >= bslot.hp:
                log(g, f"  {bslot.unit_name} destroyed!")
                pname = bslot.pilot_name
                if pname: log(g, f"  Pilot {pname} also trashed"); op.trash.append(bslot.pilot_id)
                op.trash.append(bslot.unit_id); clear_slot(bslot)
            if bslot.unit_id and bslot.ap > 0 and bslot.damage < bslot.hp:
                atk.damage += bslot.ap
                log(g, f"  {bslot.unit_name} deals {bslot.ap} damage to {atk.unit_name}")
                if atk.damage >= atk.hp:
                    log(g, f"  {atk.unit_name} destroyed in counter!")
                    pname = atk.pilot_name
                    if pname: log(g, f"  Pilot {pname} also trashed"); ap.trash.append(atk.pilot_id)
                    ap.trash.append(atk.unit_id); clear_slot(atk)
    else:
        # No blocker — damage hits defense layer (CR-4.3)
        if atk_ap <= 0:
            log(g, f"  0 AP — cannot damage defense layer [CR-4.8]")
        elif op.base_alive:
            op.base_damage += atk_ap
            log_action(g, "{attacker} deals {N} damage to {target} (HP: {current}/{max})",
                attacker=f"P{g.active_player+1}'s {atk.unit_name or 'attacker'}",
                N=atk_ap, target=f"P{2-g.active_player}'s Base",
                current=op.base_hp - op.base_damage, max=op.base_hp)
            if op.base_damage >= op.base_hp:
                log(g, f"  Base destroyed! [CR-4.4]")
                op.base_alive = False; op.base_status = None
        elif len(op.shields) > 0:
            shield = op.shields.pop(0)
            info = card_info(shield); sname = info["name"] if info else shield
            log(g, f"  Shield destroyed: {sname} [CR-4.6]")
            if info:
                effs = interpret_effects(shield)
                burst_effs = [e for e in effs if e["trigger"] == "on_burst"]
                if burst_effs:
                    for be in burst_effs:
                        ba = be["action"]
                        log(g, f"  Burst triggered: {ba}")
                        if ba == "return_to_hand":
                            op.hand.append(shield)
                            log(g, f"    {sname} added to hand via Burst")
                        elif ba == "deploy_self":
                            if info["cardType"] == "base":
                                if op.base_alive:
                                    op.trash.append(f"{op.base_id} (was base)")
                                    if len(op.shields) > 0:
                                        ret = op.shields.pop(0)
                                        op.hand.append(ret)
                                        log(g, f"    Top shield returned to hand [CR-7.3]")
                                op.base_id = shield; op.base_alive = True
                                op.base_damage = 0; op.base_hp = info["hp"]; op.base_ap = info["ap"]
                                op.base_status = "active"
                                log(g, f"    {sname} deployed as new Base from Burst")
                            else:
                                empty = [i for i, s in enumerate(op.battle_area) if s.unit_id is None]
                                if empty:
                                    si = empty[0]
                                    slot = op.battle_area[si]
                                    slot.unit_id = shield; slot.unit_name = sname
                                    slot.ap = info["ap"]; slot.hp = info["hp"]
                                    slot.damage = 0; slot.status = "active"
                                    slot.keywords = list(info["keywords"]); slot.turns_on_field = 0
                                    log(g, f"    {sname} deployed from Burst to slot {si}")
                                else:
                                    log(g, f"    No empty slot for Burst deploy")
                        elif ba == "activate_ability":
                            log(g, f"    Burst activates Main ability")
                        else:
                            log(g, f"    Unhandled Burst action: {ba}")
                            op.trash.append(shield)
                else:
                    op.trash.append(shield)
            else:
                # Unknown card — still goes to trash
                op.trash.append(shield)
        else:
            g.game_over = True; g.winner = g.active_player
            log(g, f"  DIRECT HIT! P{g.active_player+1} wins! [CR-4.9]")
            return

        # Breach damage (CR-6.3) — applies to shield area regardless of main damage target
        breach_val = 0
        for kw in atk.keywords:
            if kw.startswith("Breach"):
                parts = kw.split()
                if len(parts) > 1:
                    try: breach_val += int(parts[1])
                    except: breach_val += 1
        if breach_val > 0:
            if op.base_alive and (len(op.shields) > 0 or op.base_alive):
                op.base_damage += breach_val
                log(g, f"  Breach: {breach_val} extra damage to Base!")
                if op.base_damage >= op.base_hp:
                    log(g, f"  Base destroyed by Breach! [CR-4.4]")
                    op.base_alive = False; op.base_status = None
            elif len(op.shields) > 0:
                for _ in range(min(breach_val, len(op.shields))):
                    bshield = op.shields.pop(0)
                    info_b = card_info(bshield)
                    sname_b = info_b["name"] if info_b else bshield
                    log(g, f"  Breach destroys shield: {sname_b}")
                    op.trash.append(bshield)
            else:
                log(g, f"  Breach: {breach_val} — no shield area to hit [CR-6.3]")

    # Advance to battle_end step (CR-5.2)
    g.step = "battle_end"
    log(g, f"  Battle step → battle_end [CR-5.2]")

# ── Play Card ──────────────────────────────────────────────────────
def can_play(g, player_idx, card_id, check_slot=True):
    info = card_info(card_id)
    if not info: return False, "Unknown card"
    p = g.p[player_idx]
    if card_id not in p.hand: return False, "Card not in hand"
    if info["cardType"] == "unit" and info.get("level", 0) == 0:
        return False, "Token cannot be played from hand [CR-6.7]"
    if p.level < info["level"]: return False, f"Level不足 ({p.level}<{info['level']})"
    needed = info["cost"]
    if not (p.active >= needed or p.active + p.ex >= needed):
        return False, f"Cost不足 (active={p.active}, need={needed})"
    if check_slot and info["cardType"] in ("unit", "pilot", "base"):
        if info["cardType"] == "base":
            pass  # Base replaces current base, no slot needed
        elif not any(s.unit_id is None for s in p.battle_area):
            return False, "No empty battle area slot [CR-5.11]"
    return True, "OK"

def pay_cost(g, player_idx, cost):
    p = g.p[player_idx]
    if p.active >= cost:
        p.active -= cost; p.rested += cost
    else:
        rem = cost - p.active; p.rested += p.active; p.active = 0; p.ex -= rem

def apply_command_effect(g, player_idx, card_id):
    """Apply card effects. Handles all action types from card JSON."""
    info = card_info(card_id)
    if not info: return
    p = g.p[player_idx]; op = g.opponent()
    rules = info.get("raw_rules", [])
    name = info["name"]
    ctype = info["cardType"]

    for rule in rules:
        action = rule.get("action", "")
        params = rule.get("parameters", {})
        target = rule.get("target", {})
        val = params.get("value", 1)

        if action == "damage":
            filters = target.get("filters", {})
            candidates = []
            for i, slot in enumerate(op.battle_area):
                if not slot.unit_id: continue
                match = True
                for fkey, fval in filters.items():
                    if fkey == "status" and slot.status != fval: match = False
                if match:
                    candidates.append((i, slot))
            if candidates:
                candidates.sort(key=lambda x: x[1].hp - x[1].damage)
                si, slot = candidates[0]
                slot.damage += val
                log(g, f"  Effect: {name} deals {val} damage to {slot.unit_name} (HP: {slot.hp - slot.damage}/{slot.hp})")
                if slot.damage >= slot.hp:
                    log(g, f"  {slot.unit_name} destroyed by command!")
                    if slot.pilot_name: op.trash.append(slot.pilot_id)
                    op.trash.append(slot.unit_id); clear_slot(slot)

        elif action == "modifyAP":
            candidates = [(i, s) for i, s in enumerate(op.battle_area) if s.unit_id]
            if candidates:
                targets = [(i, get_effective_ap(g, 1 - player_idx, i)) for i, s in candidates]
                targets.sort(key=lambda x: x[1])
                si = targets[0][0]
                slot = op.battle_area[si]
                register_effect(g, effectId=f"modifyAP_{len(g.active_effects)}", source=name, timing="UNTIL_END_OF_TURN", parameters={"player_idx": 1 - player_idx, "slot_idx": si, "stat": "ap", "value": val})
                new_ap = get_effective_ap(g, 1 - player_idx, si)
                ap_sign = "+" if val >= 0 else ""
                log(g, f"  {name} modifies {slot.unit_name} AP{ap_sign}{val} (→{new_ap})")
            else:
                log(g, f"  Effect: {name} — no enemy unit to target")

        elif action == "heal":
            scope = target.get("scope", "self")
            if scope == "self_all_units":
                for slot in p.battle_area:
                    if slot.unit_id and slot.damage > 0:
                        healed = min(val, slot.damage)
                        slot.damage -= healed
                        log(g, f"  Effect: {name} heals {slot.unit_name} for {healed} HP (→{slot.hp - slot.damage}/{slot.hp})")
            elif scope == "self":
                # Heal self (the card itself)
                log(g, f"  Effect: {name} — heal self (scope=self, not a unit slot)")
            else:
                # Default: self_unit(1) — heal most damaged friendly unit
                candidates = [(i, s) for i, s in enumerate(p.battle_area) if s.unit_id and s.damage > 0]
                if candidates:
                    candidates.sort(key=lambda x: -x[1].damage)
                    si, slot = candidates[0]
                    healed = min(val, slot.damage)
                    slot.damage -= healed
                    log(g, f"  Effect: {name} heals {slot.unit_name} for {healed} HP (→{slot.hp - slot.damage}/{slot.hp})")
                else:
                    log(g, f"  Effect: {name} — no damaged unit to heal")

        elif action == "draw":
            for _ in range(val):
                if len(p.deck) == 0:
                    g.game_over = True; g.winner = 1 - player_idx
                    log(g, f"  P{player_idx+1} draws from empty deck → loses! [CR-8.2]")
                    return
                drawn = p.deck.pop(0)
                p.hand.append(drawn)
                log(g, f"  Effect: {name} — drew 1 card")

        elif action == "rest":
            candidates = [(i, s) for i, s in enumerate(op.battle_area) if s.unit_id and s.status == "active"]
            if candidates:
                candidates.sort(key=lambda x: x[1].hp - x[1].damage)
                si, slot = candidates[0]
                slot.status = "rested"
                log(g, f"  Effect: {name} — rested {slot.unit_name} (slot {si})")
            else:
                log(g, f"  Effect: {name} — no active enemy unit to rest")

        elif action == "setActive":
            if p.rested > 0:
                p.rested -= 1
                p.active += 1
                log(g, f"  Effect: {name} — activated 1 resource")
            else:
                log(g, f"  Effect: {name} — no rested resources to activate")

        elif action == "addToHand":
            if target.get("scope") == "self_shield" and len(p.shields) > 0:
                ret = p.shields.pop(0)
                p.hand.append(ret)
                info_r = card_info(ret)
                sname = info_r["name"] if info_r else ret
                log(g, f"  Effect: {name} — returned {sname} (shield) to hand")

        elif action == "deploy":
            if ctype == "base":
                if p.base_alive:
                    log(g, f"  Old base ({p.base_id}) → trash [CR-7.3]")
                    p.trash.append(p.base_id)
                    if len(p.shields) > 0:
                        ret = p.shields.pop(0); p.hand.append(ret)
                        log(g, f"  Top shield returned to hand")
                p.base_id = card_id; p.base_alive = True
                p.base_damage = 0; p.base_hp = info["hp"]; p.base_ap = info["ap"]
                p.base_status = "active"
                log(g, f"  Effect: {name} deployed as new Base (HP:{info['hp']})")

        elif action == "conditionalTokenDeploy":
            empty = [i for i, s in enumerate(p.battle_area) if s.unit_id is None]
            if not empty:
                log(g, f"  Effect: {name} — no empty slots for token")
            else:
                token_id = f"st01/T-001"
                tinfo = TOKEN_CACHE.get(token_id)
                if tinfo:
                    si = empty[0]
                    slot = p.battle_area[si]
                    slot.unit_id = token_id; slot.unit_name = tinfo["name"]
                    slot.ap = tinfo["ap"]; slot.hp = tinfo["hp"]
                    slot.damage = 0; slot.status = "active"
                    slot.keywords = ["Token"]; slot.turns_on_field = 0
                    log(g, f"  Effect: {name} — deployed {tinfo['name']} (AP:{tinfo['ap']}/HP:{tinfo['hp']}) to slot {si}")

        elif action == "activate_ability":
            log(g, f"  Effect: {name} — activates Main ability")

        else:
            log(g, f"  Effect: {name} — unhandled action: {action}")

def play_card(g, player_idx, card_id, slot_idx=None, as_pilot=False):
    p = g.p[player_idx]
    ok, reason = can_play(g, player_idx, card_id, check_slot=False)
    if not ok: log(g, f"Cannot play {card_id}: {reason}"); return False
    if card_id not in p.hand: log(g, f"{card_id} not in hand!"); return False

    info = card_info(card_id)
    p.hand.remove(card_id)
    g.turn_played[player_idx].append(card_id)
    pay_cost(g, player_idx, info["cost"])
    name, ctype = info["name"], info["cardType"]
    log(g, f"P{player_idx+1} {'plays' if ctype == 'command' else 'deploys'} {card_id}")

    if ctype == "unit":
        empty = [i for i, s in enumerate(p.battle_area) if s.unit_id is None]
        if not empty:
            log(g, f"  No empty slots [CR-5.11] — trashing oldest")
            oldest = min([(i, s.turns_on_field) for i, s in enumerate(p.battle_area) if s.unit_id], key=lambda x: x[1])[0]
            for cid in [p.battle_area[oldest].unit_id, p.battle_area[oldest].pilot_id]:
                if cid: p.trash.append(cid)
            p.battle_area[oldest] = Slot(); empty = [oldest]
        si = slot_idx if slot_idx is not None and slot_idx in empty else empty[0]
        slot = p.battle_area[si]
        slot.unit_id = card_id; slot.unit_name = name
        slot.ap = info["ap"]; slot.hp = info["hp"]
        slot.damage = 0; slot.status = "active"
        slot.keywords = list(info["keywords"]); slot.turns_on_field = 0
        log(g, f"  → Slot {si}")
        trigger_events(g, "on_deploy", player_idx, {"card_id": card_id})
        # Check auto-link with pilot already in slot
        if slot.pilot_id:
            pinfo = card_info(slot.pilot_id)
            if pinfo and slot.pilot_name in info.get("link", []):
                if "Link" not in slot.keywords: slot.keywords.append("Link")
                log(g, f"  Auto-Link: {name} + {slot.pilot_name} [CR-6.4]")
        # Deploy effects
        for d in RAW.get(card_id.split("/")[-1], {}).get("effects", {}).get("description", []):
            if "[Deploy]" in d: log(g, f"  [Deploy]: {d}")

    elif ctype == "pilot":
        # Find best slot: existing unit with matching link
        best = None
        for i, s in enumerate(p.battle_area):
            if s.unit_id and not s.pilot_id:
                uinfo = card_info(s.unit_id)
                if uinfo and name in uinfo.get("link", []):
                    best = i; break
        if best is None:
            # Any unit without pilot
            has = [i for i, s in enumerate(p.battle_area) if s.unit_id and not s.pilot_id]
            best = has[0] if has else None
        if best is None:
            # Deploy to empty slot
            empty = [i for i, s in enumerate(p.battle_area) if s.unit_id is None]
            if not empty:
                log(g, f"  No slots for pilot!"); p.hand.append(card_id); return False
            best = empty[0]
        slot = p.battle_area[best]
        slot.pilot_id = card_id; slot.pilot_name = name
        uinfo = card_info(slot.unit_id) if slot.unit_id else None
        if uinfo and name in uinfo.get("link", []):
            if "Link" not in slot.keywords: slot.keywords.append("Link")
            log(g, f"  Link Unit formed! {slot.unit_name} + {name} [CR-6.4]")
            if slot.unit_id:
                trigger_events(g, "on_pair", player_idx, {"slot": best, "pilot_id": card_id})
        else:
            log(g, f"  → Slot {best}")

    elif ctype == "command":
        is_pilot_card = info.get("command_pilot", False)
        if is_pilot_card and as_pilot:
            # Deploy [Pilot] card as a pilot onto a slot
            best = None
            for i, s in enumerate(p.battle_area):
                if s.unit_id and not s.pilot_id:
                    uinfo = card_info(s.unit_id)
                    if uinfo and name in uinfo.get("link", []):
                        best = i; break
            if best is None:
                has = [(i, s) for i, s in enumerate(p.battle_area) if s.unit_id and not s.pilot_id]
                if has:
                    best = has[0][0]
                else:
                    empty = [i for i, s in enumerate(p.battle_area) if s.unit_id is None]
                    if empty:
                        best = empty[0]
            if best is not None:
                slot = p.battle_area[best]
                slot.pilot_id = card_id; slot.pilot_name = name
                uinfo = card_info(slot.unit_id) if slot.unit_id else None
                if uinfo and name in uinfo.get("link", []):
                    if "Link" not in slot.keywords: slot.keywords.append("Link")
                    log(g, f"  Link Unit formed! {slot.unit_name} + {name} [CR-6.4]")
                else:
                    log(g, f"  → Slot {best}")
            else:
                log(g, f"  [Pilot] no slot available — deploy failed")
                p.hand.append(card_id)  # return card to hand
                return False
        else:
            if is_pilot_card:
                log(g, f"  [Pilot] dual card — playing as Command")
            apply_command_effect(g, player_idx, card_id)
            p.trash.append(card_id)

    elif ctype == "base":
        if p.base_alive:
            log(g, f"  Old base ({p.base_id}) → trash [CR-7.3]")
            p.trash.append(p.base_id)
            if len(p.shields) > 0:
                ret = p.shields.pop(0); p.hand.append(ret)
                log(g, f"  Top shield returned to hand")
        p.base_id = card_id; p.base_alive = True
        p.base_damage = 0; p.base_hp = info["hp"]; p.base_ap = info["ap"]
        p.base_status = "active"
        log(g, f"  New Base deployed (HP:{info['hp']})")

    return True

# ── Experience System ──────────────────────────────────────────────
_EXP_DIR = os.path.join(os.path.dirname(__file__), "experience") if "__file__" in dir() else "experience"

def _check_condition(cond, p, op, g):
    """Check if an experience condition matches the current game state."""
    if "turn_min" in cond and g.turn < cond["turn_min"]: return False
    if "turn_max" in cond and g.turn > cond["turn_max"]: return False
    my_units = sum(1 for s in p.battle_area if s.unit_id)
    en_units = sum(1 for s in op.battle_area if s.unit_id)
    if "my_units_min" in cond and my_units < cond["my_units_min"]: return False
    if "my_units_max" in cond and my_units > cond["my_units_max"]: return False
    if "enemy_units_min" in cond and en_units < cond["enemy_units_min"]: return False
    if "enemy_units_max" in cond and en_units > cond["enemy_units_max"]: return False
    if "my_hand_min" in cond and len(p.hand) < cond["my_hand_min"]: return False
    if "my_hand_max" in cond and len(p.hand) > cond["my_hand_max"]: return False
    empty = sum(1 for s in p.battle_area if s.unit_id is None)
    if "my_empty_slots_min" in cond and empty < cond["my_empty_slots_min"]: return False
    if "my_empty_slots_max" in cond and empty > cond["my_empty_slots_max"]: return False
    bh = p.base_hp - p.base_damage
    if "my_base_hp_min" in cond and bh < cond["my_base_hp_min"]: return False
    if "my_base_hp_max" in cond and bh > cond["my_base_hp_max"]: return False
    en_sh = len(op.shields)
    if "enemy_shields_min" in cond and en_sh < cond["enemy_shields_min"]: return False
    if "enemy_shields_max" in cond and en_sh > cond["enemy_shields_max"]: return False
    res = p.active + p.rested
    if "my_resources_min" in cond and res < cond["my_resources_min"]: return False
    if "my_resources_max" in cond and res > cond["my_resources_max"]: return False
    en_rested = sum(1 for s in op.battle_area if s.unit_id and s.status == "rested")
    if "enemy_rested_units_min" in cond and en_rested < cond["enemy_rested_units_min"]: return False
    if "enemy_rested_units_max" in cond and en_rested > cond["enemy_rested_units_max"]: return False
    en_dmg = sum(1 for s in op.battle_area if s.unit_id and s.damage > 0)
    if "enemy_damaged_units_min" in cond and en_dmg < cond["enemy_damaged_units_min"]: return False
    if "enemy_damaged_units_max" in cond and en_dmg > cond["enemy_damaged_units_max"]: return False
    has_link = any("Link" in s.keywords for s in p.battle_area)
    if "has_link_units" in cond and bool(cond["has_link_units"]) != has_link: return False
    if "is_first_turn" in cond and bool(cond["is_first_turn"]) != (g.turn == 1): return False
    unpaired = any(s.unit_id and not s.pilot_id for s in p.battle_area)
    if "has_unpaired_units" in cond and bool(cond["has_unpaired_units"]) != unpaired: return False
    en_has_blocker = any("Blocker" in s.keywords for s in op.battle_area if s.unit_id)
    if "enemy_has_blocker" in cond and bool(cond["enemy_has_blocker"]) != en_has_blocker: return False
    return True

def _merge_effects(matched):
    """Merge multiple experience files into one effect dict. For score_bonus, sum additive."""
    merged = {"score_bonus": {}, "attack_target": None, "block_priority_shift": 0, "desperate_play": None}
    _highest_pri = -1
    for pri, exp in sorted(matched, key=lambda x: -x[0]):
        eff = exp.get("effect", {})
        sb = eff.get("score_bonus")
        if sb:
            entries = sb if isinstance(sb, list) else [sb]
            for entry in entries:
                ct = entry.get("card_type"); val = entry.get("bonus", 0)
                merged["score_bonus"][ct] = merged["score_bonus"].get(ct, 0) + val
        at = eff.get("attack_target")
        if at and pri > _highest_pri:
            merged["attack_target"] = at
        bps = eff.get("block_priority_shift")
        if bps is not None:
            merged["block_priority_shift"] += bps
        dp = eff.get("desperate_play")
        if dp is not None:
            merged["desperate_play"] = merged["desperate_play"] or dp
        if pri > _highest_pri:
            _highest_pri = pri
    return merged

def load_matching_experience(p, op, g):
    """Scan experience/ dir, load only files whose conditions match. Returns merged effects."""
    import os
    if not os.path.isdir(_EXP_DIR):
        return {}
    matched = []
    try:
        for fn in sorted(os.listdir(_EXP_DIR)):
            if not fn.endswith(".yaml"):
                continue
            fpath = os.path.join(_EXP_DIR, fn)
            with open(fpath) as f:
                exp = yaml.safe_load(f)
            cond = exp.get("condition", {})
            if _check_condition(cond, p, op, g):
                matched.append((exp.get("priority", 0), exp))
    except Exception:
        pass  # silently skip invalid experience files
    return _merge_effects(matched)

# ── AI Logic ───────────────────────────────────────────────────────
def ai_decision(g, player_idx):
    p = g.p[player_idx]; op = g.opponent()
    
    # Concede check (CR-8.4) — per AI Player §6
    # All 6 conditions must be met
    enemy_units = sum(1 for s in op.battle_area if s.unit_id)
    my_units = sum(1 for s in p.battle_area if s.unit_id)
    has_removal = any(
        "damage" in str(rule) or "rest" in str(rule)
        for cid in p.hand
        for rule in (card_info(cid) or {}).get("raw_rules", [])
    )
    if (enemy_units >= 3 and my_units == 0 and len(p.hand) <= 1
        and len(p.deck) <= 3 and len(p.shields) == 0 and not has_removal):
        return "concede"
    
    if g.phase == "start": return "pass"
    if g.phase == "draw": return "draw"
    if g.phase == "resource": return "resource"

    if g.phase == "end" and g.step == "action":
        exp = load_matching_experience(p, op, g)
        score_bonuses = exp.get("score_bonus", {})
        # End action step: only play pure commands (instant effects)
        best_cmd = None; best_score = 0
        for cid in p.hand:
            info = card_info(cid)
            if not info: continue
            if info["cardType"] != "command": continue
            if info.get("command_pilot", False): continue  # [Pilot] dual cards deploy as pilot, not instant
            ok, _ = can_play(g, player_idx, cid)
            if not ok: continue
            score = 10 + score_bonuses.get("command", 0)
            if score > best_score:
                best_score = score; best_cmd = cid
        if best_cmd:
            return f"play {best_cmd}"
        return "pass"

    if g.phase == "battle":
        if g.step == "battle_end":
            return "pass"  # auto-advance
        if g.step == "attack":
            # Non-active player: decide block or pass
            # CR-5.8: only active+Blocker can block
            # Strategy: block if blocker can survive (HP>AP) or if blocking protects from lethal
            attacker_slot = g.current_attacker
            if attacker_slot is not None:
                atk = op.battle_area[attacker_slot] if hasattr(g, 'current_attacker') else None
                atk_ap = get_effective_ap(g, g.active_player, attacker_slot) if (atk and atk.unit_id) else 0
            else:
                atk_ap = 0

            # Check if this attack is lethal (shields=0, base dead)
            lethal = (len(p.shields) == 0 and not p.base_alive)

            for i, slot in enumerate(p.battle_area):
                if slot.unit_id and slot.status == "active" and "Blocker" in slot.keywords:
                    if "不可攻擊玩家" not in slot.keywords:
                        remaining_hp = slot.hp - slot.damage
                        if lethal:
                            return f"block {i}"  # Block at all costs
                        if remaining_hp > atk_ap:
                            return f"block {i}"  # Blocker survives
                        # Blocker would die — only block if protecting high-value unit
                        # High-value: Link unit, high AP (4+), or low damage
                        # For now, don't block suicidal blocks
                        pass
            return "pass"
        elif g.step == "action":
            # Action step: consider playing commands
            return "pass"

    if g.phase == "main":
        exp = load_matching_experience(p, op, g)
        score_bonuses = exp.get("score_bonus", {})
        attack_target = exp.get("attack_target")
        desperate = exp.get("desperate_play", False)

        # Priority 1: Attack with strongest unit. Experience can bias targeting.
        attackable = []
        for i, slot in enumerate(p.battle_area):
            can_attack = slot.unit_id and slot.status == "active" and (slot.turns_on_field >= 1 or "Link" in slot.keywords)
            if not can_attack or "不可攻擊玩家" in slot.keywords:
                continue

            # Evaluate enemy units as targets (Tier 1: 補刀 > 最高AP > Blocker > 最低HP > 無關鍵字)
            for j, eslot in enumerate(op.battle_area):
                if not eslot.unit_id or eslot.hp - eslot.damage <= 0:
                    continue
                remaining_hp = eslot.hp - eslot.damage
                if get_effective_ap(g, player_idx, i) <= 0:
                    continue  # 0 AP can't do anything
                if get_effective_ap(g, player_idx, i) >= remaining_hp:
                    # Can kill this unit
                    if remaining_hp == 1:
                        pri = 20  # 補刀: highest priority
                    elif "Blocker" in eslot.keywords:
                        pri = 18  # Clear blocker
                    else:
                        pri = 15 + eslot.ap  # Kill by target AP (higher AP = higher priority)
                else:
                    # Can damage but not kill
                    pri = 10 + remaining_hp  # Damage low-HP units first
                attackable.append((pri, i, f"attack {i}"))

            # Evaluate attacking defense layer
            has_shields = len(op.shields) > 0
            base_exists = op.base_alive
            if has_shields or base_exists:
                if get_effective_ap(g, player_idx, i) > 0:
                    # Base attack priority (base is the outer layer)
                    if base_exists:
                        pri = 12  # Attack base
                    else:
                        pri = 14  # Attack shields (closer to win)
                    attackable.append((pri, i, f"attack {i}"))
        if attackable:
            attackable.sort(key=lambda x: -x[0])
            return attackable[0][2]

        empty_slots = [i for i, s in enumerate(p.battle_area) if s.unit_id is None]
        has_empty = len(empty_slots) > 0

        best = None
        for cid in p.hand:
            info = card_info(cid)
            if not info: continue
            ok, _ = can_play(g, player_idx, cid)
            if not ok: continue
            score = 0
            cmd = None

            if info["cardType"] == "unit":
                if not has_empty: continue
                eff = (info["ap"] + info["hp"]) / max(1, info["cost"])
                score = int(eff * 10) + (info["level"] * 2)
                if "Blocker" in info["keywords"]: score += 5
                score += score_bonuses.get("unit", 0)
                cmd = f"deploy {cid}"

            elif info["cardType"] == "pilot":
                if not has_empty:
                    has_unpaired = any(s.unit_id and not s.pilot_id for s in p.battle_area)
                    if not has_unpaired: continue
                score = score_bonuses.get("pilot", 0)  # base from experience
                has_matching = False
                for s in p.battle_area:
                    if s.unit_id:
                        uinfo = card_info(s.unit_id)
                        if uinfo and info["name"] in uinfo.get("link", []):
                            has_matching = True
                            score += 25; break
                if not has_matching:
                    # Deploying pilot without matching Link unit is low value
                    score += 5
                cmd = f"deploy {cid}"

            elif info["cardType"] == "command":
                is_pilot = info.get("command_pilot", False)
                if is_pilot:
                    has_unit = any(s.unit_id for s in p.battle_area)
                    has_slot = has_empty or any(s.unit_id and not s.pilot_id for s in p.battle_area)
                    if has_unit and has_slot:
                        score = 12 + score_bonuses.get("pilot", 0)
                        cmd = f"deploy {cid}"
                    else:
                        for eslot in op.battle_area:
                            if eslot.unit_id and eslot.status == "rested" and eslot.hp - eslot.damage <= 1:
                                score += 15; break
                        score += score_bonuses.get("command", 0)
                        cmd = f"play {cid}" if score > 0 else None
                else:
                    for eslot in op.battle_area:
                        if eslot.unit_id and eslot.hp - eslot.damage <= 1:
                            score += 15
                    score += score_bonuses.get("command", 0)
                    cmd = f"play {cid}" if score > 0 else None

            elif info["cardType"] == "base":
                if p.base_id == "EX-BASE" or not p.base_alive:
                    score = 10 + score_bonuses.get("base", 0)
                    cmd = f"deploy {cid}"

            if cmd and score > 0:
                if best is None or score > best[0]:
                    best = (score, info["cost"], cmd)

        if best:
            return best[2]

        # Fallback: desperate play if experience allows
        if desperate:
            for cid in p.hand:
                info = card_info(cid)
                if info and info["cardType"] == "unit":
                    ok, _ = can_play(g, player_idx, cid)
                    if ok and any(s.unit_id is None for s in p.battle_area):
                        return f"deploy {cid}"
            for cid in p.hand:
                info = card_info(cid)
                if info and info.get("command_pilot", False) and info["cardType"] == "command":
                    ok, _ = can_play(g, player_idx, cid)
                    if ok:
                        has_slot = any(s.unit_id is None for s in p.battle_area) or any(s.unit_id and not s.pilot_id for s in p.battle_area)
                        if has_slot:
                            return f"deploy {cid}"

        return "pass"
    return "pass"

# ── Command Parser ─────────────────────────────────────────────────
def parse_command(g, player_idx, cmd):
    cmd = cmd.strip(); p = g.p[player_idx]; op = g.opponent()
    cl = cmd.lower()
    if cl == "pass": g.phase = "end"; g.step = "action"; g.priority = 1 - player_idx; log(g, f"P{player_idx+1} passes"); return True
    if cl == "draw": do_draw_phase(g); return True
    if cl == "resource": do_resource_phase(g); return True
    if cl == "keep": return True

    if cl.startswith("deploy ") or cl.startswith("play "):
        cid = cmd.split(" ", 1)[1].strip()
        if "/" in cid:
            pre, suf = cid.split("/", 1); cid = f"{pre}/{suf.upper()}"
        as_pilot = cl.startswith("deploy ")
        return play_card(g, player_idx, cid, as_pilot=as_pilot)

    if cl.startswith("attack "):
        slot = int(cmd.split(" ")[1]); resolve_combat(g, slot); return True

    if cl.startswith("block "):
        slot = int(cmd.split(" ")[1])
        return execute_block(g, player_idx, slot)

    if cl == "end turn":
        g.phase = "end"; g.step = "action"
        g.priority = 1 - player_idx
        log(g, f"P{player_idx+1} ends turn"); return True

    if cl == "concede":
        g.game_over = True; g.winner = 1 - player_idx
        log(g, f"P{player_idx+1} concedes! [CR-8.4]"); return True

    log(g, f"Unknown command: {cmd}"); return False

# ── Single Game Runner ─────────────────────────────────────────────
def run_game(seed, verbose=True, max_turns=50, max_actions=200):
    """Run one game with given seed. Returns (winner, turn_count, log_lines)."""
    random.seed(seed)
    g = init_game(seed=seed)
    setup_shields(g)

    g.turn = 1
    advance_turn(g)

    turn_count = 0; action_count = 0
    while not g.game_over and turn_count < max_turns and action_count < max_actions:
        action_count += 1
        if g.phase == "main":
            cmd = ai_decision(g, g.active_player)
            if verbose: log(g, f"\n  >> P{g.active_player+1} action: {cmd}")
            parse_command(g, g.active_player, cmd)
        elif g.phase == "end":
            if g.step == "action":
                na = 1 - g.active_player
                cmd = ai_decision(g, na)
                if cmd != "pass":
                    if verbose: log(g, f"  >> P{na+1} action: {cmd}")
                    parse_command(g, na, cmd); continue
                cmd = ai_decision(g, g.active_player)
                if cmd != "pass":
                    if verbose: log(g, f"  >> P{g.active_player+1} action: {cmd}")
                    parse_command(g, g.active_player, cmd); continue
                g.step = "cleanup"
                ap = g.active()
                if len(ap.hand) >= 11:
                    dc = len(ap.hand) - 10
                    for _ in range(dc): ap.trash.append(ap.hand.pop())
                    if verbose: log(g, f"P{g.active_player+1} discards {dc} (hand {len(ap.hand)+dc}→10) [CR-8.1]")
                trigger_events(g, "end_of_turn", g.active_player)
                g.active_player = 1 - g.active_player; g.turn += 1; turn_count += 1
                g.priority = g.active_player  # new active player gets priority
                if verbose: log(g, f"\n=== Turn {g.turn} | P{g.active_player+1}'s turn ===")
                advance_turn(g)
            else: break
        elif g.phase == "battle":
            if g.step == "attack":
                # Non-active player decides whether to block
                na = 1 - g.active_player
                cmd = ai_decision(g, na)
                if cmd != "pass":
                    if verbose: log(g, f"  >> P{na+1} action: {cmd}")
                    parse_command(g, na, cmd)
                    continue
                # No block — resolve damage immediately
                resolve_damage(g)
            elif g.step == "action":
                # CR-5.12: action step priority follows CR-2.10
                # Non-active player gets priority first
                na = 1 - g.active_player
                cmd = ai_decision(g, na)
                if cmd != "pass":
                    if verbose: log(g, f"  >> P{na+1} action: {cmd}")
                    parse_command(g, na, cmd)
                    continue
                # Non-active passed → active player decides
                cmd = ai_decision(g, g.active_player)
                if cmd != "pass":
                    if verbose: log(g, f"  >> P{g.active_player+1} action: {cmd}")
                    parse_command(g, g.active_player, cmd)
                    continue
                # Both passed → resolve damage
                resolve_damage(g)
            elif g.step == "battle_end":
                g.phase = "main"
                g.step = None
                g.current_attacker = None
                g.priority = g.active_player
                log(g, "  Battle ends, back to Main Phase [CR-5.3]")
        else: break

    return g.winner, g.turn, len(g.battle_log), g.first_player, g

# ── Batch Runner ───────────────────────────────────────────────────
def run_batch(count=50):
    """Run N games and collect statistics."""
    import io, contextlib
    results = []
    for i in range(count):
        seed = 100 + i
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                winner, turns, log_lines, first, g = run_game(seed, verbose=False)
            results.append({
                "seed": seed, "winner": winner, "turns": turns,
                "first_player": first, "log_lines": log_lines,
                "p1_units": sum(1 for s in g.p[0].battle_area if s.unit_id),
                "p2_units": sum(1 for s in g.p[1].battle_area if s.unit_id),
                "p1_shields": len(g.p[0].shields),
                "p2_shields": len(g.p[1].shields),
                "p1_deck": len(g.p[0].deck), "p2_deck": len(g.p[1].deck),
                "p1_resources": g.p[0].active + g.p[0].rested,
                "p2_resources": g.p[1].active + g.p[1].rested,
            })
            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{count} games done...")
        except Exception as e:
            print(f"  Seed {seed} ERROR: {e}")

    # Analysis
    total = len(results)
    p1_wins = sum(1 for r in results if r["winner"] == 0)
    p2_wins = sum(1 for r in results if r["winner"] == 1)
    draws = sum(1 for r in results if r["winner"] is None)
    avg_turns = sum(r["turns"] for r in results) / total if total else 0
    first_wins = sum(1 for r in results if r["winner"] == r["first_player"])
    second_wins = total - first_wins - draws

    print(f"\n{'='*60}")
    print(f"BATCH RESULTS: {total} games")
    print(f"{'='*60}")
    print(f"  P1 wins: {p1_wins} ({p1_wins/total*100:.1f}%)")
    print(f"  P2 wins: {p2_wins} ({p2_wins/total*100:.1f}%)")
    print(f"  Draws:   {draws} ({draws/total*100:.1f}%)")
    print(f"  First player wins: {first_wins} ({first_wins/total*100:.1f}%)")
    print(f"  Second player wins: {second_wins} ({second_wins/total*100:.1f}%)")
    print(f"  Avg turns: {avg_turns:.1f}")
    print(f"  Min turns: {min(r['turns'] for r in results)}")
    print(f"  Max turns: {max(r['turns'] for r in results)}")
    print(f"  Avg P1 final units: {sum(r['p1_units'] for r in results)/total:.1f}")
    print(f"  Avg P2 final units: {sum(r['p2_units'] for r in results)/total:.1f}")
    print(f"  Avg P1 shields left: {sum(r['p1_shields'] for r in results)/total:.1f}")
    print(f"  Avg P2 shields left: {sum(r['p2_shields'] for r in results)/total:.1f}")
    print(f"  Avg P1 resources: {sum(r['p1_resources'] for r in results)/total:.1f}")
    print(f"  Avg P2 resources: {sum(r['p2_resources'] for r in results)/total:.1f}")
    # Quick anomaly check
    anomalies = [r for r in results if r["turns"] < 5 or r["turns"] > 30]
    if anomalies:
        print(f"\n  Anomalies ({len(anomalies)}):")
        for a in anomalies:
            print(f"    seed={a['seed']} turns={a['turns']} winner=P{a['winner']+1}")

    return results

# ── Main ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if "--batch" in sys.argv:
        n = 50
        for i, a in enumerate(sys.argv):
            if a.isdigit() and i > 0:
                n = int(a)
                break
        run_batch(n)
    else:
        seed = 42
        for i, a in enumerate(sys.argv):
            if a == "--seed" and i + 1 < len(sys.argv):
                seed = int(sys.argv[i + 1])
        g = run_game(seed, verbose=True)
        print("\n" + "="*60)
        if g[0] is not None: print(f"GAME OVER — Winner: P{g[0]+1}")
        else: print(f"SIM END (no winner)")
        gs = g[4]
        for i in range(2):
            p = gs.p[i]
            u = sum(1 for s in p.battle_area if s.unit_id)
            print(f"  P{i+1}: deck={len(p.deck)} hand={len(p.hand)} active={p.active} rested={p.rested} ex={p.ex} shields={len(p.shields)} base={p.base_id}(HP:{p.base_hp - p.base_damage}/{p.base_hp}) units={u} trash={len(p.trash)}")
        print(f"\nFull log: simulation_log.txt ({g[2]} lines)")
