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

## Memory 建立時機

完成以下任一 section 後，建立一段 handoff memory：

- runtime / engine 行為變更
- display / viewer 輸出變更
- opencode agent prompt 變更
- Codex / opencode 相容性修正
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
Section: opencode-agent
Scope: .opencode/agents/gcg-ai-player.md
Changed: AI Player 改為直接輸出單行 command，不再寫 /tmp/gcg_ai_output.txt。
Verification: opencode run --agent gcg-ai-player "請只回覆 pass" 成功回 pass。
Constraints: AI Player 只能讀 viewer display text，不讀 gameState.md。
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
