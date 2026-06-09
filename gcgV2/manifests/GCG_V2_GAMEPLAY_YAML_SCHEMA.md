# GCG V2 Gameplay YAML Schema Example

這份文件示範 `gamePlay.yaml` 應該如何記錄一局 AI vs AI 對戰。重點不是只寫一行文字，而是每個 event 都要同時保留：

- 人可以直接看的 `message`
- 機器可以直接處理的 `result` 與 `state_changes`
- 當下 public-safe 局面的 `features`

`gamePlay.yaml` 是 canonical step log。它不是單純 replay 文案，也不是 raw hidden state dump。

## 1. Top-Level Shape

```yaml
schema_version: "2.0"
game_id: "game_20260608_021028_537485"
summary:
  status: "in_progress"
  winner: null
  turn: 3
  phase: "main"
  total_events: 17
events:
  - seq: 1
    ts: "2026-06-08T02:10:33+08:00"
    turn: 1
    phase: "pre-game"
    step: null
    actor: null
    viewer: "P1"
    event_type: "agent_server_init"
    public: true
    message: "Agent server 已初始化 5 個 Codex 聊天室"
    result:
      ok: true
      reason: ""
    features: {}
```

## 2. Event Rules

每條 event 都應該有這幾類資料：

`seq`
- 單調遞增
- 用來 replay、diff、review

`ts`
- ISO 8601 時間

`turn / phase / step`
- 記錄事件發生時機

`actor`
- 哪個玩家或系統做了這件事

`viewer`
- 這筆事件主要面向哪個 viewer
- 如果是 shared public log，可以先固定寫 `P1`

`event_type`
- 讓程式可以分類事件

`message`
- 人類直接閱讀的摘要

`result`
- 這次事件成功與否
- 如果有真正 state 變動，應該記在 `state_changes`

`features`
- 當下 public-safe snapshot
- 不應包含 hidden hand card ids、deck order、hidden shield ids
- `pending_choice` 必須永遠是 list；沒有待答選擇時寫 `[]`

## 3. Suggested Event Types

第一版可以先支援這些：

```text
agent_server_init
game_started
mulligan_resolved
turn_started
phase_changed
priority_passed
command_received
command_resolved
pending_choice_created
choice_resolved
trigger_resolved
rule_event
attack_resolved
game_over
```

## 4. Example: `game_started`

```yaml
- seq: 1
  ts: "2026-06-08T02:10:33+08:00"
  turn: 1
  phase: "pre-game"
  step: null
  actor: null
  viewer: "P1"
  event_type: "game_started"
  public: true
  message: "對局開始，P1 為先手。"
  result:
    ok: true
    reason: ""
    state_changes:
      - type: "create_game"
        first_player: "P1"
  features:
    turn: 1
    phase: "pre-game"
    step: null
    active_player: "P1"
    priority: "P1"
    current_attacker: null
    pending_choice: []
    game_over: false
    winner: null
    p1:
      hand_count: 5
      resources:
        active: 0
        rested: 0
        ex: 0
      deck_count: 45
      resource_deck_count: 10
      shields: 0
      base:
        card_id: "EX-BASE"
        ap: 0
        hp: 3
        damage: 0
        alive: true
        status: null
      board:
        units: 0
        empty_slots: 6
        rested_units: 0
        damaged_units: 0
        blockers: 0
        slots:
          - slot: 0
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 1
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 2
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 3
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 4
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 5
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
      trash: []
      removal: []
    p2:
      hand_count: 5
      resources:
        active: 0
        rested: 0
        ex: 1
      deck_count: 45
      resource_deck_count: 10
      shields: 0
      base:
        card_id: "EX-BASE"
        ap: 0
        hp: 3
        damage: 0
        alive: true
        status: null
      board:
        units: 0
        empty_slots: 6
        rested_units: 0
        damaged_units: 0
        blockers: 0
        slots:
          - slot: 0
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 1
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 2
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 3
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 4
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
          - slot: 5
            unit_id: null
            pilot_id: null
            ap: 0
            hp: 0
            damage: 0
            status: null
            keywords: []
            link: false
            turns_on_field: 0
      trash: []
      removal: []
```

## 5. Example: `command_resolved`

這是你最關心的例子。不是只寫 `deal 1 damage`，而是把 command、intent、result、delta、features 都記下來。

