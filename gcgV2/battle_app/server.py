#!/usr/bin/env python3
"""Local multi-game battle app server.

This server is intentionally separate from reviewboard/server.py. It keeps the
same game rules/runtime path, but replaces the battleV3 singleton with a small
in-memory registry keyed by the runtime game_id.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import types
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


BATTLE_APP_ROOT = Path(__file__).resolve().parent
GCGV2_ROOT = BATTLE_APP_ROOT
PUBLIC_ROOT = BATTLE_APP_ROOT / "public"

for path in (BATTLE_APP_ROOT, BATTLE_APP_ROOT.parent):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
if "battle_app" not in sys.modules:
    package = types.ModuleType("battle_app")
    package.__package__ = "battle_app"
    package.__path__ = [str(BATTLE_APP_ROOT)]
    sys.modules["battle_app"] = package

from battle_app.env import load_battle_app_env  # noqa: E402
from reviewboard.humanVsAI.battle_session import HumanVsAiBattleSession, ManualBattleSession  # noqa: E402
from battle_app.scenarios import ScenarioError, load_scenario, start_session_from_scenario  # noqa: E402

load_battle_app_env()


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GameRecord:
    session: HumanVsAiBattleSession | ManualBattleSession
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()


class BattleGameRegistry:
    def __init__(self):
        self._lock = threading.RLock()
        self._games: dict[str, GameRecord] = {}

    def create(self, mode: str | None = None) -> dict:
        session = _build_session(mode)
        response = session.start()
        game_id = response.get("game_id")
        if not game_id:
            raise RuntimeError("runtime did not return game_id")
        with self._lock:
            self._games[game_id] = GameRecord(session=session)
        return response

    def create_from_scenario(self, scenario_id: str, mode: str | None = None) -> dict:
        scenario = load_scenario(scenario_id)
        session = _build_session(mode)
        game_id, response = start_session_from_scenario(session, scenario)
        with self._lock:
            self._games[game_id] = GameRecord(session=session)
        return response

    def get(self, game_id: str) -> GameRecord | None:
        with self._lock:
            return self._games.get(game_id)

    def list_games(self) -> list[dict]:
        with self._lock:
            rows = []
            for game_id, record in sorted(self._games.items()):
                session = record.session
                rows.append(
                    {
                        "game_id": game_id,
                        "status": getattr(session, "_status", "unknown"),
                        "message": getattr(session, "_last_message", ""),
                        "created_at": record.created_at,
                        "updated_at": record.updated_at,
                    }
                )
            return rows

    def delete(self, game_id: str) -> bool:
        with self._lock:
            record = self._games.pop(game_id, None)
        if record is None:
            return False
        # reset() increments the session generation, causing any old AI worker
        # to drop its result instead of mutating a deleted game.
        record.session.reset()
        return True

    def touch(self, game_id: str) -> None:
        with self._lock:
            record = self._games.get(game_id)
            if record is not None:
                record.touch()


class BattleAppHandler(SimpleHTTPRequestHandler):
    registry = BattleGameRegistry()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def do_GET(self):  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path == "/api/games":
            self._send_json({"ok": True, "games": self.registry.list_games()})
            return

        route = self._parse_game_route(parsed.path)
        if route is not None:
            game_id, action = route
            if action == "state":
                self._with_game(game_id, lambda record: record.session.state())
                return
            if action == "card":
                query = parse_qs(parsed.query)
                card_id = (query.get("card_id") or [""])[0]
                self._with_game(
                    game_id,
                    lambda record: record.session.card_detail(card_id) or {},
                )
                return

        if parsed.path in {"", "/"}:
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        if parsed.path == "/api/games/scenario":
            if not _scenario_mode_enabled():
                self._send_json({"ok": False, "error": "測試場景模式未啟用。"}, status=404)
                return
            try:
                payload = self._read_json_body()
                mode = payload.get("mode")
                if mode == "manual" and not _manual_mode_enabled():
                    self._send_json({"ok": False, "error": "手動對戰模式未啟用。"}, status=404)
                    return
                self._send_json(self.registry.create_from_scenario(payload.get("scenario_id"), mode=mode))
            except ScenarioError as exc:
                self._send_json({"ok": False, "error": str(exc)}, status=400)
            except Exception as exc:  # noqa: BLE001 - API boundary
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        if parsed.path == "/api/games":
            try:
                payload = self._read_json_body()
                mode = payload.get("mode")
                if mode == "manual" and not _manual_mode_enabled():
                    self._send_json({"ok": False, "error": "手動對戰模式未啟用。"}, status=404)
                    return
                self._send_json(self.registry.create(mode=mode))
            except Exception as exc:  # noqa: BLE001 - API boundary
                self._send_json({"ok": False, "error": str(exc)}, status=500)
            return

        route = self._parse_game_route(parsed.path)
        if route is None:
            self._send_json({"ok": False, "error": "找不到 API。"}, status=404)
            return

        game_id, action = route
        if action == "command":
            payload = self._read_json_body()

            def submit(record: GameRecord):
                result = record.session.submit_command(payload.get("command"))
                record.touch()
                return result

            self._with_game(game_id, submit)
            return

        self._send_json({"ok": False, "error": "找不到 API。"}, status=404)

    def do_DELETE(self):  # noqa: N802 - http.server API
        parsed = urlparse(self.path)
        prefix = "/api/games/"
        if parsed.path.startswith(prefix) and parsed.path.count("/") == 3:
            game_id = parsed.path[len(prefix):]
            if self.registry.delete(game_id):
                self._send_json({"ok": True, "game_id": game_id, "deleted": True})
            else:
                self._send_not_found()
            return
        self._send_json({"ok": False, "error": "找不到 API。"}, status=404)

    def _with_game(self, game_id: str, callback):
        record = self.registry.get(game_id)
        if record is None:
            self._send_not_found()
            return
        try:
            self._send_json(callback(record))
        except Exception as exc:  # noqa: BLE001 - API boundary
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def _parse_game_route(self, path: str) -> tuple[str, str] | None:
        prefix = "/api/games/"
        if not path.startswith(prefix):
            return None
        rest = path[len(prefix):].strip("/")
        parts = rest.split("/")
        if len(parts) != 2:
            return None
        game_id, action = parts
        if not game_id or action not in {"state", "command", "card"}:
            return None
        return game_id, action

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _send_not_found(self):
        self._send_json({"ok": False, "error": "找不到對局。"}, status=404)

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):  # noqa: A002 - inherited API name
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))


def _scenario_mode_enabled() -> bool:
    return os.getenv("GCG_ENABLE_SCENARIO_MODE") == "1"


def _manual_mode_enabled() -> bool:
    return os.getenv("GCG_ENABLE_MANUAL_MODE") == "1"


def _build_session(mode: str | None):
    session_cls = ManualBattleSession if mode == "manual" else HumanVsAiBattleSession
    return session_cls(
        auto_pass_ai_no_move=True,
        reveal_card_names=True,
    )


def main():
    parser = argparse.ArgumentParser(description="Serve the GCG battle app.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5190)
    args = parser.parse_args()

    handler = partial(BattleAppHandler, directory=str(PUBLIC_ROOT))
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Battle app: http://{args.host}:{args.port}")
    print(f"Static root: {PUBLIC_ROOT}")
    server.serve_forever()


if __name__ == "__main__":
    main()
