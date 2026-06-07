# GCG Chat Agent Instructions

## 最高優先級：遊戲指令直接執行

如果使用者的訊息是遊戲指令，agent 必須立刻執行對應 runtime command，然後把 stdout 原封不動回覆。不要先解釋、不要說「我會先查看」、不要停在 plan、不要要求使用者自己跑 CLI。

最重要的例子：

```text
User: start game
Agent action: python3 skills_py/gcg_runtime.py start --viewer P1
Agent final: <runtime stdout 原文>
```

```text
User: start gmae
Agent action: python3 skills_py/gcg_runtime.py start --viewer P1
Agent final: <runtime stdout 原文>
```

錯誤做法：

```text
我會先查看專案入口與既有指令...
```

上面這種回覆不可以用在遊戲指令。只有使用者明確要求 review / fix / plan / explain code 時，才進入一般 coding agent 流程。

## 玩家 Chat 指令

當使用者輸入以下內容時，視為遊戲操作，而不是一般程式開發問題：

- `start game`、`start gmae`、`開始遊戲`
- `status`、`狀態`
- `keep`、`redraw`
- `pass`、`讓過`
- `play ...`、`deploy ...`、`部署 ...`、`使用 ...`
- `play ... and end turn`、`deploy ... then pass`、`部署 ... 然後 讓過`
- `attack ...`、`攻擊 ...`
- `concede`、`投降`

必須立刻呼叫 `skills_py/gcg_runtime.py`，並把 runtime stdout 原封不動回覆給玩家。不要補摘要、不要改寫、不要只說下一步。

對應命令：

```bash
python3 skills_py/gcg_runtime.py start --viewer P1
python3 skills_py/gcg_runtime.py status --viewer P1
python3 skills_py/gcg_runtime.py mulligan --player P1 --action keep --viewer P1
python3 skills_py/gcg_runtime.py mulligan --player P1 --action redraw --viewer P1
python3 skills_py/gcg_runtime.py command --player P1 --cmd "<玩家原始指令>" --viewer P1
```

指令對應規則：

- `start game` / `start gmae` / `開始遊戲` -> `start --viewer P1`
- `status` / `狀態` -> `status --viewer P1`
- `keep` -> `mulligan --player P1 --action keep --viewer P1`
- `redraw` -> `mulligan --player P1 --action redraw --viewer P1`
- 其他遊戲動作 -> `command --player P1 --cmd "<玩家原始指令>" --viewer P1`

複合指令（例如 `play st01/ST01-008 and end turn`）也必須原樣傳給 `gcg_runtime.py command --cmd "<玩家原始指令>"`。不要由 agent 或 orchestrator 自行拆句；runtime 會依 `and` / `then` / `然後` 拆成連續子指令並依序套用。

`start gmae` 是常見 typo，等同 `start game`。

如果使用者是在問程式碼、review、fix、plan，才進入一般 coding agent 流程。

## 目前架構方向

- 玩家入口永遠是 chat；不要要求玩家或 AI 直接讀 `gameState.md`。
- 遊戲狀態變更一律走 `skills_py/gcg_runtime.py` 或 `skills_py/game_engine.py`。
- 決策前一律用 `--viewer P1|P2` 產生完整可見狀態。
- AI 決策主路徑是 `GCG_AI_PROVIDER=agent-server`。
- `skills_py/gcg_agent_server.py` 是本機長駐 HTTP wrapper，內部只啟動一個 `codex app-server --stdio` process。
- 每局 `game_id` 初始化 4 個獨立 Codex room：`gcg-orchestrator`、`gcg-judge`、`gcg-ai-player:P1`、`gcg-ai-player:P2`。
- P1/P2 不得共用 thread；同一玩家多次決策必須 reuse 同一 thread。
- Orchestrator/Judge 不得和玩家共用 thread。
- Runtime 仍是唯一 state mutator；LLM 不直接改 state、不讀 hidden raw state。
- `agents/gcg-ai-player.md` 是 live player room 的主 agent spec；`skills_py/gcg_agent_server.py` 只負責載入 spec、建立 room、轉送 decision prompt。
- `gcg_skills/*.md` 是 legacy public-safe tactical skill 參考；下一階段應改為 `experience/lessons/` + LLM selector。Python 只能用非策略文字 retrieval 取得候選內容；是否適用與如何運用必須交給 LLM selector/player/judge，不得在 Python 端依技能內容決定 move 優劣或自動改 COMMAND。
- `experience/*.yaml` 是舊策略素材/分析參考，不是 Python 策略引擎，也不是 fallback；不得依 YAML 在 Python 端自動選牌、評分或改變 COMMAND。
- 修改 `agents/*.md` 後，要重啟 agent-server 或建立新 game room 才能保證新 room 使用新 base instructions。`gcg_skills/*.md` 目前是 legacy/reference；新經驗路徑應使用 `experience/lessons/` 與 LLM selector。
- 新增或修改 agent prompt / tactical skill 時，對玩家與 review 可見的指令、規則、策略文字必須使用繁體中文；只有程式碼識別字、protocol key、檔名、command syntax 可維持英文。
- `gcg_skills/*.md` 或 `experience/lessons/*.yaml` 只能提供 public-safe tactical hints，不得要求 AI 讀 raw state，也不得包含 hidden hand/deck/shield card id。
- `.opencode/agents` 與 `.opencode/skills` 目前只作 legacy prompt / rule reference；不要把它們當成主執行路徑。

