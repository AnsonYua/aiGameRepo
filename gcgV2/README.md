# GCG V2 — AI vs AI Simulator

`gcgV2/` 是獨立的 AI vs AI GUNDAM CARD GAME simulator 子專案。
本檔是給後續開發者的結構導覽與修改指南；背景文件見：

- `GCG_V2_QUICK_GUIDE.md` — 快速上手與責任邊界
- `GCG_V2_MODULE_DESIGN.md` — 模組設計原則
- `GCG_V2_HIGH_LEVEL_ARCHITECTURE.md` — 高層架構
- `knowledge/experience/HOW_TO_ADD_EXPERIENCE.md` — 如何新增經驗（lessons）
- `AGENTS.md` — coding 工作原則

## 怎麼跑

```bash
cd gcgV2

# 正式：LLM player（需要 .env 的 GCG_DEEPSEEK_API_KEY）
python3 run_simulator.py

# 離線：scripted player + reference interpreter（不需 API key，僅 ST01 卡池）
python3 run_simulator.py --players scripted --interpreter reference --seed 42

# 全部測試（31 tests，含一場完整 scripted 對局）
python3 -m unittest discover -s tests -p "test_*.py"
```

## 目錄結構

```text
gcgV2/
├── run_simulator.py          # CLI 入口
├── gcg/
│   ├── config.py             # 所有路徑/常數，皆可用環境變數覆寫
│   ├── cards.py              # CardDatabase / DeckConfig
│   ├── engine/               # Python runtime：唯一 state mutator
│   │   ├── runtime.py        #   指令解析後的執行、battle 流程、勝負判定
│   │   ├── state_store.py    #   raw state、傷害/配對/資源 primitive、snapshot
│   │   ├── action_enumerator.py  # 枚舉 legal_commands（AI 只能從這裡選）
│   │   ├── viewer.py         #   raw state → 單一玩家可見的 public-safe view
│   │   ├── rules_index.py    #   卡牌關鍵字/Link/Pilot 指定的索引
│   │   ├── command_parser.py #   COMMAND 文字 → parsed command
│   │   ├── effect_engine.py / trigger_system.py  # 效果執行與 trigger loop
│   ├── ai/                   # LLM 決策層（不改 state、不驗證合法性）
│   │   ├── prompt_builder.py #   組裝決策 prompt payload（本檔最常改，見下）
│   │   ├── player_client.py  #   per-player session、system prompt、輸出正規化
│   │   ├── lessons.py        #   經驗檔 retrieval（條件過濾，非策略引擎）
│   │   └── llm_client.py     #   DeepSeek API wrapper
│   ├── gamelog/              # gamePlay.yaml / gameState.yaml / ai_trace.yaml
│   ├── effects/              # LLM 效果解讀 + SpecGate + ST01 reference
│   └── sim/                  # bootstrap（組裝 stack）、runner（對局主迴圈）
├── knowledge/
│   ├── experience/           # 經驗（lessons）yaml，見 HOW_TO_ADD_EXPERIENCE.md
│   ├── gcg-rulebook.md       # CR 規則條文（rule_excerpts 的出處）
│   └── gcg-ai-player.md      # legacy agent-server spec（未接入 gcgV2，僅參考）
├── manifests/                # 效果字典（封閉詞彙）
├── tests/                    # unittest（scripted 完整對局 + schema 驗證）
└── out/game_*/               # 每局輸出：gamePlay.yaml、gameState.yaml、ai_trace.yaml
```

## AI 決策 pipeline（一次決策的資料流）

