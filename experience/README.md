# GCG AI 經驗檔案

此目錄中的 `.yaml` 是策略知識素材，不是 runtime 策略引擎，也不是 Python fallback。

目前主路徑是 `GCG_AI_PROVIDER=agent-server`：

```text
skills_py/ai_player.py
  -> skills_py/ai_adapters.py
  -> skills_py/gcg_agent_server.py
  -> codex app-server room
```

目前 live player prompt 的主路徑是 `agents/gcg-ai-player.md`。新經驗學習方向以 `experience/lessons/*.yaml` 作為 LLM-readable reviewed lessons；舊的 `experience/*.yaml` 與 `gcg_skills/*.md` 保留為舊策略素材與分析參考。

不要在 Python 中直接依 YAML 自動選牌、評分、選 target 或改變 COMMAND。Python 只能做 public-safe retrieval / formatting；是否適用與如何運用必須交給 LLM selector / player / judge。runtime 仍只負責顯示、合法性驗證與 state mutation。

## Lessons

`experience/lessons/*.yaml` 是給 LLM 閱讀的 reviewed lessons，不是 Python strategy engine。

建議欄位：

- `id`
- `source_game`
- `status: draft|reviewed|rejected`
- `lesson_type`
- `confidence: low|medium|high`
- `summary`
- `applies_when`
- `bad_example`
- `better_example`
- `player_instruction`
- `judge_instruction`
- `notes`

只有 `status: reviewed` 的 lesson 才應進入決策候選 retrieval。`draft` 必須先由人工或 judge/coach review。

## Legacy YAML

`experience/*.yaml` 舊檔案若含有 `priority`、`condition`、`effect`、`score_bonus` 等欄位，只能視為人工分析素材。它們不得被 Python 當成條件規則、加權規則或自動決策規則。

若某個 legacy 檔案仍有價值，應由人工或 `gcg-memory-curator` 轉成 `experience/lessons/*.yaml` 的 draft lesson，再經 review 後標記為 `reviewed`。

### 使用限制

- 只能提供 public-safe strategy hints。
- 不得把 hidden hand/deck/shield card id 寫入 prompt、replay 或 memory。
- 不得繞過 `skills_py/ai_player.py` / `skills_py/ai_adapters.py`。
- 不得在 Python 端新增策略 fallback 讓測試悄悄通過。
