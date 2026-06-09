# GCG V2 需求規格

## 1. 目標

GCG V2 的核心目標是建立一個以 LLM 為策略與卡效理解層、以 Python runtime 為真實狀態與執行層的 GCG backend。

本版本的主要產品路徑不是玩家 chat，而是：

- AI vs AI 對局
- 逐步產生 canonical `gamePlay.yaml`
- 人工 review 對局
- 將 review 結果整理成 lessons，供後續 AI decision 與 card effect interpretation 使用

## 2. 範圍

V2 先處理以下範圍：

- 支援 AI Player 自動對局
- 支援以卡牌文字與公開局面做 effect interpretation
- 支援 runtime 以 deterministic 方式驗證與套用效果
- 支援對局過程寫入 `gamePlay.yaml`
- 支援賽後人工 review 與 lesson 累積

V2 暫不要求：

- 玩家 chat UI
- 完整多使用者互動流程
- production-ready orchestration framework
- 自動 lesson 上線流程
- fine-tuning pipeline

## 3. 核心設計原則

1. Python runtime 是唯一 state mutator。
2. LLM 不直接修改 state，不直接寫 `gamePlay.yaml`。
3. LLM 主要負責：
   - effect preflight
   - AI decision
   - command resolve 語意理解
   - triggered effect interpretation 語意理解
4. Python 主要負責：
   - viewer state
   - legality validate
   - effect execute
   - trigger detect / queue / resolve orchestration
   - canonical gameplay log
5. AI 經驗成長來自可檢索、可審核、可移除的 lesson store，不依賴模型自行「永久記住」。

## 4. 主要能力需求

### 4.1 AI Player

- 系統必須支援 P1 / P2 皆由 AI 操作。
- AI Player 輸入必須是 public-safe viewer state。
- AI Player 必須輸出單一步 `COMMAND`。
- `COMMAND` 必須使用穩定的半結構化 command surface。
- AI 輸出的 `COMMAND` 必須對應 Python runtime 可接受與可解析的 command grammar。
- AI Player 可參考少量 lessons，但不能直接寫 state。

### 4.2 Effect Interpretation

- 系統必須支援以 card text + context 解讀效果。
- effect interpretation 必須分為至少兩個入口：
  - action 前的 `Effect Preflight`
  - 主動 `COMMAND` 的 `Command Resolver`
  - triggered effect 的 `Trigger Interpreter`
- effect interpretation 結果必須轉成結構化資料，不能直接以自由文字驅動 state mutation。
- 無論入口是主動 `COMMAND` 或 triggered effect，最終都必須對接同一套 Python `Runtime Validate` / `Effect Executor` contract。

### 4.3 Runtime Execution

- runtime 必須是唯一合法性驗證邊界。
- 無論是主動 action 或 triggered effect，最終都必須由同一套 Python validate / execute 流程處理。
- runtime 必須驗證：
  - timing / phase
  - cost / level
  - target legality
  - once-per-turn
  - 條件式限制
- runtime 必須以固定 primitive 套用效果。

### 4.4 Trigger / Resolve Loop System

- 系統必須支援 triggered effect detection、queue 與 resolve orchestration。
- 系統必須支援 triggered effect interpretation，並允許由 LLM 參與語意理解。
- 系統必須支援 pending choice 狀態，並由 runtime validate / execute loop 處理。
- 系統必須支援 triggered effect 的 pending choice，不只限於主 action。
- 系統必須支援 multi-step effect resolution。
- 系統必須支援 conditional effect resolution。
- 系統必須支援 runtime resolve loop。
- runtime resolve loop 必須在每次 effect apply 後持續執行 trigger detect、queue、interpretation、validate、execute，直到沒有新的 trigger effect 或 pending choice 需要處理。
- 系統必須支援 battle context 相關效果，例如：
  - blocker
  - attack redirect
  - 本戰鬥期間 AP / damage / target restriction

### 4.5 Gameplay Log

- 每局必須維護 `gamePlay.yaml`。
- `gamePlay.yaml` 是唯一 canonical gameplay log。
- `gamePlay.yaml` 必須只記錄 public-safe 資訊。
- `gamePlay.yaml` 至少包含：
  - `schema_version`
  - `game_id`
  - `summary`
  - `events`
- `events.seq` 必須單調遞增。

### 4.6 Review / Experience

- V2 必須支援人工 review `gamePlay.yaml`。
- review 的結論必須可以整理成 lesson。
- lesson 應分開至少兩類：
  - strategy lessons
  - rule / effect interpretation lessons
- lesson 寫入 experience store 可先由人工控制，不要求自動化。

## 5. 非功能需求

### 5.1 Determinism

- 相同 state + 相同 resolved intent，runtime 應產生相同結果。
- trigger detect / queue / interpret / validate / execute 的 resolve 順序必須穩定。

### 5.2 Debuggability

- 任何一步失敗都應能區分：
  - AI decision problem
  - effect interpretation problem
  - runtime validation problem
  - effect execution problem
  - trigger / resolve loop problem

### 5.3 Extensibility

- 新卡加入時，不應以每張卡 hardcode 為主路徑。
- 系統應優先擴充：
  - effect schema
  - runtime primitive
  - interpretation prompt / examples

## 6. Command Surface

V2 需要一套穩定的 command surface，作為 AI Player 與 Python runtime 之間的 contract。

但本文件暫不定案具體 DSL grammar。command surface 需於後續做完整分析後另立 spec，並以 Python runtime parser 為最終對齊目標。

## 7. 成功條件

V2 可視為達標，當以下條件成立：

1. 可穩定跑 AI vs AI 對局。
2. 對局中 AI 透過 `COMMAND` 驅動 runtime。
3. runtime 可處理 target、trigger、pending choice，以及多輪 resolve loop。
4. 每局可穩定產生 `gamePlay.yaml`。
5. 人工可根據 `gamePlay.yaml` 做 review，並把經驗沉澱成 lessons。
