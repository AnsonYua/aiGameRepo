#!/usr/bin/env python3
import argparse
import copy
import json
import os
import re
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import yaml

from humanVsAI.battle_session import HumanVsAiBattleSession


DEFAULT_REPLAY = Path(
    "/Users/hello/Desktop/cardAI/gcgV2/out/game_20260615_012734_690878/gamePlay.yaml"
)


class ReviewBoardHandler(SimpleHTTPRequestHandler):
    replay_path = DEFAULT_REPLAY
    battle_session = None
    battle_v2_session = None
    battle_v3_session = None

    def end_headers(self):
        self.send_header("Cache-Control", "no-store, max-age=0")
        super().end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/replay":
            self._send_replay()
            return
        if parsed.path == "/api/battle/state":
            self._send_json(self.battle_session.state())
            return
        if parsed.path == "/api/battleV2/state":
            self._send_json(self.battle_v2_session.state())
            return
        if parsed.path == "/api/battleV3/state":
            self._send_json(self.battle_v3_session.state())
            return
        if parsed.path == "/api/battleV3/card":
            query = parse_qs(parsed.query)
            card_id = (query.get("card_id") or [""])[0]
            detail = self.battle_v3_session.card_detail(card_id)
            self._send_json(detail if detail else {})
            return
        if parsed.path == "/mobile/battle":
            self.path = "/mobile/battle/index.html"
            return super().do_GET()
        if parsed.path == "/mobile/battleV2":
            self.path = "/mobile/battleV2/index.html"
            return super().do_GET()
        if parsed.path == "/mobile/battleV3":
            self.path = "/mobile/battleV3/index.html"
            return super().do_GET()
        if parsed.path in ("/", "/mobile"):
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/battle/start":
            self._send_json(self.battle_session.start())
            return
        if parsed.path == "/api/battle/reset":
            self._send_json(self.battle_session.reset())
            return
        if parsed.path == "/api/battle/command":
            payload = self._read_json_body()
            self._send_json(self.battle_session.submit_command(payload.get("command")))
            return
        if parsed.path == "/api/battleV2/start":
            self._send_json(self.battle_v2_session.start())
            return
        if parsed.path == "/api/battleV2/reset":
            self._send_json(self.battle_v2_session.reset())
            return
        if parsed.path == "/api/battleV2/command":
            payload = self._read_json_body()
            self._send_json(self.battle_v2_session.submit_command(payload.get("command")))
            return
        if parsed.path == "/api/battleV3/start":
            self._send_json(self.battle_v3_session.start())
            return
        if parsed.path == "/api/battleV3/reset":
            self._send_json(self.battle_v3_session.reset())
            return
        if parsed.path == "/api/battleV3/command":
            payload = self._read_json_body()
            self._send_json(self.battle_v3_session.submit_command(payload.get("command")))
            return
        self.send_error(404, "Not found")

    def _send_replay(self):
        try:
            with self.replay_path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            payload = enrich_review_hands(payload, self.replay_path)
            self._send_json(payload)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=500)

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
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def card_ids(value):
    if not isinstance(value, list):
        return []
    ids = []
    for item in value:
        if isinstance(item, str):
            ids.append(item)
        elif isinstance(item, dict):
            card_id = item.get("card_id") or item.get("id")
            if card_id:
                ids.append(card_id)
    return ids


def remove_one(hand, card_id):
    try:
        hand.remove(card_id)
    except ValueError:
        # If the exact drawn card is unknown, keep the known cards and let the
        # count mismatch render as face-down review cards.
        pass


def event_played_card(event):
    message = event.get("message") or ""
    match = re.search(r"(st\d{2}/[A-Z0-9-]+)", message)
    if not match:
        return None
    if any(token in message for token in ("部署", "使用", "play", "deploy")):
        return match.group(1)
    return None


def event_player(event):
    actor = str(event.get("actor") or "").lower()
    if actor in ("p1", "p2"):
        return actor
    message = event.get("message") or ""
    match = re.match(r"\s*(P[12])\b", message)
    if match:
        return match.group(1).lower()
    return actor