```yaml
- seq: 12
  ts: "2026-06-08T02:18:09+08:00"
  turn: 3
  phase: "main"
  step: "action"
  actor: "P1"
  viewer: "P1"
  event_type: "command_resolved"
  public: true
  command:
    raw: "play GD01-008 target p2_slot_1"
    parsed:
      action: "play_card"
      source_ref: "hand_3"
      card_id: "GD01-008"
      target_ref: "p2_slot_1"
  intent:
    kind: "play_and_resolve_effect"
    source_card_id: "GD01-008"
    timing: "deploy"
    effect_text: "Choose 1 rested enemy Unit. Deal 1 damage to it."
    chosen_targets:
      - "p2_slot_1"
    primitive_steps:
      - primitive: "deploy_card"
        controller: "P1"
        source_ref: "hand_3"
        destination: "p1_slot_0"
      - primitive: "deal_damage"
        target: "p2_slot_1"
        amount: 1
  message: "P1 使用 GD01-008，選擇 P2 欄位 1 的 rested Unit，造成 1 點傷害。"
  result:
    ok: true
    reason: ""
    state_changes:
      - type: "move_card"
        card_id: "GD01-008"
        from: "p1_hand"
        to: "p1_battle_area_0"
      - type: "deal_damage"
        target: "p2_slot_1"
        amount: 1
        damage_before: 0
        damage_after: 1
        destroyed: false
  features:
    turn: 3
    phase: "main"
    step: "action"
    active_player: "P1"
    priority: "P1"
    current_attacker: null
    game_over: false
    winner: null
    p1:
      hand_count: 4
      resources:
        active: 1
        rested: 2
        ex: 0
      deck_count: 39
      resource_deck_count: 7
      shields: 5
      base:
        card_id: "EX-BASE"
        ap: 0
        hp: 3
        damage: 0
        alive: true
        status: null
      board:
        units: 1
        empty_slots: 5
        rested_units: 0
        damaged_units: 0
        blockers: 0
        slots:
          - slot: 0
            unit_id: "GD01-008"
            pilot_id: null
            ap: 3
            hp: 3
            damage: 0
            status: "active"
            keywords: []
            link: false
            turns_on_field: 0
    p2:
      hand_count: 5
      resources:
        active: 2
        rested: 1
        ex: 1
      deck_count: 40
      resource_deck_count: 7
      shields: 5
      base:
        card_id: "EX-BASE"
        ap: 0
        hp: 3
        damage: 0
        alive: true
        status: null
      board:
        units: 1
        empty_slots: 5
        rested_units: 1
        damaged_units: 1
        blockers: 0
        slots:
          - slot: 1
            unit_id: "ST01-005"
            pilot_id: null
            ap: 2
            hp: 2
            damage: 1
            status: "rested"
            keywords: []
            link: false
            turns_on_field: 1
```

## 6. Example: `pending_choice_created`

如果 AI 沒有給齊 target 或 optional choice，runtime 應該記一條 pending choice event。

```yaml
- seq: 13
  ts: "2026-06-08T02:18:10+08:00"
  turn: 3
  phase: "main"
  step: "action"
  actor: "P1"
  viewer: "P1"
  event_type: "pending_choice_created"
  public: true
  message: "GD01-008 需要選擇 1 個 rested enemy Unit。"
  result:
    ok: true
    reason: ""
    created_pending_choice:
      choice_id: "choice_7"
      choice_type: "select_target"
      owner: "P1"
      min: 1
      max: 1
      options:
        - "p2_slot_1"
        - "p2_slot_3"
  features:
    pending_choice:
      - choice_id: "choice_7"
        choice_type: "select_target"
        owner: "P1"
        min: 1
        max: 1
        options:
          - "p2_slot_1"
          - "p2_slot_3"
```

## 7. Example: `trigger_resolved`

```yaml
- seq: 14
  ts: "2026-06-08T02:18:11+08:00"
  turn: 3
  phase: "main"
  step: "trigger"
  actor: "system"
  viewer: "P1"
  event_type: "trigger_resolved"
  public: true
  message: "ST01-001 的 Repair 2 效果解決，回復 2 點 HP。"
  trigger:
    source_card_id: "ST01-001"
    trigger_type: "end_of_turn"
    effect_text: "Repair 2"
  result:
    ok: true
    reason: ""
    state_changes:
      - type: "heal_damage"
        target: "p1_slot_0"
        amount: 2
        damage_before: 2
        damage_after: 0
  features: {}
```

## 8. Example: `rule_event`

這一條不是玩家主動 command，而是 runtime 自動裁判。

```yaml
- seq: 15
  ts: "2026-06-08T02:18:12+08:00"
  turn: 3
  phase: "main"
  step: "rule_check"
  actor: "system"
  viewer: "P1"
  event_type: "rule_event"
  public: true
  message: "P2 欄位 1 的 Unit 因傷害達到 HP 被破壞，移到 trash。"
  result:
    ok: true
    reason: ""
    state_changes:
      - type: "destroy_unit"
        target: "p2_slot_1"
        card_id: "ST01-005"
      - type: "move_card"
        card_id: "ST01-005"
        from: "p2_battle_area_1"
        to: "p2_trash"
  features: {}
```

## 9. Example: `game_over`

```yaml
- seq: 27
  ts: "2026-06-08T02:25:44+08:00"
  turn: 7
  phase: "battle"
  step: "damage"
  actor: "system"
  viewer: "P1"
  event_type: "game_over"
  public: true
  message: "P1 的最後一面盾牌與基地已失去，P2 獲勝。"
  result:
    ok: true
    reason: ""
    winner: "P2"
  features:
    turn: 7
    phase: "battle"
    step: "damage"
    active_player: "P2"
    priority: null
    current_attacker: null
    game_over: true
    winner: "P2"
```

## 10. What Not To Record

以下內容不應該直接寫入 public-safe `gamePlay.yaml`：

- 對手 hidden hand card ids
- deck 順序
- 未公開 shield card ids
- raw private prompt
- LLM chain-of-thought

可以記 count，但不要記 hidden identity。

## 11. Practical Rule

實作時可以用一條簡單原則：

- `message` 給人看
- `result.state_changes` 給程式看
- `features` 給 replay / review / lessons 看

如果一條 event 之後你仍然需要再讀別的檔，先知道「這一步做了什麼」，代表這條 event 還不夠完整。
