"""GCG V2 backend package.

Layering（由下而上）：

- ``gcg.config``    路徑與環境設定
- ``gcg.cards``     卡牌資料與牌組載入
- ``gcg.engine``    deterministic game engine（唯一 state mutator）
- ``gcg.effects``   effect dictionary harness 與 LLM 即時效果解讀
- ``gcg.ai``        LLM player 決策與 prompt 組裝
- ``gcg.gamelog``   gamePlay.yaml / gameState.yaml / ai_trace.yaml 寫入
- ``gcg.sim``       AI vs AI simulator orchestration

責任邊界：

- LLM 只輸出「選擇」（AI player）與「結構化 effect spec」（interpreter）。
- Python engine 負責合法性、目標枚舉、條件評估、primitive 執行與所有 state 變更。
"""
