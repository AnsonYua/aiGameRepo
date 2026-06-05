# GCG Testing Principles

此文件定義未來測試 GCG AI 對局時的原則。目標不是只確認程式不 crash，而是確認 chat-first runtime、`gcg-ai-player.md`、gameplay log、replay 與賽後 review 全部維持同一個方向。

## 核心原則

1. AI 決策必須走 `gcg-ai-player.md`
   - P1 AI、P2 AI、AI-vs-AI 都必須透過 `skills_py/ai_player.py` 呼叫 `opencode run --agent gcg-ai-player`。
   - Python 不得新增策略 fallback、評分器或自動選牌邏輯。
   - Python 只負責 viewer display、解析 `CONSIDER` / `COMMAND`、合法性驗證、state mutation、gameplay log 與 replay。

2. 測試必須從 chat/runtime 邊界開始
   - 測試入口使用 `skills_py/gcg_runtime.py start --json --viewer P1` 建立 game。
   - 後續所有動作使用同一個 `--game-id`，避免污染 `.gcg_active_game` 或其他測試。
   - 不直接修改 `gameState.md` 來推進正式流程；需要 fixture 時必須明確標為 fixture test。

3. Replay 是測試產物，不是附屬品
   - 每場 AI-vs-AI 測試都必須產生 `gameplay.yaml` 與 `replay.md`。
   - `gameplay.yaml` 是 canonical structured log；`replay.md` 是人類 review 用紀錄。
   - YAML 與 replay 必須從同一事件序列產生，不能各寫一套。

4. Review 要看決策品質，也要看邊界安全
   - Review 不只看誰贏；要檢查 AI 是否有使用部署、攻擊敵方 Unit、阻擋、讓過、action window 等可用決策面。
   - Review 必須檢查 public-safe：不得洩漏隱藏手牌、盾牌、牌庫內容。
   - Review 必須區分「AI 決策問題」、「runtime 合法動作問題」、「display 資訊不足問題」、「replay/log 問題」。

## AI-vs-AI Simulation Harness Contract

未來新增 AI-vs-AI harness 時，至少要跑以下流程：

```text
1. start game
   - python3 skills_py/gcg_runtime.py start --viewer P1 --json
   - 保存 game_id、state_path、gameplay_log_path、replay_path

2. mulligan
   - P1 用 auto 或固定測試指令決定 keep/redraw
   - P2 也必須透過 gcg-ai-player.md 決定 keep/redraw

3. main loop
   - 若 priority 是 P1，呼叫 runtime auto --player P1 --game-id <game_id>
   - 若 priority 是 P2，呼叫 runtime auto --player P2 --game-id <game_id>
   - 每次 auto 後讀 JSON 狀態，直到 game_over 或達到 max_turns / max_actions

4. artifacts
   - 確認 game-states/<game_id>/gameplay.yaml 存在
   - 確認 game-states/<game_id>/replay.md 存在
   - 保存一份 review summary
```

Harness 必須有上限：

- `max_turns`：避免無限對局。
- `max_actions`：避免單一 priority loop 卡死。
- `timeout_seconds`：避免 live LLM 無限等待。
- 若達上限，結果是 `incomplete`，不能算 pass。

## Replay Review Criteria

每場 AI-vs-AI replay review 必須包含以下欄位：

```text
Game:
Result:
Length:
Rules safety:
Hidden-info safety:
AI command diversity:
Combat quality:
Blocker usage:
Unit-target attack usage:
Pass/action-window quality:
Replay/log quality:
Problems:
Likely root cause:
Follow-up:
Verdict:
```

### 必須檢查項目

- `gameplay.yaml` 可被 `yaml.safe_load` 解析。
- event `seq` 單調遞增，沒有重複或倒退。
- 每個 AI 決策 event 有 `command`，並盡量有 public-safe `consideration`。
- replay 是繁體中文。
- replay 不包含 hidden hand card id、deck card id、shield card id。
- replay 不 dump 完整 raw `gameState.md`。
- AI decision 都是 runtime 合法套用後的結果；非法 command 必須在 event/result 中清楚記錄。
- 若有可阻擋情境，AI 有機會使用 `block <slot>` 或明確選擇 `pass`。
- 若有敵方橫置 Unit 且 trade 有利，AI 有機會使用 `attack <slot> unit <enemy_slot>`。
- 若 AI 長期只 `deploy` / `attack <slot>` / `pass`，review 必須標為策略面不足。

### 建議量化指標

這些不是硬性 pass/fail，但 review 應報告：

- AI 決策總數。
- P1 / P2 各自決策數。
- deploy / play / pair / attack base / attack unit / block / pass 數量。
- 非法 command 次數。
- auto-pass action window 次數。
- 觸發 game_over 或達到上限。
- 最常見的失誤類型。

## Pass / Fail Gates

AI-vs-AI replay test 只有在以下全部成立時才算 pass：

- 對局能從 start 走到 game_over，或在設定上限內產生合理 `incomplete` 結果且沒有 crash。
- P1 與 P2 AI 決策都經過 `gcg-ai-player.md`。
- `gameplay.yaml` 與 `replay.md` 都存在且可讀。
- replay / YAML 沒有 hidden-info leak。
- 沒有 Python strategy fallback。
- 沒有直接手改 state 推進正式對局。
- Review summary 明確列出問題與 root cause；不能只寫「looks good」。

若任一項失敗，測試結果必須是 fail 或 incomplete，不能標 pass。

## Review 判斷指南

將問題分類到其中一類，避免混在一起：

- AI prompt problem：`gcg-ai-player.md` 看得到資訊但選擇差，例如不阻擋致命攻擊。
- Display problem：AI 沒看到必要資訊，例如可攻擊敵方 Unit 的提示不足。
- Runtime problem：AI 輸出合法指令但 runtime 拒絕或套用錯誤。
- Log/replay problem：狀態正確但 replay 缺考量、缺事件、順序錯、或洩漏 hidden info。
- Rule-model gap：卡牌效果或規則尚未實作，導致策略無法正確評估。

Review 時要提出下一步：

- 若是 AI prompt problem，改 `.opencode/agents/gcg-ai-player.md`。
- 若是 Display problem，改 `skills_py/gcg_display.py` 或 template。
- 若是 Runtime problem，改 `skills_py/gcg_runtime.py` / `skills_py/game_engine.py`。
- 若是 Log/replay problem，改 `skills_py/gameplay_log.py`。
- 若是 Rule-model gap，先補 engine/card effect，再重跑 replay。

## Existing Harnesses

目前已有：

```bash
python3 tests/gcg_direction_harness.py
python3 tests/gcg_direction_harness.py --live-llm
python3 tests/gcg_ai_vs_ai_replay_harness.py
python3 tests/gcg_ai_vs_ai_replay_harness.py --live-llm
```

`gcg_direction_harness.py` 驗證方向與合約。`gcg_ai_vs_ai_replay_harness.py` 會產生 AI-vs-AI `gameplay.yaml`、`replay.md`、`review.md`，並依本文件欄位做 replay review。

預設 AI-vs-AI harness 使用 fake opencode subprocess，但仍強制檢查所有 AI call 都走 `opencode run --agent gcg-ai-player` adapter path；`--live-llm` 才呼叫真實 `gcg-ai-player.md`。兩種模式都不得直接手改 state 推進對局。
