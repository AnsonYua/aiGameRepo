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

## Sub-Agents（4 個代理）

| Agent | 檔案 | 職責 |
|-------|------|------|
| Orchestrator | `gcg-orchestrator.md` | 路由指令 → skill → Judge → 寫 state → Display → 輸出 |
| Display | `gcg-display.md` | 將 game_state 填入模板 → 格式化人眼可讀輸出 |
| Judge | `gcg-judge.md` | 驗證 state_diff 合法性，回傳 accept/reject |
| AI Player | `gcg-ai-player.md` | 決策引擎，輸出單行指令 |

### Orchestrator — 總控路由

| 範圍 | 檢查要點 |
|------|---------|
| 路由表 | start game / redraw/keep / auto_start / play/deploy/pair / activate / attack / block / pass / draw / resource / concede → 對應正確 skill |
| AI auto-play | priority=P2 時自動呼叫 AI Player，不走使用者輸入 |
| 啟動流程 | start game → skill_initialize → Judge → 寫 state → Display(mulligan) |
| Redraw 流程 | skill_redraw → Judge → 寫 state → P2=AI → skill_start_phase → Judge → 寫 state → Display |
| 其他指令 | 查路由 → skill → Judge → 寫 state → Display → Write→Read→Echo |
| Write→Read→Echo | 強制：Display 的回傳必須 Write 到 /tmp/gcg_output.txt → Read 回來 → 回應 = Read 結果，一字不改 |
| Judge 前置 | 呼叫 Judge 前需用 skill_card_db.md §3 預取 card_data |
| Phase lock 驗證 | 路由前手動比對 game_state.phase 與 skill 的 phase_lock，不符 → err_phase_mismatch |
| 150 行限制 | orchestrator 本身 ≤ 150 行 |
| 內嵌模板 | mulligan / compose_state 模板直接內嵌在 orchestrator 中，不依賴 ui_templates.md 讀取 |

### Display — 格式化輸出

| 範圍 | 檢查要點 |
|------|---------|
| 模板數量 | Mulligan / Main / Draw / Resource / Battle(attack/action+battle_end) / End / Start / Error 共 9 模板 |
| 變數正確性 | {variable} 全部有值可填，無遺漏/錯字 |
| Play Legality 計算 | 每張手牌依 Level (active+rested+ex) 與 Cost (active) 計算 ✅/❌ |
| 隱私遮罩 | opponent_revealed 控制對手戰區顯示，opponent_shields 只顯示數字 |
| hp_remaining | 顯示為 {hp-damage} |
| action_prefix | command→play, 其他→deploy |
| Battle log 格式 | ✔ / ✘ / • 前綴 |
| Phase 對應 | orchestrator 依當前 phase/step 選擇正確模板 |
| Error 模板 | mismatched phase → illegal command: {reason} |

### Judge — 驗證引擎

| 範圍 | 檢查要點 |
|------|---------|
| 輸入 | game_state.md（當前狀態）+ state_diff（提議變更）+ card_data |
| 輸出格式 | 僅 `accept` 或 `reject: <reason> [CR-X.Y]` |
| CR-ID 驗證 | state_diff 附帶的 CR-ID 引用是否正確 |
| 卡片數據驗證 | 新部署 unit 的 ap/hp 必須符合 card_data 基礎值 |
| 效果驗證 | trigger/cost/oncePerTurn 是否符合 card_data 的 interpreted effects |
| 語義驗证 | 資源變化→CR-3.x, 防禦層→CR-4.x, 戰鬥→CR-5.x |
| 邊界檢查 | 數值不可為負、欄位不可為 null |
| 不越權 | 只驗證規則，不修改 state、不提替代方案 |
| 輸出合約缺口 (P3-9) | skill 的 state_diff / AI 的單行指令 / Judge 的 accept-reject — 無 runtime 強制驗證 |

### AI Player — 決策引擎

