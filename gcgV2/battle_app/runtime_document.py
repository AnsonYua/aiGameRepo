"""Document-backed runtime helpers for the serverless battle API."""

from __future__ import annotations

import copy
import json
import os
import re
import tempfile
import time
from uuid import uuid4
from pathlib import Path

from gcg.cards import CardDatabase
from gcg.engine.command_parser import CommandParser
from gcg.engine.viewer import ViewerStateBuilder
from gcg.sim.bootstrap import build_simulator
from reviewboard.humanVsAI.battle_session import AI_PLAYER, HUMAN_PLAYER, HumanVsAiBattleSession
from reviewboard.humanVsAI.command_labels import build_legal_actions

from battle_app.env import load_battle_app_env
from .storage import build_game_document

load_battle_app_env()


_CARD_ID_PATTERN = re.compile(r"\bst\d{2}/[A-Z0-9-]+\b")
_REASONING_MARKERS = ("理由：", "理由:")
_CARD_DB = None


def get_card_db():
    global _CARD_DB
    if _CARD_DB is None:
        _CARD_DB = CardDatabase()
    return _CARD_DB


def _strip_reasoning(message):
    for marker in _REASONING_MARKERS:
        idx = message.find(marker)
        if idx != -1:
            return message[:idx]
    return message


class StateReader:
    def __init__(self, raw_state):
        self._raw_state = raw_state

    def get_state(self):
        return self._raw_state


class DocumentGameplayWriter:
    """Gameplay writer that keeps the canonical document in memory only."""

    def __init__(self, document=None):
        self._documents = {}
        if document:
            self._documents[document["game_id"]] = copy.deepcopy(document)

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

    def append_event(self, game_id, event):
        payload = self._document(game_id)
        payload["events"].append(event)
        payload["summary"]["turn"] = event.get("turn")
        payload["summary"]["phase"] = event.get("phase")
        payload["summary"]["total_events"] = len(payload["events"])

    def finalize(self, game_id, status, winner=None, win_reason=None):
        payload = self._document(game_id)
        payload["summary"]["status"] = status
        payload["summary"]["winner"] = winner
        payload["summary"]["win_reason"] = win_reason

    def get_gameplay_path(self, game_id):
        return f"mongo://games/{game_id}/gameplay_log"

    def get_document(self, game_id):
        return self._document(game_id)

    def _document(self, game_id):
        if game_id not in self._documents:
            self.create_gameplay_log(game_id=game_id, schema_version="2.0")
        return self._documents[game_id]


