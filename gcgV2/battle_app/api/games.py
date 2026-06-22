from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qs, urlparse


API_DIR = Path(__file__).resolve().parent
BATTLE_APP_ROOT = API_DIR.parent
GCGV2_ROOT = BATTLE_APP_ROOT.parent
for path in (GCGV2_ROOT, BATTLE_APP_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from battle_app.runtime_document import MongoBattleService, card_detail  # noqa: E402
from battle_app.storage import MissingMongoUri, MongoGameStore  # noqa: E402


_STORE = None


def get_store():
    global _STORE
    if _STORE is None:
        _STORE = MongoGameStore()
        _STORE.ensure_indexes()
    return _STORE


def get_service():
    return MongoBattleService(get_store())


class handler(BaseHTTPRequestHandler):  # noqa: N801 - Vercel Python runtime convention
    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            self._handle_get()
        except MissingMongoUri as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
        except Exception as exc:  # noqa: BLE001 - serverless API boundary
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_POST(self):  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            self._handle_post()
        except MissingMongoUri as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
        except Exception as exc:  # noqa: BLE001 - serverless API boundary
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def do_DELETE(self):  # noqa: N802 - BaseHTTPRequestHandler API
        try:
            self._handle_delete()
        except MissingMongoUri as exc:
            self._send_json({"ok": False, "error": str(exc)}, status=500)
        except Exception as exc:  # noqa: BLE001 - serverless API boundary
            self._send_json({"ok": False, "error": str(exc)}, status=500)

    def _handle_get(self):
        parsed = self._parsed_url()
        parts = self._api_parts(parsed)
        if not parts:
            store = get_store()
            self._send_json({"ok": True, "games": store.list_games()})
            return

        game_id, action = self._game_action(parts)
        if action == "card":
            query = parse_qs(parsed.query)
            card_id = (query.get("card_id") or [""])[0]
            self._send_json(card_detail(card_id) or {})
            return
        if action == "state":
            payload = get_service().get_state(game_id)
            self._send_game_payload(payload)
            return
        self._send_json({"ok": False, "error": "找不到 API。"}, status=404)

    def _handle_post(self):
        parts = self._api_parts(self._parsed_url())
        service = get_service()
        if not parts:
            self._send_json(service.create_game())
            return

        game_id, action = self._game_action(parts)
        if action == "command":
            payload = self._read_json_body()
            result = service.submit_command(game_id, payload.get("command"))
            self._send_game_payload(result)
            return
        self._send_json({"ok": False, "error": "找不到 API。"}, status=404)

    def _handle_delete(self):
        parts = self._api_parts(self._parsed_url())
        if len(parts) != 1:
            self._send_json({"ok": False, "error": "找不到 API。"}, status=404)
            return
        game_id = parts[0]
        deleted = get_store().delete_game(game_id)
        if not deleted:
            self._send_not_found()
            return
        self._send_json({"ok": True, "game_id": game_id, "deleted": True})

    def _parsed_url(self):
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        rewritten_path = (query.get("path") or [""])[0].strip("/")
        if parsed.path == "/api/games" and rewritten_path:
            return parsed._replace(path=f"/api/games/{rewritten_path}")
        return parsed

    def _api_parts(self, parsed):
        if parsed.path == "/api/games":
            return []
        prefix = "/api/games/"
        if not parsed.path.startswith(prefix):
            return []
        return [part for part in parsed.path[len(prefix):].strip("/").split("/") if part]

    def _game_action(self, parts):
        if len(parts) != 2:
            return None, None
        game_id, action = parts
        return game_id, action

    def _send_game_payload(self, payload):
        if payload is None:
            self._send_not_found()
            return
        self._send_json(payload)

    def _send_not_found(self):
        self._send_json({"ok": False, "error": "找不到對局。"}, status=404)

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

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
