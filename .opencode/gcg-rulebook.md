# GCG 綜合規則手冊

統一遊戲規則，附 CR-ID 編號。所有 Agent 引用 CR-ID 而不重述規則文字。

---

## CR-1：遊戲設置

- **CR-1.1** — 隨機方式決定 P1/P2，勝者選擇先手（FAQ Q9）
- **CR-1.2** — 後手玩家起始擁有 1 個 EX Resource
- **CR-1.3** — 每位玩家從牌庫頂面朝下放置 6 張牌作為盾牌
- **CR-1.4** — 每位玩家起始持有 EX Base（0 AP / 3 HP, damage=0, alive=true），位於盾牌最上層
- **CR-1.5** — 每位玩家起始手牌 5 張
- **CR-1.6** — 每位玩家有 10 張資源卡在資源牌庫
- **CR-1.7** — 初始化後牌庫 = 50 - 5 手牌 = 45 張；調度完成、設置 6 盾牌後 = 39 張
- **CR-1.8** — 調度（重抽）：雙方各可重抽一次，P1 先決定是否重抽。流程：將整副手牌洗回牌庫 → 洗牌 → 抽 5 張新牌

## CR-2：回合結構

**Phase（階段）**：整場遊戲的大階段，順序為 pre-game → start → draw → resource → main → battle → end。同一時間只會處於一個 phase。

**Step（子步驟）**：細部流程指示器。phase=battle 時有 attack → block → action → damage → battle_end。phase=end 時有 action → cleanup。其餘 phase 時 step=null。

- **CR-2.1** — 第 1 回合由先手玩家開始（active_player = first_player）
- **CR-2.2** — 每回合階段順序：start → draw → resource → main → end。End 階段子步驟：action → cleanup
- **CR-2.3** — Pre-game 階段：僅進行調度
- **CR-2.4** — Start 階段：重置所有橫置卡（強制，不可選擇不重置）
- **CR-2.5** — Draw 階段：從牌庫抽 1 張牌（強制）；P1 第 1 回合仍正常抽牌；抽牌時牌庫為空則立刻敗北
- **CR-2.6** — Resource 階段：從資源牌庫強制部署 1 張資源卡（不可跳過）；資源牌庫為空時仍進入此階段但立即跳過
- **CR-2.7** — Main 階段：出牌、啟動效果、宣告攻擊
- **CR-2.8** — End 階段分兩子步驟：(a) **Action Step** — 優先權開始輪流（規則見 CR-2.10），非 active player 先決定是否 activate 或 play command，雙方連續 pass 才前進到 cleanup (b) **Cleanup Step** — 棄牌：手牌 ≥11 需棄到 10（可選擇棄哪些牌），然後結束回合，active_player 切換為對方，phase 回到 start
- **CR-2.9** — 在 Main 階段 pass 或 end turn → phase 切為 end，step 設為 action，非 active player 先獲得優先權
- **CR-2.10** — Action Step 優先權規則（適用於 battle 與 end 階段的 action step）：(a) 非 active player 先選擇 activate/pass (b) 輪到 active player 選擇 (c) 一方 activate 後重新由非 active player 開始 (d) 雙方連續 pass 才推進到下一個 step/phase

## CR-3：資源系統

- **CR-3.1** — Level = resources.active + resources.rested + resources.ex
- **CR-3.2** — 出牌條件：Level 必須 ≥ 卡的 Lv
- **CR-3.3** — 支付費用：橫置所需數量的資源（active → rested）
- **CR-3.4** — EX Resources 計入 Level。用於支付費用時移除遊戲（非橫置）
- **CR-3.5** — EX Resource 上限 5 個。移除遊戲的 EX 不計入 Level
- **CR-3.6** — 資源區上限：10 張資源卡 + 5 個 EX 代幣 = 15 張

## CR-4：防禦層序

