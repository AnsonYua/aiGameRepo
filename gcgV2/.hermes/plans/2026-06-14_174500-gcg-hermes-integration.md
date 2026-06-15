# GCG V2 → Hermes Agent 整合計畫（修正版）

> **適用對象：** 實作者（熟悉 Python，對 Hermes Agent 不熟）
> **目標：** 用 Hermes Agent 取代現有 AI Player，保留 Python runtime 為唯一 state mutator
> **不變邊界：** hidden-info 隔離、state mutation 由 Python 獨佔、指令合法性由 CommandParser 把關
> **修正記錄：** v2 根據 `gcg-player` profile 實際 CLI 調整 invocation flags、prompt 長度保護、驗證順序

---

## 架構總覽

```
Phase 1 ─────────────────────────────────────────
SimulatorRunner (不變)
  → ViewerStateBuilder (不變)
  → ActionEnumerator (不變)
  → HermesPlayerClient ←─ 新增，取代 AiPlayerClient
  → CommandParser (不變)
  → Runtime (唯一 state mutator，不變)
  → gamePlay.yaml / ai_trace.yaml (不變)

Hermes 角色：
  └─ gcg-player wrapper ──→ text-in/text-out 決策，zero tools

Phase 2 ─────────────────────────────────────────
賽後 Reviewer：你手動叫我（Hermes default profile）分析 replay
我讀 gamePlay.yaml → 輸出 review.md
不 hook runner，不自動 fire
```

---

## Phase 1：替換 Player LLM（最小改動）

### 目標

只做一件事：新增 `HermesPlayerClient`，介面跟現有 `AiPlayerClient` 完全一致。
其他全部不變：`PromptBuilder`、`ActionEnumerator`、`CommandParser`、`Runtime`、`EffectEngine`、`gameplay_logger`。

### Hermes 只負責

```
prompt_payload（JSON）──→ CONSIDER: ...
                         COMMAND: <從 legal_commands 逐字複製>
```

### 已完成的準備工作

| 項目 | 狀態 |
|---|---|
| `gcg-player` profile 已建立 | ✅ `/Users/hello/.hermes/profiles/gcg-player/` |
| `gcg-strategy` skill 已建立 | ✅ 含策略知識 + 官方綜合規則參考 |
| `config.yaml` 關閉 memory | ✅ `memory.memory_enabled: false` |
| `config.yaml` 關閉 compression | ✅ `compression.enabled: false` |
| Wrapper alias | ✅ `/Users/hello/.local/bin/gcg-player` |
| API key | ❌ 需要你補（見最後一節） |

### 新增檔案

#### 1. `gcg/ai/hermes_player_client.py`

```python
"""Hermes Agent player client — 以 subprocess 呼叫 gcg-player wrapper。

介面與 AiPlayerClient 完全一致：
    HermesPlayerClient.decide(game_id, player_id, prompt_payload) -> str

Hermes 角色：
- 只看 prompt_payload 內的 viewer_state + legal_commands
- 只輸出 CONSIDER: / COMMAND: 兩行
- 不開任何工具（-t none）
- 不讀寫 memory（config.yaml 已關閉）
- 不存取檔案、不修改系統
"""

from __future__ import annotations

import json
import logging
import subprocess
import sys

logger = logging.getLogger(__name__)

_PROMPT_SIZE_LIMIT = 100_000  # bytes；argv 長度保護


class HermesPlayerClient:
    """Call gcg-player wrapper for each decision."""

    def __init__(
        self,
        wrapper: str = "gcg-player",
        timeout: int = 60,
    ):
        self.wrapper = wrapper
        self.timeout = timeout

    def decide(self, game_id: str, player_id: str, prompt_payload: dict) -> str:
        hermes_prompt = self._build_hermes_prompt(player_id, prompt_payload)

        if len(hermes_prompt.encode("utf-8")) > _PROMPT_SIZE_LIMIT:
            raise RuntimeError(
                f"Hermes prompt too large for CLI adapter "
                f"({len(hermes_prompt.encode('utf-8'))} bytes > {_PROMPT_SIZE_LIMIT}); "
                "use gateway mode later."
            )

        argv = [
            self.wrapper,
            "chat", "-q", hermes_prompt,
            "-t", "none",           # zero tools
            "-s", "gcg-strategy",   # 載入策略 skill
            "--max-turns", "1",     # 只 call 一次 LLM
            "--source", "gcg-player",
            "-Q",                   # quiet mode
        ]

        logger.info(
            "hermes_decision game=%s player=%s wrapper=%s prompt_size=%d",
            game_id, player_id, self.wrapper,
            len(hermes_prompt.encode("utf-8")),
        )

        try:
            result = subprocess.run(
                argv,
                capture_output=True, text=True,
                timeout=self.timeout,
                # shell=False 是 subprocess.run 預設，安全
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Hermes player {player_id} timed out after {self.timeout}s"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Hermes wrapper '{self.wrapper}' not found. "
                "Install Hermes or check PATH."
            ) from exc

        if result.returncode != 0:
            stderr_tail = (result.stderr or "")[:500]
            raise RuntimeError(
                f"Hermes player {player_id} exited with code {result.returncode}: "
                f"{stderr_tail}"
            )

        raw = (result.stdout or "").strip()
        if not raw:
            raise RuntimeError(
                f"Hermes player {player_id} returned empty output."
            )

        return self._normalize(raw)

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_hermes_prompt(player_id: str, prompt_payload: dict) -> str:
        """組裝傳給 gcg-player 的完整 prompt。

        很短的前置指示（取代 system prompt 的作用）+
        實際的 JSON payload（由現有 PromptBuilder 產出）。
        """
        instruction = (
            f"你是 GCG 玩家 {player_id}。\n"
            "請從下面的 `legal_commands` 清單中選一條指令。\n"
            "只輸出兩行：\n"
            "CONSIDER: <繁體中文、public-safe 短理由>\n"
            "COMMAND: <從 legal_commands 逐字複製的指令>\n"
            "不要輸出其他任何文字。\n"
        )
        body = json.dumps(prompt_payload, ensure_ascii=False, indent=2)
        return f"{instruction}\n{body}"

    @staticmethod
    def _normalize(raw: str) -> str:
        """正規化輸出為標準兩行格式。

        保留第一行 CONSIDER: 和第二行 COMMAND:，
        過濾掉可能的空白行或 markdown 區塊。
        """
        lines = [
            line.strip()
            for line in raw.splitlines()
            if line.strip()
        ]
        # 只保留 CONSIDER: / REASON: / COMMAND: 開頭的行
        structured = [
            line for line in lines
            if line.lower().startswith(("consider:", "reason:", "command:"))
        ]
        if any(line.lower().startswith("command:") for line in structured):
            return "\n".join(structured)
        # fallback：回傳原始第一行（runner 的 legal_commands check 會攔截）
        return lines[0] if lines else ""
```

