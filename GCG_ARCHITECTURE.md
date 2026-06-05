# GCG 鋼彈卡牌遊戲 — 系統架構

## Overview

本專案採用 chat-first 架構。玩家在 Codex 或 opencode chat 中輸入指令；adapter 在背後呼叫 Python runtime；runtime 負責讀寫 state、套用遊戲行為、產生完整顯示文字。

```text
玩家 chat
  -> Codex / opencode adapter
  -> skills_py/gcg_runtime.py
  -> skills_py/game_engine.py
  -> game-states/<game_id>/gameState.md
  -> skills_py/gcg_display.py --viewer P1|P2
  -> chat 完整狀態回覆
```

`gameState.md` 是內部 state source。玩家與 AI Player 不直接讀取它；所有決策前都先產生該玩家視角的完整可見狀態。

## Python / LLM Boundary

核心原則：

```text
Python 負責真相、規則、狀態與驗證。
LLM 負責語言、策略、解釋與建議。
```

本專案中，Python 是裁判與記錄員；LLM 是玩家、顧問、旁白或 reviewer。任何會改變遊戲狀態、判定合法性、決定勝負、抽牌洗牌、支付費用、造成傷害、更新 replay/gameplay log、或過濾 hidden information 的工作，都必須由 Python runtime / engine / display / log 層執行。

LLM 可以提出單行 command、解釋局面、產生策略建議、整理 replay、或協助 review code。但 LLM 輸出只能被視為提案，不能直接成為 game state、state diff、裁判結果、或 canonical replay event。所有 LLM 產生的 command 都必須回到 `skills_py/gcg_runtime.py`，由 Python 驗證與套用。

實作分界：

- 放 Python：state mutation、legal move validation、phase/priority、card cost/level/AP/HP、combat resolution、randomness、hidden-info filtering、viewer display、gameplay log/replay、regression tests。
- 放 LLM：AI 玩家決策、策略排序、自然語言解釋、玩家指令意圖輔助、文件/程式 review、replay 摘要。
- 不可交給 LLM：是否合法、狀態如何改、誰贏誰輸、抽到哪張牌、對手隱藏牌資訊、canonical event sequence。

## Runtime Boundary

`skills_py/gcg_runtime.py` 是 opencode 與 Codex 共用的穩定介面：

```bash
python3 skills_py/gcg_runtime.py start --viewer P1
python3 skills_py/gcg_runtime.py start --viewer P1 --first-player P1  # 測試用固定先手
python3 skills_py/gcg_runtime.py status --viewer P1
python3 skills_py/gcg_runtime.py status --viewer P2
python3 skills_py/gcg_runtime.py mulligan --player P1 --action keep --viewer P1
python3 skills_py/gcg_runtime.py command --player P1 --cmd "pass" --viewer P1
python3 skills_py/gcg_runtime.py auto --player P2 --viewer P1
```

Runtime 只回傳最終 display text；`--json` 可供 adapter 測試與工具整合。

`.gcg_active_game` 適合單一 chat session。並行測試或多 agent 驗證應從 `start --json` 取得 `game_id`，再對 `status` / `mulligan` / `command` / `auto` 加上 `--game-id <game_id>`，避免共享 active game 被其他流程切換。

## Components

| Component | Role |
|---|---|
| `skills_py/gcg_runtime.py` | Chat adapter 內部 CLI；統一 start/status/mulligan/command/auto |
| `skills_py/game_engine.py` | 唯一 state mutation 層 |
| `skills_py/game_state.py` | 資料結構：BaseState（EX-BASE 預設 AP:0 / HP:3）、BattleSlot、PlayerState、GameState |
| `skills_py/gcg_display.py` | 顯示層；用 `--viewer P1/P2` 套用視角與隱私 |
| `skills_py/ai_player.py` | 目前預設 P2 自動決策器 |
| `.opencode/agents/*.md` | opencode adapter / AI prompt / judge prompt 參考 |
| `.opencode/skills/gcg/*.md` | 規則與 state_diff 參考，非 Codex 必需執行依賴 |
| `gcg_simulation.py` | legacy/debug CLI，暫時保留 |

## Viewer Rules

- 任一玩家需要決策時，必須先呼叫 `gcg_display.py --viewer <player>` 或 runtime 等效命令。
- P1 viewer 顯示 P1 手牌完整內容，P2 手牌只顯示張數。
- P2 viewer 顯示 P2 手牌完整內容，P1 手牌只顯示張數。
- 戰鬥區是公開區域，對手場上單位不遮罩。

## Opencode Compatibility

opencode 可以繼續使用 `.opencode/agents/gcg-orchestrator.md` 作為 chat adapter 說明，但不應把 `@` 或 `task` spawn 視為唯一執行路徑。可用 runtime fallback：

```bash
python3 skills_py/gcg_runtime.py <subcommand> ...
```

`gcg-ai-player` 仍可用 opencode CLI 驗證：

```bash
opencode run --agent gcg-ai-player "<完整 P2 viewer status text>"
```

## Codex Compatibility

Codex adapter 直接呼叫 runtime，不依賴 opencode spawn。若未來使用 Codex subagent，subagent 只做決策驗證或回單行 command，不直接修改 state。

## File Layout

```text
cardAI/
├── README.md
├── GCG_ARCHITECTURE.md
├── opencode.json
├── gcg_simulation.py
├── skills_py/
│   ├── gcg_runtime.py
│   ├── game_engine.py
│   ├── game_state.py
│   ├── gcg_display.py
│   ├── gcg_display_templates.yaml
│   ├── ai_player.py
│   └── card_db.py
├── card/
│   ├── gcgdecks.json
│   └── data/
├── game-states/
│   └── <game_id>/gameState.md
└── .opencode/
    ├── agents/
    ├── skills/gcg/
    └── tests/
```

## Development Rules

1. 玩家入口是 chat，CLI 是內部介面。
2. 不要讓玩家或 AI 直接讀 `gameState.md`。
3. State mutation 只能經過 runtime / `game_engine.py`。
4. 回覆玩家時輸出完整 display text，不自行重排。
5. 不提交 `.DS_Store`、`__pycache__/`、`*.pyc`。
