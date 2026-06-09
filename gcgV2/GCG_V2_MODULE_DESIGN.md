# GCG V2 Module Design

## 1. 設計目的

GCG V2 是一個 AI vs AI 的 GUNDAM CARD GAME simulator program。P1 AI 與 P2 AI 自動對戰，系統把每一步決策、卡效解讀、驗證結果、state change、trigger 與規則處理寫入 canonical `gamePlay.yaml`。人之後用這份 log 做 review，再整理成 lessons。

這份設計的重點，是讓 Python 保持短、穩、清楚。Python 不負責理解每張卡的自然語言卡文；Python 只負責 state、validate、primitive execute、rules management、trigger loop 與 log。LLM 負責理解卡文、看公開局面、做決策，並把效果轉成 structured intent。

簡單講，LLM 可以說「這張卡要選 1 個 rested enemy Unit，然後造成 1 damage」，但真正扣血、移區、判定 destroyed、寫入 log 的人，一定是 Python。

## 2. 設計原則

第一，Python runtime 是唯一 state mutator。只要會改 damage、zones、resource、battle context、trigger queue 或勝負結果，就一定要經過 Python。

第二，新卡加入時，不應先想「要不要為這張卡寫一段 Python」。應先問：這張卡能不能被現有 schema 與 primitives 表示？如果可以，只要新增 card data 與 interpretation example。如果不可以，才新增 generic support。

第三，runtime 要 deterministic。相同 state 加相同 resolved intent，應產生相同結果。

第四，`gamePlay.yaml` 不是普通 replay，而是 review 與 debug 的基礎，所以每一步都要可追。

例子：卡文是 `Choose 1 rested enemy Unit. Deal 1 damage to it.`。LLM 可以輸出 target requirement 與 `deal_damage`。Python 要負責檢查 target 是否真的存在、是否敵方、是否 rested，然後才扣 1 damage。

## 3. Top-Level Modules

第一版建議只保留這些 top-level modules：

```text
simulator_runner
state_store
card_database
viewer_state_builder
ai_player_client
command_parser
llm_effect_interpreter
runtime_core
primitive_executor
gameplay_logger
review_system
lesson_store
card_onboarding_reviewer
```

這個 list 刻意保持短。像 turn flow、battle flow、Burst、keyword、choice、trigger ordering 這些邏輯，第一版先放在 `runtime_core` 內部，不急著拆成很多獨立 module。先把系統跑穩，比先把名字拆細更重要。

## 4. `simulator_runner`

`simulator_runner` 是整個 simulator 的入口。它負責開局、推進主迴圈、要求 AI 決策、把 command 交給 runtime，直到 game over。

它不解讀卡文，也不直接改 state。它只負責 orchestration。

例子：現在輪到 P1 main phase。`simulator_runner` 先建立 P1 的 viewer state，再叫 P1 AI 出一個 command，例如 `play_card hand_3 target enemy_unit_2`，然後把這個 command 交給 runtime。

## 5. `state_store`

`state_store` 是真實遊戲狀態。它保存牌在哪裡、每個物件的 instance id、damage、turn / phase / step、priority、battle context、trigger queue、pending choice queue 與 duration effects。

它是 source of truth，但不自己做策略判斷，也不自己理解卡文。

例子：一張 Unit 從 battle area 進 trash，之後又回到 hand。雖然 card id 一樣，但 runtime 應把它當成新物件，所以 `state_store` 需要 object instance id。

## 6. `card_database`

`card_database` 保存卡牌靜態資料，例如 card type、Lv、cost、AP、HP、traits、effect text、Burst text、token data。

它只提供資料，不做解讀。

例子：runtime 知道 `hand_3` 是 `ST01-012` 後，會到 `card_database` 讀它的卡文，再交給 interpreter 理解。

## 7. `viewer_state_builder`

`viewer_state_builder` 把真實 state 轉成 public-safe viewer state。AI 只能看這份資料，不能直接看 raw state。

Viewer state 應包含自己手牌、公開場面、目前 phase、priority、battle context，以及 queue head 的 pending choice options。它不能包含對手 hidden hand、deck order、hidden shield identity。

