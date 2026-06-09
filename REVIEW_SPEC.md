# GCG CardAI — Review Specification

本文件是 review checklist。方向固定為 chat-first runtime + 長駐 Codex app-server rooms。檢查時先找 bug、風險、行為回歸與缺測試；不要把舊 CLI provider 或 opencode skill routing 當成主路徑。

## 1. Runtime Boundary

| 範圍 | 檢查要點 |
|---|---|
| Chat 指令 | `start game`、`status`、`keep/redraw`、`play`、`attack`、`pass` 必須直接呼叫 `skills_py/gcg_runtime.py`。 |
| State mutator | 只有 runtime / `skills_py/game_engine.py` 能改 state。 |
| State path | 每局使用 `game-states/<game_id>/gameState.md`；並行測試必須傳 `--game-id`。 |
| Viewer | 任一決策前用 `--viewer P1|P2` 產生完整可見狀態。 |
| Hidden info | 玩家與 AI 不直接讀 raw `gameState.md`；不可暴露對手手牌、牌庫、盾牌 card id。 |
| JSON output | `--json` 必須包含 `display_text`、events、replay path、gameplay log path。 |

## 2. Agent Server

| 範圍 | 檢查要點 |
|---|---|
| Main provider | AI 主路徑是 `GCG_AI_PROVIDER=agent-server`。 |
| Process model | `skills_py/gcg_agent_server.py` 只維持一個長駐 `codex app-server --stdio` process。 |
| API | `GET /health`、`GET /metrics`、`POST /init-game`、`POST /append`、`POST /decide` 可用。 |
| Room init | `start game` 後嘗試建立 canonical rooms；失敗只 warning，不阻止開局。 |
| Thread isolation | P1/P2 thread id 不同；Judge/Orchestrator 不等於任何 player thread。 |
| Reuse | 同一 game + player 的第二次 decision reuse 原 thread。 |
| Append | 成功 public action summary 只 append 到 `gcg-orchestrator` 或指定 role，不污染 player room。 |
| Metadata | `game-states/<game_id>/ai_sessions/<role>.json` 記錄 role/thread 對應。 |
| Tools | AI player 預設不給 shell/file edit tools；未來 tool calling 只能允許 explicit GCG runtime tools。 |
| Latency | Review 必須記錄 init、first decision、same-player second decision latency。 |

## 3. AI Player Contract

| 範圍 | 檢查要點 |
|---|---|
| 輸出格式 | 只能解析 `CONSIDER: ...` + `COMMAND: ...`。 |
| Legal action | 若 prompt 有 `legal_actions:`，`COMMAND` 第一個字必須在該列表中。 |
| Public-safe | `CONSIDER` 不得包含手牌 card id、卡名、盾牌內容、牌庫內容。 |
| No fallback | Python 不可新增策略 fallback；只允許一次 contract-repair reprompt。 |
| Runtime validation | AI command 必須交回 runtime 驗證與 apply。 |
| Room separation | P1/P2 決策不能共用 room context。 |
| Prompt source | AI player 只看 viewer display，不讀 raw state file。 |

## 4. Phase Flow

| 範圍 | 檢查要點 |
|---|---|
| Pre-game | mulligan -> keep/redraw -> shuffle -> shield setup 順序是否正確。 |
| Start Phase | 行動玩家 untap -> draw 1 -> resource 1 -> advance to main。 |
| Main Phase | 可 deploy/play/pair/attack/pass；不可自動跳過玩家主要階段。 |
| Battle Phase | attack declare -> block declare -> action priority -> damage -> battle_end。 |
| Action Step | non-active 玩家先有 priority，雙方交替，皆 pass 後前進。 |
| End Phase | action step -> cleanup -> advance turn。 |
| Turn Advance | turn++，切換行動玩家，回到 start phase。 |

## 5. Combat System

| 範圍 | 檢查要點 |
|---|---|
| Attack 宣告 | 攻擊者設為 rested，current_attacker 正確。 |
| Attackable 檢查 | 活著、沒休息、不是本回合剛部署，或符合 Link。 |
| Unit target | 若敵方橫置 Unit 可攻擊，display 必須列具體 `attack <slot> unit <enemy_slot>`。 |
| Block 宣告 | 阻擋者需 active 且有 Blocker。 |
| Damage | 盾牌傷害先結算，再 unit/base/player。 |
| Shield 破壞 | 破壞的盾牌加入 opponent trash，但 replay 不揭露 hidden card id。 |
| Battle End | battle_end 後回到 main phase。 |

## 6. Display

