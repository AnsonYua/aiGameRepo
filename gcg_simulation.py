#!/usr/bin/env python3
"""
GCG Simulation - Gundam Card Game
Zero game logic coordinator.
P1=human, P2=AI by default.
"""
import sys
import time
import random
import atexit
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.absolute()
sys.path.insert(0, str(PROJECT_ROOT))

from skills_py.game_state import GameState
from skills_py.game_engine import (
    init_game, save_state, load_state, mulligan_redraw, mulligan_keep,
    setup_shields, start_phase, draw_phase, resource_phase,
    play_card, declare_attack, resolve_block, resolve_unblocked_attack,
    end_battle, pass_turn, cleanup_turn, can_play_card,
    get_phase_display, determine_winner
)
from skills_py.ai_player import ai_decide_command
from skills_py.card_db import build_card_summary, get_card_name, get_card, get_card_type


def print_banner():
    print()
    print("=" * 50)
    print("   GCG - Gundam Card Game Simulation")
    print("=" * 50)
    print()


def print_state(state: GameState, viewer: str = "P1"):
    player = state.get_player(viewer)
    opponent = state.get_opponent(viewer)
    phase_str = get_phase_display(state.phase, state.step)
    print(f"\nTurn {state.turn} | {phase_str} | {state.active_player}'s turn")
    print(f"Resources: active={player.resources_active}, rested={player.resources_rested}, EX={player.resources_ex} | Deck: {len(player.deck_cards)} | Resource Deck: {player.resource_deck_count}")
    print(f"Level: {player.level}")

    print(f"\nYour Hand ({len(player.hand_cards)}):")
    for cid in player.hand_cards:
        summary = build_card_summary(cid)
        print(f"  {summary['display']}")

    print(f"Opponent's Hand: {len(opponent.hand_cards)} cards")

    print(f"\nYour Battle Area ({player.occupied_slots}/6):")
    for s in player.battle_area:
        if s.unit_id:
            name = get_card_name(s.unit_id)
            rest = " [rested]" if s.status == "rested" else ""
            kw = f" | {' '.join(s.keywords)}" if s.keywords else ""
            print(f"  Slot{s.slot}: [{s.unit_id}] {name} | AP:{s.ap}/HP:{s.hp - s.damage} | turns:{s.turns_on_field}{rest}{kw}")
        else:
            print(f"  Slot{s.slot}: empty")

    print(f"\nOpponent's Battle Area ({opponent.occupied_slots}/6):")
    for s in opponent.battle_area:
        if s.unit_id:
            name = get_card_name(s.unit_id)
            rest = " [rested]" if s.status == "rested" else ""
            kw = f" | {' '.join(s.keywords)}" if s.keywords else ""
            print(f"  Slot{s.slot}: [{s.unit_id}] {name} | AP:{s.ap}/HP:{s.hp - s.damage}{rest}{kw}")
        else:
            print(f"  Slot{s.slot}: empty")

    p_shields = player.shields
    o_shields = opponent.shields
    base_hp = f"{player.base.hp - player.base.damage}/{player.base.hp}"
    print(f"\nShields: You {p_shields} remaining | Opponent {o_shields} remaining | Base: {player.base.card_id} | HP: {base_hp}")

    if state.battle_log:
        print(f"\nBattle Log:")
        for log in state.battle_log[-3:]:
            print(f"  {log}")

    if state.game_over:
        print()
        print("=" * 40)
        print(f"   GAME OVER - {state.winner} wins!")
        print("=" * 40)
        return

    print()
    if state.phase == "pre-game":
        print("Available: redraw | keep")
    elif state.phase == "main":
        print("Available: play <card_id> [slot] | attack <slot> | pass | concede")
    elif state.phase == "battle":
        if state.step == "attack":
            print("Available: block <slot> | pass")
        elif state.step == "action":
            print("Available: pass")
    elif state.phase in ("draw", "resource", "start"):
        print("Auto-progressing...")
    elif state.phase == "end":
        print("Available: activate <slot> | pass")


def process_mulligan(state: GameState, p1_mode: str = "human"):
    print_state(state, "P1")

    if p1_mode == "human":
        cmd = input("\nP1 mulligan (redraw/keep): ").strip().lower()
    else:
        cmd = ai_decide_command(state, "P1")

    if cmd == "redraw":
        mulligan_redraw(state, "P1")
        print_state(state, "P1")
        if p1_mode == "human":
            cmd = input("\nP1 final (keep): ").strip().lower()
        else:
            cmd = "keep"
    mulligan_keep(state, "P1")

    cmd = ai_decide_command(state, "P2")
    if cmd == "redraw":
        mulligan_redraw(state, "P2")
    mulligan_keep(state, "P2")

    setup_shields(state)
    start_phase(state)
    draw_phase(state)
    resource_phase(state)
    state.phase = "main"
    state.priority = state.active_player
    save_state(state)