## Agent Server 操作

在 repo root 啟動 server：

```bash
cd /Users/hello/Desktop/cardAI
python3 skills_py/gcg_agent_server.py --host 127.0.0.1 --port 8890
```

Provider probe：

```bash
GCG_AGENT_SERVER_URL=http://127.0.0.1:8890 GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py ai-probe --provider agent-server
```

Protocol probe：

```bash
python3 skills_py/gcg_agent_server.py --probe --timeout-seconds 60
```

HTTP API：

```text
GET  /health
GET  /metrics
POST /init-game
POST /append
POST /decide
```

`start game` 會嘗試 `/init-game` 建立 4 rooms；初始化失敗只記 warning，不阻止開局。AI 決策走 `/decide`；成功公開動作用 `/append` 注入 `gcg-orchestrator`。

## Debug / Fix 原則

- 不要把「增加 retry」當成 AI、runtime、harness 問題的預設修法。Retry 只能處理已確認的暫時性外部錯誤；若沒有量測與 root cause，不要用 retry 掩蓋問題。
- `ai-probe` 或 live harness 前必須先在 repo root：`cd /Users/hello/Desktop/cardAI`。
- live LLM 很慢時，先量測 agent-server probe 與 runtime probe，分類為 provider latency、app-server protocol、runtime issue 或 display/prompt issue。
- 修 timeout / slow harness 時，優先做 fail-fast、latency recording、review artifact 與明確錯誤分類。
- 不要在 Python 裡新增策略 fallback，也不要把多次 retry 當成 AI 變聰明。
- AI-vs-AI 達到 harness 上限時，不可只調高 `max_turns` / `max_steps` / `max_actions`。必須先 review `gameplay.yaml` / `replay.md` 並分類 root cause。
- Review 分類固定為 `AI prompt problem`、`Display problem`、`Runtime problem`、`Harness problem`、`provider app-server/model latency problem`。
- `GCG_AI_TIMEOUT_SECONDS` 與 harness 的 `--ai-timeout-seconds` 是診斷與 fail-fast 工具，不是讓測試悄悄通過的手段。

## Runtime / Display 約定

- `skills_py/gcg_runtime.py status` 與一般 command 回覆前，會自動清理空的 action priority window。
- 空 action priority window 指：`end/action` 或 `battle/action` 中，當前 priority 玩家手上沒有任何依既有 `can_play_card` Lv/cost 規則可合法使用的 `command` 卡。
- 若空 action priority window 成立，runtime 會呼叫既有 `pass_turn` 自動讓過，並在 battle log 留下 `P? 自動讓過（沒有可使用的 action card）`。
- 玩家可見的 runtime / display / battle log 文字預設使用繁體中文。
- 不要新增 `draws a card`、`deploys a resource`、`Turn N begins`、`started game as first player` 這類英文系統事件。
- 不要在主要階段自動跳過玩家決策；主要階段仍要顯示可部署、可使用、可攻擊與讓過選項。
- 基地顯示格式固定為 `基地：<card_id> | AP|HP：<ap>|<remaining_hp>`，不要使用舊格式 `HP：x/y`。
- 對手盾牌行必須同時顯示對手基地狀態，例如 `對手盾牌：6 剩餘 | 對手基地：有（EX-BASE | AP|HP：0|3）`；基地被摧毀時顯示 `對手基地：無`。

