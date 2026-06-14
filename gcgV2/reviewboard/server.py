#!/usr/bin/env python3
import argparse
import copy
import json
import re
from datetime import datetime
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import yaml


DEFAULT_REPLAY = Path(
    "/Users/hello/Desktop/cardAI/gcgV2/out/game_20260614_141722_112076/gamePlay.yaml"
)


class ReviewBoardHandler(SimpleHTTPRequestHandler):
    replay_path = DEFAULT_REPLAY

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/replay":
            self._send_replay()
            return
        if parsed.path == "/":
            self.path = "/index.html"
        super().do_GET()

    def _send_replay(self):
        try:
            with self.replay_path.open("r", encoding="utf-8") as handle:
                payload = yaml.safe_load(handle) or {}
            payload = enrich_review_hands(payload, self.replay_path)
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
            self.send_response(500)
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


def main():
    parser = argparse.ArgumentParser(description="Serve the GCG replay review board.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5178)
    parser.add_argument("--replay", type=Path, default=DEFAULT_REPLAY)
    args = parser.parse_args()

    ReviewBoardHandler.replay_path = args.replay.expanduser().resolve()
    server = ThreadingHTTPServer((args.host, args.port), ReviewBoardHandler)
    print(f"Review board: http://{args.host}:{args.port}")
    print(f"Replay file: {ReviewBoardHandler.replay_path}")
    server.serve_forever()


if __name__ == "__main__":
    main()
