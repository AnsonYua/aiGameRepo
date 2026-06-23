# Battle App Standalone 部署實作計劃

> 目標：令 `battle_app/` 成為真正可獨立部署的 package，upload 至 Vercel/server 後不需任何外部依賴即可運行。
> 
> 約束：程式碼改動最小化 — 僅調整 `gcg/config.py` 路徑預設值與各入口檔案的 `sys.path` 設定，不改 business logic，不改 import statement。

---

## 一、現狀依賴全景

`battle_app/` 目前依賴以下**外部路徑**（全部位於 `battle_app/` 之外）：

| # | 依賴 | 當前絕對位置 | 大小 | 引入方式 |
|---|------|-------------|------|----------|
| 1 | `gcg/` runtime engine | `gcgV2/gcg/` (40 個 .py) | ~150 KB | `from gcg.cards import ...` |
| 2 | `reviewboard/humanVsAI/` | `gcgV2/reviewboard/humanVsAI/` (3 個 .py) | ~27 KB | `from reviewboard.humanVsAI.battle_session import ...` |
| 3 | `card/data/` JSON | `cardAI/card/data/` (12 個 JSON) | ~500 KB | `config.card_data_root()` → `CardDatabase._load_cards()` |
| 4 | `card/gcgdecks.json` | `cardAI/card/gcgdecks.json` (1 個 JSON) | ~3 KB | `config.deck_file()` → `DeckConfig.__init__()` |
| 5 | `manifests/GCG_V2_EFFECT_DICTIONARY.yaml` | `gcgV2/manifests/` (1 個 YAML) | ~18 KB | `config.effect_dictionary_path()` → `EffectDictionary.__init__()` |
| 6 | `docs/st01-04_card_effects_schema.yaml` | `gcgV2/docs/` (4 個 YAML) | ~130 KB | `config.card_effect_schema_paths()` → `CardEffectSchemaLoader.__init__()` |
| 7 | `knowledge/gcg-ai-player.md` | `gcgV2/knowledge/` (1 個 .md) | ~8 KB | `config.player_prompt_path()` → `PromptBuilder`（僅 hermes/llm mode 使用） |

### 1.1 `gcg/` 模組內部結構（40 檔案）

```
gcg/
├── __init__.py
├── config.py              ← 唯一需要改動的檔案
├── cards.py
├── ai/
│   ├── __init__.py
│   ├── player_client.py
│   ├── hermes_player_client.py
│   ├── llm_client.py
│   ├── prompt_builder.py
│   ├── lessons.py
│   └── mcts/
│       ├── __init__.py
│       ├── config.py
│       ├── mcts_player.py
│       ├── ismcts.py
│       ├── mcts_node.py
│       ├── simulation.py
│       ├── determinization.py
│       └── heuristics.py
├── effects/
│   ├── __init__.py
│   ├── dictionary.py
│   ├── interpreter.py
│   ├── reference_st01.py
│   ├── schema_interpreter.py
│   ├── schema_loader.py
│   └── spec_gate.py
├── engine/
│   ├── __init__.py
│   ├── runtime.py
│   ├── state_store.py
│   ├── effect_engine.py
│   ├── rules_index.py
│   ├── action_enumerator.py
│   ├── trigger_system.py
│   ├── viewer.py
│   └── command_parser.py
├── gamelog/
│   ├── __init__.py
│   ├── gameplay_logger.py
│   └── writers.py
└── sim/
    ├── __init__.py
    ├── bootstrap.py
    ├── runner.py
    └── scripted_player.py
```

全部 **40 個 .py 檔案均需搬入** `battle_app/gcg/`。MCTS 模式依賴 `gcg/ai/mcts/` 下的全部 8 個檔案。

### 1.2 `battle_app/` 內部 `sys.path` 現狀

目前各入口檔案均有 `GCGV2_ROOT = BATTLE_APP_ROOT.parent` 並將其加入 `sys.path`，使 `from gcg.xxx`、`from reviewboard.xxx`、`from battle_app.xxx` 三種 import 格式同時有效。

