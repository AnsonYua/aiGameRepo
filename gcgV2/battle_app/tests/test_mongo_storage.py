from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import unittest
from copy import deepcopy
from datetime import timedelta
from pathlib import Path


BATTLE_APP_ROOT = Path(__file__).resolve().parents[1]
GCGV2_ROOT = BATTLE_APP_ROOT.parent
if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))
if str(BATTLE_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(BATTLE_APP_ROOT))

from battle_app.storage import (  # noqa: E402
    GAME_TTL,
    MongoGameStore,
    build_game_document,
    expiry_for,
    utc_now,
)
from gcg.sim.bootstrap import build_simulator  # noqa: E402


class FakeDeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class FakeCursor(list):
    def sort(self, key, direction):
        reverse = direction < 0
        return FakeCursor(sorted(self, key=lambda item: item.get(key), reverse=reverse))


class FakeCollection:
    def __init__(self):
        self.indexes = []
        self.documents = {}
        self.lock = threading.Lock()

    def create_index(self, *args, **kwargs):
        self.indexes.append((args, kwargs))
        return "idx"

    def insert_one(self, document):
        with self.lock:
            self.documents[document["game_id"]] = deepcopy(document)

    def find_one(self, query):
        with self.lock:
            document = self.documents.get(query.get("game_id"))
            return deepcopy(document) if document else None

    def find(self, query, projection):
        rows = []
        for document in self.documents.values():
            row = {}
            for key, enabled in projection.items():
                if enabled and key in document:
                    row[key] = document[key]
            rows.append(row)
        return FakeCursor(rows)

    def delete_one(self, query):
        with self.lock:
            deleted = self.documents.pop(query.get("game_id"), None) is not None
            return FakeDeleteResult(1 if deleted else 0)

    def update_one(self, query, update):
        with self.lock:
            document = self.documents.get(query.get("game_id"))
            if not document:
                return
            for key, value in update.get("$set", {}).items():
                document[key] = value

    def find_one_and_update(self, query, update, return_document=True):
        with self.lock:
            document = self.documents.get(query.get("game_id"))
            if not document:
                return None
            if "version" in query and document.get("version") != query["version"]:
                return None
            if query.get("status") and document.get("status") != query["status"]:
                return None
            alternatives = query.get("$or") or []
            if alternatives:
                matched = False
                for alternative in alternatives:
                    if "ai_lock_until" in alternative and document.get("ai_lock_until") is None:
                        matched = True
                    else:
                        lock_query = alternative.get("ai_lock_until")
                        if isinstance(lock_query, dict) and lock_query.get("$lte") is not None:
                            limit = lock_query["$lte"]
                            value = document.get("ai_lock_until")
                            matched = value is not None and value <= limit
                    if matched:
                        break
                if not matched:
                    return None
            for key, value in update.get("$set", {}).items():
                document[key] = value
            for key, value in update.get("$inc", {}).items():
                document[key] = document.get(key, 0) + value
            return deepcopy(document)


class FakeDb:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


class FakeClient:
    def __init__(self):
        self.dbs = {}

    def __getitem__(self, name):
        self.dbs.setdefault(name, FakeDb())
        return self.dbs[name]


class MongoStorageTest(unittest.TestCase):
    def test_runtime_state_is_json_round_trippable(self):
        with tempfile.TemporaryDirectory(prefix="gcg_storage_state_") as tmpdir:
            old_output_root = os.environ.get("GCG_V2_OUTPUT_ROOT")
            try:
                os.environ["GCG_V2_OUTPUT_ROOT"] = tmpdir
                runner = build_simulator(players="scripted", interpreter="reference")
                game_id = runner.start_game(decision_player="P1")
                raw_state = runner.state.get_state()
                round_tripped = json.loads(json.dumps(raw_state, ensure_ascii=False))
            finally:
                if old_output_root is None:
                    os.environ.pop("GCG_V2_OUTPUT_ROOT", None)
                else:
                    os.environ["GCG_V2_OUTPUT_ROOT"] = old_output_root

        self.assertEqual(round_tripped["game_id"], game_id)
        self.assertEqual(round_tripped, raw_state)

    def test_build_game_document_uses_structured_log_and_two_hour_ttl(self):
        timestamp = utc_now()
        document = build_game_document(
            game_id="game_test",
            runtime_state={"game_id": "game_test", "players": {"P1": {}}},
            gameplay_log={"schema_version": "2.0", "events": [{"seq": 1}]},
            status="waiting_human",
            message="等待操作。",
            now=timestamp,
        )

        self.assertEqual(document["game_id"], "game_test")
        self.assertEqual(document["gameplay_log"]["events"][0]["seq"], 1)
        self.assertEqual(document["version"], 1)
        self.assertIsNone(document["ai_lock_until"])
        self.assertEqual(document["expires_at"], timestamp + GAME_TTL)
        self.assertEqual(expiry_for(timestamp) - timestamp, timedelta(hours=2))

    def test_indexes_are_idempotent_and_expected(self):
        store = MongoGameStore(client=FakeClient())
        store.ensure_indexes()
        store.ensure_indexes()

        self.assertIn((("game_id",), {"unique": True}), store.games.indexes)
        self.assertIn((("expires_at",), {"expireAfterSeconds": 0}), store.games.indexes)
        self.assertEqual(store.games.indexes.count((("game_id",), {"unique": True})), 2)

    def test_save_game_uses_optimistic_version_and_extends_ttl(self):
        store = MongoGameStore(client=FakeClient())
        document = build_game_document(
            game_id="game_test",
            runtime_state={"game_id": "game_test"},
            gameplay_log={"events": []},
            status="waiting_human",
        )
        store.insert_game(document)

        updated = store.save_game(
            "game_test",
            expected_version=1,
            updates={"status": "waiting_ai", "runtime_state": {"game_id": "game_test", "turn": 1}},
        )

        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["status"], "waiting_ai")
        self.assertEqual(updated["runtime_state"]["turn"], 1)
        self.assertGreater(updated["expires_at"], document["expires_at"])
        with self.assertRaises(Exception):
            store.save_game("game_test", expected_version=1, updates={"status": "stale"})


if __name__ == "__main__":
    unittest.main()
