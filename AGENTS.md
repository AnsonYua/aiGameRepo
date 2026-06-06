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

本 repo 目前主要用途是讓使用者在 Codex / opencode chat 裡玩 GCG。新 session 讀到這份文件後，遇到遊戲指令時要直接執行 runtime，不要只說「我會先查看」或停在計畫。

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

- `start game` / `start gmae` / `開始遊戲` → `start --viewer P1`
- `status` / `狀態` → `status --viewer P1`
- `keep` → `mulligan --player P1 --action keep --viewer P1`
- `redraw` → `mulligan --player P1 --action redraw --viewer P1`
- 其他遊戲動作 → `command --player P1 --cmd "<玩家原始指令>" --viewer P1`

複合指令（例如 `play st01/ST01-008 and end turn`）也必須原樣傳給 `gcg_runtime.py command --cmd "<玩家原始指令>"`。不要由 agent 或 orchestrator 自行拆句；runtime 會依 `and` / `then` / `然後` 拆成連續子指令並依序套用。

`start gmae` 是常見 typo，等同 `start game`。

如果使用者是在問程式碼、review、fix、plan，才進入一般 coding agent 流程。

# Agent Handoff Memory

本專案允許 Codex、opencode 與不同 subagent 共同工作。任何 agent 在完成一個 section 的工作後，都應留下可被下一個 agent 快速理解的 memory / handoff note。

## 核心規則

- 玩家入口永遠是 chat；不要要求玩家或 AI 直接讀 `gameState.md`。
- 遊戲狀態變更一律走 `skills_py/gcg_runtime.py` 或 `skills_py/game_engine.py`。
- 決策前一律用 `--viewer P1|P2` 產生完整可見狀態。
- 回覆與文件預設使用繁體中文。
- 不提交或保留 `.DS_Store`、`__pycache__/`、`*.pyc`、`.opencode/node_modules/`。

## Debug / Fix 原則

- 不要把「增加 retry」當成 AI、runtime、harness 問題的預設修法。Retry 只能處理已確認的暫時性外部錯誤；若沒有量測與 root cause，不要用 retry 掩蓋問題。
- AI 決策 provider 必須走 `skills_py/ai_player.py` / `skills_py/ai_adapters.py`。預設 `GCG_AI_PROVIDER=opencode` 會呼叫 `opencode run --agent gcg-ai-player`；`GCG_AI_PROVIDER=codex` 會呼叫 `codex exec`；`GCG_AI_PROVIDER=claude` 目前只保留 placeholder。
- 執行 `ai-probe` 或 live harness 前必須先在 repo root：`cd /Users/hello/Desktop/cardAI`。已知可用版本：`@openai/codex@0.137.0`，`GCG_AI_PROVIDER=codex python3 skills_py/gcg_runtime.py ai-probe --provider codex` 可回 `CONSIDER: probe` / `COMMAND: pass`。
- 遇到 live LLM 很慢、逾時或重複失敗時，先量測單次最小 prompt，例如只含 `player_id`、`first_player`、`legal_actions: keep, redraw` 與調度顯示的 adapter probe：`python3 skills_py/gcg_runtime.py ai-probe --provider opencode` 或 `python3 skills_py/gcg_runtime.py ai-probe --provider codex`。若最小 prompt 仍需十幾秒，root cause 通常是 provider CLI 啟動 / model latency，不是 gameplay replay 或 prompt 太長。
- 修 timeout / slow harness 時，優先做 fail-fast、latency recording、review artifact 與明確錯誤分類；不要讓 harness 長時間卡住，也不要讓 timeout 後繼續污染同一局 replay。
- AI-vs-AI 達到 harness 上限時，不可把「調高 max_turns/max_steps/max_actions」當成預設修法。必須先 review `gameplay.yaml` / `replay.md`：若 display 有具體 ✅ attack/block 指令但 AI 選 pass/deploy，歸類為 AI player prompt problem；若 display 沒有列出具體合法指令，歸類為 Display problem；若合法指令被 runtime 拒絕，歸類為 Runtime problem。
- Review 要區分 `AI prompt problem`、`Display problem`、`Runtime problem`、`Harness problem`、`provider CLI/model latency problem`。例如 illegal `attack` 通常先看 display 是否列出具體合法攻擊；live LLM 慢則先看單次 provider probe latency。
- 若要調整 live LLM 速度，先考慮模型/agent mode/attach server/timeout 設定；不要在 Python 裡新增策略 fallback，也不要把多次 retry 當成「AI 變聰明」。
- `GCG_AI_TIMEOUT_SECONDS` 與 harness 的 `--ai-timeout-seconds` 是診斷與 fail-fast 工具。縮短 timeout 的目的是快速產生清楚的 FAIL review，不是讓測試悄悄通過。

