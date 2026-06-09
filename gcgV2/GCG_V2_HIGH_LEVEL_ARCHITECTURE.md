# GCG V2 高階架構

## 1. 目標

GCG V2 是 AI vs AI 對戰 simulator。P1 AI 與 P2 AI 依照 GUNDAM CARD GAME 規則自動對局，runtime 把每一步寫入 canonical `gamePlay.yaml`，供 replay、debug、review 與 lesson 使用。

核心邊界很簡單：LLM 負責理解卡文、讀公開局面、做策略決策；Python runtime 負責規則、合法性、狀態修改、勝負判定與 log。LLM 不直接移牌、不扣血、不決定勝負、不寫 canonical log。

例子：卡文是「Choose 1 rested enemy Unit. Deal 1 damage to it.」LLM 可以解讀成「需要 1 個 rested enemy Unit target，造成 1 damage」。Python 必須檢查 timing、target 是否存在、是否為敵方 Unit、是否 rested。通過後，Python 才扣血、把 command 放入 trash，並寫入 `gamePlay.yaml`。

```text
Harness -> Runtime Kernel -> Viewer State -> Effect Preflight
-> AI Player COMMAND -> Effect Interpreter -> Runtime Validate
-> Effect Executor -> Rules Management -> Trigger System
-> Gameplay Logger -> Review / Lessons
```

Pending choice 只在資料不足時建立。如果 AI 已提供完整 target、mode、optional choice 或 trigger order，runtime 直接 validate / execute。如果缺資料，runtime 暫停，建立 pending choice queue item，放進 pending choice queue，交回 AI 回答。

例子：`play_card hand_3 target enemy_unit_2` 且 target 合法時，直接 resolve。若 AI 只輸出 `play_card hand_3`，但卡需要 target，runtime 建立 `choice_7` 並列出合法 target。AI 下一步輸出 `choose choice_7 enemy_unit_2`。

## 2. Runtime Kernel

Runtime Kernel 是 Python 裁判。它控制 setup、mulligan、先後手、phase、action window、priority、pending choice queue、trigger queue、rules management 與 game over。這些流程必須 deterministic，不能交給 LLM 猜。

Main phase 也不是自由聊天區。Runtime 必須知道 active player、phase、可用 timing 與合法 action。AI 只能在合法窗口輸出 command。

例子：現在是 P1 main phase。P1 可以 deploy Unit、使用 Main timing command、activate `Activate/Main`、attack 或 pass。若 P2 輸出 deploy，runtime 必須拒絕，因為不是 P2 的 main phase。

## 3. Rules Management

Rules Management 是自動裁判層。它在 effect 改完 state 後，立刻處理敗北判定、HP 歸零破壞、shield 破壞、Base replacement、battle area 上限、移區後 object identity reset，以及「效果無法完整執行時盡可能執行」。

Resolve 順序固定：

```text
Validate -> Execute -> Rules Management
-> Trigger Detection -> Trigger Queue -> Trigger Resolve
-> repeat until stable
```

例子：Unit 剩 1 HP，受到 1 damage。Executor 只套用 damage。Rules Management 發現 HP 歸零，移到 trash，產生 destroyed event。Trigger System 再依 destroyed event 找 trigger。

Base replacement 也在這裡處理。部署新 Base 時，舊 Base 放入 trash，但這不是 destroyed，不應觸發 destroyed trigger。

## 4. Battle 與 Action Window

Battle 不能只是單一 `attack`。Runtime 要拆成：

```text
attack declaration -> block step -> action step
-> damage step -> battle end step
```

Battle context 存在 runtime state，不由 LLM 推測。它記錄 attacking unit、original target、current target、blocker、battle step 與 during-this-battle effects。

Action window 也要獨立建模。Action step 由 standby player 先拿 priority。雙方輪流用 Action timing command、Activate/Action effect，或 pass。雙方連續 pass 後，action step 才結束。Runtime 需要記錄 priority player、last action player、consecutive pass count、window origin 與 current timing。

