# Implement: --battle-ai-auto-pass-no-move

## Target

`/mobile/battleV2` human-vs-AI only.  
When enabled, if P2 (AI) has only `pass` as legal command, skip Hermes and auto-pass.

## Files to change

---

### 1. `reviewboard/server.py`

#### 1a. Line 263 — add argparse flag

After:

```python
parser.add_argument("--replay", type=Path, default=DEFAULT_REPLAY)
```

Add:

```python
parser.add_argument("--battle-ai-auto-pass-no-move", action="store_true",
                    help="P2 AI 無合法操作時跳過 Hermes 自動讓過")
```

`GCG_BATTLE_AI_AUTO_PASS_NO_MOVE=1` may also enable the same behavior for the
V2 session.

#### 1b. Line 23 — pass flag to session constructor

Change:

```python
battle_session = HumanVsAiBattleSession()
```

To:

```python
battle_session = HumanVsAiBattleSession(
    auto_pass_ai_no_move=args.battle_ai_auto_pass_no_move,
)
```

But `args` is only available inside `main()`. This means `battle_session` must become a local variable initialized inside `main()`, then assigned to `ReviewBoardHandler.battle_session`.

Inside `main()`, after `args = parser.parse_args()` (line 264), create two
sessions:

```python
ReviewBoardHandler.battle_session = HumanVsAiBattleSession()
ReviewBoardHandler.battle_v2_session = HumanVsAiBattleSession(
    auto_pass_ai_no_move=battle_v2_auto_pass,
)
```

Then route `/api/battleV2/*` to `battle_v2_session`. Keep `/api/battle/*`
pointing at the normal session so `/mobile/battle` is unchanged.

Remove the class-level `battle_session = HumanVsAiBattleSession()` on line 23.  
(Or keep line 23 as `battle_session = None` — the handler's `do_POST` uses `self.battle_session` which resolves to the class attribute if not set on the instance.)

---

### 2. `reviewboard/humanVsAI/battle_session.py`

#### 2a. Line 34-39 — add constructor param

Change:

```python
def __init__(
    self,
    players_mode=None,
    interpreter_mode=None,
    ai_timeout_seconds=None,
    max_ai_invalid_attempts=2,
):
```

To:

```python
def __init__(
    self,
    players_mode=None,
    interpreter_mode=None,
    ai_timeout_seconds=None,
    max_ai_invalid_attempts=2,
    auto_pass_ai_no_move=False,
):
```

#### 2b. Line 44 — store the flag

After:

```python
self.max_ai_invalid_attempts = max(1, int(max_ai_invalid_attempts))
```

Add:

```python
self.auto_pass_ai_no_move = bool(auto_pass_ai_no_move)
```

#### 2c. Lines 343-366 — add auto-pass loop in `_build_ai_task_locked`

Replace the entire method body after the guard checks with a `while True` loop.  
The auto-pass check goes after `_current_decision_locked()` but before `viewer_builder.build_for_player()`.

Full replacement for `_build_ai_task_locked`:

```python
def _build_ai_task_locked(self, generation):
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

        # --- auto-pass: skip Hermes when only pass is legal ---
        if (
            self.auto_pass_ai_no_move
            and self.players_mode == "hermes"
            and pending_choice is None
            and legal_commands == ["pass"]
        ):
            parsed = CommandParser().parse("pass", AI_PLAYER)
            self._runner.runtime.resolve_command(parsed)
            self._last_message = "P2 沒有可用操作，自動讓過。"
            self._runner.gameplay_logger.log_system_event(
                game_id=self._runner.game_id,
                event_type="auto_progress",
                payload={"message": f"{AI_PLAYER} 自動讓過（沒有可用操作）。"},
            )
            continue  # loop: auto-pass may open another action window

        # --- normal path: build Hermes prompt ---
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
```

---

## Design rules (do NOT violate)

| Rule | Reason |
|------|--------|
| Only auto-pass when `pending_choice is None` | Must not auto-pass mulligan / turn-order / burst choices |
| Only when `legal_commands == ["pass"]` | Never auto-pass when AI has any non-pass option |
| Only when `players_mode == "hermes"` | Feature skips Hermes latency; non-Hermes test/scripted players remain unchanged |
| Only for `AI_PLAYER` (`P2`) | Already guarded by `actor != AI_PLAYER` check |
| Must loop after auto-pass | One pass may produce next action window (end step → battle action step) |
| Must guard loop progress | Prevent a broken runtime state from blocking UI polling |
| Do NOT change `ActionEnumerator` / `Runtime` / `CommandParser` / `HermesPlayerClient` / `PromptBuilder` | Not needed |
| Only change `mobile/battleV2/` enough to call `/api/battleV2/*` | Required to scope the feature to V2 |

## Files NOT to change

```
gcg/engine/action_enumerator.py
gcg/engine/runtime.py
gcg/engine/command_parser.py
gcg/engine/state_store.py
gcg/ai/hermes_player_client.py
gcg/ai/prompt_builder.py
gcg/ai/llm_client.py
gcg/ai/player_client.py
gcg/sim/bootstrap.py
gcg/sim/runner.py
run_simulator.py
```

## How to test

```bash
# Start server with auto-pass enabled
python3 reviewboard/server.py --battle-ai-auto-pass-no-move --port 5178

# Open /mobile/battleV2 in browser, start game
# When P2 has no meaningful moves (e.g. no cards in hand, no attackers),
# the UI should show "P2 沒有可用操作，自動讓過。" without Hermes latency
```

## Note on `gameplay_logger.log_system_event`

If `GameplayLogger` does not have a `log_system_event` method, use this instead:

```python
self._runner.gameplay_logger.yaml_writer.append_event(
    game_id=self._runner.game_id,
    event={
        "seq": None,  # writer auto-increments
        "turn": self._runner.state.get_turn(),
        "phase": self._runner.state.get_phase(),
        "step": self._runner.state.get_step(),
        "actor": AI_PLAYER,
        "event_type": "auto_progress",
        "message": f"{AI_PLAYER} 自動讓過（沒有可用的操作）",
    },
)
```

Preferred call:

```python
self._runner.gameplay_logger.log_system_event(
    self._runner.game_id,
    "auto_progress",
    {"message": f"{AI_PLAYER} 自動讓過（沒有可用操作）。"},
)
```
