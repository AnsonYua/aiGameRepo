# GCG Card AI

這個專案是鋼彈卡牌遊戲的 chat-first 遊戲實驗。玩家入口是 chat；Python CLI/runtime 是 Codex 與 opencode 背後共用的內部引擎介面，不是玩家主要 UI。

## 主要流程

```text
玩家 chat
  -> Codex / opencode adapter
  -> skills_py/gcg_runtime.py
  -> game-states/<game_id>/gameState.md
  -> skills_py/gcg_display.py --viewer P1|P2
  -> chat 回覆完整可見狀態
```

玩家或 AI 決策前都必須收到該玩家視角的完整可見狀態。玩家與 AI Player 不直接讀 `gameState.md`。

設計邊界詳見 `GCG_ARCHITECTURE.md`：Python 是狀態安全層、基礎規則層、唯一寫入者；LLM 是語意解析層、效果解釋層、策略層。所有 LLM 產生的 proposed command / proposed state_diff 都必須回到 runtime，由 Python 驗證與套用。

## 玩家體驗

玩家在 chat 輸入自然指令：

```text
start game
keep
redraw
play st01/ST01-008 0
attack 0
pass
concede
```

adapter 將這些指令轉成 runtime CLI 呼叫，再把 runtime 回傳的完整顯示文字原封不動回覆給玩家。

## Runtime 介面

`skills_py/gcg_runtime.py` 是 opencode / Codex 共享的穩定邊界：

```bash
python3 skills_py/gcg_runtime.py start --viewer P1
python3 skills_py/gcg_runtime.py start --viewer P1 --first-player P1  # 測試用固定先手
python3 skills_py/gcg_runtime.py status --viewer P1
python3 skills_py/gcg_runtime.py status --viewer P2
python3 skills_py/gcg_runtime.py mulligan --player P1 --action keep --viewer P1
python3 skills_py/gcg_runtime.py command --player P1 --cmd "pass" --viewer P1
python3 skills_py/gcg_runtime.py auto --player P2 --viewer P1
```

所有會改變遊戲狀態的操作都應經過 runtime 或 `game_engine.py`，不要讓 chat agent 手動編輯 YAML。

單一 chat 流程可直接使用 `.gcg_active_game`。若 Codex subagent、opencode CLI 或自動測試需要並行驗證，先用 `start --json` 取得 `game_id`，後續命令加上 `--game-id <game_id>`，避免不同測試互相覆寫目前遊戲。

## 視角與隱私

- `--viewer P1`：顯示 P1 手牌完整內容，P2 手牌只顯示張數。
- `--viewer P2`：顯示 P2 手牌完整內容，P1 手牌只顯示張數。
- 戰鬥區是公開區域，雙方場上卡牌都顯示卡名、AP/HP、狀態與關鍵字。
- 盾牌與牌庫內容是非公開資訊，只顯示數量。

## Opencode / Codex 相容策略

- Codex：直接呼叫 `gcg_runtime.py`，不依賴 opencode `@` 或 `task` spawn。
- opencode：保留 `.opencode/agents/*.md` 作為 chat adapter / AI prompt / 規則參考；狀態變更仍回到同一個 runtime。
- `gcg-ai-player` 是唯一 AI 策略來源。`skills_py/ai_player.py` 只呼叫 agent、解析 `CONSIDER` / `COMMAND`，不寫 Python 策略 fallback。
- `gcg-ai-player` 只應讀完整 display text，回 public-safe 考量與單一 command，不直接改 state。
- `gcg-judge` / `.opencode/skills/gcg/*.md` 可作為複雜效果語意 reviewer，產生 proposed state_diff；最終 apply 仍必須由 Python validator/runtime 負責。

## 目前保留的 legacy/debug 入口

`gcg_simulation.py` 暫時保留作為 debug/legacy CLI。正式相容路徑以 chat adapter 呼叫 `skills_py/gcg_runtime.py` 為準。

## Regression Harness

AI-vs-AI simulation / replay review 的測試原則見 `GCG_TESTING_PRINCIPLES.md`。

修改 AI 決策、runtime combat、gameplay log 或 replay 後，至少跑：

```bash
python3 tests/gcg_direction_harness.py
```

這個 harness 不呼叫 live opencode；它用 fake subprocess 驗證 `skills_py/ai_player.py` 只會透過 `gcg-ai-player.md` adapter 決策，並檢查 public-safe consideration、`attack <slot> unit <enemy_slot>`、`block <slot>`、YAML/replay 記錄。

若要額外驗證 live LLM / opencode agent 合約：

```bash
python3 tests/gcg_direction_harness.py --live-llm
```

`--live-llm` 會實際呼叫 `opencode run --agent gcg-ai-player`，只檢查 `CONSIDER` / `COMMAND` 合約與 public-safe 輸出，不套用狀態。

AI-vs-AI replay harness：

```bash
python3 tests/gcg_ai_vs_ai_replay_harness.py
python3 tests/gcg_ai_vs_ai_replay_harness.py --live-llm
```

此 harness 會產生 `gameplay.yaml`、`replay.md`、`review.md`。預設模式 fake opencode subprocess 但仍強制所有 AI call 走 `gcg-ai-player` adapter path；`--live-llm` 才呼叫真實 agent。

## 清理規則

不要提交產生型檔案：

- `.DS_Store`
- `__pycache__/`
- `*.pyc`
