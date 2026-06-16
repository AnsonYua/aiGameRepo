# `--param` / auto-pass AI no-move 功能驗證

## 兩份分析對比

| 來源 | 針對路徑 | 正確性 |
|------|----------|--------|
| opencode | `run_simulator.py` / AI-vs-AI simulator | 分析本身正確，但**不適用於 `/mobile/battleV2`** |
| codex | `/mobile/battleV2` human-vs-AI | **正確**，命中正確檔案 |

---

## 驗證結果

### Opencode 的正確部分

- `action_enumerator.py:33` `legal_commands()` 已正確枚舉完整合法清單 ✅
- `legal_commands == ["pass"]` 代表除了讓過外無任何合法操作 ✅
- `runtime.resolve_command()` 已正確處理 pass ✅ (見 `runtime.py:297-298`)
- `command_parser.py` 已支援 `parse("pass", player_id)` ✅
- 不應改動 `action_enumerator.py`、`runtime.py`、`command_parser.py`、`hermes_player_client.py`、`prompt_builder.py`、`state_store.py` ✅

### Opencode 的不正確部分

- 建議改 `run_simulator.py:29-37`、`bootstrap.py:25-30`、`runner.py:68-93` — 這些只影響 **standalone simulator 路徑**，與 `/mobile/battleV2` 無關 ❌

### Codex 的分析 — 完全正確

#### 需要改的檔案與位置

**1. `reviewboard/server.py`**

- `line 23`: `battle_session = HumanVsAiBattleSession()` 是 class-level 屬性
- `line 259-264`: `main()` 的 `argparse` 需新增 flag
- 需新增 `--battle-ai-auto-pass-no-move` CLI flag 或 `GCG_BATTLE_AI_AUTO_PASS_NO_MOVE=1` env
- 將 flag 傳入 `HumanVsAiBattleSession(auto_pass_ai_no_move=...)`

**2. `reviewboard/humanVsAI/battle_session.py`**

- `line 34`: `__init__` 需新增 `auto_pass_ai_no_move=False` 參數
- `line 343`: `_build_ai_task_locked()` 是最佳插入點 — 此處在取得 `legal_commands`（line 353）之後、建立 Hermes prompt（line 356）之前

#### 核心邏輯（插入 `_build_ai_task_locked` 第 353 行之後）

```
if self.auto_pass_ai_no_move AND pending_choice is None AND legal_commands == ["pass"]:
    parsed = CommandParser().parse("pass", AI_PLAYER)
    self._runner.runtime.resolve_command(parsed)
    self._last_message = "P2 沒有可用操作，自動讓過。"
    continue  # loop back — auto-pass 可能觸發下一個 action window
```

#### 關鍵設計要點（codex 全部正確）

| 要點 | 驗證 |
|------|------|
| 不 auto-pass pending choices（調度、先後攻選擇等） | ✅ `pending_choice is None` 過濾 |
| 只在 `legal_commands == ["pass"]` 時 auto-pass | ✅ 不涉及策略判斷 |
| 不修改前端的合法性邏輯 | ✅ 純後端 |
| 不修改 Hermes client | ✅ skip 發生在呼叫之前 |
| 不加 Python 策略 fallback | ✅ 只處理強制合法狀態 |
| 不修改 runtime 規則 | ✅ 走既有 `resolve_command()` |
| 需要 loop | ✅ 一次 auto-pass 可能產生下一個 action window |

---

## 不應改動的檔案（兩份分析一致）

| 檔案 | 原因 |
|------|------|
| `gcg/engine/action_enumerator.py` | 枚舉邏輯已正確 |
| `gcg/engine/runtime.py` | `resolve_command(pass)` 已正確實作 |
| `gcg/engine/command_parser.py` | `parse("pass", player_id)` 已支援 |
| `gcg/engine/state_store.py` | action window / pass counting 正確 |
| `gcg/ai/hermes_player_client.py` | skip 發生在呼叫前，無需改 |
| `gcg/ai/prompt_builder.py` | 不會被呼叫到 |
| `gcg/ai/llm_client.py` / `player_client.py` | 同上 |
| `mobile/battleV2/` 合法性判斷 | 合法性仍由後端負責；前端只需改用 `/api/battleV2/*` 讓功能只套用在 V2 |

---

## 總結

- **Opencode 的分析**適用於 AI-vs-AI simulator，但 `/mobile/battleV2` 不是走 `SimulatorRunner.run()` 路徑。
- **Codex 的分析**正確指出 `/mobile/battleV2` 使用 `reviewboard/server.py` + `humanVsAI/battle_session.py`，且所有設計要點（不 auto-pass pending choice、只在 forced pass 時作用、loop 處理連鎖 action window）都正確。實作時另需把 V2 前端 API base 改成 `/api/battleV2/*`，避免影響既有 `/mobile/battle`。
- 實際上兩個分析**互補**：如果你也想在 AI-vs-AI simulator 加同樣功能，opencode 的建議是對的；如果只針對 `/mobile/battleV2`，codex 的建議是對的。