class DocumentBackedBattle:
    def __init__(self, runner, status, error=None, last_message=""):
        self.runner = runner
        self.status = status
        self.error = error
        self.last_message = last_message

    @classmethod
    def create_new(cls):
        # Reuse the local session start path so opening setup stays identical.
        session = HumanVsAiBattleSession(
            auto_pass_ai_no_move=True,
            reveal_card_names=True,
        )
        response = session.start()
        return document_from_session(session, response), response

    @classmethod
    def hydrate(cls, document):
        runner = _build_runner()
        raw_state = copy.deepcopy(document["runtime_state"])
        game_id = raw_state["game_id"]
        runner.game_id = game_id
        runner.state.game_id = game_id
        runner.state.state = raw_state

        writer = DocumentGameplayWriter(document.get("gameplay_log"))
        runner.gameplay_logger.yaml_writer = writer
        runner.gameplay_logger.current_game_id = game_id
        runner.gameplay_logger.seq = _max_event_seq(writer.get_document(game_id))
        return cls(
            runner=runner,
            status=document.get("status") or "not_started",
            error=document.get("error"),
            last_message=document.get("message") or "",
        )

    def submit_command(self, raw_command):
        if not isinstance(raw_command, str) or not raw_command.strip():
            return self._error_response("缺少 command。")
        if self.status == "waiting_ai":
            return self._error_response("對手正在思考中，請稍候。")
        if self.status == "game_over":
            return self._error_response("對局已結束。")
        if self.status == "error":
            return self.response()

        self._advance_and_update_status()
        actor, legal_commands, pending_choice = self._current_decision()
        if actor != HUMAN_PLAYER:
            return self._error_response("目前不是 P1 的決策時機。")

        try:
            parsed = CommandParser().parse(raw_command, HUMAN_PLAYER)
            normalized = parsed.command_line()
            if normalized not in set(legal_commands):
                raise ValueError(f"指令不在合法清單中：{normalized}")
            if pending_choice is not None:
                self.runner.runtime.resolve_pending_choice(parsed, pending_choice)
            else:
                self.runner.runtime.resolve_command(parsed)
        except Exception as exc:  # noqa: BLE001 - API boundary
            self.runner.gameplay_logger.log_invalid_command(
                game_id=self.runner.game_id,
                player_id=HUMAN_PLAYER,
                raw_command=raw_command,
                reason=str(exc),
            )
            return self._error_response(f"指令執行失敗：{exc}")

        self.last_message = "P1 已執行操作。"
        self._advance_and_update_status()
        return self.response()

    def run_ai_once(self):
        self._advance_and_update_status()
        if self.status != "waiting_ai":
            return self.response(), None

        actor, legal_commands, pending_choice = self._current_decision()
        if actor != AI_PLAYER or not legal_commands:
            return self.response(), None

        if pending_choice is None and legal_commands == ["pass"]:
            parsed = CommandParser().parse("pass", AI_PLAYER)
            self.runner.runtime.resolve_command(parsed)
            self.last_message = "P2 沒有可用操作，自動讓過。"
            self._advance_and_update_status()
            return self.response(), 0.0

        viewer_bundle = self.runner.viewer_builder.build_for_player(self.runner.state, AI_PLAYER)
        prompt_payload = self.runner.prompt_builder.build(viewer_bundle, legal_commands)
        started = time.time()
        raw_command = self.runner.players[AI_PLAYER].decide(self.runner.game_id, AI_PLAYER, prompt_payload)
        latency = time.time() - started

        try:
            parsed = CommandParser().parse(raw_command, AI_PLAYER)
            normalized = parsed.command_line()
            if normalized not in set(legal_commands):
                raise ValueError("指令不在合法清單中。")
            if pending_choice is not None:
                self.runner.runtime.resolve_pending_choice(parsed, pending_choice)
            else:
                self.runner.runtime.resolve_command(parsed)
        except Exception as exc:  # noqa: BLE001 - surfaced as error in Phase 2 API
            self.status = "error"
            self.error = f"AI 決策失敗，請重新開始：{exc}"
            self.last_message = self.error
            return self.response(), latency

        self.last_message = "P2 已完成決策。"
        self._advance_and_update_status()
        return self.response(), latency

    def response(self):
        legal_commands = []
        if self.status == "waiting_human":
            actor, legal_commands, _pending_choice = self._current_decision()
            if actor != HUMAN_PLAYER:
                legal_commands = []
        return response_from_parts(
            runtime_state=self.runner.state.get_state(),
            gameplay_log=self.runner.gameplay_logger.yaml_writer.get_document(self.runner.game_id),
            status=self.status,
            message=self.last_message,
            error=self.error,
            legal_commands=legal_commands,
        )

    def to_document(self, previous_document=None, response=None):
        response = response or self.response()
        gameplay_log = self.runner.gameplay_logger.yaml_writer.get_document(self.runner.game_id)
        document = build_game_document(
            game_id=self.runner.game_id,
            runtime_state=self.runner.state.get_state(),
            gameplay_log=gameplay_log,
            status=response.get("status") or self.status,
            message=response.get("message") or self.last_message,
            error=response.get("error"),
            winner=response.get("winner"),
            game_over=bool(response.get("game_over")),
            legal_commands=response.get("legal_commands") or [],
        )
        if previous_document:
            document["created_at"] = previous_document.get("created_at", document["created_at"])
            document["version"] = previous_document.get("version", 1)
            document["ai_lock_until"] = previous_document.get("ai_lock_until")
            document["ai_lock_owner"] = previous_document.get("ai_lock_owner")
        return document

    def _advance_and_update_status(self):
        self.runner.runtime.advance_until_decision_or_stable()
        if self.runner.runtime.is_game_over():
            self.status = "game_over"
            return
        actor, legal_commands, _pending_choice = self._current_decision()
        if actor == HUMAN_PLAYER:
            self.status = "waiting_human"
        elif actor == AI_PLAYER and legal_commands:
            self.status = "waiting_ai"
        else:
            self.status = "error"
            self.error = "Runtime 無法找到下一個合法決策點。"

    def _current_decision(self):
        if self.runner.runtime.is_game_over():
            return None, [], None
        pending_choice = self.runner.state.peek_pending_choice()
        if pending_choice is not None:
            actor = pending_choice.get("player_id")
            legal_commands = self.runner.enumerator.pending_choice_commands(pending_choice)
            return actor, legal_commands, pending_choice
        if self.runner.state.needs_action_window():
            actor = self.runner.state.get_priority_player()
            legal_commands = self.runner.enumerator.legal_commands(actor)
            return actor, legal_commands, None
        return None, [], None

    def _error_response(self, message):
        payload = self.response()
        payload["ok"] = False
        payload["error"] = message
        payload["message"] = message
        return payload