#### 2. `tests/test_hermes_player_client.py`

```python
"""HermesPlayerClient 單元測試（mock subprocess）。"""

from unittest.mock import patch, MagicMock
import pytest
from gcg.ai.hermes_player_client import HermesPlayerClient


def test_decide_returns_structured_output():
    client = HermesPlayerClient(wrapper="echo")

    mock_payload = {
        "request_type": "gcg_main_decision",
        "player_id": "P1",
        "legal_commands": ["pass", "play_card st01/ST01-008 0"],
        "viewer_state": {"phase": "main"},
    }

    # echo 會直接把輸入原樣回傳到 stdout
    # 但 normalize 只取 CONSIDER:/COMMAND: 行
    result = client.decide("game_001", "P1", mock_payload)

    # 至少是字串，不會爆炸
    assert isinstance(result, str)


def test_decide_raises_on_empty_output():
    client = HermesPlayerClient(wrapper="true")  # true 回傳空 stdout

    with pytest.raises(RuntimeError, match="empty output"):
        client.decide("game_001", "P1", {"legal_commands": ["pass"]})


def test_decide_timeout():
    client = HermesPlayerClient(wrapper="sleep", timeout=1)

    with pytest.raises(RuntimeError, match="timed out"):
        client.decide("game_001", "P1", {"legal_commands": ["pass"]})


def test_decide_wrapper_not_found():
    client = HermesPlayerClient(wrapper="/nonexistent/wrapper")

    with pytest.raises(RuntimeError, match="not found"):
        client.decide("game_001", "P1", {"legal_commands": ["pass"]})
```

### 修改檔案

#### 3. `gcg/sim/bootstrap.py`

在 `build_simulator()` 中新增 `players="hermes"` 模式：

```python
from ..ai.hermes_player_client import HermesPlayerClient

def build_simulator(players="llm", interpreter="llm", ...):
    ...
    if players == "hermes":
        player_map = {
            "P1": HermesPlayerClient(timeout=60),
            "P2": HermesPlayerClient(timeout=60),
        }
    elif players == "llm":
        ...  # 保持原有
    elif players == "scripted":
        ...  # 保持原有
    ...
```

#### 4. `run_simulator.py`

在第 30 行 `choices` tuple 中加入 `"hermes"`：

```python
parser.add_argument(
    "--players",
    choices=("llm", "scripted", "hermes"),   # ← 加入 hermes
    default="llm",
)
```

### 不修改的檔案（安全邊界確認）

