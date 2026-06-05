# GCG 鋼彈卡牌遊戲 — 系統架構

## Overview

GCG is a Gundam card game driven by **opencode subagents** with **zero game logic in Python**. The Python script is a thin coordinator that routes commands to subagents and captures conversation.

```
User / gcg_simulation.py
  │
  ▼
gcg-orchestrator (subagent, via task tool in TUI)
  │
  ├── skill_* (13 skills, via task tool)
  ├── gcg-judge (subagent)
  ├── gcg_display.py (Python script, via bash)
  │
  └── gcg-ai-player (primary+subagent, for AI auto-play)
```

## Agent Roles

| Agent | File | Mode | Invocation |
|-------|------|------|------------|
| **gcg-orchestrator** | `.opencode/agents/gcg-orchestrator.md` | subagent | `task` tool in TUI only |
| **gcg-ai-player** | `.opencode/agents/gcg-ai-player.md` | primary+subagent | `opencode run --agent` OR `task` tool |
| **gcg-display** | `skills_py/gcg_display.py` | Python script | `python skills_py/gcg_display.py <state> <template>` |
| **gcg-judge** | `.opencode/agents/gcg-judge.md` | primary+subagent | `opencode run --agent` OR `task` tool |

### gcg-orchestrator (subagent)

The master controller. **Cannot be invoked via CLI** (`opencode run --agent`). Must be called via the `task` tool from within a running opencode TUI session.

Flow per command:
1. Read game state from `game-states/<game_id>/gameState.md`
2. Phase lock validation (check phase vs skill's `phase_lock`)
3. Pre-fetch card data via `skill_card_db.md`
4. Route to corresponding skill (via `task` tool)
5. Call `gcg-judge` to validate state_diff
6. If reject → display error template
7. If accept → write state_diff to `game-states/<game_id>/gameState.md`
8. Call `python skills_py/gcg_display.py game-states/<game_id>/gameState.md <template> --output /tmp/gcg_output.txt`
9. Read `/tmp/gcg_output.txt` back, echo verbatim

### gcg-ai-player (primary + subagent)

Decision engine. Returns single-line commands only. Supports 5 strategy branches:
- Suppression (压制) — clear enemy units first when ahead
- Development (发展) — build board when behind
- Aggro (抢血) — all-out face damage when weak
- Counterattack (反打) — fill board for next turn
- Desperation (绝望) — all-in gamble

### gcg-judge (primary + subagent)

Validation engine. Checks state_diff against game rules (CR-IDs). Outputs only `accept` or `reject: <reason> [CR-X.Y]`.

### gcg-display (Python script)

Template filler. Transforms game_state YAML into human-readable strings using templates. Runs via `bash python skills_py/gcg_display.py` — no LLM inference needed.

## File Structure

```
cardAI/
├── gcg_simulation.py            # Thin coordinator (zero game logic)
├── GCG_ARCHITECTURE.md          # This file
├── game_state.md                # Runtime state (YAML in .md)
├── game-states/                 # Per-game state files
│   └── <game_id>/
│       └── gameState.md
├── .gcg_active_game             # Current game_id (plain text)
├── .opencode/
  │   ├── agents/
  │   │   ├── gcg-orchestrator.md
  │   │   ├── gcg-ai-player.md
  │   │   └── gcg-judge.md
│   ├── skills/gcg/
│   │   ├── skill_initialize.md
│   │   ├── skill_redraw.md
│   │   ├── skill_start_phase.md
│   │   ├── skill_draw.md
│   │   ├── skill_resource.md
│   │   ├── skill_pass.md
│   │   ├── skill_play_card.md
│   │   ├── skill_battle.md
│   │   ├── skill_block.md
│   │   ├── skill_damage.md
│   │   ├── skill_activate.md
│   │   ├── skill_termination.md
│   │   └── skill_card_db.md
│   ├── game_state_schema.md
│   ├── gcg-rulebook.md
│   ├── ui_templates.md
│   └── tests/
│       └── gcg-test-suite.md
├── card/
│   ├── gcgdecks.json
│   └── data/
│       ├── st01Card.json  ...  st09Card.json
│       ├── gd01Card.json  ...  gd03Card.json
├── replays/
│   └── gcg_replay_*.md
└── experience/
    ├── early-game-rush.yaml
    ├── defend-low-base.yaml
    └── ... (10 YAML files)
```

## gcg_simulation.py — Design

**Zero game logic. Zero AI logic.** Thin coordinator, all output in 繁體中文.

1. **Reads** game state from `game-states/<game_id>/gameState.md` (via `.gcg_active_game`)
2. **Routes** commands:
   - AI decisions → `opencode run --agent gcg-ai-player --attach <server>`
   - Game commands → `opencode run "<cmd>" --attach <server>` (default agent via headless server)
3. **Captures** conversation history in 繁體中文
4. **Saves** replays in 繁體中文 markdown on `game_over`

### When to use

```
python gcg_simulation.py                       # P1=human, P2=AI
python gcg_simulation.py --p1 ai --p2 ai       # both AI, auto-play
python gcg_simulation.py --p1 human --p2 human # both human
python gcg_simulation.py --replay              # replay from existing state
```

### Constraints

- Requires `opencode` CLI installed
- Starts a headless `opencode serve` subprocess at launch
- Each AI decision call takes 10-30s
- `gcg-orchestrator` is a subagent and NOT callable via CLI — must use the task tool in TUI
- gcg-ai-player IS callable via CLI (`opencode run --agent gcg-ai-player --attach`)

## Phase Machine (game flow)

```
pre-game (mulligan) → start → draw → resource → main
                                                       ↘
main → pass → end(action) → (both pass) → cleanup → start (next turn)
main → attack → battle(attack) → block/pass → battle(action) → (both pass) → damage → main
```

Win conditions: direct hit (CR-4.9), deck-out (CR-8.2), concede (CR-8.4).

## Development Guidelines

1. **NEVER** add game logic to `gcg_simulation.py`
2. **NEVER** modify agent files (`.opencode/agents/*.md`) without asking
3. All game rules, card data, and AI strategy live in subagent definitions and skills
4. Replay format is fixed — see existing files in `replays/`
5. All output uses 繁體中文
