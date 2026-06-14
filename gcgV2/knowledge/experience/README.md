# GCG V2 AI 經驗檔案

此目錄中的 `*.yaml` 是給 LLM 閱讀的 public-safe 戰術經驗（lessons），
不是 runtime 策略引擎，也不是 Python fallback。

**怎麼新增 / 修改 lesson、condition 詞彙表、驗證流程 → 見
[`HOW_TO_ADD_EXPERIENCE.md`](HOW_TO_ADD_EXPERIENCE.md)。**

## 目前在 gcgV2 的實際用法

```text
gcg/ai/lessons.py          載入本目錄所有 *.yaml（只讀 id / description / priority / condition）
gcg/ai/prompt_builder.py   main/block 決策時依 condition 與 public 盤面特徵過濾，
                           取 priority 最高 4 條，送 description 文字進 prompt
```

- `condition:` 只做 retrieval 過濾（決定 lesson 是否出現在 prompt），
  不評分、不選牌、不改 COMMAND；採不採用由 LLM 決定。
- `effect:` / `score_bonus:` 是舊評分引擎遺留欄位，Python 不讀取；
  舊檔案保留這些欄位僅作人工分析參考，新 lesson 不要再寫。
- mulligan 決策使用固定清單（盤面尚未成形，條件匹配無意義）：
  `early-game-no-play`、`early-game-rush`、`pilot-over-command`。

## 使用限制

- 只能提供 public-safe strategy hints；不得把 hidden hand/deck/shield
  的卡名或 card id 寫入 description。
- description 使用繁體中文，寫「原則 + 判斷方法」，不寫死一刀切規則。
- 不得在 Python 端依 lesson 內容評分、自動選牌或修改 COMMAND。

## 子目錄 `lessons/`

`lessons/` 是 draft / 待整理區，**loader 不會讀取**（只掃描本目錄第一層）。
要啟用某條 draft，整理成標準格式後移到本目錄第一層。
