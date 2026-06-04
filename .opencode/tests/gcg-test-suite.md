# GCG 綜合測試套件 — 依 CR-ID 分類

測試範圍：顯示格式、AI 決策、出牌合法性檢查。

---

## T1: Level + Cost 雙重檢查（CR-3.1 ~ CR-3.3）

測試在 `gcg-test-level-display.md`，此處不再重複。

---

## T2: EX Resource 使用（CR-3.4, CR-3.5）

### T2a: EX 計入 Level 但不可 full pay Cost
**情境**：P2 後手 Turn 1 Main，hand 有 Unforeseen Incident (Lv3/Cost1)，resources.active=1, rested=0, ex=1
- Level = 1+0+1 = 2 → 2 < 3 ❌ Level 不足（即使 active=1 來自 Resource Phase，EX 也計入 Level 仍不足）
- Cost: active=1 ≥ 1 ✅（EX 不需用於付費）
- 預期：`❌ Level不足`
- **修正備註**：原始版本設 active=0 不現實（Turn 1 Main 的 P2 已過 Resource Phase，active 至少為 1）。改用 Lv3 卡 + active=1 驗證相同邏輯。

### T2b: EX 幫忙付 Cost（資源不足時）
**情境**：P2 後手 Turn 2 Main，resources.active=0, rested=1, ex=1，hand 有 GM (Lv2/Cost1)
- Level = 0+1+1 = 2 ≥ 2 ✅
- Cost: active=0 < 1 → 可用 EX 補足（0+1 ≥ 1）✅
- 預期：`✅`（Level 夠 + 用 EX 付費）

### T2c: EX + active 混合付 Cost
**情境**：resources.active=1, rested=0, ex=1，hand 有 Zowort (Lv2/Cost2)
- Level = 1+0+1 = 2 ≥ 2 ✅
- Cost: active=1 < 2 → 加 EX: 1+1 ≥ 2 ✅
- 預期：`✅`（Level 夠 + active+EX 付費）

### T2d: EX 用完後 Level 下降
**情境**：先用 EX 付費打了 Command，剩 resources.active=1, rested=0, ex=0
- Level 降回 1
- 後續手牌 Lv≥2 全部 ❌
- 驗證：Level 為動態計算，即時反映 EX 消耗

---

## T3: Base 部署與替換（CR-7.1 ~ CR-7.6）

### T3a: 從手牌部署 Base
**情境**：Turn 3 Main，resources.active=3, Level=3，手牌有 ST01-015 White Base (Lv3/Cost2)
- Level 3 ≥ 3 ✅, Cost 3 ≥ 2 ✅ → `✅`
- 預期顯示：`deploy st01/ST01-015 — White Base（Lv3/Cost:2）✅`
- AI 決策：應評估替換 EX-BASE(3HP) → White Base(5HP) 是否值得

### T3b: Base 替換後盾牌回手
**情境**：同上，部署後 shields: 6 → 5（最上層盾牌回手），舊 EX-BASE → trash
- 顯示 shields 數應從 6 → 5
- Base HP 應從 3/3 → 5/5

### T3c: Base 破壞時 excess damage 不傳
**情境**：Base 有 2/3 HP，受 3 AP 攻擊 → damage=3 ≥ HP=3 → Base alive=false
- 剩餘 1 damage 不往下傳（不破盾牌）
- 符合 CR-4.4

---

## T4: Command [Pilot] 雙用途卡（CR-10.2）

### T4a: Thoroughly Damaged 可 play 或 deploy
**情境**：ST01-012 Thoroughly Damaged，有兩個使用方式：
- **play**（Command 效果）→ `play st01/ST01-012 — Thoroughly Damaged（Lv2/Cost:1）✅`
- **deploy**（Pilot: Hayato Kobayashi）→ `deploy st01/ST01-012 — Thoroughly Damaged（Lv2/Cost:1）✅`
- 兩種都需 Level 2 + Cost 1
- 顯示應放兩行（play + deploy）

### T4b: Link Pilot → 部署後可 pair
**情境**：部署 ST01-010 Amuro Ray (Lv4/Cost1, Pilot) 到有 Gundam (ST01-001) 的 slot
- Gundam link=[Amuro Ray] → pair 成立
- pair 後該 slot 變成 Link Unit，當回合即可攻擊（CR-6.4）

---

## T5: Attack 合法性（CR-5.4, CR-5.5）

### T5a: 新部署 Unit 不可攻擊
**情境**：Turn 3 部署 GM → 仍在同一 turn 的 Main phase
- GM 剛出場，status=active，但未滿 1 回合
- `attack slot0` ❌（不合 CR-5.4a）
- 預期：可行指令中不顯示 `attack <slot>`

### T5b: Link Unit 當回合可攻擊
**情境**：Turn 3 部署 GM + 部署 Amuro Ray pair → Link Unit
- `attack slot0` ✅（CR-5.4b：Link Unit 可立即攻擊）
- 預期：可行指令中有 `attack <slot>`

### T5c: Rested Unit 不可攻擊
**情境**：GM 已 rested（攻擊過或效果橫置）
- `attack slot0` ❌
- 預期：可行指令中不顯示該 slot

---

## T6: Block 合法性（CR-5.8 ~ CR-5.10）

### T6a: 只有直立 Blocker 可擋
**情境**：P2 battle(attack) step，對方攻擊 slot0
- Zowort(Blocker) 直立 → `block slot0` ✅
- Zowort rested → 不可阻擋 ❌
- 非 Blocker Unit → 不可阻擋 ❌

