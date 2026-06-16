# Human vs AI Mobile Battle 需求文件

## 目標

在 `reviewboard` 專案中新增 `/mobile/battle`，提供手機優先的人類 P1 對 AI P2 對戰介面。此功能應重用既有 GCG V2 runtime、合法指令枚舉、viewer-safe state 與 AI player，不把前端或 Python UI server 變成新的規則引擎。

## 範圍

- 新增手機對戰入口：`/mobile/battle`
- 固定支援 P1 人類玩家操作，P2 由 Hermes AI 自動決策。
- 前端顯示 P1 可見狀態、合法操作、最新事件與遊戲結果。
- 後端負責建立對局、推進 runtime、處理 P1 指令、呼叫 P2 AI。
- 所有狀態變更必須走既有 runtime。
- 第一版只支援本機單一 in-memory session，不做多房間。

## 非目標

- 不修改卡牌規則判定邏輯。
- 不在前端推導合法動作。
- 不在 Python server 新增策略 fallback。
- 不用 `run_simulator.py` 一次跑完整局來驅動互動 UI。
- 第一版不要求拖拉操作；先用合法指令按鈕完成可玩流程。
- 第一版不要求帳號、多人連線、持久化 session 管理。
- 第一版不支援切換 P1/P2 角色；P1 永遠是人類，P2 永遠是 AI。

## 使用者流程

1. 使用者開啟 `/mobile/battle`。
2. 點擊開始對戰。
3. 若 P1 需要選擇先後攻、調度或其他 pending choice，UI 顯示可選按鈕。
4. 若輪到 P1 行動，UI 顯示所有 `legal_commands` 對應的操作按鈕。
5. 使用者點選操作後，前端送出原始 command。
6. 後端驗證 command 是否在合法清單中，呼叫 runtime resolve。
7. 若接著輪到 P2，後端呼叫 AI player 決策並 resolve，直到再次輪到 P1、遊戲結束或發生錯誤。
8. UI 更新盤面、手牌、事件訊息、合法操作與勝負結果。

## 後端需求

### Session

- 每個 battle session 應包含：
  - `game_id`
  - `state_store`
  - `runtime`
  - `action_enumerator`
  - `viewer_builder`
  - `command_parser`
  - P2 AI player client
  - gameplay logger / trace writer
- 第一版可以使用單一 in-memory session。
- 若 server 重啟，第一版可允許 session 消失。
- 不需要新增資料庫或檔案式 session registry。

### API

#### `POST /api/battle/start`

建立新對局並回傳 P1 viewer-safe 狀態。

Response 欄位：

- `ok`
- `game_id`
- `viewer_state`
- `legal_commands`
- `events`
- `message`
- `game_over`
- `winner`

#### `GET /api/battle/state`

回傳目前 P1 viewer-safe 狀態。

Response 欄位同 `start`。

#### `POST /api/battle/command`

提交 P1 指令。

Request：

```json
{
  "command": "choose keep"
}
```

後端必須：

- 確認目前決策玩家是 P1。
- 確認 command 正規化後存在於 `legal_commands`。
- 用 `CommandParser` parse。
- 若是 pending choice，呼叫 `runtime.resolve_pending_choice`。
- 否則呼叫 `runtime.resolve_command`。
- resolve 後自動處理 P2 AI 決策，直到輪到 P1 或遊戲結束。

#### `POST /api/battle/reset`

可選。清除目前 session 並建立新局。

## AI 需求

- P2 使用既有 Hermes AI player client。
- 第一版 runtime UI 預設 AI mode 固定為 `hermes`。
- 測試可以使用 `scripted/reference` 作為離線 harness，但產品路徑不可把 scripted 當 fallback。
- AI 只能收到 viewer-safe prompt。
- AI 輸出的 command 必須驗證在合法清單中。
- 不新增 Python 策略 fallback。
- 不用多次 retry 掩蓋 AI 問題；若 AI 回覆不合法，回傳明確錯誤分類與事件。
- Hermes timeout 第一版建議維持 60 秒；逾時時應回傳清楚錯誤，不讓 UI 無限等待。