攻擊傷害的目標由規則自動決定，攻擊者不可選擇。
- **CR-4.1** — 防禦層由外而內：**Base**（最外層）→ **盾牌** → **玩家**（敗北觸發）
- **CR-4.2** — Base 位於盾牌堆最上層。盾牌堆有卡時攻擊必定打到防禦層（Base 或盾牌）
- **CR-4.3** — 攻擊目標判定順序：盾牌區有卡 → 有 Base？→ 是：打 Base；否：打第一張盾牌 → 盾牌區無卡：直擊玩家
- **CR-4.4** — Base 破壞時（damage ≥ HP）移除（alive=false），excess damage 不往下傳（全部消失）
- **CR-4.5** — Base 破壞後，後續攻擊自動打盾牌（按 CR-4.3 規則）
- **CR-4.6** — 每個盾牌有 1 HP。被破壞的盾牌揭示後進廢棄區；有 Burst 可在進廢棄前選擇是否觸發
- **CR-4.7** — 盾牌在戰鬥中破壞順序：最外層（最後放置、最靠近攻擊者）優先破壞，不可選擇（FAQ Q36）。非戰鬥效果造成的單一盾牌破壞則選擇最外層
- **CR-4.8** — 0 AP 單位無法破壞任何防禦層（Base 或盾牌）
- **CR-4.9** — 敗北條件：盾牌區無卡且戰鬥傷害直擊玩家

## CR-5：戰鬥

- **CR-5.1** — 在 Main 階段宣告攻擊，phase 切為 battle，step = attack
- **CR-5.2** — 戰鬥步驟順序：attack → block → action → damage → battle_end
- **CR-5.3** — battle_end 後 phase 回到 main
- **CR-5.4** — 攻擊單位必須為直立（未橫置），且滿足 (a) 已出場 1+ 回合（例：Turn 3 部署 → Turn 4 起可攻擊）或 (b) 為 Link Unit（CR-6.4，部署當回合即可攻擊）
- **CR-5.5** — 每次攻擊宣告一個單位，逐一解決後 phase 回到 main 方可宣告下一次攻擊
- **CR-5.6** — Breach 關鍵字（見 CR-6.3）：攻擊造成戰鬥傷害額外加上 Breach 數值的傷害到盾牌區，目標判定同 CR-4.3（有 Base 打 Base，無 Base 打盾牌）。盾牌區無卡時 Breach 不發動
- **CR-5.7** — First Strike 關鍵字：先造成傷害。若對方單位被破壞則不反擊
- **CR-5.8** — 阻擋：只有直立（未橫置）且具備 Blocker 關鍵字的單位才能阻擋
- **CR-5.9** — 阻擋將攻擊轉向 Blocker，不經過防禦層序
- **CR-5.10** — 同一次攻擊不能堆疊多個 Blocker
- **CR-5.11** — 戰區最多 6 格（0-5）。滿位時可 trash 既有單位騰出空間（不算破壞）
- **CR-5.12** — 戰鬥 action step（block → damage 之間）的優先權規則同 CR-2.10：非 active player 先，雙方連續 pass 才進 damage step

## CR-6：卡片關鍵字

- **CR-6.1** — **Blocker(阻擋者)**：直立時可阻擋攻擊。同次攻擊不可疊加
- **CR-6.2** — **First Strike(先制攻擊)**：戰鬥中先造成傷害。對方單位被破壞則不反擊
- **CR-6.3** — **Breach(突破)**【N】：攻擊時對盾牌區造成 N 點額外傷害，目標判定同 CR-4.3（有 Base 打 Base，無 Base 打盾牌）。盾牌區無卡時不發動。多個 Breach 可疊加
- **CR-6.4** — **Link(共鳴)**：Unit + 同系列 Pilot 組成的聯合單位（共鳴機體），出擊當回合即可攻擊
- **CR-6.5** — **Burst(爆發)**：帶有 Burst 的卡片在作為盾牌被破壞時可揭示並觸發其 Burst 效果。效果因卡而異（加入手牌、發動 Main 效果、部署等）
- **CR-6.6** — **Deploy(出擊時)**：卡片進場時自動觸發的效果。強制執行（除非卡面註明「可選擇」）。例：ST01-004 Guntank 進場時橫置敵方 Unit
- **CR-6.7** — **Token(代幣)**：level=0, cost=0, color=Token 的卡片。被破壞時移除遊戲（進 removal 區），不去 trash。不計入手牌，不計入牌庫。戰區 Token 佔用 slot 數同一般 Unit

