# GCG CardAI — Review Specification

> 檢查清單 / 指南，列出每次 Review 應檢視的所有範圍與要點。
> 依重要性排列，非依修復狀態 — 本文件是**備忘字典**，不是問題追蹤。

## Phase Flow（階段流程）

| 範圍 | 檢查要點 |
|------|---------|
| Pre-game | mulligan → keep/redraw → shuffle → shield setup 順序是否正確 |
| Start Phase | 行動玩家 untap → draw 1 → resource 1 → advance to main |
| Draw Phase | 僅行動玩家抽牌，步數正確 |
| Resource Phase | 僅行動玩家部署資源 |
| Main Phase | 可 play/activate/attack/pass，attack 觸發 battle 轉換 |
| Battle Phase | attack declare → block declare → action priority → damage → battle_end |
| Action Step | non-active 玩家先有 priority，雙方交替，皆 pass → 進入 damage |
| End Phase | action step → cleanup → advance turn |
| Turn Advance | turn++，切換行動玩家，回到 start phase |

## Priority System（優先權系統）

| 範圍 | 檢查要點 |
|------|---------|
| CR-2.9 | priority 欄位是否存在於 Game state |
| CR-2.10 | 行動步驟中非行動玩家先取得 priority |
| CR-5.12 | 戰鬥 action step 雙方交替 pass |
| Pass 流程 | pass → Judge 驗證 → 切換 priority → 雙方皆 pass → 前進 |
| Phase Lock | 各 skill 的 phase_lock 是否正確限制可用指令 |

## Combat System（戰鬥系統）

| 範圍 | 檢查要點 |
|------|---------|
| Attack 宣告 | 攻擊者設為 rested，current_attacker 正確 |
| Attackable 檢查 | 活著、沒休息、有 Blocker/Link 關鍵字、不是不可攻擊玩家 |
| Block 宣告 | 阻擋者需 active 且有關鍵字 Blocker |
| Block 存活 | HP > AP 才阻擋（除非致命覆寫） |
| First Strike | FS 單位優先造成傷害 |
| Breach | Breach N 跳過前 N 層直接對盾牌造成傷害 |
| Damage 堆疊 | 盾牌傷害先結算，再 unit/base 傷害 |
| Shield 破壞 | 破壞的盾牌加入 op.trash |
| Battle End | battle_end 後回到 main phase |
| Link 攻擊 | 有 Link 關鍵字的 unit 可攻擊 |

## Card Effects（卡片效果）

| 範圍 | 檢查要點 |
|------|---------|
| interpret_effects() | 原始 JSON → 標準化格式的正確性 |
| Trigger 類型 | on_deploy, on_pair, on_attack, end_of_turn 等 |
| Action 類型 | damage, modifyAP, heal, draw, rest, setActive, addToHand, deploy, conditionalTokenDeploy, activate_ability |
| Target Scope | self, self_unit, self_all_units, enemy_unit, enemy_all_units, all_all, self_base 等 |
| Burst 處理 | activate_ability、非 Base 部署、fallback trash |
| Token 卡片 | 從 gcgdecks.json extraCard 載入，不可從手牌打出 |

## Game State Schema（遊戲狀態結構）

| 範圍 | 檢查要點 |
|------|---------|
| Game dataclass | turn, first_player, active_player, phase, step, current_attacker, priority |
| Player 結構 | base, shields, hand_cards, deck/resource deck, resources, battle_area(6 slots), trash, removal |
| Slot 結構 | unit_id, pilot_id, ap, hp, damage, status, keywords |
| active_effects | effectId, source, timing, parameters, used_this_turn |
| 序列化 | to_dict() / from_dict() / write_state() 往返正確認 |
| Schema 一致性 | game_state_schema.md 與 Python dataclass 同步 |

## Experience YAML（經驗系統）