| 檔案 | `BATTLE_APP_ROOT` | `GCGV2_ROOT` | `sys.path` 加入內容 |
|------|-------------------|-------------|---------------------|
| `server.py` | `battle_app/` | `battle_app.parent` (= `gcgV2/`) | 僅 `GCGV2_ROOT` |
| `api/games.py` | `api_dir.parent` (= `battle_app/`) | `battle_app.parent` (= `gcgV2/`) | `GCGV2_ROOT` + `BATTLE_APP_ROOT` |
| `scenarios.py` | `battle_app/` | `battle_app.parent` (= `gcgV2/`) | 僅用於 `DEFAULT_SCENARIO_ROOT` |
| `env.py` | `battle_app/` | `battle_app.parent` (= `gcgV2/`) | 僅用於載入 `.env` |
| `reviewboard/.../battle_session.py` | n/a | `parents[2]` (= `gcgV2/`) | 加入 `GCGV2_ROOT` |

---

## 二、Phase 1：檔案搬移/複製操作（精確步驟）

### 2.1 必要搬移（6 組操作）

| 步驟 | 操作 | 來源 | 目標 | 備註 |
|------|------|------|------|------|
| **M1** | 複製整個目錄 | `gcgV2/gcg/` | `battle_app/gcg/` | 40 個 .py，含 `__pycache__/` 除外（用 `cp -r` 時加 `*.py` 過濾或手動清理） |
| **M2** | 複製整個目錄 | `gcgV2/reviewboard/humanVsAI/` | `battle_app/reviewboard/humanVsAI/` | 3 個 .py + `__init__.py`；`requirements.md` 可一併複製 |
| **M3** | 複製 card JSON | `cardAI/card/data/st01~st09Card.json`<br>`cardAI/card/data/gd01~gd03Card.json` | `battle_app/card/data/` | 12 個檔案，總計 ~500 KB |
| **M4** | 複製 deck config | `cardAI/card/gcgdecks.json` | `battle_app/card/gcgdecks.json` | 1 個檔案 |
| **M5** | 複製 effect dictionary | `gcgV2/manifests/GCG_V2_EFFECT_DICTIONARY.yaml` | `battle_app/manifests/GCG_V2_EFFECT_DICTIONARY.yaml` | 1 個檔案 |
| **M6** | 複製 schema YAML | `gcgV2/docs/st01_card_effects_schema.yaml`<br>`gcgV2/docs/st02_card_effects_schema.yaml`<br>`gcgV2/docs/st03_card_effects_schema.yaml`<br>`gcgV2/docs/st04_card_effects_schema.yaml` | `battle_app/schemas/st01_card_effects_schema.yaml`<br>`battle_app/schemas/st02_card_effects_schema.yaml`<br>`battle_app/schemas/st03_card_effects_schema.yaml`<br>`battle_app/schemas/st04_card_effects_schema.yaml` | 4 個檔案，目錄名從 `docs/` 改為 `schemas/` |

**重要：全部使用 `cp`（真實檔案複製），不可用 symlink。** Vercel 部署時 symlink 指向 project root 外部的目標不存在。

### 2.2 可選搬移（1 組）

| 步驟 | 操作 | 來源 | 目標 | 備註 |
|------|------|------|------|------|
| **O1** | 複製 AI prompt | `gcgV2/knowledge/gcg-ai-player.md` | `battle_app/knowledge/gcg-ai-player.md` | **僅 `hermes` / `llm` AI mode 需要**；MCTS+schema mode 不需要 |

### 2.3 不需搬移的項目

| 資源 | 原因 |
|------|------|
| `knowledge/experience/` | AI 經驗教訓，非 runtime 必須；MCTS 不使用 |
| `knowledge/gcg-rulebook.md` | 規則書文檔，非 runtime 必須 |
| `docs/` 其他檔案 | `battle_app/standalone_plan_*.md` 等計劃文檔，非 runtime 必須 |
| `out/` | Runtime 自動建立的輸出目錄 |
| `scenarios/manual/` | 測試場景，僅 `GCG_ENABLE_SCENARIO_MODE=1` 時使用（可選搬入） |
| `reviewboard/server.py` | 舊 reviewboard server，與 battle_app 無關 |
| `reviewboard/scripts/` | 舊工具 script，與 battle_app 無關 |
| `reviewboard/tests/` | 舊測試，與 battle_app 無關 |
| `.env`（專案根目錄） | `battle_app/` 有自己的 `.env.local` |

### 2.4 搬移指令（終端機執行順序）