例子：P1 可以看到自己手牌有 `ST01-012`，也可以看到 P2 場上有一個 rested Unit；但 P1 不可以看到 P2 shield 裡是哪張卡。

## 8. `ai_player_client`

`ai_player_client` 是 AI Player 的 wrapper。它把 viewer state 與 lessons 傳給 LLM，要求 LLM 回傳單一步 command。

它可以做基本格式檢查，但不負責判斷這步是否合法。

例子：AI 可以回 `attack unit_1 shield`、`play_card hand_3 target enemy_unit_2` 或 `pass`。如果 AI 在錯 timing 出牌，runtime 之後會 reject。

## 9. `command_parser`

`command_parser` 把 AI command 轉成 `ParsedCommand`。它只處理 grammar，不處理卡效語意，也不替 AI 猜 target。

第一版 command type 可以先支援 `play_card`、`activate_effect`、`attack`、`block`、`pass`、`choose`、`order_triggers`、`decline_optional`。

例子：`play_card hand_3 target enemy_unit_2` 會被 parse 成 source 是 `hand_3`，target 是 `enemy_unit_2`。如果 AI 只寫 `play_card hand_3`，parser 不會替它補 target。

## 10. `llm_effect_interpreter`

`llm_effect_interpreter` 是讓 Python 保持 lean 的核心。它讀卡文與 context，輸出 structured intent。

這份 intent 應包含 source、timing、cost、target requirement、已選 target、condition、primitive sequence、optional flag、duration。

Interpreter 不驗證合法性，不改 state，不決定 trigger priority。它只負責把「文字」變成「結構」。

例子：卡文是 `Choose 1 rested enemy Unit. Deal 1 damage to it.`，AI 已選 `enemy_unit_2`。Interpreter 可以輸出：

```json
{
  "targets": [
    {
      "id": "enemy_unit_2",
      "filter": {
        "controller": "opponent",
        "card_type": "unit",
        "status": "rested"
      }
    }
  ],
  "steps": [
    {
      "primitive": "deal_damage",
      "target": "enemy_unit_2",
      "amount": 1
    }
  ]
}
```

另一個例子：卡文是 `All friendly Link Units get AP+1 during this turn.`。Interpreter 應輸出「target filter = all friendly Link Units」與「primitive = register_duration_effect」。

## 11. `runtime_core`

`runtime_core` 是 Python 的裁判核心。它負責 phase / step、priority、play card flow、cost / Lv、battle flow、Burst、trigger ordering、rules management、pending choice queue 與 game over。

它不應該把每張卡的自然語言效果寫死在 Python 裡。它的工作是接收 `ParsedCommand` 與 structured intent，然後做 validate、execute、rules、trigger loop。

基本流程是：

1. 收到 `ParsedCommand`
2. 必要時呼叫 `llm_effect_interpreter`
3. 驗證 timing、priority、cost、target、condition
4. 若資訊不足，建立 pending choice queue item
5. 若合法，呼叫 `primitive_executor`
6. 執行 rules management
7. 偵測與 resolve triggers
8. 重複直到穩定

例子：AI 用一張 command card 指定一個 rested enemy Unit。runtime 先檢查現在是否可用這張卡、cost 是否足夠、target 是否合法，之後才扣 damage。若 damage 後 HP 歸零，再由 rules management 把 Unit 移去 trash，之後再檢查 destroyed trigger。

## 12. `primitive_executor`

`primitive_executor` 是真正改 state 的地方，但它只能執行已經 validate 的 primitive。

Primitive 應小而固定，例如 `move_card`、`deploy_card`、`pair_pilot`、`rest`、`set_active`、`deal_damage`、`heal_damage`、`draw_card`、`add_to_hand`、`create_token`、`register_duration_effect`。

例子：Interpreter 輸出 `deal_damage(target=enemy_unit_2, amount=1)`。Executor 只把 damage 加 1。它不自己判斷 destroyed；那是 runtime 的工作。

## 13. `gameplay_logger`

