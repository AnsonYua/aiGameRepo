# GCG 鋼彈卡牌遊戲 — 系統架構

## Overview

本專案採用 chat-first 架構。玩家在 Codex chat 中輸入指令；agent 只負責把遊戲指令轉成 runtime command；Python runtime 是唯一狀態邊界；AI 決策主路徑是本機長駐 `agent-server`，背後連到 `codex app-server --stdio`。

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
  -> per-game role rooms
```

`gameState.md` 是內部 state source。玩家與 AI Player 不直接讀取它；所有決策前都先產生該玩家視角的完整可見狀態。

## Agent Server Rooms

每一局 `game_id` 初始化 4 個獨立 Codex rooms：

```text
game_id
  ├─ gcg-orchestrator
  ├─ gcg-judge
  ├─ gcg-ai-player:P1
  └─ gcg-ai-player:P2
```

角色分工：

| Room | 用途 |
|---|---|
| `gcg-orchestrator` | 接收 public-safe action summary，保留流程上下文。 |
| `gcg-judge` | 目標是接入 `/decide` 做 LLM 語意審查；不作 state applier。 |
| `gcg-ai-player:P1` | P1 決策 room，只看 P1 viewer display。 |
| `gcg-ai-player:P2` | P2 決策 room，只看 P2 viewer display。 |

Session metadata 寫在 `game-states/<game_id>/ai_sessions/<role>.json`。P1/P2 必須是不同 thread；同一玩家多次決策必須 reuse 同一 thread；Judge/Orchestrator 不可和玩家共用 thread。

## Python / LLM Boundary

核心原則：

```text
Python 是狀態安全層、基礎規則層、唯一寫入者。
LLM 是策略層與語意輔助層。
```

放 Python：

- state mutation
- base rule validation
- phase / priority
- card cost / level / AP / HP
- combat resolution
- randomness
- hidden-info filtering
- viewer display
- gameplay log / replay
- regression tests

放 LLM：

- AI 玩家決策
- public-safe 考量摘要
- 卡牌效果與 command 語意 reviewer
- 依公開經驗判斷 lesson 是否適用
- replay review / 文件 review

不可交給 LLM：

- 直接寫 state
- 直接寫 replay canonical event
- 繞過 Python validator 決定勝負
- 讀取或暴露 hidden hand/deck/shield information

## Responsibility Model

| Layer | File / Component | Responsibility |
|---|---|---|
| Chat command boundary | `AGENTS.md` + Codex chat | 遊戲指令直接呼叫 runtime，stdout 原封不動回覆。 |
| Runtime boundary | `skills_py/gcg_runtime.py` | 唯一 chat-facing CLI；start/status/mulligan/command/auto；觸發 AI auto；寫 display/replay/log。 |
| Agent server | `skills_py/gcg_agent_server.py` | 長駐 `codex app-server --stdio`；提供 `/init-game`、`/append`、`/decide`、`/health`、`/metrics`。 |
| AI adapter | `skills_py/ai_adapters.py` | agent-server-only provider；HTTP 呼叫 `/decide`、`/init-game`、`/append`。 |
| AI player boundary | `skills_py/ai_player.py` | 送入 viewer display、解析 `CONSIDER` / `COMMAND`、做 public-safe consideration filtering。 |
| Rules engine | `skills_py/game_engine.py` | 基礎規則與 state mutation：抽牌、資源、出牌、攻擊、pass、勝負與 zone 移動。 |
| State model | `skills_py/game_state.py` | GameState / PlayerState / BattleSlot / BaseState 資料結構與 serialization。 |
| Display | `skills_py/gcg_display.py` | 依 viewer 產生完整可見狀態；只顯示合法可見資訊。 |
| Gameplay log | `skills_py/gameplay_log.py` | `gameplay.yaml` 與 `replay.md` 的 canonical public-safe 記錄。 |
| Card DB | `skills_py/card_db.py` | 卡片資料讀取、摘要與效果 metadata；不直接 mutate state。 |
| Legacy prompt reference | `.opencode/agents/*.md`、`.opencode/skills/gcg/*.md` | 待遷移的 prompt / rule reference；不是主執行路徑。 |

## LLM Experience Boundary

下一階段目標見 `GCG_LLM_EXPERIENCE_ROADMAP.md`。核心原則：

- Experience / lessons 不是 Python 策略 fallback。
- Python 可以讀取 public-safe lesson 與公開卡片文字，並把候選內容傳給 LLM。
- Python 不得根據 lesson 自動選牌、評分、選 target、reject command 或替換 command。
- `gcg-ai-player` 負責提出 command。
- `gcg-judge` 負責 LLM 語意審查。
- `gcg-memory-selector` / `gcg-memory-curator` 負責經驗選取與萃取。
- Runtime 仍是最終合法性與 state mutation 邊界。

## Runtime Boundary

`skills_py/gcg_runtime.py` 是穩定內部介面：

```bash
python3 skills_py/gcg_runtime.py start --viewer P1
python3 skills_py/gcg_runtime.py start --viewer P1 --first-player P1
python3 skills_py/gcg_runtime.py status --viewer P1
python3 skills_py/gcg_runtime.py status --viewer P2
python3 skills_py/gcg_runtime.py mulligan --player P1 --action keep --viewer P1
python3 skills_py/gcg_runtime.py command --player P1 --cmd "pass" --viewer P1
python3 skills_py/gcg_runtime.py auto --player P2 --viewer P1
```

Runtime 回傳最終 display text；`--json` 供 adapter、harness 與工具整合。

`.gcg_active_game` 適合單一 chat session。並行測試或多 agent 驗證應從 `start --json` 取得 `game_id`，再對後續命令加上 `--game-id <game_id>`，避免共享 active game 被其他流程切換。

## Agent Server API

```text
GET  /health
GET  /metrics
POST /init-game
POST /append
POST /decide
```

`POST /init-game` 建立 4 rooms。`POST /append` 注入 public-safe 訊息到指定 role。`POST /decide` 目前對指定 player room 追加 viewer display 並取得 `CONSIDER` / `COMMAND`；依 `GCG_LLM_EXPERIENCE_ROADMAP.md` Phase 1 後，`/decide` 需 orchestrate player -> judge -> repair，並回傳 judge metadata。

Codex app-server protocol 使用：

- `initialize`
- `thread/start`
- `thread/inject_items`
- `turn/start`
- `item/agentMessage/delta`
- `item/completed`
- `turn/completed`

## Viewer Rules

- 任一玩家需要決策時，必須先呼叫 `gcg_display.py --viewer <player>` 或 runtime 等效命令。
- P1 viewer 顯示 P1 手牌完整內容，P2 手牌只顯示張數。
- P2 viewer 顯示 P2 手牌完整內容，P1 手牌只顯示張數。
- 戰鬥區是公開區域，對手場上單位不遮罩。
- 盾牌與牌庫內容永遠不顯示 card id。

## File Layout

```text
cardAI/
├── README.md
├── AGENTS.md
├── GCG_ARCHITECTURE.md
├── GCG_AGENT_SERVER_REFACTOR_PLAN.md
├── GCG_TESTING_PRINCIPLES.md
├── REVIEW_SPEC.md
├── skills_py/
│   ├── gcg_agent_server.py
│   ├── gcg_runtime.py
│   ├── ai_adapters.py
│   ├── ai_player.py
│   ├── game_engine.py
│   ├── game_state.py
│   ├── gcg_display.py
│   ├── gcg_display_templates.yaml
│   └── card_db.py
├── tests/
│   ├── gcg_direction_harness.py
│   └── gcg_ai_vs_ai_replay_harness.py
├── card/
│   ├── gcgdecks.json
│   └── data/
├── game-states/
│   └── <game_id>/
│       ├── gameState.md
│       ├── gameplay.yaml
│       ├── replay.md
│       └── ai_sessions/
└── .opencode/
    ├── agents/
    └── skills/gcg/
```

## Development Rules

1. 玩家入口是 chat，runtime CLI 是內部介面。
2. 不要讓玩家或 AI 直接讀 `gameState.md`。
3. State mutation 只能經過 runtime / `game_engine.py`。
4. AI 決策主路徑只走 agent-server；不要新增每次 spawn CLI 的主路徑。
5. 回覆玩家時輸出完整 display text，不自行重排。
6. 不提交 `.DS_Store`、`__pycache__/`、`*.pyc`、`.opencode/node_modules/`。