## 前端需求

### 路由

- `/mobile/battle` 載入 battle UI。
- 既有 `/` 與 `/mobile` replay review 行為不應被破壞。

### 畫面

手機優先，需包含：

- 對手區：
  - 手牌張數
  - 牌庫張數
  - 資源
  - 盾牌張數
  - 基地
  - 戰鬥區
  - 廢棄區張數
- 我方區：
  - 可見手牌
  - 牌庫張數
  - 資源
  - 盾牌張數
  - 基地
  - 戰鬥區
  - 廢棄區
- 狀態列：
  - 回合
  - 階段
  - 當前優先權
  - 最新事件訊息
- 操作列：
  - pending choice options
  - legal command buttons
  - 等待 AI 狀態
  - 錯誤訊息

### 操作

- 第一版以按鈕提交 command。
- 按鈕文字必須把 raw command 轉成較易懂的繁體中文，但送出值必須保留原始 command。
- 中文操作文字應接近 AI vs AI replay / runtime 的既有繁體中文用語。
- 當後端正在處理 AI 決策時，操作按鈕應 disabled。
- 若後端回傳錯誤，UI 顯示錯誤且不自行改盤面。

### 中文操作文字

API 建議回傳 `legal_actions`，每個 action 同時包含原始 command 與中文 label：

```json
{
  "command": "attack my_slot_0 opponent_base",
  "label": "以 1 號位直接攻擊對手"
}
```

最小 mapping：

- `choose go_first` -> `選擇先攻`
- `choose go_second` -> `選擇後攻`
- `choose keep` -> `保留起手牌`
- `choose redraw` -> `重新調度`
- `play_card <card> <slot>` -> `部署 <card> 到 <slot+1> 號位`
- `play_card <card>` -> `使用 <card>`
- `pair <card> my_slot_<n>` -> `將 <card> 配對到 <n+1> 號位`
- `attack my_slot_<n> opponent_base` -> `以 <n+1> 號位直接攻擊對手`
- `attack my_slot_<n> opponent_slot_<m>` -> `以 <n+1> 號位攻擊對手 <m+1> 號位`
- `block my_slot_<n>` -> `以 <n+1> 號位阻擋`
- `activate_effect base` -> `發動基地能力`
- `pass` -> `讓過`

## 資料安全需求

- API 不得回傳 P2 hidden hand card id。
- API 不得回傳任何 deck card id。
- API 不得回傳 shield card id。
- replay/debug 檔案不得被前端 battle API 直接暴露為 raw state。
- 前端渲染必須以 P1 viewer-safe state 為資料來源。

## Runtime 整合需求

- 合法指令來源：
  - pending choice：`ActionEnumerator.pending_choice_commands`
  - action window：`ActionEnumerator.legal_commands`
- 可見狀態來源：
  - `ViewerStateBuilder.build_for_player(state, "P1")`
- 指令解析：
  - `CommandParser.parse(command, "P1")`
- 狀態推進：
  - `runtime.advance_until_decision_or_stable`
  - `runtime.resolve_pending_choice`
  - `runtime.resolve_command`

## 建議新增檔案

- `humanVsAI/battle_session.py`
  - 單一 human vs Hermes AI session wrapper。
  - 負責 start/state/command/reset。
  - 負責自動推進 P2 Hermes 決策直到回到 P1 或 game over。
- `humanVsAI/command_labels.py`
  - 將合法 command 轉成繁體中文 label。
  - 不做合法性判斷，不改 command。
- `mobile/battle/index.html`
  - `/mobile/battle` 頁面。
- `mobile/battle/battle.js`
  - 呼叫 battle API、render viewer state、送出 command。
- `mobile/battle/battle.css`
  - 手機優先 layout。