例子：P1 攻擊 P2 shield。進入 action step 時，P2 先有 priority。P2 可用 Action command 或 pass。P2 pass 後 priority 給 P1。P1 也 pass，才進 damage step。

## 5. LLM 責任

LLM 有三個入口，但都不改 state。

Effect Preflight 讀 viewer state、卡文、候選物件與 lessons，產生可行動作與缺少資訊。AI Player 根據 public-safe viewer state 與 candidate actions，輸出單一步 runtime command。Effect Interpreter 把卡文、command、trigger context 轉成 `resolved intent`；若資訊不足，回傳 unresolved requirements，讓 runtime 建 pending choice。

例子：卡文是「Choose 1 enemy Unit with 2 or less HP. Rest it.」Effect Interpreter 可以輸出 target filter：enemy Unit 且 HP <= 2，effect step：rest target。它不能自己選 target，也不能把 Unit rest。

## 6. Resolved Intent Contract

主動行動與 trigger 不應有兩套 executor。所有效果最後都轉成同一種 `resolved intent`，交給同一套 validate / execute / rules / trigger loop。

`resolved intent` 至少包含 intent type、source instance id、controller、timing、cost spec、target spec、effect steps、optional flag、duration、requires choice 與 rules text reference。

Executor 只接受固定 primitive，例如 pay cost、move card、deal damage、rest、active、deploy、pair pilot、modify AP/HP、register duration effect、draw card、reveal card。若新卡無法用現有 primitive 表示，優先擴充 generic primitive 或 schema，不寫單卡 special case。

例子：手牌 command 的 `deal 1 damage` 和 Deploy trigger 的 `deal 1 damage` 來源不同，但 primitive 相同。Runtime 只需要一套 damage validate / execute。

## 7. Trigger System

Trigger System 由 Python 控制偵測、排序與 resolve。LLM 可解讀 trigger 文字，但不能決定 priority。

Trigger Queue 規則：Burst 優先；同一玩家多個 trigger 由該玩家排序；雙方同時 trigger 時 active player 先處理；resolve 中新產生的 trigger 依固定 priority 插入。

Trigger 可能需要 optional choice、target、mode、排序或 multi-step resolve。缺少選擇時，runtime 建 pending choice queue item，讓 AI 回答 `choose`、`order_triggers` 或 `decline_optional`。

例子：P1 和 P2 同時有 Deploy trigger。Trigger Queue 先處理 active player 的 trigger，再處理 standby player。若第一個 trigger resolve 時又產生新 trigger，新 trigger 依 priority 插入，不由 LLM 自行排位。

## 8. Command Surface 與 Pending Choice

AI 與 runtime 之間要有穩定 command surface。V2 初期不必完成完整 DSL，但不能依賴自由自然語言。最小 command 類型是 `play_card`、`activate_effect`、`attack`、`block`、`pass`、`choose`、`order_triggers`、`decline_optional`。

Pending choice queue item 必須包含 choice id、owner、legal options、restrictions、optional flag 與 resume context。

例子：一張 command 有兩個 mode。AI 只輸出 `play_card hand_2`。Runtime 不猜 mode，而是建立 `choice_12`，options 是 `draw_1`、`deal_1_damage`。AI 回答 `choose choice_12 deal_1_damage` 後，runtime 繼續 resolve。

## 9. State Model

State 分三層：真實狀態是 source of truth，例如 zone、damage、resource active；衍生狀態由 continuous effects、duration effects、Pilot 修正與 battle context 算出；流程狀態包含 turn、phase、priority、battle、pending choice queue、trigger queue。

Runtime 至少維護 `base_state`、`derived_state`、`turn_state`、`priority_state`、`action_window`、`battle_context`、`pending_choice` queue、`trigger_queue`、`continuous_effects` 與 `object_instance_id`。