| 範圍 | 檢查要點 |
|---|---|
| 腳本路徑 | `skills_py/gcg_display.py`。 |
| 視角遮罩 | 自己手牌完整；對手手牌只顯示張數。 |
| 公開區 | 戰鬥區雙方單位公開。 |
| 盾牌/牌庫 | 只顯示數量，不顯示 card id。 |
| Play legality | 每張手牌依 Level / Cost 顯示 ✅/❌ 與原因。 |
| Attack legality | 合法攻擊列出具體指令；不合法要明確原因。 |
| Base format | `基地：<card_id> | AP|HP：<ap>|<remaining_hp>`。 |
| Language | 玩家可見文字使用繁體中文。 |

## 7. Gameplay Log / Replay

| 範圍 | 檢查要點 |
|---|---|
| Canonical log | `skills_py/gameplay_log.py` 是唯一 gameplay/replay 寫入邏輯。 |
| YAML | `gamePlay.yaml` 是單一 YAML document，可 `yaml.safe_load`。 |
| Sequence | event `seq` 單調遞增。 |
| Public features | 事件可記 active/priority、hand_count、resources、board summary、shields、base AP/HP/alive。 |
| Hidden info | 不得記 `hand_cards`、`deck_cards`、`shield_cards`。 |
| Replay | `replay.md` 必須由同一事件序列產生或同步更新。 |
| Review | AI-vs-AI 必須產生 `review.md` 並分類 root cause。 |

## 8. Harness

基本檢查：

```bash
python3 -m py_compile skills_py/gcg_agent_server.py skills_py/ai_adapters.py skills_py/ai_player.py skills_py/gcg_runtime.py tests/gcg_direction_harness.py tests/gcg_ai_vs_ai_replay_harness.py
python3 tests/gcg_direction_harness.py
python3 tests/gcg_ai_vs_ai_replay_harness.py
```

AI-vs-AI 預設是短上限 fail-fast。若要完整壓力測試，明確指定 `--max-turns`、`--max-steps`、`--per-auto-actions`，並保留 review artifact。

Live agent-server：

```bash
python3 skills_py/gcg_agent_server.py --host 127.0.0.1 --port 8890
GCG_AGENT_SERVER_URL=http://127.0.0.1:8890 GCG_AI_PROVIDER=agent-server python3 skills_py/gcg_runtime.py ai-probe --provider agent-server
GCG_AGENT_SERVER_URL=http://127.0.0.1:8890 GCG_AI_PROVIDER=agent-server python3 tests/gcg_ai_vs_ai_replay_harness.py --ai-timeout-seconds 60
```

Protocol probe：

```bash
python3 skills_py/gcg_agent_server.py --probe --timeout-seconds 60
```

Review harness 結果：

- `PASS`：合約、安全與 artifact 都符合。
- `INCOMPLETE`：quality signal，必須讀 replay/review 分類 root cause。
- `FAIL`：runtime、adapter、agent-server、safety 或 artifact 合約破壞。

## 9. Cleanup

| 範圍 | 檢查要點 |
|---|---|
| Legacy runtime | 不保留舊 debug CLI 作正式入口。 |
| Provider code | 不保留每次 spawn CLI 的主 provider code。 |
| Dependency | 不保留 `.opencode/node_modules/` 或不再使用的 Node package metadata。 |
| Generated files | 不提交 `.DS_Store`、`__pycache__/`、`*.pyc`、臨時 probe game state。 |
| Legacy prompt reference | `.opencode/agents` 與 `.opencode/skills` 只作待遷移參考；不可在新文件中描述成主流程。 |

## 10. Root Cause 分類

| 類型 | 判斷方式 | 下一步 |
|---|---|---|
| AI prompt problem | Display 有具體合法選項，但 AI 選差或選錯。 | 遷移/修正 player instructions。 |
| Display problem | AI 需要的合法選項或原因沒顯示。 | 改 `gcg_display.py` / template。 |
| Runtime problem | 合法 command 被拒絕或套用錯。 | 改 `gcg_runtime.py` / `game_engine.py`。 |
| Harness problem | 上限、隔離、timeout 或 artifact 收集錯。 | 改 tests。 |
| Provider latency problem | app-server path 正確但 latency 過高。 | 量測 `--probe`、HTTP path、model latency。 |
| Log/replay problem | 狀態正確但 YAML/replay 錯或洩漏資訊。 | 改 `gameplay_log.py`。 |

## Review 順序

```text
1. Runtime Boundary
2. Agent Server
3. AI Player Contract
4. Phase Flow
5. Combat System
6. Display
7. Gameplay Log / Replay
8. Harness
9. Cleanup
10. Root Cause 分類
```