## Gameplay Log / Replay 約定

- AI-vs-AI simulation / replay review 的測試原則固定在 `GCG_TESTING_PRINCIPLES.md`。
- AI-vs-AI replay harness 一律走 configured LLM provider；不得使用 fake AI player 或 Python 策略 fallback。
- AI-vs-AI replay harness 指令：`GCG_AI_PROVIDER=agent-server python3 tests/gcg_ai_vs_ai_replay_harness.py --ai-timeout-seconds 60`。
- AI-vs-AI harness 必須產生 `gameplay.yaml`、`replay.md`、`review.md`。
- AI-vs-AI `INCOMPLETE` 是 bug/quality signal，不是正常 pass。
- AI-vs-AI review 必須標記「面臨下回合斬殺仍部署」這類 lethal race 問題：例如己方基地已摧毀、對手下回合潛在攻擊者數量大於己方盾牌數、AI 仍選擇無法增加 blocker 的 deploy。此分類應視為 `AI prompt problem`，優先更新 `agents/gcg-ai-player.md` 或 `experience/lessons/*.yaml`，而不是新增 Python fallback。
- Gameplay log / replay 寫入邏輯集中在 `skills_py/gameplay_log.py`；不要在 runtime 之外手寫另一套 replay 格式。
- Runtime 每局必須維護 `game-states/<game_id>/gameplay.yaml` 作為 canonical structured gameplay log。
- Runtime 每局必須維護 `game-states/<game_id>/replay.md` 作為玩家可讀 replay；此 Markdown 必須使用繁體中文。
- `gameplay.yaml` / `replay.md` 只記錄 public-safe 資訊；不要寫入對手隱藏手牌 card id、deck card id、shield card id，也不要 dump 完整 raw `gameState.md`。
- `gameplay.yaml` 使用單一 YAML document，至少包含 `schema_version`、`game_id`、`summary`、`events`；事件 `seq` 必須單調遞增且可被 `yaml.safe_load` 解析。
- Runtime stdout 可以在最終完整 display 前輸出短事件行，例如 `P2 正在決定調度...`、`P2 選擇重新調度`，讓 chat room 看起來有進度。
- 若 runtime 使用 `--json`，輸出需包含本次回覆的 `events`、完整累積的 `all_events`、`replay_path`、`gameplay_log_path`，且 `display_text` 仍保留完整顯示文字。

## Harness

基本檢查：

```bash
python3 -m py_compile skills_py/gcg_agent_server.py skills_py/ai_adapters.py skills_py/ai_player.py skills_py/gcg_runtime.py tests/gcg_direction_harness.py tests/gcg_ai_vs_ai_replay_harness.py
python3 tests/gcg_direction_harness.py
```

Agent server protocol：

```bash
python3 skills_py/gcg_agent_server.py --probe --timeout-seconds 60
```

Runtime live path：

```bash
python3 skills_py/gcg_agent_server.py --host 127.0.0.1 --port 8890
GCG_AGENT_SERVER_URL=http://127.0.0.1:8890 GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py ai-probe --provider agent-server
```

AI-vs-AI：

```bash
GCG_AGENT_SERVER_URL=http://127.0.0.1:8890 GCG_AI_PROVIDER=agent-server python3 tests/gcg_ai_vs_ai_replay_harness.py --ai-timeout-seconds 60
```

AI-vs-AI harness 預設是短上限 fail-fast；完整壓力測試可明確加 `--max-turns`、`--max-steps`、`--per-auto-actions`。

## 清理規則

- 不提交或保留 `.DS_Store`、`__pycache__/`、`*.pyc`、`.opencode/node_modules/`。
- 不新增只為單次測試存在的 dependency 或 package 檔。
- 不把完整 `gameState.md`、完整手牌或隱藏資訊寫入文件、memory 或 replay。
- 不把暫時測試 game id 當成長期事實。
- 不把 tool trace 當作玩家可見輸出格式。