## 原則上不應修改的檔案

以下檔案是規則、合法性、viewer safety 或既有 replay 行為的核心。第一版 human vs AI UI 原則上不應修改；若真的需要動，必須先在 PR / review 中說明原因與回歸風險。

- `/Users/hello/Desktop/cardAI/gcgV2/gcg/sim/bootstrap.py`
  - `build_simulator` 組裝邏輯應保持不變；battle session 可以呼叫它或參考其 wiring，但不修改它。
- `/Users/hello/Desktop/cardAI/gcgV2/gcg/sim/runner.py`
  - `SimulatorRunner.run()` 留給 AI-vs-AI 一次跑完整局；human-vs-AI 不應改它，也不應把它變成 UI driver。
- `/Users/hello/Desktop/cardAI/gcgV2/gcg/engine/runtime.py`
  - 唯一 state mutator，不應為 UI 加特殊規則。
- `/Users/hello/Desktop/cardAI/gcgV2/gcg/engine/action_enumerator.py`
  - 合法指令來源，不應為 UI 加策略偏好或 fallback。
- `/Users/hello/Desktop/cardAI/gcgV2/gcg/engine/viewer.py`
  - viewer-safe state 邊界，不應放寬 hidden information。
- `/Users/hello/Desktop/cardAI/gcgV2/gcg/engine/command_parser.py`
  - command grammar contract，不應為 UI label 改 grammar。
- `/Users/hello/Desktop/cardAI/gcgV2/gcg/effects/*`
  - 卡牌效果解讀與執行，不應為 mobile UI 改效果邏輯。
- `/Users/hello/Desktop/cardAI/gcgV2/gcg/cards.py`
  - 卡牌資料載入，不應為 UI 加特殊 card mapping。
- `/Users/hello/Desktop/cardAI/gcgV2/run_simulator.py`
  - AI vs AI batch simulator 入口，不應改成 live UI driver。
- `/Users/hello/Desktop/cardAI/gcgV2/reviewboard/app.js`
  - 既有 replay review UI；除非抽共用 renderer，否則不應破壞 replay 流程。
- `/Users/hello/Desktop/cardAI/gcgV2/reviewboard/styles.css`
  - 既有 replay review CSS；新增 battle CSS 應盡量獨立。
- `/Users/hello/Desktop/cardAI/gcgV2/reviewboard/index.html`
  - 既有 replay review HTML；`/mobile/battle` 應使用獨立頁面。

### 紅線摘要

第一版 human-vs-AI battle 實作時，以下 12 類檔案視為紅線，不修改：

| 檔案 | 原因 |
| --- | --- |
| `gcg/sim/bootstrap.py` | `build_simulator` 組裝邏輯，不動 |
| `gcg/sim/runner.py` | `SimulatorRunner.run()` 留給 AI-vs-AI |
| `gcg/engine/runtime.py` | 唯一 state mutator |
| `gcg/engine/action_enumerator.py` | 合法指令來源 |
| `gcg/engine/viewer.py` | viewer-safe 邊界 |
| `gcg/engine/command_parser.py` | grammar contract |
| `gcg/effects/*` | 效果解讀與執行 |
| `gcg/cards.py` | 卡牌資料 |
| `run_simulator.py` | AI-vs-AI 入口 |
| `reviewboard/app.js` | 既有 replay 前端 |
| `reviewboard/index.html` | 既有 replay 頁面 |
| `reviewboard/styles.css` | 既有 replay CSS |

唯一可修改的既有檔案：

| 檔案 | 允許改動 |
| --- | --- |
| `reviewboard/server.py` | 只新增 battle API route、`/mobile/battle` 靜態檔 route、JSON helper；不得刪改既有 replay route 行為 |

要新建的檔案：

