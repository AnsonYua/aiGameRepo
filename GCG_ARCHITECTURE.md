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
Python 是狀態安全層、基礎規則層、唯一寫入者。
LLM 是語意解析層、效果解釋層、策略層。
```

本專案中，Python 是裁判、狀態安全檢查員與記錄員；LLM 是玩家、自然語言 adapter、效果語意 reviewer、顧問或旁白。LLM 可以把自然語言或複雜卡牌效果轉成 proposed command / proposed state_diff，但 proposed output 不能直接修改 game state。

所有 proposed command / proposed state_diff 必須回到 Python，由 runtime / engine 做 schema、hidden-info、zone/card count、resource、phase、priority 等基礎安全檢查，再由 Python apply 與寫入 `gameState.md`、`gameplay.yaml`、`replay.md`。

實作分界：

- 放 Python：state mutation、base rule validation、phase/priority、card cost/level/AP/HP、combat resolution、randomness、hidden-info filtering、viewer display、gameplay log/replay、proposed diff validator/applier、regression tests。
- 放 LLM：AI 玩家決策、自然語言意圖翻譯、複雜卡牌效果語意解析、proposed state_diff 產生、策略排序、文件/程式 review、replay 摘要。
- 不可交給 LLM：直接寫 state、直接寫 replay canonical event、繞過 Python validator 決定勝負、讀取或暴露 hidden information。

## Responsibility Model

| Layer | File / Agent | Responsibility |
|---|---|---|
| Chat adapter | Codex / `.opencode/agents/gcg-orchestrator.md` | 將玩家 chat 轉成 runtime 呼叫；可把自然語言翻譯成 proposed command；不判斷最終合法性、不寫 state。 |
| Runtime boundary | `skills_py/gcg_runtime.py` | 唯一 chat-facing CLI；讀取指定 game、套用 command、觸發 AI auto、寫入 display/replay/log。 |
| Rules engine | `skills_py/game_engine.py` | 基礎規則與 state mutation：抽牌、資源、出牌、攻擊、pass、勝負與 zone 移動。 |
| State model | `skills_py/game_state.py` | GameState / PlayerState / BattleSlot / BaseState 資料結構與 serialization。 |
| Display | `skills_py/gcg_display.py` | 依 viewer 產生完整可見狀態；只顯示合法可見資訊。 |
| Gameplay log | `skills_py/gameplay_log.py` | `gameplay.yaml` 與 `replay.md` 的 canonical public-safe 記錄。 |
| Card DB | `skills_py/card_db.py` | 卡片資料讀取、摘要與效果 metadata；不直接 mutate state。 |
| AI player | `.opencode/agents/gcg-ai-player.md` via `skills_py/ai_player.py` adapter | AI 策略只寫在 agent prompt；Python adapter 只負責送入 viewer display、解析 `CONSIDER` / `COMMAND`、交回 runtime 驗證。 |
| Effect reviewer | `.opencode/agents/gcg-judge.md` / `.opencode/skills/gcg/*.md` | 複雜效果語意解析與 proposed state_diff reviewer；不是最終 state applier。 |
| Legacy debug | `gcg_simulation.py` | 舊 debug CLI；正式路徑以 runtime 為準。 |

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
| `skills_py/ai_player.py` | `gcg-ai-player.md` 的薄 adapter；不包含 Python 策略 fallback |
| `.opencode/agents/*.md` | opencode adapter / AI prompt / judge prompt 參考 |
| `.opencode/skills/gcg/*.md` | 規則與 state_diff 參考，非 Codex 必需執行依賴 |
| `gcg_simulation.py` | legacy/debug CLI，暫時保留 |

## Viewer Rules

- 任一玩家需要決策時，必須先呼叫 `gcg_display.py --viewer <player>` 或 runtime 等效命令。
- P1 viewer 顯示 P1 手牌完整內容，P2 手牌只顯示張數。
- P2 viewer 顯示 P2 手牌完整內容，P1 手牌只顯示張數。
- 戰鬥區是公開區域，對手場上單位不遮罩。

## Opencode Compatibility

opencode 可以繼續使用 `.opencode/agents/gcg-orchestrator.md` 作為 chat adapter 說明，但 chat 狀態變更仍以 runtime 為唯一入口：

```bash
python3 skills_py/gcg_runtime.py <subcommand> ...
```

AI 決策一律透過 `gcg-ai-player`，包含 P2 auto、P1 auto、AI-vs-AI：

```bash
opencode run --agent gcg-ai-player "<完整 P2 viewer status text>"
```

## Codex Compatibility

Codex adapter 直接呼叫 runtime。需要 AI 決策時，runtime 透過 `skills_py/ai_player.py` 呼叫 `opencode run --agent gcg-ai-player`；不得在 Python 補一套策略。

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
