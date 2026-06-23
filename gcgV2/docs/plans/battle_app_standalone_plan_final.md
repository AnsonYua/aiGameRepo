# Battle App Standalone Deployment — v3 Final Plan（2026-06-23 15:05）

> 經三輪 review（Hermes draft → Codex draft → User isolated-copy verification）。
> User 實測確認：isolated copy of `battle_app/` 仍然 `ModuleNotFoundError: No module named 'gcg'`。
> Phase 1-5 未執行。呢份係**實作前最終可執行計劃**。

---

## 部署策略決策

| 環境 | AI mode | Interpreter | 原因 |
|------|---------|-------------|------|
| Local battle_app | `hermes` | `schema` | Hermes 依賴本機 Hermes/Codex wrapper，保留 local dev 體驗。 |
| Vercel production | `mcts` | `schema` | Vercel serverless 沒有本機 Hermes process；MCTS+schema 無外部 LLM/runtime process 依賴。 |

**Production 不使用 Hermes。** Vercel Project Settings 必須設定：

```bash
MONGODB_URI=...
GCG_BATTLE_AI_MODE=mcts
GCG_BATTLE_INTERPRETER=schema
```

建議 production MCTS 初始限速設定：

```bash
GCG_MCTS_TIME_BUDGET_MS=3000
GCG_MCTS_ITERATIONS=100
```

Local-only `battle_app/.env.local` 可保留：

```bash
GCG_BATTLE_AI_MODE=hermes
GCG_BATTLE_INTERPRETER=schema
```

若要本機模擬 production，暫時改成：

```bash
GCG_BATTLE_AI_MODE=mcts
GCG_BATTLE_INTERPRETER=schema
```

---

## 現狀 vs 目標 Diff

| # | 問題 | 現狀（14:40） | 目標狀態 | Severity |
|---|------|--------------|----------|----------|
| 1 | `battle_app/gcg/` 不存在 | ❌ 未搬 | ✅ `cp -r gcg battle_app/gcg` | **P0** |
| 2 | `battle_app/reviewboard/humanVsAI/` 不存在 | ❌ 未搬 | ✅ 搬入 | **P0** |
| 3 | `battle_app/card/data/` 不存在 | ❌ 未搬 | ✅ 搬入 | **P0** |
| 4 | `battle_app/card/gcgdecks.json` 不存在 | ❌ 未搬 | ✅ 搬入 | **P0** |
| 5 | `battle_app/manifests/` 不存在 | ❌ 未搬 | ✅ 搬入 | **P0** |
| 6 | `battle_app/schemas/` 係 symlinks → `../../docs/` | ❌ symlink | ✅ real YAML copy | **P1** |
| 7 | `battle_app/scenarios/manual/` 不存在 | ❌ local scenario tests fail | ✅ 搬入 manual scenarios | **P1** |
| 8 | `gcg/config.py` fallback path: `GCGV2_ROOT / "battle_app" / "schemas"` | ❌ double-nested (battle_app/battle_app/schemas) | ✅ `GCGV2_ROOT / "schemas"` | **P0** |
| 9 | `battle_app/server.py` `GCGV2_ROOT = BATTLE_APP_ROOT.parent` | ❌ 指向 gcgV2/ | ✅ `GCGV2_ROOT = BATTLE_APP_ROOT` | **P0** |
| 10 | `battle_app/api/games.py` `GCGV2_ROOT = BATTLE_APP_ROOT.parent` | ❌ 同上 | ✅ 同上 | **P0** |
| 11 | `battle_app/scenarios.py` `GCGV2_ROOT = BATTLE_APP_ROOT.parent` | ❌ 同上 | ✅ 同上 | **P0** |
| 12 | `battle_app/env.py` `GCGV2_ROOT = BATTLE_APP_ROOT.parent` | ❌ 同上 | ✅ 同上 | **P0** |
| 13 | `battle_app/.understand-anything/` 存在（~808KB） | ❌ 會 deploy | ✅ `rm -rf` | **P1** |
| 14 | `battle_app/__pycache__/` 存在 | ❌ 會 deploy | ✅ 清理 | **P1** |

---

## Phase 0：Pre-Flight Baseline（先確認現狀失敗）