| 檔案 | 說明 |
| --- | --- |
| `humanVsAI/battle_session.py` | 單一 in-memory BattleSession，包 step-by-step loop |
| `humanVsAI/command_labels.py` | raw command -> 繁體中文 label |
| `mobile/battle/index.html` | battle 獨立頁面 |
| `mobile/battle/battle.js` | battle 前端 state model、API、render |
| `mobile/battle/battle.css` | battle 專用 CSS，class 全部使用 `battle-` prefix |

## 必須保留的 Harness / 回歸檢查

實作 human vs AI mobile battle 時，不能刪除、弱化或繞過以下既有 harness。若相關檢查失敗，應分類 root cause，而不是調高上限或加入策略 fallback 讓它表面通過。

### GCG V2 基本檢查

```bash
cd /Users/hello/Desktop/cardAI/gcgV2
python3 -m py_compile run_simulator.py gcg/engine/runtime.py gcg/engine/action_enumerator.py gcg/engine/viewer.py gcg/engine/command_parser.py
python3 -m pytest tests/test_parser_and_gate.py tests/test_effect_flows.py tests/test_full_game.py tests/test_hermes_player_client.py
```

### Simulator smoke test

```bash
cd /Users/hello/Desktop/cardAI/gcgV2
python3 run_simulator.py --players scripted --interpreter reference --max-steps 80 --seed 1
```

### Reviewboard 檢查

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/reviewboard
python3 -m py_compile server.py humanVsAI/battle_session.py humanVsAI/command_labels.py
python3 server.py --host 127.0.0.1 --port 5178
```

人工檢查：

- `http://127.0.0.1:5178/` replay review 仍可載入。
- `http://127.0.0.1:5178/mobile` replay mobile view 仍可載入。
- `http://127.0.0.1:5178/mobile/battle` human vs AI battle 可載入。

### Human vs AI 新增 harness

建議新增一個離線測試檔：

```text
/Users/hello/Desktop/cardAI/gcgV2/reviewboard/tests/test_human_vs_ai_battle.py
```

測試應使用 `scripted/reference` 或可注入 fake Hermes client，不打真 provider：

- start battle 會建立 `game_id`。
- state response 使用 P1 viewer-safe state。
- P2 hidden hand / deck / shield card id 不出現在 response。
- 不合法 command 會被拒絕。
- 合法 P1 command 會被 resolve。
- P2 自動決策 loop 會停在下一個 P1 決策點或 game over。
- `legal_actions[].label` 是繁體中文，`legal_actions[].command` 保留 raw command。

## 驗收標準

- 開啟 `/mobile/battle` 可以開始一局新遊戲。
- P1 可以完成先後攻選擇與調度。
- P2 可以自動完成自己的選擇與行動。
- P1 在主要階段可以看到合法行動並成功送出至少一個 `play_card` 或 `pass`。
- 攻擊、阻擋、Action Step 的合法行動會依 runtime 狀態顯示。
- 遊戲結束時 UI 顯示 winner。
- API response 不包含 P2 hidden hand card id、deck card id 或 shield card id。
- 既有 replay review `/` 與 `/mobile` 仍可正常使用。

## 測試需求

- Python compile：
  - `python3 -m py_compile server.py`
  - 視實作範圍加入相關 `gcgV2/gcg/**/*.py`
- 後端單元或整合測試：
  - start battle 回傳 `game_id`
  - state 回傳 P1 viewer-safe state
  - command 拒絕不在 `legal_commands` 的指令
  - command 接受合法 P1 指令並推進狀態
  - P2 AI/scripted 可自動行動到下一個 P1 決策點
- 前端驗證：
  - 手機 viewport 可載入 `/mobile/battle`
  - 無 console error
  - 按鈕文字不溢出
  - 等待 AI 時按鈕 disabled

## 建議實作順序

1. 新增 battle session 後端 wrapper。
2. 新增 `/api/battle/start` 與 `/api/battle/state`。
3. 新增 `/api/battle/command`，先用 `scripted/reference` 驗證流程。
4. 新增 `/mobile/battle` HTML/JS/CSS。
5. 接上 `hermes` 或 `llm` AI mode。
6. 加上資料安全測試。
7. 做手機瀏覽器驗證與 replay route 回歸檢查。

