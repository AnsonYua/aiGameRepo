# GCG Level Display Test — 驗證 Level + Cost 雙重檢查

## 測試目標
確認 `gcg-display.md` 生成「可行指令」時，同時檢查 **Level (CR-3.2)** 和 **Cost (CR-3.3)**，不只看 Cost。

## 測試情境：P1 Turn 1 Main — active=1

### Game State
```
turn: 1
active_player: P1
phase: main
p1.resources: {active: 1, rested: 0, ex: 0}  → Level = 1
p1.hand_cards:
  - st01/ST01-007  # Gundam Aerial (Bit on Form), Lv4, Cost2
  - st01/ST01-005  # GM, Lv2, Cost1
  - st01/ST01-014  # Unforeseen Incident, Lv3, Cost1
  - st01/ST01-005  # GM, Lv2, Cost1
  - st01/ST01-009  # Zowort, Lv2, Cost2
  - st01/ST01-012  # Thoroughly Damaged, Lv2, Cost1
```

### Level vs Cost 對照表
| card_id | name | Lv | Cost | Level 通過? | Cost 通過? | 預期 ✅/❌ |
|---|---|---|---|---|---|---|
| ST01-007 | Gundam Aerial (Bit on Form) | 4 | 2 | ❌ (1<4) | ❌ (1<2) | ❌ Level+Cost不足 |
| ST01-005 | GM | 2 | 1 | ❌ (1<2) | ✅ (1≥1) | ❌ Level不足 |
| ST01-014 | Unforeseen Incident | 3 | 1 | ❌ (1<3) | ✅ (1≥1) | ❌ Level不足 |
| ST01-005 | GM | 2 | 1 | ❌ (1<2) | ✅ (1≥1) | ❌ Level不足 |
| ST01-009 | Zowort | 2 | 2 | ❌ (1<2) | ❌ (1<2) | ❌ Level+Cost不足 |
| ST01-012 (play) | Thoroughly Damaged (Command) | 2 | 1 | ❌ (1<2) | ✅ (1≥1) | ❌ Level不足 |
| ST01-012 (deploy) | Thoroughly Damaged (Pilot) | 2 | 1 | ❌ (1<2) | ✅ (1≥1) | ❌ Level不足 |

### Expected Output (excerpt)
```
Available Actions (computed per play legality rules ✅/❌):
  - deploy st01/ST01-007 — Gundam Aerial (Bit on Form) (Lv4/Cost:2) ❌ insufficient level
  - deploy st01/ST01-005 — GM (Lv2/Cost:1) ❌ insufficient level
  - play st01/ST01-014 — Unforeseen Incident (Lv3/Cost:1) ❌ insufficient level
  - deploy st01/ST01-005 — GM (Lv2/Cost:1) ❌ insufficient level
  - deploy st01/ST01-009 — Zowort (Lv2/Cost:2) ❌ insufficient level
  - play st01/ST01-012 — Thoroughly Damaged (Lv2/Cost:1) ❌ insufficient level
  - deploy st01/ST01-012 — Thoroughly Damaged (Lv2/Cost:1) ❌ insufficient level
  - pass — proceed to End Phase
```

All 6 hand cards must show ❌ (Level insufficient). ST01-012 is a [Pilot] dual card; must show both play and deploy lines.
Any card showing ✅ means test failure.

---

## 測試情境 2：P1 Turn 2 Main — active=2（假設下回合）

### Game State
```
active_player: P1
p1.resources: {active: 2, rested: 0, ex: 0}  → Level = 2
p1.hand_cards:
  - st01/ST01-005  # GM, Lv2, Cost1
  - st01/ST01-005  # GM, Lv2, Cost1
  - st01/ST01-009  # Zowort, Lv2, Cost2
  - st01/ST01-012  # Thoroughly Damaged, Lv2, Cost1
```

| card_id | Lv | Cost | Level 通過? | Cost 通過? | 預期 |
|---|---|---|---|---|---|
| ST01-005 | 2 | 1 | ✅ (2≥2) | ✅ (2≥1) | ✅ |
| ST01-005 | 2 | 1 | ✅ (2≥2) | ✅ (2≥1) | ✅ |
| ST01-009 | 2 | 2 | ✅ (2≥2) | ✅ (2≥2) | ✅ |
| ST01-012 (play) | 2 | 1 | ✅ (2≥2) | ✅ (2≥1) | ✅ |
| ST01-012 (deploy) | 2 | 1 | ✅ (2≥2) | ✅ (2≥1) | ✅ |

### Expected Output
```
Available Actions:
  - deploy st01/ST01-005 — GM (Lv2/Cost:1) ✅
  - deploy st01/ST01-005 — GM (Lv2/Cost:1) ✅
  - deploy st01/ST01-009 — Zowort (Lv2/Cost:2) ✅
  - play st01/ST01-012 — Thoroughly Damaged (Lv2/Cost:1) ✅
  - deploy st01/ST01-012 — Thoroughly Damaged (Lv2/Cost:1) ✅
  - pass — proceed to End Phase
```

All 4 hand cards must show ✅ (including ST01-012's 2 usage modes). Any card showing ❌ means test failure.

---

## Manual Execution

1. Ensure runtime `game_state.md` (managed by orchestrator) is set to test scenario 1 state (active=1; if no existing file, manually create game_state.yaml matching scenario 1)
2. Run orchestrator to invoke `gcg-display` (main_phase template)
3. Check the "Available Actions" section in output — confirm all cards show ❌
4. No card should show ✅ (especially GM Cost=1 must not show ✅)

Or directly verify `gcg-display.md` template already includes Level calculation rules (lines 11-21).