```bash
cd /Users/hello/Desktop/cardAI/gcgV2

# M1: 複製 gcg/ runtime engine（排除 __pycache__）
cp -r gcg battle_app/gcg
find battle_app/gcg -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null
find battle_app/gcg -name '*.pyc' -delete 2>/dev/null

# M2: 複製 reviewboard/humanVsAI/
mkdir -p battle_app/reviewboard
cp -r reviewboard/humanVsAI battle_app/reviewboard/humanVsAI
find battle_app/reviewboard -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null

# M3: 複製 card data JSON
mkdir -p battle_app/card/data
cp ../card/data/st0*Card.json battle_app/card/data/
cp ../card/data/gd0*Card.json battle_app/card/data/

# M4: 複製 deck config
cp ../card/gcgdecks.json battle_app/card/

# M5: 複製 effect dictionary
mkdir -p battle_app/manifests
cp manifests/GCG_V2_EFFECT_DICTIONARY.yaml battle_app/manifests/

# M6: 複製 schema YAML（docs/ → schemas/）
mkdir -p battle_app/schemas
cp docs/st01_card_effects_schema.yaml battle_app/schemas/
cp docs/st02_card_effects_schema.yaml battle_app/schemas/
cp docs/st03_card_effects_schema.yaml battle_app/schemas/
cp docs/st04_card_effects_schema.yaml battle_app/schemas/

# O1 (可選): 複製 AI prompt（僅 hermes/llm mode 需要）
mkdir -p battle_app/knowledge
cp knowledge/gcg-ai-player.md battle_app/knowledge/
```

---

## 三、Phase 2：`gcg/config.py` 路徑調整（唯一需要改的程式邏輯）

當 `gcg/config.py` 搬入 `battle_app/gcg/config.py` 後：
- `Path(__file__).resolve().parents[1]` → `battle_app/`（不再是 `gcgV2/`）

因此需調整以下 **3 處**預設路徑：

### 3.1 修改 `REPO_ROOT`

```python
# 舊（第 12 行）：
REPO_ROOT = GCGV2_ROOT.parent

# 新：
REPO_ROOT = GCGV2_ROOT
```

**原因**：`card/data/` 與 `card/gcgdecks.json` 已搬入 `battle_app/card/`，即 `GCGV2_ROOT/card/`。`card_data_root()` 與 `deck_file()` 均引用 `REPO_ROOT / "card" / ...`，因此 `REPO_ROOT` 必須指向 `battle_app/` 而非其上層。

### 3.2 簡化 `card_effect_schema_paths()`

```python
# 舊（第 55–73 行）：
def card_effect_schema_paths() -> list[Path]:
    raw = os.getenv("GCG_CARD_EFFECT_SCHEMA_PATHS")
    if raw:
        return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]
    # 部署時只 upload battle_app/，docs/ 唔存在 → fallback 到 battle_app/schemas/
    primary = GCGV2_ROOT / "docs" / "st01_card_effects_schema.yaml"
    if primary.exists():
        return [
            GCGV2_ROOT / "docs" / "st01_card_effects_schema.yaml",
            GCGV2_ROOT / "docs" / "st02_card_effects_schema.yaml",
            GCGV2_ROOT / "docs" / "st03_card_effects_schema.yaml",
            GCGV2_ROOT / "docs" / "st04_card_effects_schema.yaml",
        ]
    return [
        GCGV2_ROOT / "battle_app" / "schemas" / "st01_card_effects_schema.yaml",
        GCGV2_ROOT / "battle_app" / "schemas" / "st02_card_effects_schema.yaml",
        GCGV2_ROOT / "battle_app" / "schemas" / "st03_card_effects_schema.yaml",
        GCGV2_ROOT / "battle_app" / "schemas" / "st04_card_effects_schema.yaml",
    ]

# 新：
def card_effect_schema_paths() -> list[Path]:
    raw = os.getenv("GCG_CARD_EFFECT_SCHEMA_PATHS")
    if raw:
        return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]
    return [
        GCGV2_ROOT / "schemas" / "st01_card_effects_schema.yaml",
        GCGV2_ROOT / "schemas" / "st02_card_effects_schema.yaml",
        GCGV2_ROOT / "schemas" / "st03_card_effects_schema.yaml",
        GCGV2_ROOT / "schemas" / "st04_card_effects_schema.yaml",
    ]
```

