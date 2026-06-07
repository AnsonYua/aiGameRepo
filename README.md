# GCG Card AI

這個專案是鋼彈卡牌遊戲的 chat-first 遊戲實驗。玩家入口是 chat；Python runtime 是唯一遊戲狀態邊界；AI 決策主路徑是本機長駐 `agent-server`，背後連到 `codex app-server --stdio`。

## 主要流程

```text
玩家 chat
  -> skills_py/gcg_runtime.py
  -> skills_py/game_engine.py
  -> game-states/<game_id>/gameState.md
  -> skills_py/gcg_display.py --viewer P1|P2
  -> chat 回覆完整可見狀態
```

AI 決策流程：

```text
skills_py/gcg_runtime.py auto / P2 auto
  -> skills_py/ai_player.py
  -> skills_py/ai_adapters.py
  -> local agent-server HTTP API
  -> one long-lived codex app-server process
  -> per-game Codex room thread
```

每一局初始化 4 個獨立 Codex rooms：

```text
game_id
  ├─ gcg-orchestrator
  ├─ gcg-judge
  ├─ gcg-ai-player:P1
  └─ gcg-ai-player:P2
```

玩家與 AI Player 都不直接讀 `gameState.md`。任一決策前，runtime 會產生該玩家視角的完整可見狀態。

## 玩家指令

玩家在 chat 輸入：

```text
start game
keep
redraw
play st01/ST01-008 0
attack 0
pass
concede
```

chat agent 必須直接呼叫 runtime，並把 stdout 原封不動回覆。

## Runtime 介面

```bash
python3 skills_py/gcg_runtime.py start --viewer P1
python3 skills_py/gcg_runtime.py start --viewer P1 --first-player P1
python3 skills_py/gcg_runtime.py status --viewer P1
python3 skills_py/gcg_runtime.py status --viewer P2
python3 skills_py/gcg_runtime.py mulligan --player P1 --action keep --viewer P1
python3 skills_py/gcg_runtime.py command --player P1 --cmd "pass" --viewer P1
python3 skills_py/gcg_runtime.py auto --player P2 --viewer P1
```

所有會改變遊戲狀態的操作都必須經過 runtime 或 `skills_py/game_engine.py`，不要讓 chat agent 手動編輯 YAML。

單一 chat 流程可使用 `.gcg_active_game`。並行測試需先用 `start --json` 取得 `game_id`，後續命令加 `--game-id <game_id>`。

## Agent Server

啟動長駐 Codex app-server wrapper：

```bash
python3 skills_py/gcg_agent_server.py --host 127.0.0.1 --port 8890
```

用主 provider 跑 probe：

```bash
GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py ai-probe --provider agent-server
```

直接測 app-server protocol：

```bash
python3 skills_py/gcg_agent_server.py --probe --timeout-seconds 60
```

Agent server API：

```text
GET  /health
GET  /metrics
POST /init-game
POST /append
POST /decide
```

`start game` 在 `GCG_AI_PROVIDER=agent-server` 時會呼叫 `/init-game` 建 4 rooms。AI 決策走 `/decide`。成功公開動作會用 `/append` 注入 `gcg-orchestrator` room。

## 視角與隱私

- `--viewer P1`：顯示 P1 手牌完整內容，P2 手牌只顯示張數。
- `--viewer P2`：顯示 P2 手牌完整內容，P1 手牌只顯示張數。
- 戰鬥區是公開區域。
- 盾牌與牌庫內容是非公開資訊，只顯示數量。
- replay / gameplay YAML 不得包含 hidden hand/deck/shield card ids。

## Harness

修改 runtime、AI adapter、agent server、display、replay 後至少跑：

```bash
python3 tests/gcg_direction_harness.py
```

Live provider 測試：

```bash
python3 skills_py/gcg_agent_server.py --host 127.0.0.1 --port 8890
GCG_AI_PROVIDER=agent-server python3 tests/gcg_direction_harness.py --live-llm
```

AI-vs-AI replay harness：

```bash
python3 skills_py/gcg_agent_server.py --host 127.0.0.1 --port 8890
GCG_AI_PROVIDER=agent-server python3 tests/gcg_ai_vs_ai_replay_harness.py --ai-timeout-seconds 60
```

AI-vs-AI 會產生 `gameplay.yaml`、`replay.md`、`review.md`。`INCOMPLETE` 是 quality signal，必須讀 replay/review 分類 root cause，不可只調高上限。

## 清理規則

不要提交產生型檔案：

- `.DS_Store`
- `__pycache__/`
- `*.pyc`
- `.opencode/node_modules/`
- 臨時 probe game state