```text
runner.py 對局主迴圈
  → viewer.py          建 public-safe viewer_state（含 remaining_hp、keywords）
  → action_enumerator  枚舉 legal_commands（合法性只在 Python 判定）
  → prompt_builder.py  組 payload：
       instructions / legal_commands / viewer_state / viewer_markdown
       + card_reference     （相關卡牌效果文字）
       + rule_excerpts      （依決策類型的 CR 條文摘錄）
       + strategy_notes     （依決策類型的靜態戰術提示）
       + attack_annotations （每條 attack 的規則計算結果預覽）
       + block_annotations  （阻擋互換的計算結果）
       + pair_annotations   （每條 pair 是否形成 Link + 加成數值）
       + experience_summaries（條件匹配選出的 lessons，見 lessons.py）
  → player_client.py   送 LLM，要求兩行輸出 CONSIDER / COMMAND
  → command_parser.py  解析 COMMAND
  → runtime.py         驗證 + 執行 + 寫 log（唯一 state mutator）
```

決策類型（`prompt_builder._decision_kind`）：
`mulligan` / `turn_order` / `pending_choice` / `main` / `block` / `action`。

## 責任邊界（修改前必讀）

- **Python 不做策略決定。** annotations 只能輸出規則計算的「事實」
  （誰被擊破、破幾盾、是否 Link、是否直擊獲勝），不能輸出「有利/不利/建議」。
- **策略文字放 prompt 層**：strategy_notes、system prompt 檢查表、lessons。
- **lessons 的 condition 只做 retrieval 過濾**（決定哪些 lesson 出現在 prompt），
  不做評分、不改 COMMAND；採不採用由 LLM 決定。
- 玩家與 review 可見文字一律繁體中文；識別字 / command syntax 維持英文。
- prompt 內容必須 public-safe：不得含對手手牌/牌庫/盾牌的卡名或 card id。

## 常見修改對照表

| 想改什麼 | 改哪裡 |
|---|---|
| AI 在某類局面下判斷錯誤（策略層） | 先考慮 `knowledge/experience/*.yaml` 新 lesson（條件匹配，見 HOW_TO_ADD_EXPERIENCE.md）；通用原則才加 `prompt_builder.py` 的 `_STRATEGY_NOTES` |
| AI 不懂某條規則 | `prompt_builder.py` 的 `_RULE_EXCERPTS`（引用 `knowledge/gcg-rulebook.md` 的 CR 編號） |
| AI 算錯戰鬥數學 / 看不出規則後果 | `prompt_builder.py` 的 annotation 方法（`_annotate_attacks` / `_annotate_blocks` / `_annotate_pairs`）；只加「事實」 |
| 決策優先序 / 輸出格式 | `player_client.py` 的 `_default_system_prompt` |
| 新增合法指令種類 | `action_enumerator.py` + `command_parser.py` + `runtime.py`（三處都要） |
| 新卡 / 新效果 | 優先補 card data 與效果字典詞彙，不要替單卡寫 Python |
| gamePlay.yaml 記錄內容 | `gamelog/gameplay_logger.py` + `state_store.build_gameplay_snapshot`（此檔含雙方手牌明細，僅供 review/debug，不可餵給 AI prompt） |

## 修改後驗證（最低要求）

```bash
python3 -m py_compile gcg/ai/prompt_builder.py   # 改了哪個檔就 compile 哪個
python3 -m unittest discover -s tests -p "test_*.py"
```

改 prompt 層時，建議再寫一個一次性 smoke script：手工構造 viewer_state、
呼叫 `PromptBuilder.build()`、印出 payload 確認新欄位 / lesson 是否出現
（參考 git log 中近期修改的驗證方式）。

最終驗證永遠是跑一場 live 對局，然後 review `out/game_*/`：

- `gamePlay.yaml` — canonical 結構化 log（事件 + 每步 features，含雙方手牌）
- `ai_trace.yaml` — 每次 LLM 決策的完整 prompt 與回覆（查「模型看到了什麼」）
- `gameState.yaml` — public-safe 最終狀態

Review 失誤時先分類：模型沒看到資訊（補 annotation / lesson / note）
vs 看到了但判斷錯（改 lesson / note 措辭、調 priority）
vs 規則執行錯（engine bug，改 Python 並補測試）。