## Runtime / Display 約定

- `skills_py/gcg_runtime.py status` 與一般 command 回覆前，會自動清理空的 action priority window。
- 空 action priority window 指：`end/action` 或 `battle/action` 中，當前 priority 玩家手上沒有任何依既有 `can_play_card` Lv/cost 規則可合法使用的 `command` 卡。
- 若空 action priority window 成立，runtime 會呼叫既有 `pass_turn` 自動讓過，並在 battle log 留下 `P? 自動讓過（沒有可使用的 action card）`。
- 玩家可見的 runtime / display / battle log 文字預設使用繁體中文；不要新增 `draws a card`、`deploys a resource`、`Turn N begins`、`started game as first player` 這類英文系統事件。
- battle log 系統事件範例：`P1 抽一張牌`、`P1 部署一張資源`、`回合 2 開始 — P1 的回合`、`P2 為先手 [CR-1.1]`、`P1 選擇重新調度`、`P2 保留手牌`。
- 不要在主要階段自動跳過玩家決策；主要階段仍要顯示可部署、可使用、可攻擊與讓過選項。
- 基地顯示格式固定為 `基地：<card_id> | AP|HP：<ap>|<remaining_hp>`，不要使用舊格式 `HP：x/y`。
- 對手盾牌行必須同時顯示對手基地狀態，例如 `對手盾牌：6 剩餘 | 對手基地：有（EX-BASE | AP|HP：0|3）`；基地被摧毀時顯示 `對手基地：無`。

## Gameplay Log / Replay 約定

- AI-vs-AI simulation / replay review 的測試原則固定在 `GCG_TESTING_PRINCIPLES.md`；新增完整 AI-vs-AI harness 或 review 時必須遵守該文件。
- AI-vs-AI replay harness 指令：`python3 tests/gcg_ai_vs_ai_replay_harness.py`；live LLM 模式：`python3 tests/gcg_ai_vs_ai_replay_harness.py --live-llm`。切換 provider 用環境變數，例如 `GCG_AI_PROVIDER=codex python3 tests/gcg_ai_vs_ai_replay_harness.py --live-llm`。
- AI-vs-AI harness 必須產生 `gameplay.yaml`、`replay.md`、`review.md`，review 欄位需符合 `GCG_TESTING_PRINCIPLES.md`。
- AI-vs-AI `INCOMPLETE` 是 bug/quality signal，不是正常 pass。下一步一定是回看 replay 並分類 root cause；只有 review 證明 AI 持續正常推進防禦層且上限明顯太低時，才調高上限。
- Gameplay log / replay 寫入邏輯集中在 `skills_py/gameplay_log.py`；不要在 runtime 之外手寫另一套 replay 格式。
- Runtime 每局必須維護 `game-states/<game_id>/gameplay.yaml` 作為 canonical structured gameplay log。
- Runtime 每局必須維護 `game-states/<game_id>/replay.md` 作為玩家可讀 replay；此 Markdown 必須使用繁體中文。
- `gameplay.yaml` / `replay.md` 只記錄 public-safe 資訊；不要寫入對手隱藏手牌 card id，也不要 dump 完整 raw `gameState.md`。
- `gameplay.yaml` 使用單一 YAML document，至少包含 `schema_version`、`game_id`、`summary`、`events`；事件 `seq` 必須單調遞增且可被 `yaml.safe_load` 解析。
- 每個事件應保留 public features，例如 active/priority、雙方 hand_count、resources、board summary、shields、base AP/HP/alive；不要加入 `hand_cards`、`deck_cards`、`shield_cards`。
- `replay.md` 必須由 gameplay log 事件產生或同步更新，避免 YAML 與 Markdown 時間線不一致。
- Runtime stdout 可以在最終完整 display 前輸出短事件行，例如 `P2 正在決定調度...`、`P2 選擇重新調度`，讓 chat room 看起來有進度。
- 若 runtime 使用 `--json`，輸出需包含本次回覆的 `events`、完整累積的 `all_events`、`replay_path`、`gameplay_log_path`，且 `display_text` 仍保留完整顯示文字。
- 實作或修改 gameplay log/replay 後，除了本地驗證，應 spawn subagent 做獨立驗證：start → keep/redraw → P2 mulligan/auto flow、YAML parse、繁中 replay、hidden-info safety。