## `/mobile` 前端整合計畫

### 現況

目前 `reviewboard` 的前端是 replay review UI：

- `/` 載入 `index.html`
- `/mobile` 也載入 `index.html`
- `app.js` 透過 `window.location.pathname === "/mobile"` 切換 mobile replay class
- `app.js` 從 `/api/replay` 讀取 `gamePlay.yaml`
- 前端 state 是 replay event index：
  - `state.replay`
  - `state.events`
  - `state.index`

這代表 `/mobile` 現在不是 live battle，而是 replay 的 mobile layout。`/mobile/battle` 應新增為獨立 live battle route，不應取代 `/mobile`。

### 路由整合

`server.py` 的路由建議調整為：

```text
/              -> /index.html        # 既有 replay desktop
/mobile        -> /index.html        # 既有 replay mobile
/mobile/battle -> /mobile/battle/index.html
```

API 路由分離：

```text
/api/replay          # 既有 replay API
/api/battle/start    # live battle
/api/battle/state    # live battle
/api/battle/command  # live battle
/api/battle/reset    # live battle
```

此切分可以避免 replay UI 和 battle UI 共用同一組 frontend state，降低回歸風險。

實作注意：

- `GET /api/battle/state` 與 `GET /mobile/battle` 要在 `do_GET` 分流。
- `POST /api/battle/start`、`POST /api/battle/command`、`POST /api/battle/reset` 要在 `do_POST` 分流。
- `server.py` 不應新增遊戲規則判斷，只負責 HTTP routing 與 JSON request/response。

### 檔案整合策略

第一版建議使用獨立 battle frontend：

```text
mobile/battle/index.html
mobile/battle/battle.js
mobile/battle/battle.css
```

不要第一版就大幅重構既有 `app.js` / `styles.css`。原因：

- `app.js` 是 replay event timeline 模型，battle 是 live viewer state 模型。
- replay 需要 `Previous / Next / Slider / Timeline`。
- battle 需要 `Start / legal action buttons / waiting AI / command errors`。
- 兩者生命週期不同，硬塞同一檔會讓 state 分支複雜。

第一版可以少量複製 card render helper；等 battle UI 穩定後，再評估抽共用 renderer。

### 共用 renderer 的第二階段計畫

若第一版驗證通過，可在第二階段抽出共用 render helper：

```text
shared/board_render.js
shared/card_assets.js
```

可抽出的 helper：

- `imageFor(cardId)`
- `imageCard(cardId, className)`
- `cardBack(className)`
- `renderResources(playerId, player)`
- `renderBase(playerId, player)`
- `renderShields(playerId, player)`
- `renderSlots(playerId, player)`

不建議第一版抽出的內容：

- replay timeline render
- replay event index state
- battle legal action render
- battle API client

### Battle frontend state model

`battle.js` 應使用 live state，而不是 replay events：

```js
const state = {
  gameId: null,
  viewerState: null,
  legalActions: [],
  events: [],
  busy: false,
  error: null,
};
```

主要流程：

```js
async function startBattle() {
  state.busy = true;
  const payload = await postJson("/api/battle/start", {});
  applyPayload(payload);
}

async function refreshBattle() {
  const payload = await fetchJson("/api/battle/state");
  applyPayload(payload);
}

async function submitCommand(command) {
  state.busy = true;
  render();
  const payload = await postJson("/api/battle/command", { command });
  applyPayload(payload);
}
```

### 等待 Hermes AI 的整合方式

Hermes 決策可能需要數十秒。若 UI 要顯示「對手思考中...」並每 1.5 秒 poll `GET /api/battle/state`，後端必須採用背景 worker 模式，而不是讓 `POST /api/battle/command` 一直阻塞到 Hermes 回來。

