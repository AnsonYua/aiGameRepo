"""File writers for game outputs（gameState.yaml / gamePlay.yaml / ai_trace.yaml）。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import yaml


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data):
        return True


def _serialize_yaml(payload):
    return yaml.dump(payload, allow_unicode=True, sort_keys=False, Dumper=_NoAliasSafeDumper)


def _ensure_game_dir(output_root, game_id):
    game_dir = Path(output_root) / game_id
    game_dir.mkdir(parents=True, exist_ok=True)
    return game_dir


class SnapshotWriter:
    def __init__(self, output_root):
        self.output_root = Path(output_root)

    def write_game_state(self, game_id, snapshot):
        path = _ensure_game_dir(self.output_root, game_id) / "gameState.yaml"
        path.write_text(_serialize_yaml(snapshot), encoding="utf-8")


class GameplayYamlWriter:
    """gamePlay.yaml writer。

    事件先累積在記憶體，每 flush_interval 筆寫檔一次，finalize 時必定寫檔，
    避免逐事件全檔重寫造成 O(n²) 序列化成本。
    """

    def __init__(self, output_root, flush_interval=25):
        self.output_root = Path(output_root)
        self.flush_interval = flush_interval
        self._documents = {}
        self._dirty_counts = {}

    def create_gameplay_log(self, game_id, schema_version):
        self._documents[game_id] = {
            "schema_version": schema_version,
            "game_id": game_id,
            "summary": {
                "status": "in_progress",
                "winner": None,
                "win_reason": None,
                "turn": 0,
                "phase": "pre-game",
                "total_events": 0,
            },
            "events": [],
        }
        self._dirty_counts[game_id] = 0
        self._write(game_id)

    def append_event(self, game_id, event):
        payload = self._document(game_id)
        payload["events"].append(event)
        payload["summary"]["turn"] = event.get("turn")
        payload["summary"]["phase"] = event.get("phase")
        payload["summary"]["total_events"] = len(payload["events"])
        self._dirty_counts[game_id] = self._dirty_counts.get(game_id, 0) + 1
        if self._dirty_counts[game_id] >= self.flush_interval:
            self._write(game_id)
            self._dirty_counts[game_id] = 0

    def finalize(self, game_id, status, winner=None, win_reason=None):
        payload = self._document(game_id)
        payload["summary"]["status"] = status
        payload["summary"]["winner"] = winner
        payload["summary"]["win_reason"] = win_reason
        self._write(game_id)
        self._dirty_counts[game_id] = 0

    def get_gameplay_path(self, game_id):
        return str(self.output_root / game_id / "gamePlay.yaml")

    def _document(self, game_id):
        if game_id not in self._documents:
            path = Path(self.get_gameplay_path(game_id))
            self._documents[game_id] = yaml.safe_load(path.read_text(encoding="utf-8"))
        return self._documents[game_id]

    def _write(self, game_id):
        path = _ensure_game_dir(self.output_root, game_id) / "gamePlay.yaml"
        path.write_text(_serialize_yaml(self._documents[game_id]), encoding="utf-8")


class AiTraceWriter:
    def __init__(self, output_root):
        self.output_root = Path(output_root)
        self._documents = {}

    def append_trace(
        self,
        game_id,
        player_id,
        request_type,
        system_prompt,
        prompt,
        raw_reply,
        normalized_reply,
    ):
        payload = self._documents.setdefault(game_id, {"game_id": game_id, "traces": []})
        payload["traces"].append({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "game_id": game_id,
            "player_id": player_id,
            "request_type": request_type,
            "system_prompt": system_prompt,
            "prompt": prompt if isinstance(prompt, str) else json.loads(json.dumps(prompt)),
            "raw_reply": raw_reply,
            "normalized_reply": normalized_reply,
        })
        path = _ensure_game_dir(self.output_root, game_id) / "ai_trace.yaml"
        path.write_text(_serialize_yaml(payload), encoding="utf-8")

    def get_trace_path(self, game_id):
        return str(self.output_root / game_id / "ai_trace.yaml")