| 範圍 | 檢查要點 |
|------|---------|
| 條件檢查 | turn, units, base HP, shields, hand count, resource count, board empty 等 |
| 權重合併 | 多個 matching YAML 的優先級與加成效應 |
| 重疊檔案 | 是否有 redundant YAML（如 defend-low-base vs defensive-comeback） |
| attack_target 偏誤 | kill / damage / base 三種模式 |
| Priority 合理 | 高優先級是否確實覆蓋低優先級 |
| YAML 格式 | 欄位名稱英文、註解可中文、格式與 Python 引擎相容 |

## Agent Skills（13 個技能）

| 範圍 | 檢查要點 |
|------|---------|
| 前置資料 (frontmatter) | triggers, phase_lock 是否正確 |
| 觸發條件 | 是否只有被列出的 trigger 才會路由至此技能 |
| state_diff 輸出 | 格式正確，僅含必要變更欄位 |
| Phase Lock | 不能在不允許的階段被呼叫 |
| 150 行限制 | 技能檔案不超過 150 行 |
| 委派模式 | 不重複其他技能的邏輯，透過 orchestrator 路由 |

## Runtime / Agents

| 元件 | 檔案 | 職責 |
|-------|------|------|
| Runtime | `skills_py/gcg_runtime.py` | chat adapter 內部 CLI；統一 start/status/mulligan/command/auto |
| Orchestrator | `gcg-orchestrator.md` | opencode chat adapter；呼叫 runtime，轉發完整顯示文字 |
| Display | `skills_py/gcg_display.py` | 將 game_state 填入模板 → 格式化人眼可讀輸出（Python 腳本，非 agent） |
| Judge / Effect Reviewer | `gcg-judge.md` | 複雜效果語意 reviewer；可檢查 proposed state_diff，但非最終 state applier |
| AI Player | `gcg-ai-player.md` | 唯一 AI 策略來源，輸出 public-safe 考量與單一指令 |

### Runtime / Orchestrator — Chat-first 流程

| 範圍 | 檢查要點 |
|------|---------|
| Runtime 指令 | `start` / `status` / `mulligan` / `command` / `auto` 全部可用 |
| Chat 入口 | 玩家輸入由 chat adapter 轉成 runtime command；玩家不直接跑 CLI |
| AI auto-play | priority=P1/P2 時可用 `gcg_runtime.py auto --player <player>` 自動處理；玩家 chat 預設仍自動處理 P2 |
| 啟動流程 | start game → `gcg_runtime.py start --viewer P1` → 回完整調度狀態 |
| Redraw 流程 | 使用者輸入 → `gcg_runtime.py mulligan --player P1 --action keep|redraw` → 回 display_text |
| 其他指令 | chat 指令 → `gcg_runtime.py command --player P1 --cmd ...` → 回完整 display text |
| 決策狀態輸出 | 任一玩家需要決策時，先用 `gcg_display.py --viewer <P1/P2>` 或 runtime 等效輸出完整可見狀態；玩家/AI 不直接讀 `gameState.md` |
| 150 行限制 | orchestrator 本身 ≤ 150 行 |
| 遊戲狀態檔管理 | start game 時產生唯一 game_id（`game_<YYYYMMDD_HHMMSS>`），建立 `game-states/<game_id>/` 目錄，將 game_id 寫入 `.gcg_active_game` |
| State I/O 路徑 | 所有「讀 state」從 `game-states/<game_id>/gameState.md`，所有「寫 state」至同一路徑。非 `game_state.md` |
| 子代理資料傳遞 | 呼叫 AI Player 時傳入該玩家視角的完整顯示文字；子代理不直接讀取 game state 檔案 |
| 路徑初始化檢查 | 啟動後先讀 `.gcg_active_game`；不存在時只接受 `start game` 指令，拒絕其他操作 |

### Display — 格式化輸出（Python 腳本）

