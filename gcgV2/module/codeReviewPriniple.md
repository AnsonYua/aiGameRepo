code review principle

- no duplicate function name
- don't call function through too many layers
- use real class names; do not encode temporary status in the class name such as `Placeholder...`
- if a loop is not fully wired, keep a normal class name and use an explicit flag such as `loop_implemented = False`
- keep bootstrap ownership inside the runner; `__main__` should not manually build internal runner state such as `viewer_bundle`
- `run()` should detect current game state first, then decide whether the next step belongs to player decision or runtime auto-processing
- do not hardcode initial viewer player to `P1`; use the current decision owner from game state
- for pending choice flow, follow `gameState.yaml` / state enum names directly, such as `pending_choice.type = choose_turn_order`
- do not invent extra intermediate enums when existing state fields already express the decision kind
- when both players use the same LLM API path, differentiate by injected viewer state, player-specific experience, and prompt context instead of branching into separate ad hoc flow names