`object_instance_id` 很重要。卡牌移到新 location 後是新物件，舊 target、duration effect、once-per-turn tracking 不應套到新物件。

例子：Unit 從 battle area 進 trash，再被效果拿回 hand。即使 card id 相同，也要給新的 `object_instance_id`。舊 battle 的 `during this battle` buff 不可延續。

Viewer State Builder 從真實 state 產生 public-safe viewer state。AI 可看自己的手牌，但不可看對手 hidden hand、deck order、hidden shield identity。`gamePlay.yaml` 也遵守同樣原則。

## 10. Gameplay Log 與 Review

`gamePlay.yaml` 是 canonical log，不是普通 replay。它至少包含 `schema_version`、`game_id`、`summary`、`events`。Event `seq` 必須單調遞增，且可被 `yaml.safe_load` 解析。

Log 應記錄 AI command、resolved intent、validate 結果、execute 結果、rules management 結果、trigger enqueue / order / resolve、pending choice queue item 建立與完成、phase / battle / priority transition，以及 public-safe state delta。

Log 不寫 hidden hand identity、hidden deck order、hidden shield identity 或內部 prompt。涉及 hidden card 時，用 public-safe 文字。

例子：shield 被破壞時，log 寫「P2 一張 shield 被破壞」。如果該 shield 是 Burst 並公開加入 hand，才記錄公開的 card id。不要 dump raw state。

Review 用 log 分類問題：AI decision、effect interpretation、runtime validation、effect execution、trigger / resolve loop、rules management、provider latency。

例子：AI 在 action step 沒 blocker 卻 pass。Reviewer 看 `gamePlay.yaml`：viewer state 是否列出合法 blocker？AI 輸出什麼？runtime validate 是否正確？這樣才能判斷是 AI、display 還是 runtime 問題。

## 11. Review / Lesson Store

Lesson store 不參與 state mutation。它只提供可檢索、可審核、可移除的 lessons 給 LLM 使用。

Strategy lesson 幫 AI Player 做決策。Rule / effect interpretation lesson 幫 Effect Interpreter 穩定解讀卡文。Python 不可根據 lesson 自動選牌、評分或改 COMMAND。

例子：review 發現 AI 快被斬殺時仍 deploy 不能防守的 Unit。這可以寫成 strategy lesson：「面臨下回合 lethal 時，優先增加 blocker 或降低對手攻擊數。」Python runtime 不可以自動把 deploy 改成 block。

## 12. New Card Onboarding

加入新卡前，先做 card effect support review。Review 問三件事：卡文能否轉成現有 `resolved intent`？target filter、choice、duration、condition 是否已支援？現有 primitive 是否足夠？

若足夠，只新增卡牌資料、必要 interpretation example，並跑 fixture 或最小對局。若不足，新增 generic primitive 或 schema extension，不寫 `if card_id == ...`。

例子：新卡是「All friendly Units get AP+1 during this turn.」如果已有 friendly Unit filter 與 `modify_ap_until_turn_end`，只需新增卡牌資料。

例子：新卡是「Look at the top 3 cards of your deck. Add 1 Unit to your hand and place the rest at the bottom of your deck.」若 runtime 尚未支援看牌、從公開候選選牌、放回 deck bottom，就新增 `look_top_cards`、`choose_from_revealed_cards`、`move_to_bottom_deck` 這類 generic primitive。

## 13. 成功標準

V2 成功不是只跑完一局，而是可以穩定重播、debug、review。

必須成立：相同 state + 相同 resolved intent = 相同結果；phase、battle、action window、rules management、trigger priority、pending choice 都由 Python deterministic 控制；`gamePlay.yaml` 足以讓 reviewer 分辨錯誤來源；lessons 改進 LLM，不改變 runtime 裁判邊界。

例子：同一個 saved game state、同一個 resolved intent、同一個 random seed，重跑 10 次都應產生相同 `gamePlay.yaml` events。若結果不同，就是 runtime kernel、trigger ordering 或 state mutation bug。