`gameplay_logger` 負責寫 canonical `gamePlay.yaml`。這是 simulator 的主要輸出。

它應記錄 AI command、interpreted intent、validation result、primitive delta、rules result、trigger events、pending choice queue item、phase change 與 game result。

它不能寫 hidden raw state。

例子：P1 打掉 P2 一張 shield。Logger 可以寫「P1 的攻擊造成 1 次 shield break」，但不可以把那張未公開 shield 的 card id 直接寫進 log。

## 14. `review_system`

`review_system` 讀 `gamePlay.yaml`，幫人或 AI 做賽後 review。

它的工作不是修正結果，而是分類問題：AI decision problem、effect interpretation problem、runtime validation problem、execution problem、rules problem、trigger ordering problem。

例子：AI 明明快被斬殺，卻仍然部署一張不能防守的 Unit。這應被標成 AI decision problem，而不是 runtime bug。

## 15. `lesson_store`

`lesson_store` 保存 lessons，供 AI decision 與 effect interpretation 使用。

它不應變成 Python 的策略 fallback。Python 不能因為某條 lesson 覺得 AI 這步不好，就偷偷改 command。

例子：lesson 可以寫「面臨 lethal race 時，優先保留 blocker」。AI 可以參考；runtime 不可以代 AI 改答案。

## 16. `card_onboarding_reviewer`

`card_onboarding_reviewer` 用來看新卡是否被現有 runtime 支援。它會讀卡文，嘗試映射到現有 schema 與 primitives。

如果現有 support 足夠，就只新增 card data 與 example。如果不足，就指出缺少哪個 generic capability。

例子：新卡寫 `Look at the top 3 cards of your deck. Add 1 Unit to your hand and place the rest at the bottom of your deck.`。如果 runtime 還沒有 `look_top_cards` 或 `move_to_bottom_deck`，reviewer 就應要求新增這些 generic primitives。

## 17. Program Flow

一局對戰的大流程應該很清楚。`simulator_runner` 要求 AI 出 command，`command_parser` 解析 command，`llm_effect_interpreter` 把卡文轉成 structured intent，`runtime_core` 做 validate 與流程控制，`primitive_executor` 改 state，`gameplay_logger` 把結果寫進 `gamePlay.yaml`。

Pending choice queue 不是每次都要經過。只有 command 缺少必要 target、mode、optional decision 或 trigger ordering 時，runtime 才建立 queue item。若 AI 一開始已經給齊，例如 `play_card hand_3 target enemy_unit_2`，就直接 validate 與 execute。

例子：AI 使用 `ST01-012` 並指定對手一個 rested Unit。Interpreter 轉成 `deal_damage 1`。Runtime 驗證 target 合法後執行 damage，之後 rules management 檢查是否 destroyed，再把整件事寫進 `gamePlay.yaml`。

## 18. New Card Flow

新卡加入時，先做 support review，再決定要不要改 Python。

流程應是：

1. 新增 card data
2. 用 `card_onboarding_reviewer` 分析卡文
3. 檢查現有 schema 與 primitives 是否足夠
4. 若不足，只新增 generic support
5. 用 fixture 或 AI vs AI 測試
6. 檢查 `gamePlay.yaml` 是否合理

例子：若新卡只是「對 1 個 enemy Unit 造成 1 damage」，通常不需要改 Python。若新卡是「雙方同時選擇一張手牌丟棄」，就可能要新增 generic simultaneous choice support。

## 19. 邊界總結

LLM-facing modules 是 `ai_player_client`、`llm_effect_interpreter`、`card_onboarding_reviewer`。它們負責理解、決策與分析，但不改 state。

Runtime-facing modules 是 `runtime_core` 與 `primitive_executor`。它們負責驗證、執行、規則處理與 trigger loop。

Data-facing modules 是 `state_store`、`card_database`、`viewer_state_builder`、`gameplay_logger`、`lesson_store`。它們負責保存資料、顯示資料與記錄資料。

這樣的分工有一個實際好處：新卡大多只需要新增 card data 與 interpretation support，不需要每次都改一堆 Python 邏輯。
