#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import queue
import re
import shlex
import socketserver
import subprocess
import sys
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).parent.parent.absolute()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills_py.agent_specs import (
    build_card_text_context,
    render_agent_instructions,
    render_judge_prompt,
    render_player_decision_prompt,
    render_selector_prompt,
)
from skills_py.memory_store import filter_lessons_by_ids, format_lessons, search_candidate_lessons

PROVIDER_NAME = "agent-server/codex-app-server"

ORCHESTRATOR_ROLE = "gcg-orchestrator"
JUDGE_ROLE = "gcg-judge"
MEMORY_SELECTOR_ROLE = "gcg-memory-selector"
PLAYER_P1_ROLE = "gcg-ai-player:P1"
PLAYER_P2_ROLE = "gcg-ai-player:P2"
GAME_ROLES = (ORCHESTRATOR_ROLE, JUDGE_ROLE, MEMORY_SELECTOR_ROLE, PLAYER_P1_ROLE, PLAYER_P2_ROLE)


# ## Codex app-server architecture
# This process is a small HTTP wrapper around one long-lived
# `codex app-server --stdio` child process. A GCG game maps to four Codex
# threads, and each thread behaves like an independent chatroom.
#
# Runtime remains the only state mutator. These Codex threads only receive
# public-safe text and return AI decisions; they should not read gameState.md or
# edit files.
@dataclass
class BackendMetrics:
    started_at: float = field(default_factory=time.time)
    requests: int = 0
    failures: int = 0
    total_backend_seconds: float = 0.0
    last_error: str = ""
    sessions: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeVerdict:
    verdict: str
    reason: str = ""
    suggested_command: str = ""
    raw_output: str = ""

    @property
    def accepted(self) -> bool:
        return self.verdict == "accept"

    def to_dict(self) -> dict[str, str]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "suggested_command": self.suggested_command,
            "raw_output": self.raw_output,
        }


