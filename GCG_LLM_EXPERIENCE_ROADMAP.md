# GCG LLM 經驗學習架構路線圖

## 目標

本文件定義下一階段 `gcg_agent_server` 的重構方向。核心目標是讓 AI player 透過 LLM 子代理、公開經驗記憶與裁判審查逐步變聰明，而不是把策略寫成 Python fallback。

```text
AI player 不是靠 Python 自動選牌、評分或改 command 變聰明。
AI player 是靠 LLM 讀取、選擇、解釋、運用經驗變聰明。
```

## 不可違反的原則

- Runtime / `game_engine.py` 仍是唯一 state mutator。
- Python 不得根據經驗 YAML、lesson 或 skill 自動選牌、改 command、選 target 或做策略評分。
- Python 不得 hardcode 類似「ST01-014 一定要 target」這種策略/語意判斷來替 AI 決策。
- Python 可以做資料管線：建立 room、reuse thread、讀寫 public-safe lesson、搜尋候選經驗、轉送 prompt、parse protocol、寫 replay/review。
- Python 可以提供公開卡片文字給 LLM，例如 viewer 可見手牌的 effect description；這是資料供給，不是策略判斷。
- LLM 負責判斷經驗是否適用、玩家決策、語意審查、錯誤萃取與經驗整理。
- 所有經驗、lesson、judge reason、player instruction 預設使用繁體中文。
- 不得把 hidden hand/deck/shield card id 寫入 memory、lesson、judge prompt 或 replay。

## 目標資料流

目前主流程大致是：

```text
runtime visible display
  -> gcg-agent-server
  -> gcg-ai-player:P1/P2
  -> runtime apply
```

目標流程是：

```text
runtime visible display
  -> gcg-agent-server
  -> memory-selector LLM
  -> gcg-ai-player:P1/P2
  -> gcg-judge LLM
  -> runtime apply
  -> game/review 結束後
  -> memory-curator LLM
  -> public-safe experience memory
```

## 角色設計

### `gcg-ai-player:P1` / `gcg-ai-player:P2`

職責：

- 只根據自己的 viewer display、被選出的 lessons、judge repair feedback 做決策。
- 輸出固定格式：

```text
CONSIDER: <繁體中文 public-safe 簡短理由>
COMMAND: <runtime command only>
```

禁止：

- 讀 raw `gameState.md`。
- 暴露 hidden info。
- 把 display 中 `—` 後面的說明複製進 COMMAND。
- 在 command card 明顯需要目標時輸出 targetless command，除非 lesson/judge 明確說目前 command surface 無法表達且應改選其他 action。

### `gcg-judge`

目前狀態：已建立 room，但尚未真正進入決策流程。

目標職責：

- 讀同一份 viewer display、selected lessons、player proposed command。
- 讀 public-safe card text context，例如 viewer display 已公開或該 viewer 自己手牌中的卡片效果文字。
- 做 LLM 語意審查，不做 state mutation。
- 判斷 command 是否與公開資訊、卡片文字、過往 lessons、可見 command surface 相容。
- 若 reject，提供 public-safe 修正理由與可選建議。

輸出固定格式：

```text
VERDICT: accept|reject
REASON: <繁體中文 public-safe 理由>
SUGGESTED_COMMAND: <可省略；若提供，必須是 runtime command only>
```

Judge 不應是 Python hardcoded validator；Judge 是 LLM 子代理。

`SUGGESTED_COMMAND` 只是修正提示。Python 不得直接用 judge suggestion 取代 player command；若需要修正，必須把 judge feedback 送回 player room，讓 player 自己重新輸出 `COMMAND`。

### `gcg-memory-selector`

新增角色。

職責：

- 不決定 move。
- 從候選 lessons / episodes 中選出本次決策最相關的 0-5 條。
- 說明每條 lesson 為何適用或不適用。
- 幫 player / judge 降低 context 噪音。

輸出建議格式：