class MongoBattleService:
    def __init__(self, store):
        self.store = store

    def create_game(self):
        document, response = DocumentBackedBattle.create_new()
        self.store.insert_game(document)
        return response

    def get_state(self, game_id):
        document = self.store.get_game(game_id)
        if document is None:
            return None
        if document.get("status") == "waiting_ai":
            owner = f"poll-{uuid4().hex}"
            locked = self.store.acquire_ai_lock(game_id, owner=owner)
            if locked is not None:
                return self._run_locked_ai_step(game_id, locked, owner)
        return response_from_document(document)

    def submit_command(self, game_id, raw_command):
        document = self.store.get_game(game_id)
        if document is None:
            return None
        battle = DocumentBackedBattle.hydrate(document)
        response = battle.submit_command(raw_command)
        updated = battle.to_document(previous_document=document, response=response)
        saved = self.store.save_game(
            game_id,
            expected_version=document["version"],
            updates=_updates_from_document(updated),
        )
        return response_from_document(saved)

    def _run_locked_ai_step(self, game_id, locked_document, owner):
        battle = DocumentBackedBattle.hydrate(locked_document)
        response, latency = battle.run_ai_once()
        updated = battle.to_document(previous_document=locked_document, response=response)
        updated["ai_lock_until"] = None
        updated["ai_lock_owner"] = None
        if latency is not None:
            updated["last_ai_latency_seconds"] = latency
            updated["last_ai_lock_owner"] = owner
        saved = self.store.save_game(
            game_id,
            expected_version=locked_document["version"],
            updates=_updates_from_document(updated),
        )
        return response_from_document(saved)


def document_from_session(session, response):
    runner = session._runner
    game_id = runner.game_id
    return build_game_document(
        game_id=game_id,
        runtime_state=runner.state.get_state(),
        gameplay_log=runner.gameplay_logger.yaml_writer.get_document(game_id),
        status=response.get("status") or "not_started",
        message=response.get("message") or "",
        error=response.get("error"),
        winner=response.get("winner"),
        game_over=bool(response.get("game_over")),
        legal_commands=response.get("legal_commands") or [],
    )


def response_from_document(document):
    return response_from_parts(
        runtime_state=document["runtime_state"],
        gameplay_log=document.get("gameplay_log") or {"game_id": document["game_id"], "events": []},
        status=document.get("status") or "not_started",
        message=document.get("message") or "",
        error=document.get("error"),
        legal_commands=document.get("legal_commands") or [],
    )