**原因**：schema YAML 已搬入 `battle_app/schemas/` = `GCGV2_ROOT/schemas/`。不再需要 `docs/` 路徑與 `battle_app/schemas/` fallback 的雙重判斷。

### 3.3 其餘函數無需修改

| 函數 | 當前預設值 | 搬移後有效性 | 需改？ |
|------|-----------|-------------|--------|
| `card_data_root()` | `REPO_ROOT / "card" / "data"` | `battle_app/card/data/` ✅ | 否（`REPO_ROOT` 改後自動正確） |
| `deck_file()` | `REPO_ROOT / "card" / "gcgdecks.json"` | `battle_app/card/gcgdecks.json` ✅ | 否（同上） |
| `output_root()` | `GCGV2_ROOT / "out"` | `battle_app/out/` ✅ | 否 |
| `effect_dictionary_path()` | `GCGV2_ROOT / "manifests" / "GCG_V2_EFFECT_DICTIONARY.yaml"` | `battle_app/manifests/GCG_V2_EFFECT_DICTIONARY.yaml` ✅ | 否 |
| `knowledge_root()` | `GCGV2_ROOT / "knowledge"` | `battle_app/knowledge/` ✅ | 否 |
| `player_prompt_path()` | `knowledge_root() / "gcg-ai-player.md"` | `battle_app/knowledge/gcg-ai-player.md` ✅（若已搬入） | 否 |
| `experience_root()` | `knowledge_root() / "experience"` | `battle_app/knowledge/experience/`（不存在於部署中） | 否（MCTS 不使用） |

**合計 config.py 改動：約 15 行**（`REPO_ROOT` 1 行 + `card_effect_schema_paths()` 替換 ~14 行）。

### 3.4 `load_local_env()` 行為變化

```python
def load_local_env() -> None:
    for candidate in (Path.cwd() / ".env", GCGV2_ROOT / ".env"):
```

搬移後 `GCGV2_ROOT` = `battle_app/`，因此會嘗試載入 `battle_app/.env`。這是合理的行為：本地開發用 `battle_app/.env.local`，部署時 Vercel 直接注入環境變數。**無需修改**。

---

## 四、Phase 3：`battle_app/` 內部 `sys.path` 調整

搬移後，`gcg/` 與 `reviewboard/` 進入 `battle_app/` 內部。各檔案的 `sys.path` 設定需確保以下三種 import 格式同時有效：

| Import 格式 | 需要的 sys.path 路徑 |
|-------------|---------------------|
| `from gcg.xxx import ...` | `battle_app/`（因為 `gcg/` 在 `battle_app/` 裡面） |
| `from reviewboard.humanVsAI.xxx import ...` | `battle_app/`（因為 `reviewboard/` 在 `battle_app/` 裡面） |
| `from battle_app.xxx import ...` | `battle_app/` 的**上層目錄**（因為 `battle_app/` 本身需作為 package） |

因此每個入口檔案需同時將 **`BATTLE_APP_ROOT`** 與 **`BATTLE_APP_ROOT.parent`** 加入 `sys.path`。

### 4.1 `server.py`（第 24–29 行）

```python
# 舊：
BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT.parent
PUBLIC_ROOT = BATTLE_APP_ROOT / "public"

if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))

# 新：
BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT          # ← 改：battle_app 即為 GCGV2_ROOT
PUBLIC_ROOT = BATTLE_APP_ROOT / "public"

for _p in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):  # ← 改：兩個路徑都加入
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
```

### 4.2 `api/games.py`（第 10–15 行）

```python
# 舊：
API_DIR = Path(__file__).resolve().parent
BATTLE_APP_ROOT = API_DIR.parent
GCGV2_ROOT = BATTLE_APP_ROOT.parent
for path in (GCGV2_ROOT, BATTLE_APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# 新：
API_DIR = Path(__file__).resolve().parent
BATTLE_APP_ROOT = API_DIR.parent
GCGV2_ROOT = BATTLE_APP_ROOT          # ← 改：battle_app 即為 GCGV2_ROOT
for _p in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):  # ← 改：使用明確語意
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
```

實際上 `api/games.py` 原本就已加入兩個路徑，只是 `GCGV2_ROOT` 的語意需要更新。功能性上原本就正確。

