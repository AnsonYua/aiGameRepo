# GCG 長駐 Codex Agent Server 重構計畫

## 狀態

此計畫已進入實作方向：主 provider 是 `agent-server`，背後使用長駐 `codex app-server --stdio`。本文件保留原始決策脈絡與 harness 驗收標準；實際架構以 `GCG_ARCHITECTURE.md`、`GCG_TESTING_PRINCIPLES.md`、`REVIEW_SPEC.md` 與 `AGENTS.md` 為準。

尚未完成的後續清理：`.opencode/agents/gcg-ai-player.md` 仍保留較完整的策略 prompt，可作為遷移到 app-server player instructions 的參考。遷移完成前不要直接刪除該策略內容。

## 目標

目前慢的主因不是「沒有 session id」，而是每次 AI 決策都可能啟動一次 CLI process。即使用 `codex exec resume`，仍要付出 process startup、讀設定、恢復 thread、初始化 agent 的成本。

本重構的目標是把 AI 決策主路徑改成長駐 `codex app-server --stdio`：

```text
runtime command
  -> local GCG agent server
    -> already-running codex app-server
      -> existing Codex thread / chatroom
```

而不是：

```text
runtime command
  -> spawn codex exec
    -> resume session
      -> run one decision
    -> exit process
```

## 架構

每一局 `game_id` 都初始化 4 個獨立聊天室：

```text
game_id
  ├─ gcg-orchestrator
  ├─ gcg-judge
  ├─ gcg-ai-player:P1
  └─ gcg-ai-player:P2
```

角色分工：

- `gcg-orchestrator`：保留 public-safe 流程摘要與動作歷史。Python runtime 仍是唯一狀態修改者。
- `gcg-judge`：保留 public-safe 規則判定上下文。第一版不主動呼叫裁判，只先建立獨立 room。
- `gcg-ai-player:P1`：P1 決策聊天室，只根據 P1 viewer display 回 `CONSIDER` / `COMMAND`。
- `gcg-ai-player:P2`：P2 決策聊天室，只根據 P2 viewer display 回 `CONSIDER` / `COMMAND`。

Codex app-server protocol 使用方式：

- `initialize`：agent server 啟動時初始化 protocol。
- `thread/start`：每個 role 建立一個 Codex thread。
- `turn/start`：對既有 thread 追加一輪訊息。
- notification stream：收集 `item/agentMessage/delta`、`item/completed`、`turn/completed` 作為決策輸出。

## 需求

- 玩家 chat 指令不變：`start game`、`status`、`keep/redraw`、`play`、`attack`、`pass`。
- `start game` 後嘗試呼叫 agent server `/init-game` 建立 4 rooms。
- `/init-game` 失敗只寫 warning event，不阻止開局。
- AI 決策主路徑使用 `GCG_AI_PROVIDER=agent-server`，不得每次 spawn `codex exec`。
- P1/P2 必須是不同 thread；同一玩家多次決策必須 reuse 同一 thread。
- Orchestrator/Judge 不可與任何 player 共用 thread。
- AI player thread 預設 read-only sandbox、approval never、network disabled；第一版不給自訂 tools。
- Session metadata 寫入 `game-states/<game_id>/ai_sessions/`，方便 review thread 對應關係。

## HTTP API

本機 agent server 提供：

```text
GET  /health
GET  /metrics
POST /init-game
POST /append
POST /decide
```

`POST /init-game`：

```json
{
  "game_id": "game_xxx",
  "timeout_seconds": 30
}
```

`POST /append`：

```json
{
  "game_id": "game_xxx",
  "role": "gcg-orchestrator",
  "message": "P1 執行：pass",
  "timeout_seconds": 10
}
```

`POST /decide`：

```json
{
  "game_id": "game_xxx",
  "player_id": "P2",
  "prompt": "<viewer display>",
  "timeout_seconds": 60
}
```

## Harness 驗收

Unit harness：

- `init_game` 建立剛好 4 個 role sessions。
- P1/P2 thread id 不同。
- P1 第二次 decision reuse P1 thread id。
- Judge/Orchestrator thread id 不等於 player thread id。
- `/append` 追加到指定 role，不會建立 player thread。

Runtime harness：

- `python3 skills_py/gcg_runtime.py start --viewer P1`
- `GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py mulligan --player P1 --action keep --viewer P1`
- P2 AI 決策需走 agent-server `/decide`。

Provider harness：

- 啟動 server：`python3 skills_py/gcg_agent_server.py --host 127.0.0.1 --port 8890`
- Probe：`GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py ai-probe --provider agent-server`
- 回覆必須能 parse 成 `CONSIDER:` / `COMMAND:`。

AI-vs-AI 測速：

- `GCG_AI_PROVIDER=agent-server python3 tests/gcg_ai_vs_ai_replay_harness.py --ai-timeout-seconds 60`
- 觀察 replay / review 與 provider elapsed time。
- 若 timeout，分類為 provider latency 或 runtime issue，不新增 retry 掩蓋問題。

## 不做的事

- 不改玩家可見指令。
- 不改遊戲規則。
- 不改 replay 格式。
- 不把 hidden hand/deck/shield card id 寫入 replay 或 gameplay YAML。
- 不更新 memory。