| 範圍 | 檢查要點 |
|------|---------|
| 腳本路徑 | `skills_py/gcg_display.py` |
| 模板數量 | Mulligan / Main / Draw / Resource / Battle(attack/action/battle_end) / End / Start / Error 共 10 模板 |
| 變數正確性 | {variable} 全部有值可填，無遺漏/錯字 |
| Play Legality 計算 | 每張手牌依 Level (active+rested+ex) 與 Cost (active) 計算 ✅/❌ |
| 隱私遮罩 | 對手手牌與盾牌卡明細隱藏；戰鬥區是公開區域，對手場上單位顯示明細 |
| hp_remaining | 顯示為 {hp-damage} |
| action_prefix | command→使用, 其他→部署 |
| Battle log 格式 | ✔ / ✘ / • 前綴 |
| Phase 對應 | orchestrator 依當前 phase/step 選擇正確模板 |
| Error 模板 | mismatched phase → 非法指令: {reason} |
| 速度 | 無 LLM 推論，純字串插值，~0.1s |

### Judge — 效果語意 Reviewer

| 範圍 | 檢查要點 |
|------|---------|
| 輸入 | public-safe state features / viewer context + proposed state_diff + card_data |
| 輸出格式 | 僅 semantic `accept` 或 `reject: <reason> [CR-X.Y]` |
| CR-ID 驗證 | state_diff 附帶的 CR-ID 引用是否正確 |
| 卡片數據驗證 | 新部署 unit 的 ap/hp 必須符合 card_data 基礎值 |
| 效果驗證 | trigger/cost/oncePerTurn 是否符合 card_data 的 interpreted effects |
| 語義驗证 | 資源變化→CR-3.x, 防禦層→CR-4.x, 戰鬥→CR-5.x |
| 邊界檢查 | 數值不可為負、欄位不可為 null |
| 不越權 | 只驗證效果語意與規則引用，不修改 state、不提替代方案 |
| Python final gate | Judge accept 不可直接 apply；必須由 Python validator 檢查 schema、zone/card count、resource、phase、priority、hidden-info safety 後才可套用 |

### AI Player — 決策引擎

| 範圍 | 檢查要點 |
|------|---------|
| 輸出格式 | `CONSIDER: <public-safe 短考量>` + `COMMAND: <單一指令>` |
| CLI 相容輸出 | 不得用 Write/Read 寫入 `/tmp`；runtime 只套用 COMMAND，replay 記錄 CONSIDER |
| 視角映射 | player_id=P1→me=p1,opponent=p2；player_id=P2→me=p2,opponent=p1 |
| 先後手 | first_player 決定 EX resource 有無 |
| 階段對應 | pre-game→keep/redraw, start→pass, draw→draw, resource→resource, main→策略, battle→attack/block, end→end turn |
| 5 策略分支 | 橫掃/發展/搶血/反打/絕望 — 各分支條件與權重正確 |
| 局勢評估 | 防禦差、場面差、可攻擊 Unit 數、資源差、手牌差計算 |
| Blocker 影響 | 對方 Blocker 直立數、HP vs AP 補刀判斷 |
| 攻擊優先順序 | 補刀(20) > Blocker(18) > 依 AP 擊殺(15+) > 傷害(10+)；敵方橫置 Unit 可用 `attack <slot> unit <enemy_slot>` |
| Block 決策 | 直立+Blocker 關鍵字檢查，HP>AP 存活判斷，致命覆寫 |
| 投降條件 (CR-8.4) | 6 條件全滿足才 concede |
| 經驗 YAML 橋接 | 5 分支映射到 Python scoring 權重，MCP 記憶層為可選橋接 |
| 出牌合法性自查 | Level/費用/cardType/slot/pair 條件，Once per turn 檢查 |
| Dual [Pilot] 卡 | deploy→Pilot, play→Command 的雙路由 |
| card_data 預取 | 依 orchestrator 傳入的 card_data 對照表做決策 |

## Python Engine（simulate_game.py）