```bash
cd /Users/hello/Desktop/cardAI/gcgV2

# 建立 isolated copy 測試
ISODIR=$(mktemp -d)
cp -R battle_app "$ISODIR/battle_app"
cd "$ISODIR/battle_app"
python3 -c "import api.games" 2>&1
# 預期：ModuleNotFoundError: No module named 'gcg'

cd /Users/hello/Desktop/cardAI/gcgV2
rm -rf "$ISODIR"
```

呢個係 baseline。做完 Phase 1-4 後再跑一次，必須 pass。

---

## Phase 1：檔案搬移（replace symlinks with real copies）

全部用 `cp`（real copy），唔用 symlink。**先 delete 現有 target directory，再 cp，確保重跑 plan 不會殘留舊檔或 nested copy。**

```bash
cd /Users/hello/Desktop/cardAI/gcgV2

# === 1a: 清除現有 target directories / symlinks ===
rm -rf battle_app/gcg
rm -rf battle_app/reviewboard/humanVsAI
rm -rf battle_app/card
rm -rf battle_app/manifests
rm -rf battle_app/schemas
rm -rf battle_app/knowledge
rm -rf battle_app/scenarios

# === 1b: M1 — gcg/ runtime engine ===
cp -r gcg battle_app/gcg
find battle_app/gcg -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null
find battle_app/gcg -name '*.pyc' -delete 2>/dev/null

# === 1c: M2 — reviewboard/humanVsAI/ ===
mkdir -p battle_app/reviewboard
cp -r reviewboard/humanVsAI battle_app/reviewboard/humanVsAI
find battle_app/reviewboard -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null

# Confirm __init__.py exists
test -f battle_app/reviewboard/humanVsAI/__init__.py || touch battle_app/reviewboard/humanVsAI/__init__.py

# === 1d: M3 — card data JSON（12 files）===
mkdir -p battle_app/card/data
cp ../card/data/st0*Card.json battle_app/card/data/
cp ../card/data/gd0*Card.json battle_app/card/data/

# === 1e: M4 — deck config ===
cp ../card/gcgdecks.json battle_app/card/

# === 1f: M5 — effect dictionary ===
mkdir -p battle_app/manifests
cp manifests/GCG_V2_EFFECT_DICTIONARY.yaml battle_app/manifests/

# === 1g: M6 — schema YAML（real copies, NOT symlinks）===
mkdir -p battle_app/schemas
cp docs/st01_card_effects_schema.yaml battle_app/schemas/
cp docs/st02_card_effects_schema.yaml battle_app/schemas/
cp docs/st03_card_effects_schema.yaml battle_app/schemas/
cp docs/st04_card_effects_schema.yaml battle_app/schemas/

# Verify: schemas/ must be real files, not symlinks
file battle_app/schemas/st01_card_effects_schema.yaml
# Expected: "ASCII text" or "UTF-8 Unicode text", NOT "symbolic link"

# === 1h: O1 (optional) — AI prompt ===
mkdir -p battle_app/knowledge
cp knowledge/gcg-ai-player.md battle_app/knowledge/

# === 1i: local manual scenarios（for scenario/dev tests; production flag remains off）===
mkdir -p battle_app/scenarios
cp -R scenarios/manual battle_app/scenarios/manual
```

---

## Phase 2：`battle_app/gcg/config.py` 路徑調整

搬移後 `Path(__file__).resolve().parents[1]` 自動 resolve 為 `battle_app/`。

### 改動 2.1：`REPO_ROOT`（1 行，第 12 行）

```python
# 現狀：
REPO_ROOT = GCGV2_ROOT.parent

# 改為：
REPO_ROOT = GCGV2_ROOT
```

**原因**：`card/data/`、`card/gcgdecks.json` 已搬入 `battle_app/card/` = `GCGV2_ROOT/card/`。`card_data_root()` 同 `deck_file()` 都用 `REPO_ROOT / "card" / ...`。

### 改動 2.2：`card_effect_schema_paths()`（replace 現有 fallback 邏輯，第 55-73 行）