def trace_hand_snapshots(trace_path):
    if not trace_path.exists():
        return [], {}
    with trace_path.open("r", encoding="utf-8") as handle:
        trace = yaml.safe_load(handle) or {}

    snapshots = []
    opening_hands = {}
    for item in trace.get("traces", []):
        prompt = item.get("prompt") or {}
        if not isinstance(prompt, dict):
            continue
        player_id = item.get("player_id") or prompt.get("player_id")
        ts = parse_ts(item.get("ts"))

        opening = card_ids(prompt.get("opening_hand"))
        if player_id in ("P1", "P2") and opening:
            opening_hands[player_id.lower()] = opening

        viewer_state = prompt.get("viewer_state") or {}
        players = viewer_state.get("players") or {}
        for pid, player in players.items():
            hand = card_ids(player.get("hand"))
            if not hand:
                continue
            snapshots.append(
                {
                    "ts": ts,
                    "player": str(pid).lower(),
                    "turn": viewer_state.get("turn"),
                    "phase": viewer_state.get("phase"),
                    "hand": hand,
                }
            )

    snapshots.sort(key=lambda item: item["ts"] or datetime.min)
    return snapshots, opening_hands


def attach_review_hand(features, player_key, known_hand):
    player = features.get(player_key)
    if not isinstance(player, dict):
        return
    if card_ids(player.get("hand")):
        player.pop("review_hand", None)
        player.pop("review_hand_unknown_count", None)
        return
    count = int(player.get("hand_count") or 0)
    visible = list(known_hand[:count])
    player["review_hand"] = visible
    player["review_hand_unknown_count"] = max(0, count - len(visible))


def has_direct_hands(payload):
    events = payload.get("events")
    if not isinstance(events, list):
        return False
    for event in events:
        features = event.get("features") or {}
        for player_key in ("p1", "p2"):
            player = features.get(player_key)
            if isinstance(player, dict) and card_ids(player.get("hand")):
                return True
    return False


def enrich_review_hands(payload, replay_path):
    events = payload.get("events")
    if not isinstance(events, list):
        return payload
    if has_direct_hands(payload):
        return payload

    trace_path = replay_path.with_name("ai_trace.yaml")
    snapshots, opening_hands = trace_hand_snapshots(trace_path)
    if not snapshots and not opening_hands:
        return payload

    enriched = copy.deepcopy(payload)
    known_hands = {"p1": [], "p2": []}
    snapshot_index = 0

    for event in enriched.get("events", []):
        event_ts = parse_ts(event.get("ts"))
        features = event.get("features") or {}

        if event.get("seq", 0) >= 2:
            for player_key, hand in opening_hands.items():
                if not known_hands[player_key]:
                    known_hands[player_key] = list(hand)

        while snapshot_index < len(snapshots):
            snapshot = snapshots[snapshot_index]
            if snapshot["ts"] and event_ts and snapshot["ts"] > event_ts:
                break
            player = snapshot["player"]
            if event.get("turn") == snapshot["turn"] and event.get("phase") == snapshot["phase"]:
                known_hands[player] = list(snapshot["hand"])
            snapshot_index += 1

        if event.get("event_type") == "phase_changed" and "抽 1 張牌" in (event.get("message") or ""):
            actor = event_player(event)
            if actor in known_hands:
                known_hands[actor].append(None)

        played = event_played_card(event)
        actor = event_player(event)
        if played and actor in known_hands:
            remove_one(known_hands[actor], played)

        for player_key in ("p1", "p2"):
            attach_review_hand(features, player_key, known_hands[player_key])

    return enriched


def env_flag_enabled(name):
    value = os.getenv(name)
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def main():
    parser = argparse.ArgumentParser(description="Serve the GCG replay review board.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5178)
    parser.add_argument("--replay", type=Path, default=DEFAULT_REPLAY)
    parser.add_argument(
        "--battle-ai-auto-pass-no-move",
        action="store_true",
        help="P2 AI 無合法操作時跳過 Hermes 自動讓過",
    )
    args = parser.parse_args()

    ReviewBoardHandler.replay_path = args.replay.expanduser().resolve()
    ReviewBoardHandler.battle_session = HumanVsAiBattleSession()
    battle_v2_auto_pass = (
        args.battle_ai_auto_pass_no_move
        or env_flag_enabled("GCG_BATTLE_AI_AUTO_PASS_NO_MOVE")
    )
    ReviewBoardHandler.battle_v2_session = HumanVsAiBattleSession(
        auto_pass_ai_no_move=battle_v2_auto_pass,
    )
    ReviewBoardHandler.battle_v3_session = HumanVsAiBattleSession(
        auto_pass_ai_no_move=battle_v2_auto_pass,
        reveal_card_names=True,
    )
    server = ThreadingHTTPServer((args.host, args.port), ReviewBoardHandler)
    print(f"Review board: http://{args.host}:{args.port}")
    print(f"Replay file: {ReviewBoardHandler.replay_path}")
    server.serve_forever()


if __name__ == "__main__":
    main()