### 4.3 `scenarios.py`（第 14–16 行）

```python
# 舊：
BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT.parent
DEFAULT_SCENARIO_ROOT = GCGV2_ROOT / "scenarios" / "manual"

# 新：
BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT          # ← 改
DEFAULT_SCENARIO_ROOT = GCGV2_ROOT / "scenarios" / "manual"
```

`scenarios.py` 不手動操作 `sys.path`，但 `DEFAULT_SCENARIO_ROOT` 指向 `scenarios/manual/`。若部署時需要 scenario mode，則 `scenarios/manual/` 也需複製進 `battle_app/`（可選項目）。若不需要 scenario mode，此變更不影響運行。

### 4.4 `env.py`（第 13–14 行）

```python
# 舊：
BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT.parent

# 新：
BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT          # ← 改
```

`env.py` 使用 `GCGV2_ROOT` 載入 `.env` 檔案。搬移後 `battle_app/` 即為根目錄，無需存取上層。

### 4.5 `reviewboard/humanVsAI/battle_session.py`（第 19–21 行）

```python
# 目前：
GCGV2_ROOT = Path(__file__).resolve().parents[2]
if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))
```

搬移後此檔案位於 `battle_app/reviewboard/humanVsAI/battle_session.py`，`parents[2]` 會自動 resolve 為 `battle_app/`。**完全無需修改**，因為 `gcg/` 就在 `battle_app/` 下面。

### 4.6 `runtime_document.py` 與 `storage.py`

`runtime_document.py` 和 `storage.py` **沒有** `sys.path` 操作，它們依賴呼叫者（`server.py` 或 `api/games.py`）設置好 `sys.path`。搬移後無需修改。

---

## 五、Phase 4：清理（Cleanup）

| 步驟 | 動作 | 原因 |
|------|------|------|
| **C1** | 刪除 `battle_app/gcg/__pycache__/` 及所有 `.pyc` | 不應 deploy |
| **C2** | 刪除 `battle_app/reviewboard/__pycache__/` | 同上 |
| **C3** | 刪除 `battle_app/.understand-anything/` | 本地分析工具產物，非 runtime 必須 |
| **C4** | 刪除 `battle_app/__pycache__/` | 同上 |
| **C5** | 確保 `.gitignore` 或 `.vercelignore` 排除 `__pycache__/`、`.understand-anything/`、`out/` | 減小部署包大小 |
| **C6** | 檢查 `gcg/config.py` 舊有 `docs/` fallback 邏輯是否已移除 | Phase 2 應已移除 |

---

## 六、必要 vs 可選 vs 不需要

| 資源 | 必要性 | 使用條件 | 大小 |
|------|--------|----------|------|
| `gcg/` (40 .py) | ✅ **必要** | 任何模式都需要 | ~150 KB |
| `reviewboard/humanVsAI/` (3 .py) | ✅ **必要** | `battle_session.py` 是 server 核心 | ~27 KB |
| `card/data/` (12 JSON) | ✅ **必要** | `CardDatabase` 載入卡片資料 | ~500 KB |
| `card/gcgdecks.json` | ✅ **必要** | `DeckConfig` 載入牌組 | ~3 KB |
| `manifests/GCG_V2_EFFECT_DICTIONARY.yaml` | ✅ **必要** | `EffectDictionary` 載入效果詞彙表；schema interpreter 也需要 | ~18 KB |
| `schemas/st01~04_card_effects_schema.yaml` | ✅ **必要**（schema mode） | `GCG_BATTLE_INTERPRETER=schema` | ~130 KB |
| `knowledge/gcg-ai-player.md` | ⚠️ **可選** | 僅 `GCG_BATTLE_AI_MODE=hermes` / `llm` 需要；MCTS 不需要 | ~8 KB |
| `knowledge/experience/` | ❌ 不需要 | AI 經驗教訓；MCTS 不使用；hermes mode 才會用到 | ~200 KB |
| `knowledge/gcg-rulebook.md` | ❌ 不需要 | 文件 | ~10 KB |
| `scenarios/manual/` | ⚠️ **可選** | 僅 `GCG_ENABLE_SCENARIO_MODE=1` 需要 | ~10 KB |
| `out/` | ❌ 不需要 | Runtime 自動建立 | n/a |
| `docs/plans/` | ❌ 不需要 | 計劃文件 | n/a |