第一版最終採用：

- P1 送出 command 後，`POST /api/battle/command` 只 resolve P1 command，若下一個 actor 是 P2，啟動 background AI worker，立即回傳 `status: "waiting_ai"`。
- background AI worker 絕對不能在呼叫 Hermes 時持有 session lock，否則前端 polling 會被 Hermes latency 卡住。
- worker 正確 lock 節奏：
  - 持 lock：`advance_until_decision_or_stable()`，確認輪到 P2，組好 `viewer_bundle`、`prompt_payload` 與 `legal_commands`。
  - 釋放 lock：呼叫 `players["P2"].decide(...)`。這裡可能卡 30-60 秒，但不得阻塞 `GET /api/battle/state`。
  - 重新持 lock：parse raw command、驗證 normalized command 在 `legal_commands` 中、resolve runtime，然後回到 loop。
- 前端收到 `waiting_ai` 後顯示 spinner 與 `對手思考中...`，每 1.5 秒呼叫 `GET /api/battle/state`。
- 當 state 回到 `waiting_human` 或 `game_over`，前端停止 polling 並顯示 legal actions 或勝負。
- 若 Hermes timeout 或回傳不合法 command，session 設為 `error`，前端顯示錯誤，不自行改盤面。

Session status 建議值：

```text
not_started
waiting_human
waiting_ai
game_over
error
```

背景 worker 注意事項：

- 使用單一 in-memory session lock，避免 P1 連點造成 state race。
- `waiting_ai` 時拒絕新的 P1 command。
- AI worker 不做策略 fallback。
- AI worker 不修改 frontend 檔案、不讀 raw hidden state，只走 viewer-safe prompt。

### V1 邊緣情境決策

- Page refresh：V1 可接受回到 Screen 0。BattleSession 是單一 in-memory session，不保證瀏覽器重新整理後恢復同一局。
- AI timeout / 非法指令：採用方案 A。UI 顯示紅色錯誤訊息 `AI 決策失敗，請重新開始`，不做 rollback，也不提供 `重試當前回合`。
- 若前端在 `waiting_ai` 時被繞過送 command，後端必須 reject，不能排隊執行。

`applyPayload` 只接受後端狀態，不在前端預先改盤面：

```js
function applyPayload(payload) {
  state.gameId = payload.game_id;
  state.viewerState = payload.viewer_state;
  state.legalActions = payload.legal_actions || [];
  state.events = payload.events || [];
  state.error = payload.error || null;
  state.busy = false;
  render();
}
```

### Viewer state 到 UI 的 mapping

Battle UI 的資料來源應是：

```text
payload.viewer_state.players.P1
payload.viewer_state.players.P2
```

注意 `ViewerStateBuilder` 目前使用大寫 player key：`P1` / `P2`。既有 replay `app.js` 使用小寫 `p1` / `p2` 的 `features`。因此 battle frontend 不應直接重用 replay event render function，除非先做 adapter。

建議新增 adapter：

```js
function playerBlock(viewerState, playerId) {
  return viewerState?.players?.[playerId] || {};
}
```

Battle slot 欄位來源是：

```text
player.battle_area
```

Replay slot 欄位目前是：

```text
player.board.slots
```

所以若要複用 `renderSlots`，需要 adapter：

```js
function adaptBattlePlayer(player) {
  return {
    ...player,
    board: { slots: player.battle_area || [] },
    shields: player.shield_count,
  };
}
```

### Battle UI layout

手機版建議使用同一個視覺語言，但不要完整複製 replay timeline：

```text
[對手摘要]
[對手戰鬥區]
[戰鬥訊息 / 最新事件]
[我方戰鬥區]
[我方手牌]
[操作列 legal actions]
```

操作列固定在底部：

- `開始對戰`
- pending choice buttons
- legal action buttons
- `等待 AI...`
- `重新開始`

按鈕文字使用後端 `legal_actions[].label`。