---

## T7: Token 卡處理（CR-6.7）

### T7a: Token 不可從手牌 deploy
**情境**：Token 卡 (level=0, cost=0, color=Token) 不在手牌中
- 不會出現在 hand_cards（效果直接產生到 battle_area）
- 顯示時應標註 Token 類型

### T7b: Token 破壞進 removal 而非 trash
**情境**：T-001 Gundam Token(AP3/HP3) 被破壞
- 不進 trash → 進 removal
- 顯示 battle_area slot 變為 empty

---

## T8: Once per turn 追蹤（CR-10.4）

### T8a: 已使用的 Once per turn 不可重複
**情境**：Suletta Mercury [Attack][Once per Turn] 效果已使用
- `active_effects` 中記錄 `used_this_turn: true`
- 再次 `activate <effect_id>` → ❌
- Start Phase 時 reset

---

## T9: 戰鬥流程（CR-5.1 ~ CR-5.3, CR-5.12）

### T9a: Attack → Block → Damage → Main
**情境**：完整戰鬥循環
1. Main→ `attack slot0` → phase=battle, step=attack ✅
2. 對方 `block slot0` → step=block ✅
3. 雙方 `pass` (action step) → step=damage → damage resolves
4. phase=main ✅（CR-5.3）

### T9b: 0 AP 不可破壞防禦層（CR-4.8）
**情境**：Unit 的 AP=0（如 Thoroughly Damaged 以 Pilot 部署時 AP=0）
- 攻擊時無法對 Base 或盾牌造成任何傷害
- 只能打敵 Unit（且 0 AP 也無法破壞任何東西）

---

## T10: End Phase 手牌限制（CR-8.1）

### T10a: 手牌 ≥11 → 需棄到 10
**情境**：End phase cleanup step，手牌 = 12
- 需棄 2 張
- 顯示：「Discard 2 cards (hand: 12 → 10)」
- AI 應選擇哪些卡棄掉

---

## T11: Game Over 條件（CR-9.1）

### T11a: 直擊敗北
**情境**：shields=0, Base dead, 戰鬥傷害攻擊
- 防禦層序：盾牌區無卡 → 直擊玩家
- game_over=true, winner=對方
- 顯示敗北訊息

### T11b: 抽牌敗北（CR-8.2）
**情境**：Draw phase，deck_count=0
- 需抽牌但牌庫空 → 即時敗北
- game_over=true

---

## T12: 顯示格式邊界案例

### T12a: 戰區全滿（CR-5.11）
**情境**：battle_area 6 slot 全滿
- 顯示：「Your Battle Area (6/6): ...」
- deploy 時需加註：可 trash 既有 Unit 騰空間

### T12b: Opponent 戰區部分顯示
**情境**：對手戰區 slot0 有 Unit，其餘未知
- 顯示：「- Slot0: Unknown（有 Unit）」
- 「- Slot1: empty」... 已知空位顯示 empty

### T12c: 資源/EX 上限
**情境**：resources.active=10（遊戲上限）+ ex=5
- Level = 15（CR-3.6）
- 顯示應正確標示總和

---

## 測試矩陣

| Test | CR-ID | Phase | 關鍵驗證點 | 預期結果 |
|------|-------|-------|-----------|---------|
| T1 | 3.1-3.3 | main | Level+Cost 同時檢查 | Level 不足全 ❌ |
| T2a | 3.4 | main | EX 計入 Level 但仍不足 | ❌ Level不足 |
| T2b | 3.4-3.5 | main | EX 補 Cost | ✅ 用 EX 付費 |
| T2c | 3.4 | main | EX+active 混合付 Cost | ✅ |
| T2d | 3.4 | main | EX 用完後 Level 下降 | 後續卡 ❌ |
| T3a | 7.1-7.3 | main | Base deployment | ✅ |
| T3b | 7.3 | main | 盾牌回手 | shields-1 |
| T3c | 4.4 | battle | Base 破壞 excess 不傳 | 盾牌不受傷 |
| T4a | 10.2 | main | [Pilot] 雙用途 | play+deploy 兩行 |
| T4b | 6.4 | main | Link pair 當回合可攻擊 | attack ✅ |
| T5a | 5.4a | main | 新部署不可攻擊 | 無 attack |
| T5b | 5.4b | main | Link 可攻擊 | attack ✅ |
| T5c | 5.4 | main | Rested 不可攻擊 | 無 attack |
| T6a | 5.8 | battle | 僅直立 Blocker 可擋 | block ✅/❌ |
| T7a | 6.7 | main | Token 不從手牌出 | 手牌無 Token |
| T7b | 6.7 | any | Token 進 removal | removal++ |
| T8a | 10.4 | main | Once per turn 限制 | 不可重複 |
| T9a | 5.1-5.3 | battle | 戰鬥循環 | phase→main |
| T9b | 4.8 | battle | 0 AP 不能破防 | 0 damage |
| T10a | 8.1 | end(cleanup) | 手牌限制 | 棄到 10 |
| T11a | 9.1a | battle | 直擊敗北 | game_over |
| T11b | 8.2 | draw | 抽空牌庫敗北 | game_over |
| T12a | 5.11 | main | 戰區滿 | 可 trash 騰位 |
| T12c | 3.6 | main | 資源上限 | Level=15 |