**MCTS + schema 最小部署包大小估算：~830 KB**（不含 `knowledge/` 與 `scenarios/`）。

---

## 七、驗證步驟

### 7.1 靜態檢查

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app

# 1. 確認所有必要目錄存在
ls -d gcg/ reviewboard/humanVsAI/ card/data/ card/gcgdecks.json \
      manifests/GCG_V2_EFFECT_DICTIONARY.yaml \
      schemas/st01_card_effects_schema.yaml

# 2. py_compile 全部模組
python3 -m py_compile server.py api/games.py runtime_document.py scenarios.py env.py storage.py
python3 -m py_compile gcg/config.py
python3 -m py_compile gcg/cards.py
python3 -m py_compile gcg/sim/bootstrap.py
python3 -m py_compile gcg/effects/schema_loader.py
python3 -m py_compile gcg/effects/dictionary.py
python3 -m py_compile gcg/ai/mcts/__init__.py
python3 -m py_compile reviewboard/humanVsAI/battle_session.py
python3 -m py_compile reviewboard/humanVsAI/command_labels.py
```

### 7.2 路徑解析驗證

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app

python3 -c "
import sys; sys.path.insert(0, '.')
from gcg.config import (
    GCGV2_ROOT, card_effect_schema_paths, card_data_root,
    deck_file, effect_dictionary_path, output_root
)
print('GCGV2_ROOT:', GCGV2_ROOT)
print('schema_paths:')
for p in card_effect_schema_paths():
    print(f'  {p}  exists={p.exists()}')
print('card_data_root:', card_data_root(), 'exists=', card_data_root().exists())
print('deck_file:', deck_file(), 'exists=', deck_file().exists())
print('effect_dict:', effect_dictionary_path(), 'exists=', effect_dictionary_path().exists())
print('output_root:', output_root())
assert GCGV2_ROOT.name == 'battle_app', f'Expected battle_app, got {GCGV2_ROOT.name}'
assert all(p.exists() for p in card_effect_schema_paths()), 'Schema files missing!'
assert card_data_root().exists(), 'Card data root missing!'
assert deck_file().exists(), 'Deck file missing!'
assert effect_dictionary_path().exists(), 'Effect dictionary missing!'
print('ALL PATH CHECKS PASSED')
"
```

### 7.3 模擬部署環境測試（最關鍵）

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app

# 3a. Import 完整 stack（不啟動 server）
GCG_BATTLE_AI_MODE=mcts GCG_BATTLE_INTERPRETER=schema python3 -c "
import sys; sys.path.insert(0, '.')
# 模擬 server.py 的 sys.path 設定
from pathlib import Path
BATTLE_APP_ROOT = Path('.').resolve()
for p in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# 測試所有 critical imports
from gcg.cards import CardDatabase
from gcg.engine.command_parser import CommandParser
from gcg.engine.viewer import ViewerStateBuilder
from gcg.sim.bootstrap import build_simulator
from gcg.effects.dictionary import EffectDictionary
from gcg.effects.schema_loader import CardEffectSchemaLoader
from gcg.ai.mcts import MctsPlayer
from reviewboard.humanVsAI.battle_session import HumanVsAiBattleSession
from reviewboard.humanVsAI.command_labels import build_legal_actions
from battle_app.env import load_battle_app_env
from battle_app.scenarios import load_scenario, ScenarioError
from battle_app.runtime_document import DocumentBackedBattle

load_battle_app_env()

# 實例化核心組件
db = CardDatabase()
print(f'CardDatabase loaded: {len(db.cards)} cards')

schema = CardEffectSchemaLoader().load()
print(f'Schema loaded: {len(schema.cards)} cards')

dictionary = EffectDictionary()
print(f'EffectDictionary loaded: {len(dictionary.primitives)} primitives')

# 建立 simulator runner（MCTS + schema）
runner = build_simulator(players='mcts', interpreter='schema', output_root='/tmp/gcg_test')
print(f'Simulator built: game_id={runner.game_id}')

print('ALL CRITICAL IMPORTS AND INSTANTIATIONS PASSED')
"