### `/mobile` 與 `/mobile/battle` 的 CSS 關係

第一版建議：

- `styles.css` 繼續服務 replay。
- `mobile/battle/battle.css` 服務 battle。
- battle CSS class 全部加 `battle-` prefix，例如：
  - `.battle-app`
  - `.battle-board`
  - `.battle-actions`
  - `.battle-card`

避免和 replay CSS 的 `.board`、`.slot`、`.controls` 等 class 互相污染。

### Browser 驗證計畫

實作後要用手機與桌面 viewport 檢查：

Desktop：

```text
http://127.0.0.1:5178/
http://127.0.0.1:5178/mobile
http://127.0.0.1:5178/mobile/battle
```

Mobile viewport：

```text
390x844
430x932
```

檢查項目：

- `/mobile` replay view 仍可操作 previous/next/slider。
- `/mobile/battle` 可以開始對戰。
- AI 決策中有 loading / disabled 狀態。
- legal action 中文按鈕不溢出。
- 我方手牌圖可點擊或至少可清楚辨識。
- 對手 hidden hand 只顯示張數或背面。
- 沒有 console error。

### 前端整合風險

- Replay `features.p1/p2` 與 live `viewer_state.players.P1/P2` schema 不同，直接重用 render function 會出錯。
- replay UI 有 timeline slider，battle UI 沒有 event index；兩者不應共用同一個 global `state`。
- 既有 CSS class 名稱很通用，例如 `.board`、`.slot`、`.controls`，battle CSS 若不用 prefix 容易互相影響。
- Hermes AI latency 會讓 button click 等待較久；前端必須有 busy 狀態。
- 後端處理 P2 AI 時可能 timeout；前端必須顯示錯誤，不能假裝 command 成功。

### 前端完成定義

- `/mobile` replay 行為不變。
- `/mobile/battle` 不依賴 replay `gamePlay.yaml`。
- `/mobile/battle` 所有盤面資料都來自 battle API 的 P1 viewer-safe state。
- 所有操作按鈕都由 `legal_actions` 產生。
- 前端不自行組合 runtime command，除了提交後端給的 `command`。
- 前端不根據卡牌資訊自行判斷可否攻擊、部署、阻擋或使用效果。

## 最終 Implementation Plan

### Phase 0：保護邊界

1. 確認目前分支是 `codex/mobile-human-vs-ai-plan`。
2. 確認紅線檔案沒有 staged / modified。
3. 實作過程只允許修改 `reviewboard/server.py`，其餘程式碼一律新增檔案。
4. 不修改既有 `/` 與 `/mobile` replay UI。

### Phase 1：後端 BattleSession

新增：

```text
humanVsAI/battle_session.py
humanVsAI/command_labels.py
```

`battle_session.py` 負責：

- 建立單一 in-memory session。
- 呼叫既有 wiring 建立 runtime stack。
- 固定 P1 human、P2 Hermes。
- `start()`：建立 game，推進到 P1 或 P2 決策；若是 P2，啟動 background AI worker。
- `state()`：回傳目前 P1 viewer-safe state。
- `submit_command(command)`：只接受 P1 當前合法 command。
- `reset()`：清掉舊 session 並建立新 session。
- AI worker：自動跑 P2 Hermes，直到回到 P1、game over 或 error。

`command_labels.py` 負責：

- 將 raw legal command 轉成繁體中文 label。
- 回傳 `legal_actions = [{"command": raw, "label": zh}]`。
- 不做合法性判斷。
- 不改 raw command。

### Phase 2：server.py 路由

只修改：

```text
reviewboard/server.py
```

新增 `do_GET` 分流：

```text
GET /mobile/battle
GET /api/battle/state
```

新增 `do_POST` 分流：

```text
POST /api/battle/start
POST /api/battle/command
POST /api/battle/reset
```

保留既有行為：

```text
GET /
GET /mobile
GET /api/replay
```

`server.py` 只做：