def process_ai_turn(state: GameState, player_id: str):
    while not state.game_over:
        if state.phase == "main":
            cmd = ai_decide_command(state, player_id)
        elif state.phase == "battle":
            cmd = ai_decide_command(state, player_id)
        elif state.phase == "end":
            cmd = ai_decide_command(state, player_id)
        else:
            cmd = "pass"

        if cmd == "pass":
            if state.phase == "main":
                pass_turn(state, player_id)
                save_state(state)
                return
            elif state.phase == "end" and state.step == "action":
                if player_id == state.priority:
                    if state.priority == state.active_player:
                        cleanup_turn(state)
                    else:
                        state.priority = state.active_player
                else:
                    state.priority = state.active_player
                save_state(state)
                return
            elif state.phase == "battle" and state.step == "action":
                end_battle(state)
                save_state(state)
                return
            continue

        parts = cmd.split()
        if parts[0] == "play" and len(parts) >= 2:
            card_id = parts[1]
            slot = int(parts[2]) if len(parts) >= 3 else None
            ok, reason = play_card(state, player_id, card_id, slot)
            if ok:
                print(f"\n[AI {player_id}] played {card_id}")
            else:
                print(f"\n[AI {player_id}] failed to play {card_id}: {reason}")
                pass_turn(state, player_id)
                save_state(state)
                return

        elif parts[0] == "attack" and len(parts) >= 2:
            slot = int(parts[1])
            ok, reason = declare_attack(state, player_id, slot)
            if ok:
                print(f"\n[AI {player_id}] attacks with slot {slot}")
                resolve_unblocked_attack(state)
                end_battle(state)
            else:
                print(f"\n[AI {player_id}] failed to attack: {reason}")

        save_state(state)

        winner = determine_winner(state)
        if winner:
            return


def process_command(state: GameState, cmd: str, player_id: str) -> bool:
    parts = cmd.strip().split()
    if not parts:
        return True

    action = parts[0].lower()

    if action == "pass":
        if state.phase == "main":
            if player_id == state.active_player:
                pass_turn(state, player_id)
                save_state(state)
                return True
            else:
                print("Not your turn to pass")
        elif state.phase == "end" and state.step == "action":
            if player_id == state.active_player:
                cleanup_turn(state)
                save_state(state)
                return True
            else:
                state.priority = state.active_player
                save_state(state)
                return True

    elif action == "play" and len(parts) >= 2:
        card_id = parts[1]
        slot = None
        if len(parts) >= 3:
            try:
                slot = int(parts[2])
            except ValueError:
                print(f"Invalid slot: {parts[2]}")
                return True
        ok, reason = play_card(state, player_id, card_id, slot)
        if ok:
            print(f"Played {card_id} successfully")
            save_state(state)
        else:
            print(f"Error: {reason}")
        return True

    elif action == "attack" and len(parts) >= 2:
        try:
            slot = int(parts[1])
            ok, reason = declare_attack(state, player_id, slot)
            if ok:
                if state.step == "attack":
                    resolve_unblocked_attack(state)
                    end_battle(state)
                save_state(state)
            else:
                print(f"Error: {reason}")
        except ValueError:
            print(f"Invalid slot: {parts[1]}")
        return True

    elif action == "concede":
        state.game_over = True
        state.winner = state.get_opponent(player_id).player_id
        print(f"\n{player_id} concedes. {state.winner} wins!")
        save_state(state)
        return False

    elif action == "state":
        print_state(state, player_id)
        return True

    elif action == "quit" or action == "exit":
        return False

    else:
        print(f"Unknown command: {action}")
        print("Available: play <card_id> [slot] | attack <slot> | pass | concede | state | quit")
        return True

    return True


def run_simulation(p1_mode: str = "human", p2_mode: str = "ai"):
    print_banner()

    game_id = f"game_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    state = init_game(game_id)
    print(f"Game ID: {game_id}")
    print(f"First player: {state.first_player}")
    print(f"P1 mode: {p1_mode} | P2 mode: {p2_mode}")

    save_state(state)

    process_mulligan(state, p1_mode)

    current_viewer = "P1"

    while not state.game_over:
        print_state(state, current_viewer)

        if state.game_over:
            break

        if state.phase in ("draw", "resource", "start"):
            continue

        active = state.active_player

        if active == "P2" and p2_mode == "ai":
            print(f"\n[AI P2 is thinking...]")
            time.sleep(1)
            process_ai_turn(state, "P2")
            if state.game_over:
                break
            continue

        if active == "P1" and p1_mode == "ai":
            print(f"\n[AI P1 is thinking...]")
            time.sleep(1)
            process_ai_turn(state, "P1")
            if state.game_over:
                break
            continue

        if active == current_viewer:
            cmd = input(f"\n{active}> ").strip()
            if not process_command(state, cmd, active):
                break
        else:
            print(f"\nWaiting for {active}...")
            time.sleep(1)

    print(f"\nGame {state.game_id} finished.")
    save_replay(state)
    print(f"Replay saved.")


def save_replay(state: GameState):
    replay_dir = PROJECT_ROOT / "replays"
    replay_dir.mkdir(exist_ok=True)
    replay_file = replay_dir / f"gcg_replay_{state.game_id}.md"
    with open(replay_file, "w") as f:
        f.write(f"# GCG Replay — {state.game_id}\n\n")
        f.write(f"- **Winner**: {state.winner}\n")
        f.write(f"- **First Player**: {state.first_player}\n")
        f.write(f"- **Final Turn**: {state.turn}\n\n")
        f.write("## Battle Log\n\n")
        for log in state.battle_log:
            f.write(f"- {log}\n")
        f.write(f"\n## Final State\n\n")
        import yaml
        f.write("```yaml\n")
        yaml.dump(state.to_dict("P1"), f, allow_unicode=True, default_flow_style=False)
        f.write("```\n")


def main():
    p1_mode = "human"
    p2_mode = "ai"

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--p1" and i + 1 < len(args):
            p1_mode = args[i + 1]
            i += 2
        elif args[i] == "--p2" and i + 1 < len(args):
            p2_mode = args[i + 1]
            i += 2
        elif args[i] == "--replay":
            print("Replay mode not yet implemented")
            return
        else:
            i += 1

    run_simulation(p1_mode, p2_mode)


if __name__ == "__main__":
    main()