```python
# 現狀（有 bug — battle_app/battle_app/schemas double-nesting）：
def card_effect_schema_paths() -> list[Path]:
    raw = os.getenv("GCG_CARD_EFFECT_SCHEMA_PATHS")
    if raw:
        return [Path(part).expanduser() for part in raw.split(os.pathsep) if part.strip()]
    primary = GCGV2_ROOT / "docs" / "st01_card_effects_schema.yaml"
    if primary.exists():
        return [
            GCGV2_ROOT / "docs" / "st01_card_effects_schema.yaml",
            ...
        ]
    return [
        GCGV2_ROOT / "battle_app" / "schemas" / "st01_card_effects_schema.yaml",  # ← BUG
        ...
    ]

# 改為（簡化，直接指向 schemas/）：
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

**原因**：`GCGV2_ROOT` = `battle_app/`，所以 `GCGV2_ROOT / "schemas"` = `battle_app/schemas/`。不再需要 `docs/` 或 `battle_app/battle_app/schemas` 嘅 fallback 邏輯。

### 無需修改（REPO_ROOT 改後自動正確）

| 函數 | 預設值 | 搬移後解析 |
|------|--------|-----------|
| `card_data_root()` | `REPO_ROOT / "card" / "data"` | `battle_app/card/data/` ✅ |
| `deck_file()` | `REPO_ROOT / "card" / "gcgdecks.json"` | `battle_app/card/gcgdecks.json` ✅ |
| `effect_dictionary_path()` | `GCGV2_ROOT / "manifests" / "..."` | `battle_app/manifests/` ✅ |
| `output_root()` | `GCGV2_ROOT / "out"` | `battle_app/out/` ✅ |
| `knowledge_root()` | `GCGV2_ROOT / "knowledge"` | `battle_app/knowledge/` ✅ |

---

## Phase 3：`battle_app/` 內部 `sys.path` 調整 ⚠️

搬移後 `gcg/` 同 `reviewboard/` 喺 `battle_app/` 裡面。需同時支持三種 import：

| Import 格式 | 需要嘅 sys.path |
|-------------|----------------|
| `from gcg.xxx import ...` | `battle_app/` |
| `from reviewboard.xxx import ...` | `battle_app/` |
| `from battle_app.xxx import ...` | `battle_app/` 嘅 **parent** |

所以每個入口檔案需同時加 `BATTLE_APP_ROOT` 同 `BATTLE_APP_ROOT.parent` 入 `sys.path`。

### 3.1 `battle_app/server.py`

新增 import：

```python
import types
```

```python
# 現狀（第 24-29 行）：
BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT.parent
PUBLIC_ROOT = BATTLE_APP_ROOT / "public"
if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))

# 改為：
BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT
PUBLIC_ROOT = BATTLE_APP_ROOT / "public"
for _p in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# 若 deployment root 係 battle_app contents，而唔係 parent/battle_app，
# 需要將目前 root 註冊成 battle_app package，令 battle_app.* imports 成立。
if "battle_app" not in sys.modules:
    package = types.ModuleType("battle_app")
    package.__package__ = "battle_app"
    package.__path__ = [str(BATTLE_APP_ROOT)]
    sys.modules["battle_app"] = package