- parse JSON body
- 呼叫 BattleSession
- 回傳 JSON
- static file route

`server.py` 不做：

- runtime command legality 判斷
- AI prompt building
- 策略判斷
- hidden state inspection

### Phase 3：前端 battle 頁面

新增：

```text
mobile/battle/index.html
mobile/battle/battle.js
mobile/battle/battle.css
```

`index.html`：

- 獨立 battle 頁面。
- 不引用 `app.js`。
- 不引用 `styles.css`，除非只引用 reset 類基礎樣式；第一版建議完全獨立。

`battle.js`：

- 管理 live battle state。
- 呼叫 battle API。
- render P1/P2 viewer-safe board。
- render `legal_actions`。
- waiting AI 時每 1.5 秒 poll `/api/battle/state`。
- 不根據卡牌自行判斷合法動作。

`battle.css`：

- 所有 class 使用 `battle-` prefix。
- 手機優先。
- 不覆蓋 replay `.board`、`.slot`、`.controls`。

### Phase 4：玩家互動畫面

實作以下 screen：

1. Screen 0：開始畫面
   - 顯示 `開始對戰`
   - click -> `POST /api/battle/start`
2. Screen 1：先後攻 pending choice
   - 顯示 `選擇先攻`、`選擇後攻`
3. Screen 2：調度 pending choice
   - 顯示 P1 手牌圖
   - 顯示 `保留起手牌`、`重新調度`
4. Screen 3：等待 AI
   - 顯示 spinner
   - 顯示 `對手思考中...`
   - 每 1.5 秒 poll state
5. Screen 4：玩家行動
   - 操作面板分組：
     - 攻擊
     - 部署
     - 配對
     - 使用
     - 阻擋
     - 能力
   - 底部固定 `讓過`
   - 部署操作可顯示卡牌縮圖與目標欄位
   - 點擊手牌可以捲動到相關 action 區塊，但不自行產生命令
6. Screen 5：遊戲結束
   - 顯示勝負
   - 顯示 `再來一局`

### Phase 5：測試與驗證

先跑靜態檢查：

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/reviewboard
python3 -m py_compile server.py humanVsAI/battle_session.py humanVsAI/command_labels.py
```

再跑 GCG V2 回歸：

```bash
cd /Users/hello/Desktop/cardAI/gcgV2
python3 -m py_compile run_simulator.py gcg/engine/runtime.py gcg/engine/action_enumerator.py gcg/engine/viewer.py gcg/engine/command_parser.py
python3 -m pytest tests/test_parser_and_gate.py tests/test_effect_flows.py tests/test_full_game.py tests/test_hermes_player_client.py
python3 run_simulator.py --players scripted --interpreter reference --max-steps 80 --seed 1
```

啟動 reviewboard：

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/reviewboard
python3 server.py --host 127.0.0.1 --port 5178
```

瀏覽器檢查：

- `http://127.0.0.1:5178/`
- `http://127.0.0.1:5178/mobile`
- `http://127.0.0.1:5178/mobile/battle`

Mobile viewport：

- `390x844`
- `430x932`

必須確認：

- replay desktop/mobile 沒壞。
- battle 可以 start。
- P1 可以選先後攻與調度。
- P2 Hermes 進入等待狀態並可完成決策。
- legal action 中文 label 正常。
- 點 action 後盤面只根據後端 response 更新。
- P2 hidden hand / deck / shield card id 沒出現在 battle API response。
- 無 console error。

### Phase 6：完成條件

完成時必須同時滿足：

- 紅線檔案無 diff。
- 既有 replay `/` 和 `/mobile` 行為不變。
- `/mobile/battle` 可完成至少一輪 P1 command -> P2 Hermes response -> 回到 P1。
- battle API 僅回傳 viewer-safe state。
- 沒有 Python 策略 fallback。
- 沒有新增 dependency。
- 沒有保留暫時測試 game id 或 tool trace。