| 範圍 | 檢查要點 |
|------|---------|
| 輸出格式 | 僅單行指令：play/deploy/pair/activate/attack/block/pass/end turn/draw/resource/redraw/keep/concede |
| Write→Read→Echo | 輸出 Write 到 /tmp/gcg_ai_output.txt → Read 回 → 回應 = Read 結果 |
| 視角映射 | player_id=P1→me=p1,opponent=p2；player_id=P2→me=p2,opponent=p1 |
| 先後手 | first_player 決定 EX resource 有無 |
| 階段對應 | pre-game→keep/redraw, start→pass, draw→draw, resource→resource, main→策略, battle→attack/block, end→end turn |
| 5 策略分支 | 橫掃/發展/搶血/反打/絕望 — 各分支條件與權重正確 |
| 局勢評估 | 防禦差、場面差、可攻擊 Unit 數、資源差、手牌差計算 |
| Blocker 影響 | 對方 Blocker 直立數、HP vs AP 補刀判斷 |
| 攻擊優先順序 | 補刀(20) > Blocker(18) > 依 AP 擊殺(15+) > 傷害(10+) |
| Block 決策 | 直立+Blocker 關鍵字檢查，HP>AP 存活判斷，致命覆寫 |
| 投降條件 (CR-8.4) | 6 條件全滿足才 concede |
| 經驗 YAML 橋接 | 5 分支映射到 Python scoring 權重，MCP 記憶層為可選橋接 |
| 出牌合法性自查 | Level/費用/cardType/slot/pair 條件，Once per turn 檢查 |
| Dual [Pilot] 卡 | deploy→Pilot, play→Command 的雙路由 |
| card_data 預取 | 依 orchestrator 傳入的 card_data 對照表做決策 |

## Python Engine（simulate_game.py）

| 範圍 | 檢查要點 |
|------|---------|
| 與技能一致性 | Python 實作邏輯與 13 個 skill .md 一致 |
| 回合流程 | run_game() main loop 正確經過所有階段 |
| 隨機種子 | init_game(seed) 可重現 |
| 批次模式 | run_batch(N) 統計正確（勝率、回合數） |
| Command Effect | 11+ action types 全部實作 |
| 經驗載入 | load_matching_experience() 匹配正確 |
| 日誌 | log_action() 輸出格式與 §12 一致 |

## UI Templates（ui_templates.md）

| 範圍 | 檢查要點 |
|------|---------|
| 階段模板 | Start / Draw / Resource / Main / Battle(3 substeps) / End |
| 變數命名 | 所有模板變數格式一致（{variable}） |
| 對手資訊 | opponent_shields 顯示、opponent_revealed 條件邏輯 |
| 動作列表 | play, deploy, pair, activate, attack, block, pass, draw, resource, end |

## Judge / Enforcement（驗證與強制力）

| 範圍 | 檢查要點 |
|------|---------|
| Judge 輸出 | 僅 accept 或 reject: <reason> [CR-X.Y] |
| Phase Mismatch | phase_lock 違反時是否拒絕 |
| 輸出合約 | orchestrator 僅轉發 display template，不自由生成 |
| Write→Read→Echo | 所有 agent 是否遵守此模式 |

## 測試

| 範圍 | 檢查要點 |
|------|---------|
| 測試覆蓋 | gcg-test-level-display.md + gcg-test-suite.md 涵蓋哪些情境 |
| 預期輸出 | 測試案例的 expected output 是否與實際一致 |
| 邊界案例 | 空戰區、滿盾牌、0 AP、token 限制等 |

## 全域規定

| 範圍 | 檢查要點 |
|------|---------|
| 程式碼無註解 | 所有 .py 檔案無多餘註解 |
| 中文字 | 僅繁體中文（體/門/關/開/發/時/從/點/對/過/來/說/會/與/為/傳/傷/僅） |
| 術語一致性 | 行動玩家/非行動玩家、調度/讓過、橫置/直立、盾牌/資源 |
| 檔案大小 | agent 檔案 < 150 行，技能檔案 < 150 行 |
| 無 .deck_tracking.json | 已全部移除，無遺留參考 |
| CR-ID 參考 | 所有規則引用使用 CR-X.Y 格式 |

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
