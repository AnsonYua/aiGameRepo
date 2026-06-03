---
name: skill_initialize
triggers: [start game]
phase_lock: pre-game
---

# skill_initialize

根據 `first_player`（P1|P2）建立初始遊戲狀態（CR-1）。

## 流程

1. 設定 `turn: 1`, `active_player: first_player`, `phase: start`
2. 後手 EX Resource +1（CR-1.2）
3. 初始化雙方：Base（CR-1.4）、shields=6（CR-1.3）、hand_cards=5（CR-1.5）、deck_count=39（CR-1.7）、resource_deck_count=10（CR-1.6）、battle_area=6 null 格、trash=[], removal=[]
4. 回傳完整 `game_state` 作為 `state_diff` 的 set 操作

## 輸出

```yaml
state_diff:
  turn: 1
  first_player: <P1|P2>
  active_player: <first_player>
  phase: start
  step: null
  p1:
    base: { card_id: "EX-BASE", ap: 0, hp: 3, damage: 0, alive: true, status: null }
    shields: 6
    hand_cards: [<5 card_ids, e.g. GCG-XXX>]
    deck_count: 39
    resource_deck_count: 10
    resources: { active: 0, rested: 0, ex: <0|1> }
    battle_area: [{slot:0,unit_id:null,pilot_id:null,ap:0,hp:0,damage:0,status:null,keywords:[],link:false}, ...]
    trash: []
    removal: []
  p2:
    # 同 p1 結構
  active_effects: []
  battle_log: ["<player> started game as first player [CR-1.1]"]
  game_over: false
  winner: null
```
