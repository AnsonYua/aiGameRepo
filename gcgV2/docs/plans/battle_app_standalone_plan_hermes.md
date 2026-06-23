# Battle App Standalone Deployment Plan (Hermes Draft)

## 目標

令 `battle_app/` 成為**真正 standalone 部署單位**：將 `battle_app/` upload 去 server 後，唔需要任何外部依賴即可運行。

## 現狀問題

`battle_app/` 依家依賴以下**外部路徑**（相對 `gcgV2/` 而言喺 `battle_app/` 出面）：

| 依賴 | 當前位置 | 引用方式 |
|------|----------|----------|
| `gcg/` runtime engine | `gcgV2/gcg/` | `from gcg.cards import ...` |
| `reviewboard/humanVsAI/` | `gcgV2/reviewboard/humanVsAI/` | `from reviewboard.humanVsAI.battle_session import ...` |
| card data JSON | `cardAI/card/data/` | config.py `card_data_root()` |
| deck config | `cardAI/card/gcgdecks.json` | config.py `deck_file()` |
| effect dictionary | `gcgV2/manifests/GCG_V2_EFFECT_DICTIONARY.yaml` | config.py `effect_dictionary_path()` |
| schema YAML | `gcgV2/docs/st*_card_effects_schema.yaml` | config.py `card_effect_schema_paths()` |
| knowledge | `gcgV2/knowledge/` | config.py `knowledge_root()` |

## 策略：將依賴搬入 battle_app/

### 最終目錄結構

```
battle_app/                         ← 新 repo root（GCGV2_ROOT）
├── server.py                       # 現有，唔改
├── env.py                          # 現有，唔改
├── scenarios.py                    # 現有，唔改
├── runtime_document.py             # 現有，唔改
├── storage.py                      # 現有，唔改
├── public/
│   ├── battleV3.js
│   ├── battleV3.css
│   └── index.html
├── api/
│   └── games.py
├── tests/
│   ├── test_env.py
│   ├── test_local_multiroom.py
│   ├── test_runtime_document.py
│   └── test_mongo_storage.py
├── schemas/                        # ← new: 取代 docs/
│   ├── st01_card_effects_schema.yaml
│   ├── st02_card_effects_schema.yaml
│   ├── st03_card_effects_schema.yaml
│   └── st04_card_effects_schema.yaml
├── manifests/                      # ← moved in
│   └── GCG_V2_EFFECT_DICTIONARY.yaml
├── card/                           # ← moved in
│   ├── data/
│   │   ├── st01Card.json
│   │   ├── st02Card.json
│   │   ├── st03Card.json
│   │   ├── st04Card.json
│   │   ├── st05Card.json
│   │   ├── st06Card.json
│   │   ├── st07Card.json
│   │   ├── st08Card.json
│   │   ├── st09Card.json
│   │   ├── gd01Card.json
│   │   ├── gd02Card.json
│   │   └── gd03Card.json
│   └── gcgdecks.json
├── gcg/                            # ← moved in
│   ├── __init__.py
│   ├── config.py                   # ← 需調整路徑（見下文）
│   ├── ai/
│   ├── cards/
│   ├── effects/
│   │   ├── dictionary.py
│   │   ├── interpreter.py
│   │   ├── reference_st01.py
│   │   ├── schema_interpreter.py
│   │   ├── schema_loader.py
│   │   ├── spec_gate.py
│   │   └── __init__.py
│   ├── engine/
│   ├── gamelog/
│   └── sim/
├── reviewboard/                    # ← moved in（只需 humanVsAI/）
│   └── humanVsAI/
│       ├── battle_session.py
│       ├── command_labels.py
│       └── requirements.md
├── knowledge/                      # ← optional: MCTS+schema 唔需要，保留俾 hermes mode
│   └── gcg-ai-player.md
└── out/                            # ← runtime 自動建立，唔需要 source control
```

### Phase 1: Move Files（不改變程式碼邏輯）

| # | 動作 | Source → Dest |
|---|------|---------------|
| 1 | Move `gcg/` dir | `gcgV2/gcg/` → `battle_app/gcg/` |
| 2 | Move `reviewboard/humanVsAI/` dir | `gcgV2/reviewboard/humanVsAI/` → `battle_app/reviewboard/humanVsAI/` |
| 3 | Copy `card/data/` JSONs | `cardAI/card/data/` → `battle_app/card/data/` |
| 4 | Copy `card/gcgdecks.json` | `cardAI/card/gcgdecks.json` → `battle_app/card/gcgdecks.json` |
| 5 | Copy `manifests/` | `gcgV2/manifests/` → `battle_app/manifests/` |
| 6 | Copy schema YAMLs | `gcgV2/docs/st*_card_effects_schema.yaml` → `battle_app/schemas/` |
| 7 | (Optional) Copy `knowledge/gcg-ai-player.md` | `gcgV2/knowledge/gcg-ai-player.md` → `battle_app/knowledge/gcg-ai-player.md` |

**注意**: 用 **copy** 唔好用 symlink。Deploy 時 Vercel/project root 只係 `battle_app/`，symlink 出去 project root 外面唔可靠。

### Phase 2: Adjust config.py Paths（必要的最小改動）

由於 `gcg/config.py` 搬入 `battle_app/gcg/config.py` 後：
- `Path(__file__).resolve().parents[1]` 會 resolve 做 `battle_app/`（而唔係以前嘅 `gcgV2/`）

以下 6 行需要調整路徑預設值：