class AgentSessionBackend(ABC):
    """Provider-facing interface for long-lived GCG chatrooms."""

    @abstractmethod
    def init_game(self, game_id: str, timeout_seconds: float) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def append(self, game_id: str, role: str, message: str, timeout_seconds: float) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def decide(self, game_id: str, player_id: str, prompt: str, timeout_seconds: float) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def snapshot_metrics(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError


class JsonLineCodexClient:
    """Tiny JSON-RPC client for `codex app-server --stdio`."""

    def __init__(self, argv: list[str] | None = None) -> None:
        self.argv = argv or ["codex", "app-server", "--stdio"]
        self.process: subprocess.Popen[str] | None = None
        self._request_id = 0
        self._pending: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._notifications: queue.Queue[dict[str, Any]] = queue.Queue()
        self._stderr_lines: list[str] = []
        self._io_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        self.process = subprocess.Popen(
            self.argv,
            cwd=str(PROJECT_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()
        self.request(
            "initialize",
            {
                "clientInfo": {"name": "gcg-agent-server", "version": "0.2"},
                "capabilities": {"experimental": True},
            },
            timeout_seconds=15.0,
        )
        self.notify("initialized")
        self._started = True

    def close(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

    def request(self, method: str, params: Any, timeout_seconds: float) -> Any:
        self._ensure_running()
        with self._pending_lock:
            self._request_id += 1
            request_id = self._request_id
            response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
            self._pending[request_id] = response_queue
        self._write_json({"id": request_id, "method": method, "params": params})
        try:
            response = response_queue.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            with self._pending_lock:
                self._pending.pop(request_id, None)
            raise TimeoutError(f"codex app-server request timed out: {method}") from exc
        if "error" in response:
            raise RuntimeError(f"codex app-server {method} error: {response['error']}")
        return response.get("result")

    def notify(self, method: str, params: Any | None = None) -> None:
        message: dict[str, Any] = {"method": method}
        if params is not None:
            message["params"] = params
        self._write_json(message)

    def next_notification(self, timeout_seconds: float) -> dict[str, Any]:
        self._ensure_running()
        try:
            return self._notifications.get(timeout=timeout_seconds)
        except queue.Empty as exc:
            raise TimeoutError("timed out waiting for codex app-server notification") from exc

    def stderr_tail(self, limit: int = 20) -> str:
        return "\n".join(self._stderr_lines[-limit:])

    def _ensure_running(self) -> None:
        if self.process and self.process.poll() is not None:
            raise RuntimeError(f"codex app-server exited with code {self.process.returncode}: {self.stderr_tail()}")

    def _write_json(self, payload: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("codex app-server process is not started")
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._io_lock:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()

    def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                self._stderr_lines.append(f"non-json stdout: {line[:300]}")
                continue
            request_id = message.get("id")
            if request_id is not None:
                with self._pending_lock:
                    response_queue = self._pending.pop(int(request_id), None)
                if response_queue:
                    response_queue.put(message)
            else:
                self._notifications.put(message)

    def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        for line in self.process.stderr:
            line = line.strip()
            if line:
                self._stderr_lines.append(line)


class CodexAppServerBackend(AgentSessionBackend):
    def __init__(self, client: JsonLineCodexClient | None = None) -> None:
        self.client = client or JsonLineCodexClient(_codex_app_server_argv())
        self.metrics = BackendMetrics()
        self._lock = threading.RLock()
        self._threads: dict[tuple[str, str], str] = {}
        self._started = False

    def start(self) -> None:
        with self._lock:
            if not self._started:
                self.client.start()
                self._started = True

    def health(self) -> dict[str, Any]:
        try:
            self.start()
            return {"ok": True, "provider": PROVIDER_NAME, "sessions": len(self._threads)}
        except Exception as exc:
            self.metrics.last_error = str(exc)
            return {"ok": False, "provider": PROVIDER_NAME, "error": str(exc)}

    def init_game(self, game_id: str, timeout_seconds: float) -> dict[str, Any]:
        started = time.monotonic()
        with self._lock:
            self.metrics.requests += 1
            try:
                self.start()
                threads = {role: self._thread_id(game_id, role, timeout_seconds) for role in GAME_ROLES}
                elapsed = time.monotonic() - started
                self.metrics.total_backend_seconds += elapsed
                return _ok_response(game_id=game_id, elapsed=elapsed, threads=threads)
            except Exception as exc:
                return self._failure_response(exc, started, game_id=game_id, threads={})

    def append(self, game_id: str, role: str, message: str, timeout_seconds: float) -> dict[str, Any]:
        started = time.monotonic()
        with self._lock:
            self.metrics.requests += 1
            try:
                self.start()
                role = _canonical_role(role)
                thread_id = self._thread_id(game_id, role, timeout_seconds)
                # ## Append without inference
                # `thread/inject-items` writes a raw Responses API user message into
                # the thread history. This keeps the room context warm without paying
                # for an LLM turn after every public action summary.
                self.client.request(
                    "thread/inject_items",
                    {"threadId": thread_id, "items": [_user_response_item(message)]},
                    timeout_seconds=min(timeout_seconds, 30.0),
                )
                elapsed = time.monotonic() - started
                self.metrics.total_backend_seconds += elapsed
                return _ok_response(game_id=game_id, elapsed=elapsed, role=role, thread_id=thread_id)
            except Exception as exc:
                return self._failure_response(exc, started, game_id=game_id, role=role, thread_id="")

    def decide(self, game_id: str, player_id: str, prompt: str, timeout_seconds: float) -> dict[str, Any]:
        started = time.monotonic()
        with self._lock:
            self.metrics.requests += 1
            try:
                self.start()
                role = _player_role(player_id)
                thread_id = self._thread_id(game_id, role, timeout_seconds)
                judge_thread_id = self._thread_id(game_id, JUDGE_ROLE, timeout_seconds)
                card_text_context = build_card_text_context(prompt)
                candidate_lessons = search_candidate_lessons(prompt)
                candidate_lesson_ids = [lesson.lesson_id for lesson in candidate_lessons]
                selector_thread_id = ""
                selector_output = ""
                selected_lesson_ids: list[str] = []
                selected_lessons_text = ""
                if candidate_lessons:
                    selector_thread_id = self._thread_id(game_id, MEMORY_SELECTOR_ROLE, timeout_seconds)
                    selector_prompt = render_selector_prompt(prompt, format_lessons(candidate_lessons), card_text_context)
                    selector_output = self._run_turn(selector_thread_id, selector_prompt, timeout_seconds)
                    selected_lesson_ids = _parse_selected_lesson_ids(selector_output)
                    selected_lessons = filter_lessons_by_ids(candidate_lessons, selected_lesson_ids)
                    selected_lessons_text = format_lessons(selected_lessons)
                decision_prompt = render_player_decision_prompt(
                    prompt,
                    player_id,
                    selected_lessons_text=selected_lessons_text,
                    card_text_context=card_text_context,
                )
                output = self._run_turn(thread_id, decision_prompt, timeout_seconds)
                judge = self._judge_decision(
                    judge_thread_id,
                    prompt,
                    output,
                    selected_lessons_text,
                    card_text_context,
                    timeout_seconds,
                )
                repair_attempted = False
                judge_history = [judge.to_dict()]
                if not judge.accepted:
                    repair_attempted = True
                    repair_prompt = render_player_decision_prompt(
                        prompt,
                        player_id,
                        selected_lessons_text=selected_lessons_text,
                        card_text_context=card_text_context,
                        judge_feedback=_judge_feedback_text(judge),
                    )
                    output = self._run_turn(thread_id, repair_prompt, timeout_seconds)
                    judge = self._judge_decision(
                        judge_thread_id,
                        prompt,
                        output,
                        selected_lessons_text,
                        card_text_context,
                        timeout_seconds,
                    )
                    judge_history.append(judge.to_dict())
                if not judge.accepted:
                    raise RuntimeError(f"judge rejected final command: {judge.reason or judge.raw_output}")
                elapsed = time.monotonic() - started
                self.metrics.total_backend_seconds += elapsed
                return _ok_response(
                    game_id=game_id,
                    elapsed=elapsed,
                    role=role,
                    thread_id=thread_id,
                    stdout=output,
                    judge=judge.to_dict(),
                    judge_history=judge_history,
                    judge_thread_id=judge_thread_id,
                    repair_attempted=repair_attempted,
                    selected_lesson_ids=selected_lesson_ids,
                    candidate_lesson_ids=candidate_lesson_ids,
                    selector_thread_id=selector_thread_id,
                    selector_output=selector_output,
                    card_text_context_included=bool(card_text_context),
                )
            except Exception as exc:
                return self._failure_response(exc, started, game_id=game_id, role=_player_role(player_id), thread_id="")

    def snapshot_metrics(self) -> dict[str, Any]:
        avg = self.metrics.total_backend_seconds / self.metrics.requests if self.metrics.requests else 0.0
        self.metrics.sessions = {f"{game_id}:{role}": thread_id for (game_id, role), thread_id in self._threads.items()}
        return {
            "provider": PROVIDER_NAME,
            "uptime_seconds": time.time() - self.metrics.started_at,
            "requests": self.metrics.requests,
            "failures": self.metrics.failures,
            "average_backend_seconds": avg,
            "last_error": self.metrics.last_error,
            "sessions": self.metrics.sessions,
        }

    def close(self) -> None:
        self.client.close()

    def _failure_response(self, exc: Exception, started: float, **extra: Any) -> dict[str, Any]:
        self.metrics.failures += 1
        self.metrics.last_error = str(exc)
        elapsed = time.monotonic() - started
        response = _error_response(str(exc), elapsed)
        response.update(extra)
        return response

    def _thread_id(self, game_id: str, role: str, timeout_seconds: float) -> str:
        role = _canonical_role(role)
        key = (game_id, role)
        if key in self._threads:
            return self._threads[key]
        result = self.client.request(
            "thread/start",
            {
                "cwd": str(PROJECT_ROOT),
                "approvalPolicy": "never",
                "sandbox": "read-only",
                "baseInstructions": _base_instructions(role),
                "ephemeral": True,
                "serviceName": "gcg-agent-server",
                "threadSource": "user",
            },
            timeout_seconds=min(timeout_seconds, 30.0),
        )
        thread = (result or {}).get("thread") or {}
        thread_id = thread.get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise RuntimeError(f"thread/start did not return a thread id: {result}")
        self._threads[key] = thread_id
        _write_session_metadata(game_id, role, thread_id)
        return thread_id

    def _run_turn(self, thread_id: str, prompt: str, timeout_seconds: float) -> str:
        result = self.client.request(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt, "text_elements": []}],
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
                "summary": "none",
            },
            timeout_seconds=min(timeout_seconds, 30.0),
        )
        turn = (result or {}).get("turn") or {}
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise RuntimeError(f"turn/start did not return a turn id: {result}")

        deadline = time.monotonic() + timeout_seconds
        deltas: list[str] = []
        completed_messages: list[str] = []
        while time.monotonic() < deadline:
            remaining = max(0.1, deadline - time.monotonic())
            notification = self.client.next_notification(timeout_seconds=remaining)
            method = notification.get("method")
            params = notification.get("params") or {}
            if params.get("threadId") != thread_id:
                continue
            if params.get("turnId") and params.get("turnId") != turn_id:
                continue
            if method == "item/agentMessage/delta":
                delta = params.get("delta")
                if isinstance(delta, str):
                    deltas.append(delta)
            elif method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
                    completed_messages.append(item["text"])
            elif method == "turn/completed":
                turn_payload = params.get("turn") or {}
                if turn_payload.get("status") == "failed":
                    raise RuntimeError(f"codex turn failed: {turn_payload.get('error')}")
                output = (completed_messages[-1] if completed_messages else "".join(deltas)).strip()
                if not output:
                    output = _agent_text_from_turn(turn_payload).strip()
                if not output:
                    raise RuntimeError("codex turn completed without an agent message")
                return output
        raise TimeoutError(f"codex app-server turn timed out after {timeout_seconds:g}s")

    def _judge_decision(
        self,
        judge_thread_id: str,
        prompt: str,
        player_output: str,
        selected_lessons_text: str,
        card_text_context: str,
        timeout_seconds: float,
    ) -> JudgeVerdict:
        judge_prompt = render_judge_prompt(
            prompt,
            player_output,
            selected_lessons_text=selected_lessons_text,
            card_text_context=card_text_context,
        )
        output = self._run_turn(judge_thread_id, judge_prompt, timeout_seconds)
        return _parse_judge_output(output)


class AgentRequestHandler(BaseHTTPRequestHandler):
    backend: AgentSessionBackend

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(self.backend.health(), status=200)
        elif self.path == "/metrics":
            self._write_json(self.backend.snapshot_metrics(), status=200)
        else:
            self._write_json({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        if self.path == "/init-game":
            self._handle_init_game()
        elif self.path == "/append":
            self._handle_append()
        elif self.path == "/decide":
            self._handle_decide()
        else:
            self._write_json({"error": "not found"}, status=404)

    def _handle_init_game(self) -> None:
        try:
            payload = self._read_payload()
            game_id = str(payload.get("game_id") or "")
            timeout_seconds = float(payload.get("timeout_seconds") or 30.0)
            if not game_id:
                raise ValueError("game_id is required")
            result = self.backend.init_game(game_id, timeout_seconds)
            self._write_json(result, status=200 if result.get("returncode") == 0 else 500)
        except Exception as exc:
            self._write_json(_error_response(str(exc), 0.0), status=400)

    def _handle_append(self) -> None:
        try:
            payload = self._read_payload()
            game_id = str(payload.get("game_id") or "")
            role = str(payload.get("role") or "")
            message = str(payload.get("message") or "")
            timeout_seconds = float(payload.get("timeout_seconds") or 10.0)
            if not game_id or not role or not message:
                raise ValueError("game_id, role, and message are required")
            result = self.backend.append(game_id, role, message, timeout_seconds)
            self._write_json(result, status=200 if result.get("returncode") == 0 else 500)
        except Exception as exc:
            self._write_json(_error_response(str(exc), 0.0), status=400)

    def _handle_decide(self) -> None:
        try:
            payload = self._read_payload()
            game_id = str(payload.get("game_id") or "")
            player_id = str(payload.get("player_id") or "")
            prompt = str(payload.get("prompt") or "")
            timeout_seconds = float(payload.get("timeout_seconds") or 60.0)
            if not game_id or not player_id or not prompt:
                raise ValueError("game_id, player_id, and prompt are required")
            result = self.backend.decide(game_id, player_id, prompt, timeout_seconds)
            self._write_json(result, status=200 if result.get("returncode") == 0 else 500)
        except Exception as exc:
            self._write_json(_error_response(str(exc), 0.0), status=400)

    def _read_payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def _write_json(self, data: dict[str, Any], status: int) -> None:
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class GCGThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def run_probe(timeout_seconds: float = 60.0) -> dict[str, Any]:
    backend = CodexAppServerBackend()
    prompt = "\n".join(
        [
            "game_id: probe_game",
            "player_id: P1",
            "first_player: P1",
            "legal_actions: pass",
            "",
            "Probe only. Return exactly:",
            "CONSIDER: probe",
            "COMMAND: pass",
        ]
    )
    try:
        init = backend.init_game("probe_game", timeout_seconds)
        append = backend.append("probe_game", ORCHESTRATOR_ROLE, "公開事件：probe 開始", timeout_seconds)
        first = backend.decide("probe_game", "P1", prompt, timeout_seconds)
        second = backend.decide("probe_game", "P1", prompt, timeout_seconds)
        return {"init": init, "append": append, "first": first, "second": second, "metrics": backend.snapshot_metrics()}
    finally:
        backend.close()


def serve(host: str, port: int) -> None:
    backend = CodexAppServerBackend()
    AgentRequestHandler.backend = backend
    server = GCGThreadingHTTPServer((host, port), AgentRequestHandler)
    try:
        print(f"GCG agent server listening on http://{host}:{port}", flush=True)
        server.serve_forever()
    finally:
        backend.close()


def _agent_text_from_turn(turn: dict[str, Any]) -> str:
    for item in reversed(turn.get("items") or []):
        if isinstance(item, dict) and item.get("type") == "agentMessage" and isinstance(item.get("text"), str):
            return item["text"]
    return ""


def _parse_judge_output(output: str) -> JudgeVerdict:
    verdict = ""
    reason = ""
    suggested_command = ""
    for line in [line.strip() for line in output.splitlines() if line.strip()]:
        lower = line.lower()
        if lower.startswith("verdict:"):
            value = line.split(":", 1)[1].strip().lower()
            if value in {"accept", "accepted", "pass"}:
                verdict = "accept"
            elif value in {"reject", "rejected", "fail"}:
                verdict = "reject"
            else:
                verdict = value
        elif lower.startswith("reason:"):
            reason = line.split(":", 1)[1].strip()
        elif lower.startswith("suggested_command:"):
            suggested_command = line.split(":", 1)[1].strip()
    if verdict not in {"accept", "reject"}:
        raise RuntimeError(f"judge output missing VERDICT: {output.strip()[:200]}")
    return JudgeVerdict(verdict=verdict, reason=reason, suggested_command=suggested_command, raw_output=output)


def _parse_selected_lesson_ids(output: str) -> list[str]:
    for line in [line.strip() for line in output.splitlines() if line.strip()]:
        if line.lower().startswith("selected_lesson_ids:"):
            raw = line.split(":", 1)[1].strip()
            if not raw:
                return []
            return [part.strip() for part in raw.split(",") if part.strip()]
    raise RuntimeError(f"selector output missing SELECTED_LESSON_IDS: {output.strip()[:200]}")


def _judge_feedback_text(judge: JudgeVerdict) -> str:
    lines = [
        f"上一個 COMMAND 被 judge 判定為 reject。",
        f"REASON: {judge.reason or '未提供'}",
    ]
    if judge.suggested_command:
        lines.append(f"SUGGESTED_COMMAND 僅供你參考，必須由你重新輸出 COMMAND: {judge.suggested_command}")
    return "\n".join(lines)


def _base_instructions(role: str) -> str:
    if role == ORCHESTRATOR_ROLE:
        return render_agent_instructions("gcg-orchestrator")
    if role == JUDGE_ROLE:
        return render_agent_instructions("gcg-judge")
    if role == MEMORY_SELECTOR_ROLE:
        return render_agent_instructions("gcg-memory-selector")
    if role in {PLAYER_P1_ROLE, PLAYER_P2_ROLE}:
        player_id = role.rsplit(":", 1)[1]
        return render_agent_instructions("gcg-ai-player", player_id=player_id, tactical_skills="")
    raise ValueError(f"unknown GCG role: {role}")


def _canonical_role(role: str) -> str:
    normalized = role.strip()
    if normalized in GAME_ROLES:
        return normalized
    if normalized in {"P1", "player_P1", "gcg-ai-player-P1"}:
        return PLAYER_P1_ROLE
    if normalized in {"P2", "player_P2", "gcg-ai-player-P2"}:
        return PLAYER_P2_ROLE
    if normalized in {"memory-selector", "selector"}:
        return MEMORY_SELECTOR_ROLE
    raise ValueError(f"unknown GCG role: {role}")


def _player_role(player_id: str) -> str:
    player = player_id.strip().upper()
    if player == "P1":
        return PLAYER_P1_ROLE
    if player == "P2":
        return PLAYER_P2_ROLE
    raise ValueError(f"unknown player_id: {player_id}")


def _user_response_item(message: str) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": message}],
    }


def _session_metadata_path(game_id: str, role: str) -> Path:
    safe_game_id = re.sub(r"[^A-Za-z0-9_.-]", "_", game_id)
    filename = role.replace(":", "_").replace("/", "_") + ".json"
    return PROJECT_ROOT / "game-states" / safe_game_id / "ai_sessions" / filename


def _write_session_metadata(game_id: str, role: str, thread_id: str) -> None:
    path = _session_metadata_path(game_id, role)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider": PROVIDER_NAME,
        "game_id": game_id,
        "role": role,
        "thread_id": thread_id,
        "created_at": time.time(),
        "note": "This records the long-lived Codex app-server thread for review. Runtime state remains in gameState.md.",
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _ok_response(elapsed: float, **extra: Any) -> dict[str, Any]:
    response = {
        "provider": PROVIDER_NAME,
        "stdout": extra.pop("stdout", ""),
        "stderr": "",
        "returncode": 0,
        "elapsed_seconds": elapsed,
        "backend_elapsed_seconds": elapsed,
    }
    response.update(extra)
    return response


def _error_response(stderr: str, elapsed: float) -> dict[str, Any]:
    return {
        "provider": PROVIDER_NAME,
        "stdout": "",
        "stderr": stderr,
        "returncode": 1,
        "elapsed_seconds": elapsed,
        "backend_elapsed_seconds": elapsed,
    }


def _codex_app_server_argv() -> list[str]:
    raw = os.environ.get("GCG_CODEX_APP_SERVER_ARGV", "").strip()
    if raw:
        return shlex.split(raw)
    return ["codex", "app-server", "--stdio"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Local GCG Codex app-server backed agent API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8890)
    parser.add_argument("--probe", action="store_true", help="run a two-turn Codex app-server protocol probe and exit")
    parser.add_argument("--timeout-seconds", type=float, default=60.0)
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(run_probe(args.timeout_seconds), ensure_ascii=False, indent=2))
        return 0
    serve(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
