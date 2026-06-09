# GCG 鋼彈卡牌遊戲 — 系統架構

## Overview

本專案採用 AI-vs-AI gameplay-log-first 架構。核心目標是讓 P1/P2 兩個 AI 玩家透過同一套 runtime 進行完整對局，並把對局過程記錄到既有結構的 `gamePlay.yaml`。Python runtime 是唯一狀態邊界；AI 決策主路徑是本機長駐 `agent-server`，背後連到 `codex app-server --stdio`。

```text
tests/gcg_ai_vs_ai_replay_harness.py
  -> skills_py/gcg_runtime.py start --json
  -> skills_py/gcg_runtime.py auto --player P1|P2 --json
  -> skills_py/game_engine.py
  -> game-states/<game_id>/gameState.md
  -> game-states/<game_id>/gamePlay.yaml
```

Notation:

- `A -> B` 表示一次 AI-vs-AI 對局的主要執行流程會從 A 走到 B，或由 A 觸發 B。
- 若 `B` 是檔案路徑，表示流程執行後會把狀態或紀錄寫到該檔案。
- 這不是 Python import 關係，也不是 shell pipe，只是高階 operational flow。

AI 決策流程：

```text
skills_py/gcg_runtime.py auto --player P1|P2
  -> skills_py/ai_player.py
  -> skills_py/ai_adapters.py
  -> local agent-server HTTP API
  -> one long-lived codex app-server process
  -> per-game role rooms
```

`gameState.md` 是內部 state source。AI Player 不直接讀取它；所有 AI 決策前都先產生該玩家視角的完整可見狀態。`gamePlay.yaml` 是 canonical structured replay log，必須沿用目前單一 YAML document 結構，至少包含 `schema_version`、`game_id`、`summary`、`events`，且事件 `seq` 必須單調遞增並保持 public-safe。

## Agent Server Rooms

每一局 `game_id` 初始化 5 個獨立 Codex rooms：

```text
game_id
  ├─ gcg-orchestrator
  ├─ gcg-judge
  ├─ gcg-memory-selector
  ├─ gcg-ai-player:P1
  └─ gcg-ai-player:P2
```

角色分工：

| Room | 用途 |
|---|---|
| `gcg-orchestrator` | 接收 public-safe action summary，保留流程上下文。 |
| `gcg-judge` | 目標是接入 `/decide` 做 LLM 語意審查；不作 state applier。 |
| `gcg-memory-selector` | 從候選 lessons 中選出本次決策相關經驗；不決定 move。 |
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
| Simulation boundary | `tests/gcg_ai_vs_ai_replay_harness.py` | AI-vs-AI 對局入口；建立 game、驅動 P1/P2 auto、檢查 `gamePlay.yaml` 與 `review.md`。 |
| Runtime boundary | `skills_py/gcg_runtime.py` | 唯一 state-facing CLI/API；start/status/mulligan/command/auto；觸發 AI auto；寫 display/replay/log。 |
| Agent server | `skills_py/gcg_agent_server.py` | 長駐 `codex app-server --stdio`；提供 `/init-game`、`/append`、`/decide`、`/health`、`/metrics`。 |
| AI adapter | `skills_py/ai_adapters.py` | agent-server-only provider；HTTP 呼叫 `/decide`、`/init-game`、`/append`。 |
| AI player boundary | `skills_py/ai_player.py` | 送入 viewer display、解析 `CONSIDER` / `COMMAND`、做 public-safe consideration filtering。 |
| Rules engine | `skills_py/game_engine.py` | 基礎規則與 state mutation：抽牌、資源、出牌、攻擊、pass、勝負與 zone 移動。 |
| State model | `skills_py/game_state.py` | GameState / PlayerState / BattleSlot / BaseState 資料結構與 serialization。 |
| Display | `skills_py/gcg_display.py` | 依 viewer 產生完整可見狀態；只顯示合法可見資訊。 |
| Gameplay log | `skills_py/gameplay_log.py` | `gamePlay.yaml` 的 canonical public-safe 記錄。 |
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
- `gcg-memory-curator` 不是每局 init room；需要整理 replay/review 時由 `/curate-memory` lazy 建立。
- Runtime 仍是最終合法性與 state mutation 邊界。

## Runtime / Simulation Boundary

`skills_py/gcg_runtime.py` 是穩定內部介面。AI-vs-AI harness 應使用 `--json` 建立 game 並驅動雙方決策：

```bash
GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py start --json --viewer P1
GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py auto --player P1 --game-id <game_id> --json --viewer P1
GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py auto --player P2 --game-id <game_id> --json --viewer P2
```

Runtime 回傳最終 display text；`--json` 供 adapter、harness 與工具整合，並必須包含本次 events、累積 all_events、`gameplay_log_path`。

`.gcg_active_game` 只適合手動 debug。AI-vs-AI replay harness 必須從 `start --json` 取得 `game_id`，再對後續命令加上 `--game-id <game_id>`，避免共享 active game 被其他流程切換。

AI-vs-AI replay harness 是主要產品路徑：

```bash
GCG_AGENT_SERVER_URL=http://127.0.0.1:8890 GCG_AI_PROVIDER=agent-server python3 tests/gcg_ai_vs_ai_replay_harness.py --ai-timeout-seconds 60
```

每場對局必須產生：

- `game-states/<game_id>/gamePlay.yaml`：canonical structured gameplay log，沿用目前 schema。
- `game-states/<game_id>/review.md`：賽後 review 與 root-cause 分類。

## Agent Server API

```text
GET  /health
GET  /metrics
POST /init-game
POST /append
POST /decide
POST /curate-memory
```

`POST /init-game` 建立 5 rooms。`POST /append` 注入 public-safe 訊息到指定 role。`POST /decide` 會 orchestrate memory-selector -> player -> judge -> repair，並回傳 judge / lesson metadata。`POST /curate-memory` 把 public-safe review/replay 文字交給 `gcg-memory-curator` 產生 draft lesson；不自動寫入 reviewed lesson。

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
│       ├── gamePlay.yaml
│       └── ai_sessions/
└── .opencode/
    ├── agents/
    └── skills/gcg/
```

## Development Rules

1. 主要入口是 AI-vs-AI replay harness；Codex chat 只保留為手動 debug 或臨時操作入口。
2. 不要讓 AI 直接讀 `gameState.md`。
3. State mutation 只能經過 runtime / `game_engine.py`。
4. AI 決策主路徑只走 agent-server；不要新增每次 spawn CLI 的主路徑。
5. AI-vs-AI 對局必須維護 `gamePlay.yaml` 與 `review.md`。
6. 不提交 `.DS_Store`、`__pycache__/`、`*.pyc`、`.opencode/node_modules/`。
