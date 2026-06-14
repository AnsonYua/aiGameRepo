# GCG V2 Coding Instructions

本檔只適用於 `gcgV2/` 這個子專案的程式開發、review、debug、refactor 工作。
遊戲 chat 指令、runtime 操作規則、agent-server 架構限制，仍以更高層或使用者明確要求為準。

## Karpathy 風格工作原則

### 1. 先想清楚再改

- 先明確說出目前採用的需求理解。
- 若有會影響實作的假設，先攤開。
- 若有兩種以上合理做法，先點出主要 tradeoff。
- 若風險高且不能安全猜測，先問一句短問題。
- 若任務低風險且方向清楚，可以簡短說明假設後直接做。

### 2. 先做最小可行改動

- 只實作這次需求需要的內容。
- 不預先做未被要求的抽象化、通用化或可配置化。
- 單一呼叫者不要硬拆出新 abstraction。
- 既有 repo 能簡單表達的事，不新增 dependency。
- 若第一個想法像是在設計架構，先退一步找更直接的版本。

### 3. 改動要外科手術式

- 只碰完成任務所需的檔案。
- 保持當地風格，不順手重排、改名、全面格式化。
- 只清理由自己改動造成的未使用 import / helper / variable。
- 看到無關但可疑的 dead code 或設計問題，分開說，不要混在同一個 patch。

### 4. 先定義成功條件，再宣告完成

- bug fix：指出原本壞掉的情境與修正後預期。
- feature：指出使用者可觀察到的新行為。
- refactor：指出哪些行為必須保持不變。
- review：優先列出風險、回歸點、缺測。

完成前至少做最窄但有意義的驗證；若沒跑檢查，要明講原因。

## 在這個專案的套用方式

- prompt / lesson / rule 文字修改：優先保持繁體中文。
- 不要把 Python 變成策略引擎；strategy hints 應留在 prompt / lesson 層。
- 不要為了暫時通過測試而加策略 fallback 或大量 retry。
- 優先做可回歸驗證：
  - `python3 -m py_compile ...`
  - 相關 harness
  - 直接檢查 prompt payload / viewer output / runtime log

## 非 trivial 任務的回報格式

必要時可用以下四行對齊使用者預期：

```text
Assumption:
Changed:
Verified:
Remaining risk:
```

只在任務真的有複雜度時使用；簡單改動不要硬套模板。