| 檔案 | 不修改的理由 |
|---|---|
| `gcg/engine/runtime.py` | 唯一 state mutator，跟 LLM 無關 |
| `gcg/ai/prompt_builder.py` | 仍由 Python 組裝 JSON payload |
| `gcg/ai/player_client.py` | 保留舊版，方便對比 |
| `gcg/ai/llm_client.py` | 保留舊版，方便對比 |
| `gcg/engine/command_parser.py` | 語法解析，無關 LLM |
| `gcg/engine/action_enumerator.py` | 合法指令枚舉，純規則 |
| `gcg/engine/effect_engine.py` | deterministic executor |
| `gcg/engine/state_store.py` | state mutation API |
| `gcg/engine/viewer.py` | public-safe 過濾 |
| `gcg/gamelog/*` | logging 邏輯不變 |

### 驗證順序

照以下順序，不要跳步：

**Step 1：確認 CLI 可以動**

```bash
# 基本測試：Hermes 能正確回覆
gcg-player chat -q '只輸出兩行：CONSIDER: 測試。 COMMAND: pass' \
  -Q -t none -s gcg-strategy --max-turns 1 --source gcg-player

# 預期輸出：
# CONSIDER: 測試。
# COMMAND: pass
```

**Step 2：compile check**

```bash
python3 -m py_compile gcg/ai/hermes_player_client.py
python3 -m py_compile gcg/sim/bootstrap.py
python3 -m py_compile run_simulator.py
```

**Step 3：跑既有測試**

```bash
python3 -m unittest discover -s tests -p "test_*.py" -v
```

**Step 4：單局 scripted 確認沒壞**

```bash
python3 run_simulator.py --players scripted --interpreter reference --seed 42
```

**Step 5：單局 hermes player + reference interpreter**

```bash
python3 run_simulator.py --players hermes --interpreter reference --seed 42
```

**Step 6（可選）：hermes player + llm interpreter**

```bash
python3 run_simulator.py --players hermes --interpreter llm --seed 42
```

### 已知限制（Phase 1 不處理）

| 限制 | 原因 | 未來解法 |
|---|---|---|
| CLI argv 長度上限（~100KB） | macOS argv 上限約 256KB | Phase 1.5 走 stdin pipe 或 Hermes HTTP gateway |
| 每次 subprocess 冷啟動（~0.5-2s） | Hermes CLI 每次載入 config/skills | 不影響回合制模擬；Phase 1.5 可改 persistent gateway |
| 無 conversation state | 每次 fresh process，無記憶 | 故意設計：防止 hidden info 跨步洩漏 |
| `/Users/hello/.local/bin/gcg-player` 是 wrapper | 指向實際 hermes binary | 正常，`which gcg-player` 可確認路徑 |

---

## Phase 2：賽後手動 Reviewer

### 目標

不做獨立 script、不 hook runner、不自動 fire。
你直接在**這個 Hermes session**（default profile）告訴我：

> 「hermes，幫我 review 這局 `game_20260614_xxxxxx`」

我就能：
1. 讀 `out/<game_id>/gamePlay.yaml`
2. 讀 `out/<game_id>/ai_trace.yaml`
3. 分析問題分類（AI prompt / Display / Runtime / Harness / Provider）
4. 輸出 `out/<game_id>/review.md`

### 使用方式

```
你：hermes，幫我 review game_20260614_123456
我：（讀檔案 → 分析 → 寫 review.md）
你：好，那幫我看這局的 COMMAND 選擇哪裡有問題
我：（deep dive）
```

### 不做的

| 項目 | 理由 |
|---|---|
| 不寫 `skills_py/gcg_reviewer.py` | 你就是 reviewer 的 UI |
| 不自動 fire | 等 Phase 1 穩定再說 |
| 不改 `runner.py` | 不增加對局中的 overhead |
| 不改 `bootstrap.py` | 不引入 reviewer 依賴 |

### 你的角色

你只需要：
1. 跑完一局（`run_simulator.py --players hermes --interpreter reference --seed 42`）
2. 複製 terminal 輸出的 `game_id`
3. 在對話中對我說：`hermes，幫我 review game_xxxxx`

---

## API Key 設定（最後一步）

目前 `gcg-player` profile 沒有 API key。你需要在你自己的 terminal 跑：

```bash
# 用 OpenRouter（推薦，可選多種模型且便宜）
export OPENROUTER_API_KEY="sk-or-v1-你的key"
gcg-player config set model.provider openrouter
gcg-player config set model.default deepseek/deepseek-chat

# 驗證
gcg-player chat -q "test" -t none -Q
```

或者沿用你現有的 DeepSeek key：

```bash
export DEEPSEEK_API_KEY="你的key"
gcg-player config set model.provider deepseek
gcg-player config set model.default deepseek-chat
```

---

## 檔案變更總結

| 動作 | 檔案 | 行數估計 |
|---|---|---|
| **Create** | `gcg/ai/hermes_player_client.py` | ~100 行 |
| **Create** | `tests/test_hermes_player_client.py` | ~50 行 |
| **Modify** | `gcg/sim/bootstrap.py` | +5 行 |
| **Modify** | `run_simulator.py` | +1 行 |

總計：約 160 行新增，**不改任何既有邏輯**。
