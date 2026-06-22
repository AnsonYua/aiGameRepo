"""MongoDB persistence boundary for the battle app.

The local Phase 1 server does not depend on this module. Phase 2 will use it
to make the same /api/games contract work on serverless runtimes where process
memory and local files are not durable.
"""

from __future__ import annotations

import copy
import os
from datetime import datetime, timedelta, timezone
from uuid import uuid4


DEFAULT_DB_NAME = "gcg_battle_app"
GAMES_COLLECTION = "games"
GAME_TTL = timedelta(hours=2)
AI_LOCK_TTL = timedelta(seconds=90)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def expiry_for(updated_at: datetime | None = None) -> datetime:
    return (updated_at or utc_now()) + GAME_TTL


def json_safe_copy(value):
    """Return a JSON-shaped deep copy for state/log payloads."""
    return copy.deepcopy(value)


def build_game_document(
    *,
    game_id: str,
    runtime_state: dict,
    gameplay_log: dict,
    status: str,
    message: str = "",
    error: str | None = None,
    winner: str | None = None,
    game_over: bool = False,
    legal_commands: list[str] | None = None,
    now: datetime | None = None,
) -> dict:
    timestamp = now or utc_now()
    return {
        "game_id": game_id,
        "runtime_state": json_safe_copy(runtime_state),
        "gameplay_log": json_safe_copy(gameplay_log),
        "status": status,
        "message": message,
        "error": error,
        "winner": winner,
        "game_over": bool(game_over),
        "legal_commands": list(legal_commands or []),
        "version": 1,
        "ai_lock_until": None,
        "ai_lock_owner": None,
        "created_at": timestamp,
        "updated_at": timestamp,
        "expires_at": expiry_for(timestamp),
    }


class MissingMongoUri(RuntimeError):
    pass


class VersionConflict(RuntimeError):
    pass


class MongoGameStore:
    def __init__(
        self,
        *,
        uri: str | None = None,
        client=None,
        db_name: str = DEFAULT_DB_NAME,
        collection_name: str = GAMES_COLLECTION,
    ):
        if client is None:
            uri = uri or os.getenv("MONGODB_URI")
            if not uri:
                raise MissingMongoUri("MONGODB_URI is required for MongoGameStore")
            from pymongo import MongoClient, ReturnDocument  # imported lazily for local Phase 1

            client = MongoClient(uri)
            self._return_document_after = ReturnDocument.AFTER
        else:
            self._return_document_after = True
        self.client = client
        self.db = client[db_name]
        self.games = self.db[collection_name]

    def ensure_indexes(self) -> None:
        self.games.create_index("game_id", unique=True)
        self.games.create_index("expires_at", expireAfterSeconds=0)

    def insert_game(self, document: dict) -> None:
        self.games.insert_one(copy.deepcopy(document))

    def get_game(self, game_id: str) -> dict | None:
        document = self.games.find_one({"game_id": game_id})
        return copy.deepcopy(document) if document else None

    def list_games(self) -> list[dict]:
        projection = {
            "_id": False,
            "game_id": True,
            "status": True,
            "message": True,
            "winner": True,
            "game_over": True,
            "created_at": True,
            "updated_at": True,
            "expires_at": True,
        }
        return list(self.games.find({}, projection).sort("updated_at", -1))

    def delete_game(self, game_id: str) -> bool:
        result = self.games.delete_one({"game_id": game_id})
        return result.deleted_count > 0

    def save_game(self, game_id: str, *, expected_version: int, updates: dict) -> dict:
        timestamp = utc_now()
        payload = copy.deepcopy(updates)
        payload["updated_at"] = timestamp
        payload["expires_at"] = expiry_for(timestamp)
        result = self.games.find_one_and_update(
            {"game_id": game_id, "version": expected_version},
            {"$set": payload, "$inc": {"version": 1}},
            return_document=self._return_document_after,
        )
        if result is None:
            raise VersionConflict(f"game version changed before save: {game_id}")
        return copy.deepcopy(result)

    def acquire_ai_lock(self, game_id: str, *, owner: str | None = None, now: datetime | None = None) -> dict | None:
        timestamp = now or utc_now()
        owner = owner or f"worker-{uuid4().hex}"
        lock_until = timestamp + AI_LOCK_TTL
        return self.games.find_one_and_update(
            {
                "game_id": game_id,
                "status": "waiting_ai",
                "$or": [
                    {"ai_lock_until": None},
                    {"ai_lock_until": {"$lte": timestamp}},
                ],
            },
            {
                "$set": {
                    "ai_lock_until": lock_until,
                    "ai_lock_owner": owner,
                }
            },
            return_document=self._return_document_after,
        )

    def release_ai_lock(self, game_id: str, *, owner: str | None = None) -> None:
        query = {"game_id": game_id}
        if owner is not None:
            query["ai_lock_owner"] = owner
        self.games.update_one(
            query,
            {"$set": {"ai_lock_until": None, "ai_lock_owner": None}},
        )