```text
SELECTED_LESSONS:
- <lesson_id>: <為何適用>
IGNORED_LESSONS:
- <lesson_id>: <為何不適用>
```

### `gcg-memory-curator`

新增角色。

職責：

- 在一局結束或 review 後，讀 public-safe `gamePlay.yaml` / `replay.md` / `review.md`。
- 萃取錯誤、成功案例與可重用教訓。
- 產生 draft lessons；經人工或 judge/coach review 後才可標記為 reviewed。
- 不把單局偶然現象直接升級成通用規則；必須寫明適用條件與信心。
- 不寫 hidden info。

Curator 輸出不是直接可執行策略，而是 LLM-readable lesson。

## Experience / Memory 目錄建議

建議逐步把 `experience/` 改成以下結構：

```text
experience/
  lessons/
    command-target-required-st01-014.yaml
    low-base-non-blocker-defense.yaml
    lethal-race-deploy-mistake.yaml

  raw/
    game_<id>/
      gamePlay.yaml
      replay.md
      review.md

  rejected/
    wrong-or-too-specific-lessons.yaml

  index.jsonl
```

`experience/*.yaml` 舊檔案可先保留為 legacy reference，但不應由 Python 當策略引擎直接使用。

## Lesson 格式建議

Lesson 應該是 LLM 可讀、public-safe、可審查的文件。

範例：

```yaml
id: command-target-required-st01-014
source_game: game_20260607_214139_166237
status: reviewed
lesson_type: command_semantics
confidence: medium
summary: >
  ST01-014 的卡片文字要求選擇 1 個敵方 Unit。
  `play st01/ST01-014` 沒有指定目標，因此語意不完整。
applies_when:
  - 可見手牌或可行指令中有 command card。
  - 卡片文字包含 Choose / 選擇，且效果需要公開目標。
  - proposed COMMAND 使用該 card 但沒有指定 target。
bad_example: "targetless use/play ST01-014"
better_example: "使用 ST01-014 時需附上當前公開、合法的敵方 Unit 目標欄位"
player_instruction: >
  若 command card 文字要求選擇目標，COMMAND 必須包含公開目標。
  若目前 display 沒有列出可表達 target 的合法 command，避免輸出 targetless play/use。
judge_instruction: >
  若 proposed command 使用需要目標的 command card 但沒有指定目標，應 reject 並要求 player 修正。
notes: >
  此 lesson 不是 Python fallback。是否適用由 memory-selector / player / judge LLM 判斷。
```

## `gcg_agent_server` 完整目標 Pipeline

### Phase 3+ 完整 `/decide` Pipeline

```text
1. runtime 呼叫 /decide，傳入 game_id、player_id、viewer display。
2. agent-server 讀取 public-safe candidate lessons 與 public-safe card text context。
3. memory-selector LLM 選出 relevant lessons。
4. player room 根據 display + selected lessons + card text context 輸出 COMMAND。
5. judge room 根據 display + selected lessons + card text context + proposed command 輸出 VERDICT。
6. 若 judge accept，agent-server 回傳 player command。
7. 若 judge reject，agent-server 把 judge reason 送回同一 player room，允許 repair 一次。
8. repair 後再交 judge review 一次。
9. 若第二次 judge 仍 reject，agent-server 回傳失敗 metadata，不得自行套用 judge 建議或替 player 選 command。
10. agent-server 回傳 final command 與 judge metadata 給 runtime。
11. runtime 仍用既有 legality / state mutation 邊界 apply。
```

### Python 可以做的事

- `memory_store.search(display)` 回傳候選 lessons。
- 呼叫 selector / player / judge rooms。
- parse `COMMAND:` / `VERDICT:`。
- 把 judge metadata 寫入 `ai_evaluation` 或 review artifact。
- 控制最多 repair 次數，避免無限 loop。
- 如果 judge 或 player timeout，記錄 `ai_failure` / `judge_failure`。
- 如果 judge 最終 reject，回傳 provider failure 或明確 `judge_rejected` metadata，避免 runtime 靜默套用語意不完整 command。

