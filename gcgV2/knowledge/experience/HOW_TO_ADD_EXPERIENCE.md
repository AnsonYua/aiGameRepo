# 如何新增經驗（Lesson）

本文說明 gcgV2 的經驗（lesson）機制：檔案格式、條件詞彙、選入流程，
以及新增一條 lesson（或新增一種條件）時需要更動哪些檔案。

## 機制總覽

```text
knowledge/experience/*.yaml          ← lesson 檔（你要加的東西）
        │ 載入：gcg/ai/lessons.py  load_experience_summaries()
        ▼
main / block 決策時：
  gcg/ai/prompt_builder.py  _lesson_features()   從 public viewer_state 算盤面特徵
  gcg/ai/lessons.py         match_summaries()    用 lesson 的 condition 過濾
        │ 符合者依 priority 由高到低取前 4 條
        ▼
payload["experience_summaries"]      ← 只送 id + description 文字給 LLM
```

設計邊界（不可違反）：

- condition 只決定「這條 lesson 要不要出現在 prompt」，**不做評分、不選牌、
  不改 COMMAND**。採不採用由 LLM 決定。
- `effect:` / `score_bonus:` 是舊評分引擎遺留欄位，Python **不讀取**；
  新 lesson 不要再寫這兩個欄位。
- description 必須 public-safe：不得引用對手隱藏手牌/牌庫/盾牌內容，
  不得寫死特定 slot / card id 當作指令範例。
- description 用繁體中文。

## Lesson 檔案格式

一個檔案一條 lesson，放在 `knowledge/experience/` 下：

```yaml
# 一句話說明這條經驗的來源（哪一局、哪個 turn、什麼失誤）。
#
# 註：此檔僅作 public-safe prompt/context 素材，不是 Python 策略 fallback。
id: race-shield-push          # 唯一 id（= 檔名去掉 .yaml）
priority: 10                  # 越高越先被選入（同時符合的 lesson 取前 4 條）
description: '對手基地已毀時，每次攻擊防禦層固定破 1 盾。先數回合：…'
condition:                    # 全部條件都符合才會出現（AND）
  enemy_base_present: false
  my_units_min: 2
```

寫 description 的建議：

- 寫「原則 + 判斷方法」，不要寫死「永遠做 X」。
  例：`全部攻擊防禦層通常優於分兵擊殺單位；擊殺單位只在能阻止對手反向斬殺時才優先`
  優於 `永遠打臉`。一刀切規則會在反例局面製造新 bug。
- 一條 lesson 只講一件事；想講兩件事就拆兩個檔案。
- priority 參考：致勝/保命類 9-10，價值判斷類 7-8，節奏偏好類 ≤6。

## 目前支援的 condition 詞彙

定義在 `gcg/ai/lessons.py` 的 `_CONDITION_CHECKS`；
特徵值來源是 `gcg/ai/prompt_builder.py` 的 `_lesson_features()`。

| condition key | 意義 |
|---|---|
| `turn_min` / `turn_max` | 回合數下限 / 上限 |
| `my_units_min` / `my_units_max` | 我方場上單位數 |
| `my_empty_slots_min` / `my_empty_slots_max` | 我方空格數 |
| `enemy_units_min` / `enemy_units_max` | 對手場上單位數 |
| `enemy_rested_units_min` | 對手橫置單位數下限 |
| `enemy_damaged_units_min` | 對手受傷單位數下限 |
| `my_base_hp_max` | 我方基地剩餘 HP 上限（基地不存在視為 0） |
| `my_base_present` / `enemy_base_present` | 我方 / 對手基地是否存在（bool） |
| `my_shields_min` / `my_shields_max` | 我方盾牌數 |
| `enemy_shields_min` / `enemy_shields_max` | 對手盾牌數 |
| `has_link_units` | 我方場上是否有「未 Link 且有 Link 名單」的單位（bool） |
| `has_unpaired_units` | 我方場上是否有未配對 Pilot 的單位（bool） |

注意：寫了表中不存在的 key，該 lesson 會**永遠不匹配**（fail-safe），
不會報錯——新增 lesson 後務必跑下面的 smoke 驗證。

## 新增一條 lesson（詞彙夠用時）

只需要做兩件事：

1. 在 `knowledge/experience/` 新增 `<id>.yaml`（格式如上）。
2. 驗證（見下）。

不用改任何 Python——loader 會自動掃描目錄下所有 `*.yaml`。

## 新增一種 condition（詞彙不夠時）

需要改兩個檔案：

1. `gcg/ai/lessons.py` — 在 `_CONDITION_CHECKS` 加一個 key → lambda。
2. `gcg/ai/prompt_builder.py` — 在 `_lesson_features()` 補對應特徵值。
   特徵只能從 public viewer_state（必要時加 card_db 的卡面資料）計算，
   不得讀 hidden state。

跨區條件（例如「手牌裡有對應 Link Pilot」）需要同時看 hand 與 battle_area，
也是在 `_lesson_features()` 算好 bool 再給 condition 用。

## 驗證步驟

```bash
cd gcgV2

# 1. compile（若改了 Python）
python3 -m py_compile gcg/ai/lessons.py gcg/ai/prompt_builder.py

# 2. smoke：構造目標盤面，確認 lesson 會 / 不會出現
python3 - <<'EOF'
from gcg.ai.prompt_builder import PromptBuilder
from gcg.cards import CardDatabase

pb = PromptBuilder(card_db=CardDatabase())
# 構造最小 viewer_state（參考 tests/ 或 git log 中的 smoke 範例），
# 重點：players 兩邊的 battle_area / base / shield_count / turn 要符合你的 condition
# payload = pb.build({'viewer_state': vs, 'markdown': ''}, ['pass'])
# print([l['id'] for l in payload.get('experience_summaries', [])])
EOF

# 3. 全套測試
python3 -m unittest discover -s tests -p "test_*.py"

# 4. 最終：跑一場 live 對局，在 out/game_*/ai_trace.yaml 搜你的 lesson id，
#    確認它在預期的決策出現，且模型的 CONSIDER 有回應它
python3 run_simulator.py
```

## 從 replay review 沉澱 lesson 的流程

1. Review `out/game_*/gamePlay.yaml`（事件 + 每步 features，含雙方手牌明細）
   找到失誤的 turn / seq。
2. 開 `out/game_*/ai_trace.yaml` 找同一決策，先分類：
   - **模型沒看到資訊** → 優先補 annotation（`prompt_builder.py`）或 rule excerpt，
     不是 lesson；
   - **看到了但價值判斷錯** → 適合 lesson（本文流程）；
   - **所有局面都該遵守的通用原則** → 放 `_STRATEGY_NOTES` 或 system prompt
     檢查表（`player_client.py`），不要佔 lesson 名額。
3. 寫 lesson 時在檔頭註解標明來源對局與 turn，方便日後回溯。
4. 跑上面的驗證；下一場對局 review 時確認該失誤類型不再出現。
