# GCG AI 經驗檔案

此目錄中的 `.yaml` 是策略知識素材，不是 runtime 策略引擎，也不是 Python fallback。

目前主路徑是 `GCG_AI_PROVIDER=agent-server`：

```text
skills_py/ai_player.py
  -> skills_py/ai_adapters.py
  -> skills_py/gcg_agent_server.py
  -> codex app-server room
```

若未來要使用這些經驗檔，必須先由 runtime 或 agent-server 轉成 public-safe prompt context，再交給對應的 `gcg-ai-player:P1|P2` room。不要在 Python 中直接依 YAML 自動選牌、評分或改變 COMMAND；runtime 仍只負責顯示、合法性驗證與 state mutation。

## 格式

```yaml
id: unique-name
priority: 1-10
condition:
  turn_max: 5
  my_units_max: 3
description: 人類可讀的說明
effect:
  score_bonus:
    - card_type: unit
      bonus: 10
    - card_type: pilot
      bonus: 5
  attack_target: kill
  block_priority_shift: -2
```

### 條件欄位（皆可選，AND 邏輯）

| 欄位 | 型別 | 說明 |
|------|------|------|
| turn_min / turn_max | int | 回合數範圍 |
| my_units_min / my_units_max | int | 己方戰區單位數量 |
| enemy_units_min / enemy_units_max | int | 敵方單位數量 |
| my_hand_min / my_hand_max | int | 手牌張數 |
| my_empty_slots_min / my_empty_slots_max | int | 戰區空格數 |
| my_base_hp_min / my_base_hp_max | int | 己方 Base 剩餘 HP |
| enemy_shields_min / enemy_shields_max | int | 敵方盾牌剩餘張數 |
| my_resources_min / my_resources_max | int | 己方總資源數（active+rested） |
| enemy_rested_units_min / enemy_rested_units_max | int | 敵方橫置單位數 |
| enemy_damaged_units_min / enemy_damaged_units_max | int | 敵方受傷單位數 |
| has_link_units | bool | 玩家是否有共鳴單位 |
| is_first_turn | bool | 是否為遊戲第一回合 |
| has_unpaired_units | bool | 玩家是否有無駕駛員的單位 |
| enemy_has_blocker | bool | 敵方是否有阻擋者單位 |

### 效果欄位

| 欄位 | 說明 |
|------|------|
| score_bonus | 評估 `card_type`（unit/pilot/command/base）時加權 |
| attack_target | `"kill"` 優先擊殺，`"damage"` 優先削血，`"base"` 優先搶攻基地 |
| block_priority_shift | 選擇阻擋者時偏移欄位優先度（越負越偏好高索引） |
| desperate_play | `true` — 即使分數低也允許出牌 |

### 優先級解析

當多個經驗檔案同時符合條件時，**所有效果相加**。
若 `attack_target` 衝突，以 `priority` 最高的檔案為準。

### 使用限制

- 只能提供 public-safe strategy hints。
- 不得把 hidden hand/deck/shield card id 寫入 prompt、replay 或 memory。
- 不得繞過 `skills_py/ai_player.py` / `skills_py/ai_adapters.py`。
- 不得在 Python 端新增策略 fallback 讓測試悄悄通過。