# 3b. 啟動 local server 並測試 API
GCG_BATTLE_AI_MODE=mcts GCG_BATTLE_INTERPRETER=schema python3 server.py --host 127.0.0.1 --port 5191 &
SERVER_PID=$!
sleep 2

# 建立對局
curl -s -X POST http://127.0.0.1:5191/api/games | python3 -m json.tool
# 列出對局
curl -s http://127.0.0.1:5191/api/games | python3 -m json.tool

kill $SERVER_PID 2>/dev/null
```

### 7.4 對局功能測試

```bash
# 建立對局並取得 game_id
GAME_ID=$(curl -s -X POST http://127.0.0.1:5191/api/games | python3 -c "import sys,json; print(json.load(sys.stdin).get('game_id',''))")
echo "Game ID: $GAME_ID"

# 查詢狀態
curl -s "http://127.0.0.1:5191/api/games/${GAME_ID}/state" | python3 -m json.tool

# 提交指令（P1 第一回合通常可部署）
curl -s -X POST "http://127.0.0.1:5191/api/games/${GAME_ID}/command" \
  -H "Content-Type: application/json" \
  -d '{"command": "pass"}' | python3 -m json.tool
```

---

## 八、風險評估

| # | 風險 | 嚴重性 | 緩解措施 | 發生機率 |
|---|------|--------|----------|----------|
| **R1** | `gcg/config.py` 中有未被發現的 hardcoded 絕對路徑 | **中** | Phase 2 已審查全部 6 個路徑函數。額外 grep `gcg/` 尋找所有 `Path(` 使用 | 低 |
| **R2** | `gcg/ai/hermes_player_client.py` 內部引用 `knowledge/gcg-ai-player.md`，若未搬入會在 hermes mode 報錯 | **低** | MCTS mode 不使用 hermes player；若需 hermes mode，確保 O1 已執行 | 低（MCTS 模式不受影響） |
| **R3** | Vercel `api/games.py` 的 Python runtime 預設 `sys.path` 可能與本地不同 | **中** | `api/games.py` 已明確設定 `sys.path`；Phase 3 更新後應覆蓋任何預設行為 | 中 |
| **R4** | `CardDatabase._load_cards()` 使用 `*Card.json` glob，若 card data 目錄不存在會靜默載入 0 張卡 | **高** | Phase 2 確保 `card_data_root()` 指向 `battle_app/card/data/`；驗證步驟 7.2 檢查 card count | 低（已有驗證） |
| **R5** | Vercel 部署包大小限制（通常 50MB） | **低** | 最小部署包 ~830KB，遠低於限制 | 極低 |
| **R6** | `battle_app/scenarios.py` 的 `DEFAULT_SCENARIO_ROOT` 指向 `scenarios/manual/`，若未搬入會導致 scenario mode 報錯 | **低** | 不啟用 `GCG_ENABLE_SCENARIO_MODE` 則不會觸發此路徑 | 低 |
| **R7** | 搬移後 `gcgV2/` 原位置的 `gcg/` 目錄仍存在，可能導致混淆 | **低** | 建議將原 `gcgV2/gcg/` rename 為 `gcgV2/gcg.bak/` 以確保不會意外引用 | 低 |
| **R8** | `battle_app/tests/` 中的測試可能依賴舊的專案根目錄結構 | **低** | 測試檔案路徑引用可能需要更新，但這不影響 production 部署 | 中（測試可能需要適配） |

---

## 九、明確不變項目

以下項目在本次實作中**絕不修改**：

- ❌ **所有 `from gcg.xxx import ...` 格式的 import statement**（gcg 內部模組間引用）
- ❌ **所有 `from reviewboard.xxx import ...` 格式的 import statement**
- ❌ **所有 business logic**（`battle_session.py`、`bootstrap.py`、`runtime.py`、`state_store.py`、`effect_engine.py`、`rules_index.py`、`action_enumerator.py`、`MctsPlayer`、`ISMCTS` 等核心邏輯）
- ❌ **`battle_app/server.py`、`runtime_document.py`、`storage.py`、`scenarios.py` 的核心邏輯**
- ❌ **`battle_app/public/` 中的前端檔案**（`battleV3.js`、`battleV3.css`、`index.html`）
- ❌ **`battle_app/.env.local` 與 `.env.example` 的內容**（可手動更新註解）
- ❌ **`card/data/*.json`、`card/gcgdecks.json`、`manifests/*.yaml`、`schemas/*.yaml` 的內容**
- ❌ **任何 effect engine、state store、action enumerator、rules index 的演算法或合約**

---

## 十、最終部署目錄結構

```
battle_app/                              ← 部署根目錄（即 GCGV2_ROOT）
├── server.py                            # local server entry
├── env.py                               # 環境變數載入
├── scenarios.py                         # 測試場景
├── runtime_document.py                  # Document-backed battle runtime
├── storage.py                           # MongoDB persistence
├── public/                              # 靜態前端
│   ├── battleV3.js
│   ├── battleV3.css
│   └── index.html
├── api/                                 # Vercel serverless entry
│   └── games.py
├── tests/                               # 測試
│   ├── test_env.py
│   ├── test_local_multiroom.py
│   ├── test_runtime_document.py
│   └── test_mongo_storage.py
├── gcg/                                 # ← 搬入：runtime engine (40 .py)
│   ├── __init__.py
│   ├── config.py                        # ← 已調整路徑
│   ├── cards.py
│   ├── ai/
│   │   ├── mcts/                        # MCTS player 全部依賴
│   │   └── ...
│   ├── effects/
│   ├── engine/
│   ├── gamelog/
│   └── sim/
├── reviewboard/                         # ← 搬入：battle session
│   └── humanVsAI/
│       ├── __init__.py
│       ├── battle_session.py
│       └── command_labels.py
├── card/                                # ← 搬入：卡片資料
│   ├── data/
│   │   ├── st01Card.json
│   │   ├── st02Card.json
│   │   ├── ... (12 個 JSON)
│   │   └── gd03Card.json
│   └── gcgdecks.json
├── manifests/                           # ← 搬入：效果詞彙表
│   └── GCG_V2_EFFECT_DICTIONARY.yaml
├── schemas/                             # ← 搬入：結構化效果 schema (原 docs/)
│   ├── st01_card_effects_schema.yaml
│   ├── st02_card_effects_schema.yaml
│   ├── st03_card_effects_schema.yaml
│   └── st04_card_effects_schema.yaml
├── knowledge/                           # ← 可選：AI prompt（僅 hermes/llm mode）
│   └── gcg-ai-player.md
├── .env.local                           # 本地開發環境變數
├── .env.example                         # 環境變數範本
└── .gitignore                           # 排除 __pycache__/ out/ .understand-anything/
```

---

## 十一、執行順序總結

| Phase | 內容 | 預估時間 | 風險 |
|-------|------|----------|------|
| **Phase 1** | 執行 shell 指令搬移/複製全部依賴檔案 | 1 分鐘 | 低（純檔案操作） |
| **Phase 2** | 修改 `gcg/config.py` 的 `REPO_ROOT` 與 `card_effect_schema_paths()` | 2 分鐘 | 低（3 處改動） |
| **Phase 3** | 修改 `server.py`、`api/games.py`、`scenarios.py`、`env.py` 的 `sys.path` 設定 | 3 分鐘 | 低（4 個檔案，最小改動） |
| **Phase 4** | 清理 `__pycache__/`、`.understand-anything/` | 1 分鐘 | 低 |
| **Phase 5** | 執行 7.1–7.4 驗證步驟 | 5 分鐘 | 中（首次完整驗證） |
| **Phase 6** | （可選）Vercel 部署測試 | 5 分鐘 | 中（依賴 Vercel 環境） |

**總預估時間：~20 分鐘**

---

## 十二、回滾方案

若部署失敗需要回滾：

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app

# 1. 刪除搬入的依賴目錄（保留原有檔案）
rm -rf gcg/ reviewboard/ card/ manifests/ schemas/ knowledge/

# 2. 用 git restore 恢復被修改的檔案
git checkout -- server.py api/games.py scenarios.py env.py
# gcg/config.py 在原位置，未受搬移影響（原檔仍在 gcgV2/gcg/config.py）
```

由於 `gcgV2/gcg/config.py` 原檔未被修改（`battle_app/gcg/config.py` 是獨立複本），回滾後所有內容恢復原狀。

---

*計劃生成時間：2026-06-23*
*目標模式：GCG_BATTLE_AI_MODE=mcts + GCG_BATTLE_INTERPRETER=schema*