### Python 不可以做的事

- 根據 lesson 自己 reject command。
- 根據 lesson 自己替換 command。
- 根據 judge `SUGGESTED_COMMAND` 自己替換 command。
- 自己選 target。
- 自己判斷哪張牌戰術分數最高。
- 把 memory retrieval 結果當作 deterministic rule engine。

## `gcg-judge` 接入策略

Phase 1 最小可行版本：

```text
player proposed command
  -> judge semantic review
  -> accept: return
  -> reject: player repair once
```

Phase 1 不呼叫 memory-selector，`selected_lessons=[]`。Phase 2 可加入少量 reviewed lessons store，Phase 3 才把 lesson 適用性判斷交給 memory-selector LLM。

Judge prompt 必須包含：

- 最新 viewer display。
- Player 的 `CONSIDER` / `COMMAND`。
- Selected lessons。
- Public-safe card text context。
- 明確規則：Judge 不改 state、不讀 hidden info、不直接執行 command。

Judge 可 reject 的類型應由 LLM 推理，不由 Python pattern 決定。常見例子：

- command card 文字要求目標，但 proposed command 沒有目標。
- proposed command 使用了 display 沒有支援或不清楚的 command syntax。
- player 把說明文字複製到 command。
- player reason 和 command 明顯矛盾。
- selected lesson 明確指出相似情況曾失敗，而 player 沒有處理。

## Memory Selector 策略

第一版可以用簡單文字搜尋取得候選 lessons，但「是否適用」交給 LLM selector。

```text
Python 粗取候選：
- card id match
- card name match
- visible keywords
- lesson_type
- recent high-confidence lessons

LLM selector 精選：
- 選 0-5 條
- 說明適用性
- 排除不相關 lesson
```

注意：Python 的搜尋只是 retrieval，不是策略判斷。
Python 可以排序「文字相似度」或「近期高信心 lesson」，但不得排序「哪個 move 比較好」。

## Memory Curator 策略

Curator 不應每局自動把所有事件變成 lesson。建議只在以下情況產生 lesson：

- `review.md` 標記 hard failure。
- replay 有明確 bad move，且原因可由公開資訊解釋。
- judge 多次 reject 同類錯誤。
- 使用者人工指出某個 move 有問題。
- live harness 產生重複 quality signal。

Curator 產生 lesson 後，應標記：

- `status: draft|reviewed|rejected`
- `confidence: low|medium|high`
- `source_game`
- `lesson_type`
- `applies_when`
- `bad_example`
- `better_example`
- `player_instruction`
- `judge_instruction`

第一版可以要求人工 review 後才把 `draft` 改為 `reviewed`。

## 分階段實作

### Phase 0：文件與原則鎖定

目標：

- 建立本文件。
- 更新 `AGENTS.md` / `GCG_ARCHITECTURE.md`，明確寫入「經驗不是 Python 策略 fallback」。
- 實作前需確認 `gcg-judge` 是否仍只是 room placeholder；完成 Phase 1 後，它必須已接入 `/decide`，不可再被當成未使用 room。

驗收：

- 文件清楚列出 Python / LLM 邊界。
- 沒有新增 Python strategy fallback。

### Phase 1：Active Judge Pipeline

目標：

- 讓 `/decide` 內部真的呼叫 `gcg-judge`。
- Judge 只做 LLM semantic review。
- Reject 時 reprompt player 一次。
- 回傳結果包含 judge metadata。

建議回傳 metadata：

```json
{
  "stdout": "CONSIDER: ...\nCOMMAND: ...",
  "judge": {
    "verdict": "accept",
    "reason": "...",
    "suggested_command": ""
  },
  "repair_attempted": false
}
```

驗收：

- `gcg-judge` 不再只是建立 room。
- Tests 驗證 judge room 被呼叫。
- Runtime apply 邊界不變。
- Python 不根據 judge reason 自行選 command。
- 若第二次 judge 仍 reject，agent-server 必須回傳失敗，不得自動套用 judge suggestion。