```python
# === gcg/config.py ===

# 1. GCGV2_ROOT 保持不變 — parents[1] 自動指向 battle_app/ ✅
GCGV2_ROOT = Path(__file__).resolve().parents[1]

# 2. REPO_ROOT 改為指向 GCGV2_ROOT（card/data/ 已搬入 battle_app/）
#    舊: REPO_ROOT = GCGV2_ROOT.parent
#    新: REPO_ROOT = GCGV2_ROOT
REPO_ROOT = GCGV2_ROOT

# 3. card_effect_schema_paths() — 簡化，只指向 schemas/
#    舊: GCGV2_ROOT / "docs" / "st01_card_effects_schema.yaml"（+ fallback）
#    新: GCGV2_ROOT / "schemas" / "st01_card_effects_schema.yaml"
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

# 4. effect_dictionary_path() — 已經正確 ✅
#    manifests/ 搬入 battle_app/manifests/，路徑唔使改

# 5. card_data_root() — REPO_ROOT 改咗就自動正確 ✅

# 6. deck_file() — REPO_ROOT 改咗就自動正確 ✅
```

**合計改動：約 5 行**（REPO_ROOT 改 1 行 + card_effect_schema_paths 簡化 ~4 行）

### Phase 3: Cleanup（刪除暫時性/多餘嘢）

| 動作 | 原因 |
|------|------|
| Remove `battle_app/schemas/*.yaml` symlinks | 改用 real copy |
| Remove `config.py` 入面嘅 `docs/` fallback 邏輯 | GCGV2_ROOT 已指向 battle_app/，`docs/` 唔存在 |
| Remove `battle_app/.understand-anything/` | 唔應該 deploy |
| Remove `battle_app/__pycache__/` | gitignore |

### Phase 4: Verify

```bash
# 1. py_compile check（所有 modules）
cd battle_app
python3 -m py_compile server.py api/games.py runtime_document.py scenarios.py
python3 -m py_compile gcg/config.py gcg/cards/__init__.py gcg/effects/schema_loader.py gcg/sim/bootstrap.py
python3 -m py_compile reviewboard/humanVsAI/battle_session.py

# 2. Import test（simulate 部署環境）
python3 -c "
import sys; sys.path.insert(0, '.')
from gcg.config import GCGV2_ROOT, card_effect_schema_paths, card_data_root, deck_file, effect_dictionary_path
print('GCGV2_ROOT:', GCGV2_ROOT)
print('schema_paths:', card_effect_schema_paths())
print('card_data_root:', card_data_root())
print('deck_file:', deck_file())
print('effect_dict:', effect_dictionary_path())
assert all(p.exists() for p in card_effect_schema_paths())
assert card_data_root().exists()
assert deck_file().exists()
assert effect_dictionary_path().exists()
print('ALL PATHS OK')
"

# 3. Start server test
python3 server.py --host 127.0.0.1 --port 5190 &
sleep 2
curl -s http://127.0.0.1:5190/api/games
kill %1
```

## 可選 vs 必需要搬嘅嘢

| 資源 | 必需？ | 備註 |
|------|--------|------|
| `gcg/` | ✅ 必需 | runtime engine |
| `reviewboard/humanVsAI/` | ✅ 必需 | battle session |
| `card/data/` | ✅ 必需 | card JSON database |
| `card/gcgdecks.json` | ✅ 必需 | deck config |
| `manifests/GCG_V2_EFFECT_DICTIONARY.yaml` | ✅ 必需 | LLM interpreter 詞彙表；schema interpreter 都要 |
| `schemas/st*_card_effects_schema.yaml` | ✅ 必需（schema mode） | GCG_BATTLE_INTERPRETER=schema |
| `knowledge/gcg-ai-player.md` | ⚠️ optional | 只有 hermes/llm AI mode 需要；MCTS 唔需要 |
| `knowledge/experience/` | ❌ 唔需要部署 | AI 經驗教訓，唔係 runtime 必須 |
| `out/` | ❌ runtime auto-create | 唔使搬 |
| `manifests/GCG_V2_GAMEPLAY_YAML_SCHEMA.md` | ❌ | 文檔，唔係 runtime 必須 |

## Risk Assessment

| Risk | Severity | Mitigation |
|------|----------|------------|
| `gcg/config.py` 入面有 hardcode 咗 `docs/` 以外嘅舊路徑 | LOW | Phase 2 檢查晒全部 `_path_from_env` defaults |
| `reviewboard/humanVsAI/requirements.md` 入面有 absolute path references | LOW | 文檔 only，唔影響 runtime |
| Vercel `api/games.py` 行唔到 `build_simulator()`（Mongo 路徑唔同） | MEDIUM | 需要分別測試 local server vs Vercel API |
| `CardDatabase` load path 可能 hardcode 咗 absolute path | LOW | `CardDatabase.__init__` 用 `config.card_data_root()`，跟 config 走 |
| 搬完後 `gcgV2/` 原本位置嘅 import 會 broken | LOW | 其他 tool（reviewboard/server.py 等）可能需要 update，但 battle_app 本身唔受影響 |
| `battle_app/api/games.py` sys.path insert 指向舊 GCGV2_ROOT | MEDIUM | Phase 2 需檢查 `api/games.py:12` 嘅 `GCGV2_ROOT = BATTLE_APP_ROOT.parent`；搬完後 BATTLE_APP_ROOT.parent 唔同咗 |

## 不變項目

- ❌ 不改任何 business logic
- ❌ 不改 import statements（`from gcg.xxx import` 等）
- ❌ 不改 `battle_session.py`、`bootstrap.py`、`server.py`、`scenarios.py`、`runtime_document.py` 嘅 logic
- ❌ 不改 effect engine、state store、action enumerator、rules index 任何嘢
