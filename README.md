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
- opencode：保留 `.opencode/agents/*.md` 作為 chat adapter / AI prompt / 規則參考，但執行路徑應 fallback 到同一個 runtime。
- `gcg-ai-player` 只應讀完整 display text 並回單行 command，不直接改 state。

## 目前保留的 legacy/debug 入口

`gcg_simulation.py` 暫時保留作為 debug/legacy CLI。正式相容路徑以 chat adapter 呼叫 `skills_py/gcg_runtime.py` 為準。

## 清理規則

不要提交產生型檔案：

- `.DS_Store`
- `__pycache__/`
- `*.pyc`