```

### 3.2 `battle_app/api/games.py`

新增 import：

```python
import types
```

```python
# 現狀（第 10-15 行）：
GCGV2_ROOT = BATTLE_APP_ROOT.parent
for path in (GCGV2_ROOT, BATTLE_APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

# 改為：
GCGV2_ROOT = BATTLE_APP_ROOT
for _p in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
if "battle_app" not in sys.modules:
    package = types.ModuleType("battle_app")
    package.__package__ = "battle_app"
    package.__path__ = [str(BATTLE_APP_ROOT)]
    sys.modules["battle_app"] = package
```

### 3.3 `battle_app/scenarios.py`

```python
# 現狀（第 14-15 行）：
GCGV2_ROOT = BATTLE_APP_ROOT.parent

# 改為：
GCGV2_ROOT = BATTLE_APP_ROOT
```

### 3.4 `battle_app/env.py`

```python
# 現狀（第 13-14 行）：
GCGV2_ROOT = BATTLE_APP_ROOT.parent

# 改為：
GCGV2_ROOT = BATTLE_APP_ROOT
```

### 3.5 `battle_app/reviewboard/humanVsAI/battle_session.py` — **無需修改**

```python
GCGV2_ROOT = Path(__file__).resolve().parents[2]
# battle_app/reviewboard/humanVsAI/battle_session.py → parents[2] = battle_app/ ✅
```

---

## Phase 4：清理部署不應包含嘅檔案

```bash
cd /Users/hello/Desktop/cardAI/gcgV2

# Remove generated local tooling（~808KB）
rm -rf battle_app/.understand-anything/

# Remove all __pycache__
find battle_app -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null
find battle_app -name '*.pyc' -delete 2>/dev/null
```

新增 `battle_app/.vercelignore`，避免測試、local env、生成物進入 deployment package：

```text
tests/
**/__pycache__/
**/*.pyc
.understand-anything/
out/
.env
.env.local
.DS_Store
```

同時在 `battle_app/vercel.json` 的 Python function 設定加入 bundle 排除，避免 tests / generated local files 被打包入 function：

```json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "outputDirectory": "public",
  "functions": {
    "api/games.py": {
      "maxDuration": 300,
      "excludeFiles": "{tests/**,**/__pycache__/**,**/*.pyc,.understand-anything/**,out/**}"
    }
  },
  "rewrites": [
    {
      "source": "/api/games/:path*",
      "destination": "/api/games?path=:path*"
    }
  ]
}
```

⚠️ **現有嘅 `maxDuration: 300` 同 `rewrites` 必須保留**；只係新增 `excludeFiles` field（唔好 overwrite 現有 config）。

---

## Phase 5：驗證（~5 分鐘）

### 5.1 py_compile

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app
for f in server.py api/games.py runtime_document.py scenarios.py env.py storage.py \
         gcg/config.py gcg/cards.py gcg/sim/bootstrap.py \
         gcg/effects/schema_loader.py gcg/effects/dictionary.py \
         gcg/ai/mcts/__init__.py \
         reviewboard/humanVsAI/battle_session.py reviewboard/humanVsAI/command_labels.py; do
    python3 -m py_compile "$f" || echo "FAIL: $f"
done
```

### 5.2 路徑解析驗證

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app
python3 -c "
import sys
from pathlib import Path
BATTLE_APP_ROOT = Path('.').resolve()
for p in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):
    if str(p) not in sys.path: sys.path.insert(0, str(p))

from gcg.config import *
print('GCGV2_ROOT:', GCGV2_ROOT)
assert GCGV2_ROOT.name == 'battle_app', f'Expected battle_app, got {GCGV2_ROOT.name}'

# Verify all schema paths are real files
for p in card_effect_schema_paths():
    assert p.exists(), f'MISSING: {p}'
    assert not p.is_symlink(), f'SYMLINK (not real copy): {p}'
    print(f'  {p}  real_file=True')

assert card_data_root().exists()
assert deck_file().exists()
assert effect_dictionary_path().exists()
print('ALL PATH CHECKS PASSED')
"
```

### 5.3 完整 import stack（MCTS+schema）

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app
GCG_BATTLE_AI_MODE=mcts GCG_BATTLE_INTERPRETER=schema python3 -c "
import sys
from pathlib import Path
BATTLE_APP_ROOT = Path('.').resolve()
for p in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):
    if str(p) not in sys.path: sys.path.insert(0, str(p))

from gcg.cards import CardDatabase
from gcg.sim.bootstrap import build_simulator
from gcg.effects.dictionary import EffectDictionary
from gcg.effects.schema_loader import CardEffectSchemaLoader
from reviewboard.humanVsAI.battle_session import HumanVsAiBattleSession
from battle_app.env import load_battle_app_env

load_battle_app_env()
db = CardDatabase()
print(f'Cards: {len(db.cards)}')
assert len(db.cards) > 0, 'CardDatabase empty!'

schema = CardEffectSchemaLoader().load()
print(f'Schema cards: {len(schema.cards)}')
assert len(schema.cards) > 0, 'Schema index empty!'

runner = build_simulator(players='mcts', interpreter='schema', output_root='/tmp/gcg_test')
print(f'Runner built: game_id={runner.game_id}')
print('ALL IMPORTS + INSTANTIATION PASSED')
"
```

### 5.4 Local server API smoke test

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app
GCG_BATTLE_AI_MODE=mcts GCG_BATTLE_INTERPRETER=schema \
  python3 server.py --host 127.0.0.1 --port 5191 &
sleep 2
curl -s http://127.0.0.1:5191/api/games
curl -s -X POST http://127.0.0.1:5191/api/games | python3 -m json.tool
kill %1 2>/dev/null
```

### 5.5 ⭐ Isolated Copy Test（definitive proof）

```bash
cd /Users/hello/Desktop/cardAI/gcgV2

ISODIR=$(mktemp -d)
cp -R battle_app "$ISODIR/battle_app"
cd "$ISODIR/battle_app"

GCG_BATTLE_AI_MODE=mcts GCG_BATTLE_INTERPRETER=schema python3 -c "
import sys
from pathlib import Path
BATTLE_APP_ROOT = Path('.').resolve()
for p in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):
    if str(p) not in sys.path: sys.path.insert(0, str(p))
import api.games
print('api.games import ok')
from gcg.sim.bootstrap import build_simulator
runner = build_simulator(players='mcts', interpreter='schema', output_root='/tmp/gcg_test')
print('ISOLATED COPY: PASS — runner built successfully')
" 2>&1

cd /Users/hello/Desktop/cardAI/gcgV2
rm -rf "$ISODIR"
```

**如果 5.5 fail，deploy 仍然唔會 work。** 呢個係最終 acceptance test。

### 5.5b Vercel Project Root Contents Test（stricter）

模擬 Vercel 將 `battle_app/` 設為 project root，deployment root 直接包含 `api/`, `gcg/`, `runtime_document.py` 等檔案，而唔係 parent folder 入面再有 `battle_app/` directory。

```bash
cd /Users/hello/Desktop/cardAI/gcgV2

ROOT=$(mktemp -d)
cp -R battle_app/. "$ROOT/"
cd "$ROOT"

GCG_BATTLE_AI_MODE=mcts GCG_BATTLE_INTERPRETER=schema python3 -c "
import api.games
print('api.games import ok')
from battle_app.runtime_document import DocumentBackedBattle
from gcg.sim.bootstrap import build_simulator
runner = build_simulator(players='mcts', interpreter='schema', output_root='/tmp/gcg_test')
print('VERCEL ROOT COPY: PASS — runner built successfully')
"

cd /Users/hello/Desktop/cardAI/gcgV2
rm -rf "$ROOT"
```

呢個 test 比 5.5 更接近 Vercel project-root packaging；必須 pass。

---

### 5.6 Production env contract check

Vercel production 必須具備以下 env vars；不要將 secrets 寫入 git：

```bash
MONGODB_URI=...
GCG_BATTLE_AI_MODE=mcts
GCG_BATTLE_INTERPRETER=schema
```

Local `.env.local` 的 `hermes` 不應被同步到 production。

---

## Phase 6：Vercel Build / Preview / Production Gate

### 6.1 Local Vercel build

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app
vercel build
vercel build --prod
```

兩個 build 都必須成功。若 `vercel build --prod` 缺 `MONGODB_URI` 或 project env，先在 Vercel Project Settings 補齊，不要 commit secret。

### 6.2 Preview deploy smoke

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app
PREVIEW_URL=$(vercel deploy)
curl -s "$PREVIEW_URL/api/games"
CREATE_PAYLOAD=$(curl -s -X POST "$PREVIEW_URL/api/games")
echo "$CREATE_PAYLOAD" | python3 -m json.tool
```

`POST /api/games` 必須回傳 `ok: true`、`game_id`、`viewer_state`。如果只係 `/api/games` list 成功但 create game 失敗，仍然不算通過。

### 6.2a Preview game lifecycle test

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app
PREVIEW_URL=$(vercel deploy)
GAME_ID=$(curl -s -X POST "$PREVIEW_URL/api/games" | python3 -c "import sys,json; print(json.load(sys.stdin)['game_id'])")
echo "Game: $GAME_ID"

# Verify state route works (tests vercel.json rewrites rule)
curl -s "$PREVIEW_URL/api/games/$GAME_ID/state" | python3 -c "
import sys,json
s=json.load(sys.stdin)
assert 'viewer_state' in s, 'Missing viewer_state'
assert 'legal_commands' in s, 'Missing legal_commands'
print('State ok: phase={} step={}'.format(s['viewer_state'].get('phase'), s['viewer_state'].get('step')))
"

# Verify command route works with an actual legal command from state
STATE=$(curl -s "$PREVIEW_URL/api/games/$GAME_ID/state")
CMD=$(echo "$STATE" | python3 -c "import sys,json; s=json.load(sys.stdin); print(s['legal_commands'][0])")
curl -s -X POST "$PREVIEW_URL/api/games/$GAME_ID/command" \
  -H "Content-Type: application/json" \
  -d "{\"command\":\"$CMD\"}" | python3 -c "
import sys,json
s=json.load(sys.stdin)
assert s.get('ok') is True, s
print('Command ok:', s.get('message'))
"
```

`/api/games/<id>/state` 同 `/api/games/<id>/command` 必須 return 200。呢個係 battleV3.js 實際 call 嘅 endpoint。

### 6.3 Production deploy smoke

```bash
cd /Users/hello/Desktop/cardAI/gcgV2/battle_app
PROD_URL=$(vercel deploy --prod)
curl -s "$PROD_URL/api/games"
CREATE_PAYLOAD=$(curl -s -X POST "$PROD_URL/api/games")
echo "$CREATE_PAYLOAD" | python3 -m json.tool
```

部署後檢查 Vercel logs，確認沒有 Python import error、Mongo connection error、schema load error：

```bash
vercel logs "$PROD_URL" --level error
```

---

## Production Ready Definition

只有以下全部通過，先可以叫 production ready：

1. `battle_app/` isolated copy 可以 `import api.games`。
2. isolated copy 可以 `build_simulator(players="mcts", interpreter="schema")`。
3. 所有 schema YAML 是 real files，不是 symlink。
4. `CardDatabase` 載入 card count > 0。
5. `CardEffectSchemaLoader` 載入 schema card count > 0。
6. `vercel build` 與 `vercel build --prod` 成功。
7. Preview `POST /api/games` 成功建立 game。
8. Production `POST /api/games` 成功建立 game。
9. Vercel production env 是 `mcts + schema`，不是 `hermes`。

---

## 改動總結

| 改動類型 | 檔案數 | 行數 | 內容 |
|----------|--------|------|------|
| 檔案搬移 (cp) | 60+ files | n/a | Phase 1 |
| `config.py` path fix | 1 file | ~15 lines | REPO_ROOT + schema paths |
| `server.py` sys.path | 1 file | ~5 lines | GCGV2_ROOT + dual sys.path |
| `api/games.py` sys.path | 1 file | ~3 lines | GCGV2_ROOT + dual sys.path |
| `scenarios.py` sys.path | 1 file | ~1 line | GCGV2_ROOT |
| `env.py` sys.path | 1 file | ~1 line | GCGV2_ROOT |
| 清理 / deploy ignore | 2 files | ~15 lines | rm generated files + `.vercelignore` + `excludeFiles` |

**合共 ~6 檔案，~25 行 code change。全部係 path/sys.path 調整。冇 business logic 改動。**

---

## 不變項目

- ❌ 所有 `from gcg.xxx import` / `from reviewboard.xxx import` statement
- ❌ 所有 business logic（runtime、state_store、effect_engine、rules_index、action_enumerator、MctsPlayer、ISMCTS 等）
- ❌ `battle_session.py`、`bootstrap.py`、`command_labels.py` 邏輯
- ❌ `battle_app/` frontend（battleV3.js、battleV3.css、index.html）
- ❌ `card/data/*.json`、`gcgdecks.json`、`manifests/*.yaml`、`schemas/*.yaml` 內容
- ❌ 任何 effect engine / state store / action enumerator / rules index 合約

---

## 補充事項（Supplemental Notes）

### S1：Duplicated Dependencies `.gitignore` 策略

Phase 1 將 `gcg/`、`reviewboard/`、`card/`、`manifests/`、`schemas/`、`knowledge/` 複製入 `battle_app/`。git 會見到 ~65 個新 tracked files。需決定：

| 策略 | 做法 | 優點 | 缺點 |
|------|------|------|------|
| **Track in git** | 直接 commit，`.gitignore` 唔排除 | Deploy 即 repo 一模一樣 | 源頭改動後需手動 sync |
| **Ignore + rebuild** | `.gitignore` 加 `gcg/`、`reviewboard/` 等；CI/deploy script 跑 Phase 1 `cp` | 單一 source of truth | Deploy pipeline 需 rebuild step |

**建議**：短期用 Track in git（快速驗證 standalone deploy）；長期用 Ignore + rebuild（避免 code duplication drift）。Implement 時先 track，後續再決定遷移。

### S2：Vercel Python Runtime Version

當前 code 使用 Python 3.9+ 特性。Vercel Python runtime version 應用 `pyproject.toml` 指定，避免 runtime version ambiguity。新增 `battle_app/pyproject.toml`：

```toml
[project]
requires-python = ">=3.11"
```

不要在 `vercel.json` 加未驗證的 `pythonVersion` 欄位；Python version 以 `pyproject.toml` 為準。Non-blocking，但建議同 standalone deploy 一齊做。

### S3：Scenarios Path Safety

`scenarios.py` 喺 module load 時計算 `DEFAULT_SCENARIO_ROOT`，指向 `GCGV2_ROOT / "scenarios" / "manual"`。為保持 local scenario tests / QA mode，Phase 1 copies `scenarios/manual` into `battle_app/scenarios/manual`。Vercel production 仍應確認 `GCG_ENABLE_SCENARIO_MODE` 不存在，避免開放測試場景 API。

### S4：`knowledge/gcg-ai-player.md` on Vercel（dead weight）

Phase 1 copies `knowledge/gcg-ai-player.md` as optional。MCTS+schema production 唔需要佢。如果追求最小部署包，喺 `.vercelignore` 加 `knowledge/`。Non-blocking（~8KB）。

### S5：Phase 6 Smoke —`api/games.py` vs `server.py` Route Difference

- `server.py`（local）直接處理 `/api/games/{id}/state` 同 `/api/games/{id}/command`
- `api/games.py`（Vercel）用 `rewrites` rule 將 `/api/games/:path*` rewrite 做 `/api/games?path=:path*`

Phase 6.2a 已測試呢個 rewrite rule。如果 rewrite 唔 work，`GET /api/games/<id>/state` 會 404 而唔係 200。

### S6：Dependency Sync Risk

搬移後 `battle_app/gcg/` 變成獨立 copy。如果 `gcgV2/gcg/`（原位置）有 update（例如 fix MCTS bug、加新 effect engine primitive），`battle_app/gcg/` 唔會自動同步。短期風險低（code freeze 後實作），長期需要：

```bash
# Sync script（未來使用）
diff -rq gcgV2/gcg battle_app/gcg  # check drift
rsync -av --delete gcgV2/gcg/ battle_app/gcg/  # sync
```

可另開 ticket 處理，唔影響第一次 deploy。

---

## Implementation Record（2026-06-23）

Branch: `codex/battle-app-standalone-vercel`

Implemented:

- Copied runtime dependencies into `battle_app/`: `gcg/`, `reviewboard/humanVsAI/`, `card/`, `manifests/`, `schemas/`, `knowledge/`, and `scenarios/manual/`.
- Replaced schema symlinks with real YAML copies.
- Updated standalone path roots in `battle_app/gcg/config.py`, `battle_app/server.py`, `battle_app/api/games.py`, `battle_app/scenarios.py`, and `battle_app/env.py`.
- Added a lightweight package alias in `battle_app/server.py` and `battle_app/api/games.py` so `battle_app.*` imports work when Vercel deploys the contents of `battle_app/` as the project root; the alias sets `__package__` and `__path__`.
- Added Vercel deployment hygiene: `battle_app/.vercelignore`, `battle_app/pyproject.toml`, and `vercel.json` `excludeFiles`.
- Kept Hermes local-only; production target remains MCTS+schema through Vercel env vars.

Verified locally:

```text
python3 -m py_compile server.py api/games.py runtime_document.py scenarios.py env.py storage.py gcg/config.py gcg/cards.py gcg/sim/bootstrap.py gcg/effects/schema_loader.py gcg/effects/dictionary.py gcg/ai/mcts/__init__.py reviewboard/humanVsAI/battle_session.py reviewboard/humanVsAI/command_labels.py
Path checks: GCGV2_ROOT == battle_app; schema YAML files exist and are not symlinks; card/deck/manifest paths exist.
MCTS+schema import/instantiation: api.games import ok; CardDatabase=545; Schema cards=74; runner built.
Isolated copy: api.games import ok; build_simulator(players="mcts", interpreter="schema") passed.
Vercel-root contents copy: api.games import ok; battle_app.runtime_document import ok; build_simulator(players="mcts", interpreter="schema") passed.
Local HTTP smoke: GET /api/games and POST /api/games returned ok with a game_id.
python3 -m unittest battle_app.tests.test_local_multiroom battle_app.tests.test_runtime_document battle_app.tests.test_api_games battle_app.tests.test_mongo_storage battle_app.tests.test_env
```

Deferred:

- `vercel build`, preview deploy, and production smoke require Vercel CLI plus linked Vercel project settings and production `MONGODB_URI`.
