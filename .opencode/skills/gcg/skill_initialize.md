---
name: skill_initialize
triggers: [start game]
phase_lock: pre-game
---

# skill_initialize

## 輸出規則
你的回覆是 state_diff YAML。用 **Write** 工具寫入 `/tmp/gcg_skill_output.txt`，用 **Read** 工具讀回，你的回覆就是 Read 的結果。

根據 `first_player`（P1|P2）建立初始遊戲狀態（CR-1）。

## 流程

1. 設定 `turn: 1`, `active_player: first_player`, `phase: pre-game`（Mulligan 在 pre-game 進行，CR-2.3）
2. 後手 EX Resource +1（CR-1.2）
3. 從 `card/gcgdecks.json` 讀取該玩家的牌庫（見 `skill_card_db.md` §4 `get_deck(playerId)`），隨機洗牌後：前 5 張作為手牌、剩餘 45 張作為牌庫。**Shields 先設為 0，待 Mulligan 完成後再從牌庫頂設置**（CR-1.8 → CR-1.5）
4. 初始化雙方：Base（CR-1.4）、resource_deck_count=10（CR-1.6）、battle_area=6 null 格、trash=[], removal=[]
5. 剩餘 45 張牌庫的 card_id 順序需記錄於 `.deck_tracking.json`（由 orchestrator 在 §1 step 8 寫入）
6. 回傳完整 `game_state` 作為 `state_diff` 的 set 操作
7. 輸出後：Orchestrator 依 §5 Mulligan Flow 處理後續（使用 ui_templates.md §compose_mulligan）

## 輸出

```yaml
state_diff:
  turn: 1
  first_player: <P1|P2>
  active_player: <first_player>
  phase: pre-game
  step: null
  current_attacker: null
  p1:
    base: { card_id: "EX-BASE", ap: 0, hp: 3, damage: 0, alive: true, status: null }
    shields: 0
    hand_cards: [<5 card_ids, e.g. "st01/ST01-001">]
    deck_count: 45
    resource_deck_count: 10
    resources: { active: 0, rested: 0, ex: <0|1> }
    battle_area: [{slot:0,unit_id:null,pilot_id:null,ap:0,hp:0,damage:0,status:null,keywords:[],link:false}, ...]
    trash: []
    removal: []
  p2:
    # 同 p1 結構
  active_effects: []
  battle_log: ["<player> started game as first player [CR-1.1]"]  # 模板見 ui_templates.md §log_initialize
  game_over: false
  winner: null
```