def response_from_parts(*, runtime_state, gameplay_log, status, message, error, legal_commands):
    viewer_bundle = ViewerStateBuilder().build_for_player(StateReader(runtime_state), HUMAN_PLAYER)
    viewer_state = viewer_bundle["viewer_state"]
    decision_type = viewer_state.get("decision_type")
    if status == "waiting_ai":
        decision_type = "wait"
    elif status == "error":
        decision_type = "error"
    elif status == "game_over":
        decision_type = "game_over"

    visible_legal_commands = list(legal_commands) if status == "waiting_human" else []
    return {
        "ok": status != "error",
        "status": status,
        "game_id": runtime_state.get("game_id"),
        "viewer_state": viewer_state,
        "legal_commands": visible_legal_commands,
        "legal_actions": build_legal_actions(visible_legal_commands, card_db=get_card_db()),
        "events": public_events(gameplay_log),
        "message": response_message(status, message, error, viewer_state, runtime_state),
        "decision_type": decision_type,
        "game_over": bool(runtime_state.get("game_over")),
        "winner": runtime_state.get("winner"),
        "error": error,
    }


def response_message(status, message, error, viewer_state, runtime_state):
    if status == "waiting_ai":
        return "對手思考中..."
    if status == "error":
        return error or "AI 決策失敗，請重新開始。"
    if status == "game_over":
        return f"對局結束，勝者：{runtime_state.get('winner')}。"
    pending = viewer_state.get("pending_choice") or {}
    if pending.get("visible") and pending.get("message"):
        return pending["message"]
    return message


def public_events(gameplay_log, limit=16):
    events = gameplay_log.get("events") or []
    public = []
    for event in events[-limit:]:
        public.append({
            "seq": event.get("seq"),
            "turn": event.get("turn"),
            "phase": event.get("phase"),
            "step": event.get("step"),
            "actor": event.get("actor"),
            "event_type": event.get("event_type"),
            "message": public_message(event),
            "ok": (event.get("result") or {}).get("ok"),
        })
    return public


def public_message(event):
    actor = event.get("actor")
    event_type = event.get("event_type")
    if actor == AI_PLAYER and event_type == "command_rejected":
        return "AI 輸出不合法指令，正在重新決策。"
    message = _strip_reasoning(str(event.get("message") or "")).strip()
    return _CARD_ID_PATTERN.sub(card_name_replacer, message)


def card_name_replacer(match):
    card_id = match.group(0)
    card = get_card_db().get(card_id)
    name = card.get("name") if card else None
    return name or card_id


def card_detail(card_id):
    if not card_id:
        return None
    card = get_card_db().get(card_id)
    if card is None:
        return None
    return {
        "id": card.get("id"),
        "name": card.get("name"),
        "cardType": card.get("cardType"),
        "color": card.get("color"),
        "level": card.get("level", 0),
        "cost": card.get("cost", 0),
        "ap": card.get("ap", 0),
        "hp": card.get("hp", 0),
        "zone": list(card.get("zone", [])),
        "traits": list(card.get("traits", [])),
        "link": list(card.get("link", [])),
        "keywords": list(card.get("keywords", [])),
        "descriptions": list(card.get("effects", {}).get("description", [])),
    }


def _build_runner():
    output_root = os.getenv("GCG_BATTLE_APP_TMP_OUTPUT_ROOT")
    if not output_root:
        output_root = str(Path(tempfile.gettempdir()) / "gcg_battle_app_runtime")
    return build_simulator(
        players=os.getenv("GCG_BATTLE_AI_MODE", "hermes"),
        interpreter=os.getenv("GCG_BATTLE_INTERPRETER", "llm"),
        output_root=output_root,
    )


def _max_event_seq(gameplay_log):
    events = gameplay_log.get("events") or []
    return max((int(event.get("seq") or 0) for event in events), default=0)


def _updates_from_document(document):
    keys = (
        "runtime_state",
        "gameplay_log",
        "status",
        "message",
        "error",
        "winner",
        "game_over",
        "legal_commands",
        "ai_lock_until",
        "ai_lock_owner",
        "last_ai_latency_seconds",
        "last_ai_lock_owner",
    )
    return {key: copy.deepcopy(document.get(key)) for key in keys}
