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
PROVIDER_NAME = "agent-server/codex-app-server"

ORCHESTRATOR_ROLE = "gcg-orchestrator"
JUDGE_ROLE = "gcg-judge"
PLAYER_P1_ROLE = "gcg-ai-player:P1"
PLAYER_P2_ROLE = "gcg-ai-player:P2"
GAME_ROLES = (ORCHESTRATOR_ROLE, JUDGE_ROLE, PLAYER_P1_ROLE, PLAYER_P2_ROLE)


# ## Codex app-server architecture
# This process is a small HTTP wrapper around one long-lived
# `codex app-server --stdio` child process. A GCG game maps to four Codex
# threads, and each thread behaves like an independent chatroom.
#
# Runtime remains the only state mutator. These Codex threads only receive
# public-safe text and return AI decisions; they should not read gameState.md or
# edit files.
PLAYER_BASE_INSTRUCTIONS = """You are the GCG AI player for a card game runtime.

You must not edit files, inspect hidden state files, or call tools. Decide only from
the visible runtime display provided in the latest user message.

Return exactly two non-empty lines:
CONSIDER: <public-safe Traditional Chinese short reason>
COMMAND: <one legal runtime command>

CONSIDER must not reveal hand card ids, card names, shield contents, deck contents,
or chain-of-thought. If legal_actions is keep, redraw, COMMAND must be exactly keep
or redraw. If the display lists concrete commands marked with a check mark, choose
one of those commands exactly. If no legal action is safe, use COMMAND: pass.

Win the game; do not merely make legal moves. Prefer actions in this order when
they are listed as legal:
1. Reduce opponent defense layers with attack base/shield/player.
2. Destroy a rested enemy unit with favorable attack unit.
3. Block attacks that would meaningfully damage your defense layers.
4. Deploy or pair only when it improves pressure or defense more than attacking.
Pass only when no useful attack, block, deploy, pair, or play exists.

The latest viewer display is authoritative. Ignore older board state if it conflicts
with the latest display.
"""


ORCHESTRATOR_BASE_INSTRUCTIONS = """You are the GCG orchestrator chatroom for one card game.

Keep only public-safe game flow context. Python runtime is the source of truth for
state mutation, legality, and display. Do not inspect hidden state files or edit
files. Treat appended actions as conversation context for coordination.
"""


JUDGE_BASE_INSTRUCTIONS = """You are the GCG judge chatroom for one card game.

Review public-safe rule context only when asked. Python runtime is the final
validator/applier. Do not inspect hidden state files or edit files.
"""


@dataclass
class BackendMetrics:
    started_at: float = field(default_factory=time.time)
    requests: int = 0
    failures: int = 0
    total_backend_seconds: float = 0.0
    last_error: str = ""
    sessions: dict[str, str] = field(default_factory=dict)


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
                    timeout_seconds=min(timeout_seconds, 10.0),
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
                output = self._run_turn(thread_id, prompt, timeout_seconds)
                elapsed = time.monotonic() - started
                self.metrics.total_backend_seconds += elapsed
                return _ok_response(
                    game_id=game_id,
                    elapsed=elapsed,
                    role=role,
                    thread_id=thread_id,
                    stdout=output,
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
        append = backend.append("probe_game", ORCHESTRATOR_ROLE, "公開事件：probe 開始", 10.0)
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


def _base_instructions(role: str) -> str:
    if role == ORCHESTRATOR_ROLE:
        return ORCHESTRATOR_BASE_INSTRUCTIONS
    if role == JUDGE_ROLE:
        return JUDGE_BASE_INSTRUCTIONS
    if role in {PLAYER_P1_ROLE, PLAYER_P2_ROLE}:
        player_id = role.rsplit(":", 1)[1]
        return "\n".join([PLAYER_BASE_INSTRUCTIONS, f"\nYou are the persistent chatroom for {player_id}."])
    raise ValueError(f"unknown GCG role: {role}")


def _canonical_role(role: str) -> str:
    normalized = role.strip()
    if normalized in GAME_ROLES:
        return normalized
    if normalized in {"P1", "player_P1", "gcg-ai-player-P1"}:
        return PLAYER_P1_ROLE
    if normalized in {"P2", "player_P2", "gcg-ai-player-P2"}:
        return PLAYER_P2_ROLE
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
