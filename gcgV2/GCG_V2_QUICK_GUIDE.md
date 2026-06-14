# GCG V2 Quick Guide

## 這個資料夾是什麼

`gcgV2/` 是一個 AI vs AI simulator 子專案。

- 目標：讓 AI 用 COMMAND 驅動 Python runtime 對戰
- 輸出：每局產生 canonical `gamePlay.yaml`（外加 `gameState.yaml`、`ai_trace.yaml`）
- 用途：debug、review、沉澱 lessons

## 怎麼跑

```bash
cd gcgV2

# 正式：LLM player + LLM 即時效果解讀（需要 .env 的 GCG_DEEPSEEK_API_KEY）
python3 run_simulator.py

# 離線：scripted player + reference interpreter（不需 API key，僅 ST01 卡池）
python3 run_simulator.py --players scripted --interpreter reference --seed 42

# 測試
python3 -m unittest discover -s tests -p "test_*.py"
```

## 責任邊界（最重要的一件事）

- **LLM 只做兩件事**：
  1. AI Player：從 Python 枚舉好的 `legal_commands` 中逐字選 1 條
  2. Effect Interpreter：對局中即時把卡牌文字翻譯成結構化 effect spec
     （只能使用 `manifests/GCG_V2_EFFECT_DICTIONARY.yaml` 的封閉詞彙）
- **Python engine 做其餘一切**：合法性、目標枚舉、條件評估、primitive 執行、
  trigger/resolve loop、phase machine、所有 state 變更、logging。
- LLM 輸出進 executor 前必過 `SpecGate`；gate 失敗 → re-prompt 一次 → 再失敗就拒絕，
  分類為 interpretation problem，不執行、不猜測。

## 目前最重要的檔案

- `run_simulator.py`：CLI 入口
- `gcg/sim/runner.py`：對局主迴圈（advance → 枚舉 → 問 AI → parse → resolve）
- `gcg/sim/bootstrap.py`：整個 stack 的接線
- `gcg/engine/runtime.py`：runtime facade（單一 resolve pipeline、phase machine、battle、trigger loop）
- `gcg/engine/state_store.py`：真實 state 容器（source of truth 在記憶體）
- `gcg/engine/action_enumerator.py`：合法 COMMAND 枚舉（AI 的選單）
- `gcg/engine/effect_engine.py`：目標枚舉、條件評估、primitive executor
- `gcg/engine/trigger_system.py`：trigger 偵測與 queue
- `gcg/engine/rules_index.py`：per-card 偵測（keyword / trigger timing / 可否攻擊玩家）
- `gcg/effects/interpreter.py`：LLM 即時效果解讀（含 cache 與 SpecGate）
- `gcg/effects/spec_gate.py`：effect spec schema 驗證
- `gcg/effects/reference_st01.py`：ST01 人工標準答案 spec（測試/離線/對照用，非主路徑）
- `gcg/ai/prompt_builder.py` + `gcg/ai/player_client.py`：決策 prompt 與 LLM player
- `gcg/gamelog/`：gamePlay.yaml / gameState.yaml / ai_trace.yaml 寫入
- `gcg/engine/viewer.py`：public-safe viewer state + markdown

## Command surface

```
choose <option_id>                 回答 pending choice
play_card <card_id> [<slot>]       部署 Unit / 使用 Command 卡 / 部署 Base
pair <card_id> my_slot_<n>         配對 Pilot（或 [Pilot] 指定的 Command 卡）
activate_effect base               發動基地 [Activate/Main] 能力
attack my_slot_<n> <target>        target = opponent_base | opponent_slot_<n>（限 rested）
block my_slot_<n>                  以 Blocker 阻擋
pass / end turn                    讓過
```

AI 一律從 `legal_commands` 逐字複製，不自行發明指令。

## 讀 code 的順序建議

1. `gcg/sim/runner.py`（主迴圈）
2. `gcg/engine/runtime.py`（resolve pipeline）
3. `gcg/engine/effect_engine.py` + `gcg/effects/spec_gate.py`（效果執行契約）
4. `gcg/engine/action_enumerator.py`
5. `gcg/effects/interpreter.py`（LLM 入口）

## 如果你接下來要做事

- 想補流程：先看 `gcg/sim/runner.py`
- 想補規則：先看 `gcg/engine/runtime.py`
- 想補效果詞彙：改 `manifests/GCG_V2_EFFECT_DICTIONARY.yaml` + `gcg/engine/effect_engine.py` 的 primitive handler
- 想補 AI 決策 prompt：先看 `gcg/ai/prompt_builder.py`
- 想補 lessons：先看 `knowledge/experience/`
- 新卡池回歸測試：在 `gcg/effects/reference_st01.py` 模式下補人工 spec，對照 LLM 輸出