### Phase 2：Public-Safe Lessons Store

目標：

- 建立 `experience/lessons/`。
- 定義 lesson schema。
- 先加入少量人工 reviewed lessons，例如 ST01-014 targetless command 案例。
- 保留 legacy `experience/*.yaml`，但標記為 reference。

驗收：

- Lesson 不含 hidden info。
- Lesson 是 LLM-readable，不是 Python executable strategy。
- `/decide` 尚可不使用 selector；Phase 1 judge 可先以 `selected_lessons=[]` 運作。Phase 2 可先手動注入少量 reviewed lessons 做驗證。

### Phase 3：Memory Selector LLM

目標：

- 新增 `agents/gcg-memory-selector.md`。
- `/decide` 先用 Python 做粗略 candidate retrieval，再讓 selector LLM 選 relevant lessons。
- Player / Judge 只收到 selected lessons，不收到全部 experience。

驗收：

- Selector 不輸出 COMMAND。
- Selector 不決定 move。
- Logs 記錄 selected lesson ids。
- 相同局面能穩定選出相關 lesson。

### Phase 4：Memory Curator LLM

目標：

- 新增 `agents/gcg-memory-curator.md`。
- 讀 public-safe replay/review 後產生 draft lesson。
- 不自動把 draft 當真；需要人工或 judge/coach review 後變成 `reviewed`。

驗收：

- Curator 產出的 lesson 不含 hidden info。
- Lesson 有 source、適用條件、bad/better example、confidence。
- 錯誤或過度泛化 lesson 可進 `experience/rejected/`。

### Phase 5：Review / Harness 整合

目標：

- `gamePlay.yaml` / `review.md` 記錄 judge verdict、selected lesson ids、repair attempt。
- AI-vs-AI review 能標記：
  - judge reject rate
  - repair success rate
  - selected lessons 是否有幫助
  - repeated mistake 是否仍發生

驗收：

- Review 可回答：「AI 是否因經驗避免同類錯誤？」
- 不靠 Python fake AI 或 fallback 讓測試通過。

### Phase 6：逐步淘汰 Legacy Prompt / Experience

目標：

- `.opencode/agents` 與舊 `experience/*.yaml` 只保留為 reference。
- 有價值的內容由 curator / 人工轉成 reviewed lesson。
- Player base prompt 保持短，主要靠 selected lessons 與 judge feedback 補充。

驗收：

- Base prompt 不塞大量歷史。
- 決策 context 可解釋：display + selected lessons + judge feedback。
- Python 不直接讀 legacy YAML 當策略。

## ST01-014 案例如何進新架構

不要用 Python 寫死：

```text
if card == ST01-014:
    reject targetless command
```

應該建立 lesson：

```text
source_game: game_20260607_214139_166237
bad move pattern: targetless use/play ST01-014
reason: 卡片文字需要 Choose 1 enemy Unit，但 command 沒有指定目標。
instruction: 看到需要目標的 command card 時，player 必須指定公開目標；judge 應 reject targetless command。此 lesson 不提供可直接複製的 COMMAND。
```

之後流程：

```text
display 出現 ST01-014 或類似 command card
  -> retrieval 找到 lesson candidate
  -> selector 判斷此 lesson 適用
  -> player 避免 targetless command
  -> judge 若仍看到 targetless command，reject 並要求 repair
  -> runtime 只 apply judge accept 後的 player command
```

## 對未來 AI 的實作提醒

實作本路線圖時，請先回答這三個問題：

1. 這個變更是否讓 Python 更像策略玩家？
2. 這個變更是否把經驗當成 deterministic rule engine？
3. 這個變更是否讓 LLM player / judge / curator 承擔更多推理責任？

若 1 或 2 是 yes，通常方向錯了。
若 3 是 yes，且 runtime 邊界仍安全，才符合本文件目標。