| 範圍 | 檢查要點 |
|------|---------|
| Runtime 一致性 | Runtime 只呼叫 `game_engine.py` mutation，不讓 adapter 手動改 YAML |
| Game state 路徑解析 | 讀取 `.gcg_active_game` 取得 game_id，組合 `game-states/<game_id>/gameState.md` |
| Viewer 正確性 | `status --viewer P1/P2` 與 `gcg_display.py --viewer P1/P2` 一致 |
| Legacy 邊界 | `gcg_simulation.py` 保留為 debug/legacy，不作正式 chat adapter 入口 |

## UI Templates（ui_templates.md）

| 範圍 | 檢查要點 |
|------|---------|
| 階段模板 | Start / Draw / Resource / Main / Battle(3 substeps) / End |
| 變數命名 | 所有模板變數格式一致（{variable}） |
| 對手資訊 | opponent_shields 顯示；對手戰鬥區單位公開顯示 |
| 動作列表 | play, deploy, pair, activate, attack, block, pass, draw, resource, end |

## Judge / Enforcement（驗證與強制力）

| 範圍 | 檢查要點 |
|------|---------|
| Judge 輸出 | 僅 semantic accept 或 reject: <reason> [CR-X.Y] |
| Phase Mismatch | phase_lock 違反時是否拒絕 |
| Python validator | 所有 proposed command / proposed state_diff 必須先通過 Python safety checks，再由 runtime apply |
| 輸出合約 | orchestrator 僅轉發 display template，不自由生成 |
| CLI 相容輸出 | agent 直接輸出合約文字，不依賴 `/tmp` Write/Read |

## 測試

| 範圍 | 檢查要點 |
|------|---------|
| 測試覆蓋 | gcg-test-level-display.md + gcg-test-suite.md 涵蓋哪些情境 |
| 預期輸出 | 測試案例的 expected output 是否與實際一致 |
| 邊界案例 | 空戰區、滿盾牌、0 AP、token 限制等 |
| Codex subagent | 實作後 spawn explorer 驗證 start → keep → P2 auto → P1 status |
| opencode CLI | 使用 `opencode run --agent gcg-ai-player` 驗證 AI 可讀完整 viewer status 並回 CONSIDER / COMMAND |

## 全域規定

| 範圍 | 檢查要點 |
|------|---------|
| 程式碼無註解 | 所有 .py 檔案無多餘註解 |
| 中文字 | 僅繁體中文（體/門/關/開/發/時/從/點/對/過/來/說/會/與/為/傳/傷/僅） |
| 術語一致性 | 行動玩家/非行動玩家、調度/讓過、橫置/直立、盾牌/資源 |
| 檔案大小 | agent 檔案 < 150 行，技能檔案 < 150 行 |
| 無 .deck_tracking.json | 已全部移除，無遺留參考 |
| CR-ID 參考 | 所有規則引用使用 CR-X.Y 格式 |
| 遊戲狀態隔離 | 每局遊戲使用獨立 `game-states/<game_id>/gameState.md`，永不覆寫單一 `game_state.md` |
| `.gcg_active_game` 同步 | runtime 與 chat adapter 透過 `.gcg_active_game` 溝通當前遊戲 ID，檔案內容須一致 |

---

## 各區塊 Review 順序（建議）

```
1. Phase Flow          — 確認遊戲能完整跑完一局
2. Game State Schema   — 確認 state 結構正確
3. Combat System       — 確認戰鬥邏輯正確
4. Card Effects        — 確認效果解析與觸發
5. Sub-Agents          — 確認 4 代理各自正確（Orchestrator/Display/Judge/AI）
6. Agent Skills        — 確認 13 技能各自正確
7. Experience YAML     — 確認經驗平衡無冗餘
8. Python Engine       — 確認 Python 實作一致
9. UI Templates        — 確認輸出模板無誤
10. Tests              — 確認測試涵蓋
11. 全域規定            — 確認風格/語言/格式一致
```