## CR-7：Base

- **CR-7.1** — 盾牌區同時只能有 1 個 Base
- **CR-7.2** — 預設 Base：EX Base（代幣，0 AP / 3 HP）。EX-BASE 沒有狀態欄位
- **CR-7.3** — 部署新 Base 卡（從手牌或 Burst 觸發）：舊 Base（含 EX-BASE）進廢棄區，然後將最上層盾牌加入手牌。新 Base 卡的 HP 取代舊 Base 的 HP 成為防禦層外層
- **CR-7.4** — Base 破壞 ≠ 敗北。需盾牌也為 0 時傷害才會直擊玩家
- **CR-7.5** — 部署的 Base 卡有狀態（active/rested），記錄於 `base.status`。可使用支付「Rest this Base」的能力。被 rested 不影響其防禦功能（仍正常吸收傷害）。Start Phase (CR-2.4) 重置為 active
- **CR-7.6** — Base 卡的破壞依 CR-4.4（damage ≥ HP 時移除，excess 不往下傳）。Base 破壞後，`base.alive=false`，`base.status` 清空

## CR-8：手牌與牌庫限制

- **CR-8.1** — 手牌無上限，但 End 階段手牌 ≥11 時需棄到 10 張（可選擇棄哪些牌）
- **CR-8.2** — 牌庫為空 + 需抽牌 → 敗北
- **CR-8.3** — 資源牌庫為空時 Resource 階段仍發生但跳過（無卡可部署，直接進 Main 階段）
- **CR-8.4** — 投降 → 立即敗北

## CR-9：遊戲終止

- **CR-9.1** — 敗北條件：(a) 盾牌=0 + 戰鬥傷害直擊玩家，(b) 牌庫=0 + 需抽牌，(c) 投降
- **CR-9.2** — 敗北時：game_over=true, winner=對方

## CR-10：卡片類型與啟動時機

### 卡片類型

- **CR-10.1** — 四種卡片類型：unit（單位）、pilot（駕駛員）、command（指令）、base（基地）
  - **Unit**：部署到 battle_area，可攻擊/阻擋
  - **Pilot**：部署到 battle_area，可與 Unit pair 形成 Link
  - **Command**：從手牌使用，效果立即結算，進 trash。部分 Command 有 [Pilot] 子類
  - **Base**：部署替換防禦層的 Base，佔用 Base 槽位（CR-7）
- **CR-10.2** — **雙用途 [Pilot]**：Command 卡若帶有 [Pilot][PilotName] 子類，可選擇以 Command 方式使用（發動 Main 效果）或以 Pilot 方式部署（使用規則旁標示的 AP/HP 數值）。部署為 Pilot 時進 battle_area，可與 Unit pair 形成 Link

### 啟動時機

- **CR-10.3** — 效果的啟動時機標示（寫於卡面方括號）：
  - `[Main]` — 僅在 Main phase 可使用
  - `[Main]/[Action]` — 在 Main phase 或 Battle/End 的 Action step 可使用
  - `[Activate/Main]` — 手動啟動型效果，支付費用後在 Main phase 可使用
  - `[Attack]` — 宣告攻擊時觸發
  - `[Deploy]` — 卡片進場時自動觸發（CR-6.6）
  - `[Burst]` — 作為盾牌被破壞時可觸發（CR-6.5）
- **CR-10.4** — **Once per turn**：標示 `[Once per Turn]` 的效果一回合只能啟動一次。使用後記錄於 `active_effects`，回合結束時清除

### 代幣生成

- **CR-10.5** — 效果產生 Token 時：將 Token 卡部署到 battle_area 的空 slot（佔用戰區空間，不佔用手牌空間）。Token 被破壞時進 removal 區（CR-6.7）