## Memory 建立時機

完成以下任一 section 後，建立一段 handoff memory：

- runtime / engine 行為變更
- display / viewer 輸出變更
- opencode agent prompt 變更
- AI provider adapter / Codex / opencode / Claude Code 相容性修正
- 測試流程或驗證結果
- 刪除檔案、停用 legacy 入口、更新架構文件

## Memory 格式

使用短段落或條列，至少包含：

```text
Section:
Scope:
Changed:
Verification:
Constraints:
Next:
```

欄位說明：

- `Section`：例如 `runtime`, `display`, `opencode-agent`, `cleanup`, `testing`。
- `Scope`：這次 memory 涵蓋哪些檔案或功能。
- `Changed`：實際改了什麼，不寫泛泛而談。
- `Verification`：跑過哪些命令，結果是 pass / fail。
- `Constraints`：仍需遵守或尚未解決的限制。
- `Next`：下一個 agent 若接手，最應該先看或先做什麼。

## 範例

```text
Section: ai-provider-adapter
Scope: skills_py/ai_player.py, skills_py/ai_adapters.py, .opencode/agents/gcg-ai-player.md
Changed: AI Player 必須輸出 CONSIDER / COMMAND；runtime 只套用 COMMAND，replay 記錄 public-safe CONSIDER。provider 可用 GCG_AI_PROVIDER 在 opencode / codex / claude placeholder 間切換。
Verification: 在 `/Users/hello/Desktop/cardAI` 執行 `python3 skills_py/gcg_runtime.py ai-probe --provider opencode` 或 `GCG_AI_PROVIDER=codex python3 skills_py/gcg_runtime.py ai-probe --provider codex` 成功回 CONSIDER / COMMAND。
Constraints: AI Player 只能讀 viewer display text，不讀 gameState.md；Python adapter 不新增策略 fallback。
Next: 若 AI command 要套用 state，交給 skills_py/gcg_runtime.py command --player P2 --cmd "<command>"。
```

## 儲存位置

- 若使用 Codex：在最終回覆中保留 handoff memory 摘要。
- 若使用 opencode 且有可用 memory 工具：將同樣內容存成 memory，標籤建議使用 `gcg`, `handoff`, `<section>`。
- 若 memory 工具不可用：更新相關 `.md` 文件或在最終回覆中清楚列出 handoff memory。

## 不要做的事

- 不要把完整 `gameState.md`、完整手牌或隱藏資訊寫入 memory。
- 不要把暫時測試 game id 當成長期事實。
- 不要把 tool trace 當作玩家可見輸出格式。
- 不要新增只為單次測試存在的 dependency 或 package 檔。
