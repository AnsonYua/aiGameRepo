#!/usr/bin/env python3
"""
Regression harness for the GCG AI/runtime boundary.

This intentionally uses only stdlib assertions so it can run in any local
checkout without installing pytest. Default tests do not call a live LLM; they
fake the adapter boundary and the Codex app-server protocol.
"""

from __future__ import annotations

import shutil
import sys
import os
import json
import argparse
import importlib.util
import io
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills_py import ai_adapters, ai_player
from skills_py.agent_specs import render_player_decision_prompt
from skills_py.ai_adapters import AIAdapterResult
from skills_py.gcg_agent_server import GAME_ROLES, JUDGE_ROLE, ORCHESTRATOR_ROLE, PLAYER_P1_ROLE, CodexAppServerBackend, _base_instructions
from skills_py.ai_player import _parse_ai_output, _public_safe_consideration, ai_decide
from skills_py.game_engine import init_game, save_state
from skills_py.game_state import BattleSlot, GameState
from skills_py.gcg_display import render
from skills_py.gcg_runtime import _handle_command
from skills_py.memory_store import LESSONS_DIR, format_lessons, load_reviewed_lessons, search_candidate_lessons


ACTIVE_GAME_FILE = PROJECT_ROOT / ".gcg_active_game"
GAME_STATES_DIR = PROJECT_ROOT / "game-states"


def _load_replay_harness_module():
    path = PROJECT_ROOT / "tests" / "gcg_ai_vs_ai_replay_harness.py"
    spec = importlib.util.spec_from_file_location("gcg_ai_vs_ai_replay_harness_for_tests", path)
    assert_true(spec is not None and spec.loader is not None, "could not load replay harness module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeAdapter:
    provider = "fake"

    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.prompts: list[str] = []

    def run(self, prompt: str, timeout_seconds: float) -> AIAdapterResult:
        self.prompts.append(prompt)
        return AIAdapterResult(
            stdout=self.outputs[len(self.prompts) - 1],
            returncode=0,
            elapsed_seconds=0.01,
            provider=self.provider,
            argv=["fake-ai", "<prompt>"],
        )


class FakeHttpResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeHttpResponse":
        return self

    def __exit__(self, *args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


class FakeCodexClient:
    def __init__(self) -> None:
        self.thread_counter = 0
        self.turn_counter = 0
        self.thread_requests: list[dict] = []
        self.inject_requests: list[dict] = []
        self.turn_requests: list[dict] = []
        self.notifications: list[dict] = []

    def start(self) -> None:
        return None

    def request(self, method: str, params: dict, timeout_seconds: float) -> dict:
        if method == "thread/start":
            self.thread_counter += 1
            self.thread_requests.append(params)
            return {"thread": {"id": f"thread-{self.thread_counter}"}}
        if method == "thread/inject_items":
            self.inject_requests.append(params)
            return {}
        if method == "turn/start":
            self.turn_counter += 1
            self.turn_requests.append(params)
            turn_id = f"turn-{self.turn_counter}"
            thread_id = params["threadId"]
            input_text = params.get("input", [{}])[0].get("text", "")
            if "SELECTED_LESSON_IDS:" in input_text or "請從候選 lessons" in input_text:
                agent_text = "SELECTED_LESSON_IDS: command-target-required-st01-014\nREASON: 當前可見 ST01-014。\n"
            elif "萃取可重用 lesson draft" in input_text or "status 必須是 draft" in input_text:
                agent_text = "id: draft-test\nstatus: draft\nlesson_type: review\nconfidence: low\nsummary: 測試 draft。\n"
            elif "VERDICT: accept" in input_text or "請審查以下 GCG AI player 決策" in input_text:
                agent_text = "VERDICT: accept\nREASON: 語意完整，可交給 runtime 驗證。\n"
            else:
                agent_text = "CONSIDER: fake\nCOMMAND: pass"
            self.notifications.append(
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": {"type": "agentMessage", "text": agent_text},
                    },
                }
            )
            self.notifications.append(
                {
                    "method": "turn/completed",
                    "params": {"threadId": thread_id, "turnId": turn_id, "turn": {"status": "completed"}},
                }
            )
            return {"turn": {"id": turn_id}}
        raise AssertionError(f"unexpected fake codex request: {method}")

    def next_notification(self, timeout_seconds: float) -> dict:
        if not self.notifications:
            raise AssertionError("expected fake notification")
        return self.notifications.pop(0)

    def close(self) -> None:
        return None


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def make_main_state(game_id: str = "harness_ai_adapter") -> GameState:
    state = init_game(game_id)
    state.first_player = "P1"
    state.active_player = "P1"
    state.phase = "main"
    state.step = None
    state.priority = "P1"
    state.p1.hand_cards = ["st01/ST01-005"]
    state.p2.hand_cards = ["st01/ST01-008"]
    state.p1.deck_cards = []
    state.p2.deck_cards = []
    state.p1.shield_cards = []
    state.p2.shield_cards = []
    state.p1.resources_active = 2
    state.p1.resources_rested = 0
    state.p1.resources_ex = 0
    state.p2.resources_active = 0
    state.p2.resources_rested = 0
    state.p2.resources_ex = 1
    state.p1.shields = 6
    state.p2.shields = 6
    return state


def cleanup_harness_state() -> None:
    for path in GAME_STATES_DIR.glob("harness_*"):
        if path.is_dir():
            shutil.rmtree(path)


def test_ai_output_contract() -> None:
    parsed = _parse_ai_output("CONSIDER: 公開場面需保守處理\nCOMMAND: attack 0 unit 1\n")
    assert_true(parsed.command == "attack 0 unit 1", "COMMAND line should be parsed")
    assert_true(parsed.consideration == "公開場面需保守處理", "CONSIDER line should be parsed")
    annotated = _parse_ai_output("CONSIDER: 優先推進防禦層\nCOMMAND: 攻擊 0 — 攻擊對手防禦層\n")
    assert_true(annotated.command == "攻擊 0", "COMMAND parser should strip display annotation text")
    compact_annotated = _parse_ai_output("CONSIDER: 優先推進防禦層\nCOMMAND: 攻擊 0—攻擊對手防禦層\n")
    assert_true(compact_annotated.command == "攻擊 0", "COMMAND parser should strip compact display annotation text")


def test_ai_decide_uses_gcg_agent_and_reprompts_invalid_allowed() -> None:
    state = make_main_state()
    outputs = [
        "CONSIDER: 無法安全決策\nCOMMAND: pass\n",
        "CONSIDER: 依公開場面選擇保留\nCOMMAND: keep\n",
    ]
    adapter = FakeAdapter(outputs)
    original_get_adapter = ai_player.ai_adapters.get_ai_adapter

    def fake_get_adapter(provider: str | None = None) -> FakeAdapter:
        return adapter

    ai_player.ai_adapters.get_ai_adapter = fake_get_adapter
    try:
        decision = ai_decide(state, "P1", {"keep", "redraw"})
    finally:
        ai_player.ai_adapters.get_ai_adapter = original_get_adapter

    assert_true(decision.command == "keep", "AI adapter should reprompt invalid legal action")
    assert_true(decision.provider == "fake", "AI decision should record adapter provider")
    assert_true(len(adapter.prompts) == 2, "AI adapter should retry once through adapter path")
    assert_true("上一個 COMMAND 不合法：pass" in adapter.prompts[1], "retry prompt should explain invalid command")


def test_agent_server_adapter_posts_decide_request() -> None:
    original_urlopen = ai_adapters.urllib.request.urlopen
    original_url = os.environ.get("GCG_AGENT_SERVER_URL")
    calls: list[dict] = []

    def fake_urlopen(request, timeout: float) -> FakeHttpResponse:
        calls.append({"request": request, "timeout": timeout})
        return FakeHttpResponse(
            {
                "provider": "agent-server/codex-app-server",
                "stdout": "CONSIDER: probe\nCOMMAND: pass\n",
                "stderr": "",
                "returncode": 0,
                "elapsed_seconds": 1.25,
                "judge": {"verdict": "accept", "reason": "語意完整"},
                "repair_attempted": False,
                "selected_lesson_ids": ["lesson-a"],
            }
        )

    ai_adapters.urllib.request.urlopen = fake_urlopen
    os.environ["GCG_AGENT_SERVER_URL"] = "http://127.0.0.1:8765"
    try:
        adapter = ai_adapters.get_ai_adapter("agent-server")
        result = adapter.run("game_id: harness_agent\nplayer_id: P1\nlegal_actions: pass", 10)
    finally:
        ai_adapters.urllib.request.urlopen = original_urlopen
        if original_url is None:
            os.environ.pop("GCG_AGENT_SERVER_URL", None)
        else:
            os.environ["GCG_AGENT_SERVER_URL"] = original_url

    body = json.loads(calls[0]["request"].data.decode("utf-8"))
    assert_true(result.provider == "agent-server/codex-app-server", "agent-server adapter should preserve backend provider")
    assert_true(result.stdout.strip().endswith("COMMAND: pass"), "agent-server adapter should return stdout")
    assert_true(result.metadata and result.metadata["judge"]["verdict"] == "accept", "agent-server adapter should preserve judge metadata")
    assert_true(result.metadata["selected_lesson_ids"] == ["lesson-a"], "agent-server adapter should preserve selected lesson ids")
    assert_true(body["game_id"] == "harness_agent", "agent-server request should include game_id from prompt")
    assert_true(body["player_id"] == "P1", "agent-server request should include player_id from prompt")
    assert_true(body["timeout_seconds"] == 10, "agent-server request should include timeout")


def test_agent_server_adapter_preserves_error_response_metadata() -> None:
    original_urlopen = ai_adapters.urllib.request.urlopen
    original_url = os.environ.get("GCG_AGENT_SERVER_URL")

    def fake_urlopen(request, timeout: float) -> FakeHttpResponse:
        payload = {
            "provider": "agent-server/codex-app-server",
            "stdout": "",
            "stderr": "judge final reject",
            "returncode": 1,
            "elapsed_seconds": 2.5,
            "judge": {"verdict": "reject", "reason": "語意仍不完整"},
            "judge_history": [{"verdict": "reject"}, {"verdict": "reject"}],
            "repair_attempted": True,
            "selected_lesson_ids": ["lesson-a"],
        }
        raise ai_adapters.urllib.error.HTTPError(
            request.full_url,
            500,
            "Internal Server Error",
            hdrs=None,
            fp=io.BytesIO(json.dumps(payload).encode("utf-8")),
        )

    ai_adapters.urllib.request.urlopen = fake_urlopen
    os.environ["GCG_AGENT_SERVER_URL"] = "http://127.0.0.1:8765"
    try:
        adapter = ai_adapters.get_ai_adapter("agent-server")
        result = adapter.run("game_id: harness_agent_error\nplayer_id: P1\nlegal_actions: pass", 10)
    finally:
        ai_adapters.urllib.request.urlopen = original_urlopen
        if original_url is None:
            os.environ.pop("GCG_AGENT_SERVER_URL", None)
        else:
            os.environ["GCG_AGENT_SERVER_URL"] = original_url

    assert_true(result.returncode == 1, "agent-server adapter should preserve backend failure returncode")
    assert_true(result.stderr == "judge final reject", "agent-server adapter should preserve backend stderr")
    assert_true(result.metadata and result.metadata["judge"]["verdict"] == "reject", "error response should preserve judge metadata")
    assert_true(result.metadata["repair_attempted"] is True, "error response should preserve repair metadata")


def test_agent_server_init_and_append_helpers() -> None:
    original_urlopen = ai_adapters.urllib.request.urlopen
    original_url = os.environ.get("GCG_AGENT_SERVER_URL")
    calls: list[dict] = []

    def fake_urlopen(request, timeout: float) -> FakeHttpResponse:
        calls.append({"request": request, "timeout": timeout})
        return FakeHttpResponse(
            {
                "provider": "agent-server/codex-app-server",
                "stdout": "",
                "stderr": "",
                "returncode": 0,
                "elapsed_seconds": 0.01,
                "threads": {},
            }
        )

    ai_adapters.urllib.request.urlopen = fake_urlopen
    os.environ["GCG_AGENT_SERVER_URL"] = "http://127.0.0.1:8765"
    try:
        ai_adapters.agent_server_init_game("harness_http", 10)
        ai_adapters.agent_server_append("harness_http", ORCHESTRATOR_ROLE, "P1 執行：pass", 10)
    finally:
        ai_adapters.urllib.request.urlopen = original_urlopen
        if original_url is None:
            os.environ.pop("GCG_AGENT_SERVER_URL", None)
        else:
            os.environ["GCG_AGENT_SERVER_URL"] = original_url

    init_body = json.loads(calls[0]["request"].data.decode("utf-8"))
    append_body = json.loads(calls[1]["request"].data.decode("utf-8"))
    assert_true(calls[0]["request"].full_url.endswith("/init-game"), "init helper should POST /init-game")
    assert_true(init_body["game_id"] == "harness_http", "init helper should include game_id")
    assert_true(calls[1]["request"].full_url.endswith("/append"), "append helper should POST /append")
    assert_true(append_body["role"] == ORCHESTRATOR_ROLE, "append helper should include role")


def test_codex_app_server_backend_separates_player_threads() -> None:
    fake_client = FakeCodexClient()
    backend = CodexAppServerBackend(client=fake_client)
    p1_thread = backend._thread_id("harness_game", "P1", 10)
    p2_thread = backend._thread_id("harness_game", "P2", 10)
    p1_thread_again = backend._thread_id("harness_game", "P1", 10)

    assert_true(p1_thread == "thread-1", "P1 should get the first thread")
    assert_true(p2_thread == "thread-2", "P2 should get a separate thread")
    assert_true(p1_thread_again == p1_thread, "P1 should reuse its own thread")
    assert_true(len(fake_client.thread_requests) == 2, "backend should create only one thread per game/player")


def test_codex_app_server_backend_initializes_canonical_game_rooms() -> None:
    fake_client = FakeCodexClient()
    backend = CodexAppServerBackend(client=fake_client)
    result = backend.init_game("harness_agent_rooms", 10)
    threads = result["threads"]

    assert_true(result["returncode"] == 0, f"init_game should succeed: {result}")
    assert_true(set(threads) == set(GAME_ROLES), "init_game should create the canonical GCG rooms")
    assert_true(len(set(threads.values())) == len(GAME_ROLES), "each GCG room should have its own Codex thread")
    assert_true(len(fake_client.thread_requests) == len(GAME_ROLES), "backend should call thread/start for each role")
    session_dir = GAME_STATES_DIR / "harness_agent_rooms" / "ai_sessions"
    for role in GAME_ROLES:
        path = session_dir / f"{role.replace(':', '_')}.json"
        assert_true(path.exists(), f"session metadata should be written for {role}")


def test_codex_app_server_backend_reuses_persisted_session_metadata() -> None:
    first_client = FakeCodexClient()
    first_backend = CodexAppServerBackend(client=first_client)
    first = first_backend.init_game("harness_persisted_rooms", 10)

    second_client = FakeCodexClient()
    second_backend = CodexAppServerBackend(client=second_client)
    thread_id = second_backend._thread_id("harness_persisted_rooms", PLAYER_P1_ROLE, 10)

    assert_true(thread_id == first["threads"][PLAYER_P1_ROLE], "backend restart should reuse persisted player room thread id")
    assert_true(len(second_client.thread_requests) == 0, "reusing persisted room should not create a replacement thread")


def test_codex_app_server_backend_appends_to_orchestrator_room() -> None:
    fake_client = FakeCodexClient()
    backend = CodexAppServerBackend(client=fake_client)
    init = backend.init_game("harness_append_room", 10)
    result = backend.append("harness_append_room", ORCHESTRATOR_ROLE, "P1 執行：pass", 10)

    assert_true(result["returncode"] == 0, f"append should succeed: {result}")
    assert_true(result["thread_id"] == init["threads"][ORCHESTRATOR_ROLE], "append should target orchestrator thread")
    assert_true(len(fake_client.inject_requests) == 1, "append should use thread/inject_items")
    item = fake_client.inject_requests[0]["items"][0]
    assert_true(item["type"] == "message" and item["role"] == "user", "append should inject a user message item")
    assert_true("P1 執行" in item["content"][0]["text"], "append text should preserve public action summary")


def test_codex_app_server_backend_reuses_player_thread_for_decisions() -> None:
    fake_client = FakeCodexClient()
    backend = CodexAppServerBackend(client=fake_client)
    init = backend.init_game("harness_decide_room", 10)
    prompt = "game_id: harness_decide_room\nplayer_id: P1\nlegal_actions: pass\n"

    first = backend.decide("harness_decide_room", "P1", prompt, 10)
    second = backend.decide("harness_decide_room", "P1", prompt, 10)

    assert_true(first["returncode"] == 0 and second["returncode"] == 0, "decide calls should succeed")
    assert_true(first["thread_id"] == init["threads"]["gcg-ai-player:P1"], "P1 decide should use P1 room")
    assert_true(second["thread_id"] == first["thread_id"], "P1 second decision should reuse P1 room")
    assert_true(init["threads"][JUDGE_ROLE] != first["thread_id"], "judge room must not share player thread")
    assert_true(len(fake_client.thread_requests) == len(GAME_ROLES), "decide should not create extra threads after init_game")
    assert_true(first["judge"]["verdict"] == "skipped", "low-risk decide should include skipped judge metadata")
    assert_true(first["judge_mode"] == "risk", "default judge mode should be risk")
    assert_true(first["judge_thread_id"] == "", "low-risk decide should not run judge turn")
    assert_true(len(fake_client.turn_requests) == 2, "two low-risk decide calls should only run player turns")


def test_codex_app_server_backend_repairs_after_judge_reject() -> None:
    class RejectThenAcceptClient(FakeCodexClient):
        def __init__(self) -> None:
            super().__init__()
            self.judge_calls = 0

        def request(self, method: str, params: dict, timeout_seconds: float) -> dict:
            if method != "turn/start":
                return super().request(method, params, timeout_seconds)
            self.turn_counter += 1
            self.turn_requests.append(params)
            turn_id = f"turn-{self.turn_counter}"
            thread_id = params["threadId"]
            input_text = params.get("input", [{}])[0].get("text", "")
            if "請從候選 lessons" in input_text:
                agent_text = "SELECTED_LESSON_IDS: command-target-required-st01-014\nREASON: 當前可見 ST01-014。\n"
            elif "請審查以下 GCG AI player 決策" in input_text:
                self.judge_calls += 1
                if self.judge_calls == 1:
                    agent_text = "VERDICT: reject\nREASON: COMMAND 缺少必要目標。\nSUGGESTED_COMMAND: 使用 st01/ST01-014 unit 1\n"
                else:
                    agent_text = "VERDICT: accept\nREASON: 已修正語意。\n"
            elif "Judge 修正意見" in input_text:
                agent_text = "CONSIDER: 依 judge 意見補上公開目標。\nCOMMAND: 使用 st01/ST01-014 unit 1"
            else:
                agent_text = "CONSIDER: 想使用公開 command。\nCOMMAND: 使用 st01/ST01-014"
            self.notifications.append(
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": {"type": "agentMessage", "text": agent_text},
                    },
                }
            )
            self.notifications.append(
                {
                    "method": "turn/completed",
                    "params": {"threadId": thread_id, "turnId": turn_id, "turn": {"status": "completed"}},
                }
            )
            return {"turn": {"id": turn_id}}

    fake_client = RejectThenAcceptClient()
    backend = CodexAppServerBackend(client=fake_client)
    backend.init_game("harness_judge_repair", 10)
    prompt = "game_id: harness_judge_repair\nplayer_id: P1\nlegal_actions: 使用 st01/ST01-014\n"
    result = backend.decide("harness_judge_repair", "P1", prompt, 10)

    assert_true(result["returncode"] == 0, f"repair decide should succeed: {result}")
    assert_true(result["repair_attempted"] is True, "judge reject should trigger one player repair")
    assert_true(result["judge"]["verdict"] == "accept", "final judge verdict should be accept")
    assert_true(result["stdout"].startswith("CONSIDER:") and "COMMAND:" in result["stdout"], "final stdout should be player contract output")
    assert_true("unit 1" in result["stdout"], "final stdout should come from repaired player command")
    assert_true(fake_client.judge_calls == 2, "judge should review original and repaired command")
    assert_true(len(fake_client.turn_requests) == 5, "selector, player, judge, repair player, judge turns should run")
    repair_prompt = fake_client.turn_requests[3]["input"][0]["text"]
    assert_true("Judge 修正意見" in repair_prompt, "repair prompt should be sent to player room")
    assert_true(fake_client.turn_requests[3]["threadId"] != fake_client.turn_requests[2]["threadId"], "repair turn must not run in judge room")


def test_codex_app_server_backend_fails_closed_after_second_judge_reject() -> None:
    class AlwaysRejectClient(FakeCodexClient):
        def request(self, method: str, params: dict, timeout_seconds: float) -> dict:
            if method != "turn/start":
                return super().request(method, params, timeout_seconds)
            self.turn_counter += 1
            self.turn_requests.append(params)
            turn_id = f"turn-{self.turn_counter}"
            thread_id = params["threadId"]
            input_text = params.get("input", [{}])[0].get("text", "")
            if "請從候選 lessons" in input_text:
                agent_text = "SELECTED_LESSON_IDS: command-target-required-st01-014\nREASON: 當前可見 ST01-014。\n"
            elif "請審查以下 GCG AI player 決策" in input_text:
                agent_text = "VERDICT: reject\nREASON: COMMAND 仍缺少必要目標。\n"
            else:
                agent_text = "CONSIDER: 嘗試使用 command。\nCOMMAND: 使用 st01/ST01-014"
            self.notifications.append(
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": {"type": "agentMessage", "text": agent_text},
                    },
                }
            )
            self.notifications.append(
                {
                    "method": "turn/completed",
                    "params": {"threadId": thread_id, "turnId": turn_id, "turn": {"status": "completed"}},
                }
            )
            return {"turn": {"id": turn_id}}

    fake_client = AlwaysRejectClient()
    backend = CodexAppServerBackend(client=fake_client)
    backend.init_game("harness_judge_reject_closed", 10)
    prompt = "game_id: harness_judge_reject_closed\nplayer_id: P1\nlegal_actions: 使用 st01/ST01-014\n"
    result = backend.decide("harness_judge_reject_closed", "P1", prompt, 10)

    assert_true(result["returncode"] == 1, "second judge reject should fail closed")
    assert_true(result["stdout"] == "", "failed judge decision should not return player command stdout")
    assert_true(result["repair_attempted"] is True, "failure metadata should preserve repair_attempted")
    assert_true(len(result["judge_history"]) == 2, "failure metadata should preserve both judge verdicts")
    assert_true(result["judge"]["verdict"] == "reject", "final judge metadata should be reject")


def test_codex_app_server_backend_curates_memory_as_draft_only() -> None:
    fake_client = FakeCodexClient()
    backend = CodexAppServerBackend(client=fake_client)
    init = backend.init_game("harness_curator", 10)
    before_lesson_files = {path.name for path in LESSONS_DIR.glob("*.yaml")} if LESSONS_DIR.exists() else set()
    result = backend.curate_memory("harness_curator", "Review: public-safe bad move", 10)
    after_lesson_files = {path.name for path in LESSONS_DIR.glob("*.yaml")} if LESSONS_DIR.exists() else set()

    assert_true(result["returncode"] == 0, f"curate_memory should succeed: {result}")
    assert_true(result["role"] == "gcg-memory-curator", "curator response should identify curator role")
    assert_true("status: draft" in result["stdout"], "curator should produce draft lesson text")
    assert_true("gcg-memory-curator" not in init["threads"], "curator should not be part of per-game init rooms")
    assert_true(before_lesson_files == after_lesson_files, "curator should not write draft lessons into reviewed store")
    reviewed_ids = [lesson.lesson_id for lesson in load_reviewed_lessons()]
    assert_true("draft-test" not in reviewed_ids, "curator draft output should not become reviewed memory automatically")


def test_codex_app_server_backend_rejects_hidden_curator_source() -> None:
    fake_client = FakeCodexClient()
    backend = CodexAppServerBackend(client=fake_client)
    result = backend.curate_memory("harness_curator_hidden", "gameState.md\nhand_cards: [st01/ST01-001]", 10)

    assert_true(result["returncode"] == 1, "curator should reject raw hidden state source text")
    assert_true("public-safe" in result["stderr"], "curator hidden-source failure should explain public-safe requirement")
    assert_true(len(fake_client.turn_requests) == 0, "hidden-source rejection should happen before any LLM turn")


def test_codex_app_server_backend_health_reports_start_failure() -> None:
    class FailingClient:
        def start(self) -> None:
            raise RuntimeError("codex app-server unavailable")

        def close(self) -> None:
            return None

    backend = CodexAppServerBackend(client=FailingClient())
    health = backend.health()
    assert_true(health["ok"] is False, "health should fail when backend cannot start")
    assert_true("codex app-server unavailable" in health["error"], "health error should expose backend startup failure")


def test_player_base_instructions_include_experience_context() -> None:
    instructions = _base_instructions(PLAYER_P1_ROLE)
    assert_true("GCG AI 玩家" in instructions, "player prompt should load from markdown agent spec")
    assert_true("P1" in instructions, "player-specific room identity should be rendered")
    assert_true("沒有 `Blocker` 的高 HP Unit 不會保護基地或盾牌" in instructions, "player prompt should include defense truth")
    assert_true("lethal-race-check" not in instructions, "player base prompt should not load all experience")


def test_player_decision_prompt_includes_explicit_context_only() -> None:
    prompt = "\n".join([
        "game_id: skill_prompt",
        "player_id: P1",
        "legal_actions: deploy, attack, pass",
        "盾牌：6 剩餘 | 基地：EX-BASE | AP|HP：0|1",
        "攻擊合法性：攻擊 0 — 攻擊對手防禦層 ✅",
        "可行指令：部署 st01/ST01-004 — Guntank ✅",
    ])
    rendered = render_player_decision_prompt(
        prompt,
        "P1",
        selected_lessons_text="id: lesson-1\nsummary: 公開經驗。",
        card_text_context="card_id: st01/ST01-004\nname: Guntank",
    )
    assert_true("id: lesson-1" in rendered, "explicit selected lesson context should be included")
    assert_true("card_id: st01/ST01-004" in rendered, "explicit card text context should be included")
    assert_true("COMMAND 只能輸出命令本體" in rendered, "decision prompt should forbid copying display annotations")


def test_player_decision_prompt_does_not_auto_inject_legacy_skills() -> None:
    prompt = "\n".join([
        "game_id: skill_prompt_healthy",
        "player_id: P1",
        "legal_actions: deploy, pass",
        "盾牌：6 剩餘 | 基地：EX-BASE | AP|HP：0|3",
        "對手盾牌：6 剩餘 | 對手基地：有（EX-BASE | AP|HP：0|3）",
        "可行指令：部署 st01/ST01-004 — Guntank ✅",
    ])
    rendered = render_player_decision_prompt(prompt, "P1")
    assert_true("low-base-defense" not in rendered, "player prompt should not auto-inject legacy skills")
    assert_true("lethal-race" not in rendered, "player prompt should not auto-inject legacy skills")


def test_memory_store_returns_llm_readable_candidates_only() -> None:
    prompt = "\n".join([
        "game_id: harness_memory",
        "player_id: P1",
        "legal_actions: 使用 st01/ST01-014",
        "可行指令：使用 st01/ST01-014 — Unforeseen Incident ✅",
    ])
    lessons = search_candidate_lessons(prompt)
    lesson_ids = [lesson.lesson_id for lesson in lessons]
    assert_true("command-target-required-st01-014" in lesson_ids, "memory retrieval should find matching reviewed lesson")
    formatted = format_lessons(lessons)
    assert_true("player_instruction" in formatted, "formatted lessons should be LLM-readable context")
    assert_true("COMMAND:" not in formatted, "memory store should not emit executable player command protocol")


def test_memory_store_does_not_retrieve_card_lesson_from_generic_command_words() -> None:
    prompt = "\n".join([
        "game_id: harness_memory_generic",
        "player_id: P1",
        "legal_actions: pass",
        "Return exactly:",
        "CONSIDER: probe",
        "COMMAND: pass",
    ])
    lesson_ids = [lesson.lesson_id for lesson in search_candidate_lessons(prompt)]
    assert_true("command-target-required-st01-014" not in lesson_ids, "generic COMMAND wording should not retrieve card-specific lessons")


def test_ai_decide_does_not_replace_active_game_pointer() -> None:
    state = make_main_state("harness_ai_active_pointer")
    ACTIVE_GAME_FILE.write_text("preserve_active_game", encoding="utf-8")
    adapter = FakeAdapter(["CONSIDER: 依公開場面選擇讓過\nCOMMAND: pass\n"])
    original_get_adapter = ai_player.ai_adapters.get_ai_adapter

    def fake_get_adapter(provider: str | None = None) -> FakeAdapter:
        return adapter

    ai_player.ai_adapters.get_ai_adapter = fake_get_adapter
    try:
        ai_decide(state, "P1")
    finally:
        ai_player.ai_adapters.get_ai_adapter = original_get_adapter

    assert_true(
        ACTIVE_GAME_FILE.read_text(encoding="utf-8").strip() == "preserve_active_game",
        "AI display rendering must not replace .gcg_active_game",
    )


def test_ai_evaluation_includes_agent_server_metadata() -> None:
    from skills_py.gcg_runtime import _ai_evaluation

    decision = ai_player.AIDecision(
        command="pass",
        consideration="依公開場面讓過。",
        provider="agent-server",
        metadata={
            "judge": {"verdict": "accept", "reason": "語意完整"},
            "repair_attempted": False,
            "selected_lesson_ids": ["lesson-a"],
        },
    )
    data = _ai_evaluation(decision)
    assert_true(data["judge"]["verdict"] == "accept", "ai_evaluation should include judge metadata")
    assert_true(data["repair_attempted"] is False, "ai_evaluation should include repair metadata")
    assert_true(data["selected_lesson_ids"] == ["lesson-a"], "ai_evaluation should include selected lesson ids")


def test_replay_review_counts_applied_ai_metadata() -> None:
    replay_harness = _load_replay_harness_module()
    game_id = "harness_review_applied_metadata"
    game_dir = GAME_STATES_DIR / game_id
    game_dir.mkdir(parents=True, exist_ok=True)
    gameplay = {
        "schema_version": 1,
        "game_id": game_id,
        "summary": {},
        "events": [
            {
                "seq": 1,
                "event_type": "decision_applied",
                "actor": "P1",
                "command": "keep",
                "message": "P1 保留手牌",
                "result": {"ok": True, "reason": ""},
                "ai_evaluation": {
                    "chosen_command": "keep",
                    "judge": {"verdict": "accept", "reason": "調度語意完整"},
                    "repair_attempted": False,
                    "selected_lesson_ids": ["mulligan-lesson"],
                },
            }
        ],
    }
    (game_dir / "gamePlay.yaml").write_text(yaml.safe_dump(gameplay, allow_unicode=True), encoding="utf-8")
    (game_dir / "replay.md").write_text("# Replay\n", encoding="utf-8")
    analysis = replay_harness.analyze(game_id, [{"game_over": False}], ai_adapter_calls=1, max_reached=False)

    assert_true(analysis["judge_verdicts"] == ["accept"], "review analyze should count decision_applied AI judge metadata")
    assert_true(analysis["selected_lesson_ids"] == ["mulligan-lesson"], "review analyze should count decision_applied selected lessons")


def test_consideration_sanitizer_blocks_hidden_info() -> None:
    state = make_main_state()
    text = "用 st01/ST01-005 和 GM 的手牌曲線建立優勢"
    sanitized = _public_safe_consideration(state, "P1", text)
    assert_true("st01/ST01-005" not in sanitized, "sanitizer must remove hidden card id")
    assert_true("GM" not in sanitized, "sanitizer must remove hidden card name")
    assert_true("手牌" not in sanitized, "sanitizer must not write hand details to public replay")


def test_display_lists_concrete_attack_legality() -> None:
    state = make_main_state("harness_display_attack")
    state.p1.hand_cards = []
    state.p1.battle_area[0] = BattleSlot(
        slot=0,
        unit_id="st01/ST01-005",
        ap=2,
        hp=2,
        damage=0,
        status="active",
        turns_on_field=0,
    )
    state.p1.battle_area[1] = BattleSlot(
        slot=1,
        unit_id="st01/ST01-009",
        ap=3,
        hp=2,
        damage=0,
        status="active",
        turns_on_field=1,
    )
    state.p2.battle_area[2] = BattleSlot(
        slot=2,
        unit_id="st01/ST01-008",
        ap=1,
        hp=1,
        damage=0,
        status="rested",
        keywords=["Blocker"],
        turns_on_field=1,
    )
    save_state(state, set_active=False)
    text = render(str(GAME_STATES_DIR / state.game_id / "gameState.md"), viewer="P1")
    assert_true("欄位0 不能攻擊：剛部署的 Unit 本回合不能攻擊" in text, "display should explain summoning sickness")
    assert_true("攻擊 1 — 攻擊對手防禦層✅" in text, "display should list legal base attack command")
    assert_true("攻擊 1 unit 2 — 攻擊敵方欄位2✅" in text, "display should list legal unit attack command")


def test_display_lists_concrete_block_legality() -> None:
    state = make_main_state("harness_display_block")
    state.phase = "battle"
    state.step = "block"
    state.active_player = "P1"
    state.priority = "P2"
    state.current_attacker = 0
    state.p1.battle_area[0] = BattleSlot(
        slot=0,
        unit_id="st01/ST01-005",
        ap=2,
        hp=2,
        status="active",
        turns_on_field=1,
    )
    state.p2.battle_area[1] = BattleSlot(
        slot=1,
        unit_id="st01/ST01-009",
        ap=3,
        hp=2,
        status="active",
        keywords=["Blocker"],
        turns_on_field=1,
    )
    save_state(state, set_active=False)
    text = render(str(GAME_STATES_DIR / state.game_id / "gameState.md"), viewer="P2")
    assert_true("阻擋 1 — 使用欄位1 阻擋✅" in text, "display should list legal block command")


def test_runtime_attack_enemy_unit() -> None:
    state = make_main_state("harness_unit_attack")
    state.p1.battle_area[0] = BattleSlot(
        slot=0,
        unit_id="st01/ST01-005",
        ap=2,
        hp=2,
        damage=0,
        status="active",
        turns_on_field=1,
    )
    state.p2.battle_area[1] = BattleSlot(
        slot=1,
        unit_id="st01/ST01-008",
        ap=1,
        hp=1,
        damage=0,
        status="rested",
        keywords=["Blocker"],
        turns_on_field=1,
    )
    ok, reason = _handle_command(state, "P1", "attack 0 unit 1")
    assert_true(ok, f"unit-target attack should be legal: {reason}")
    assert_true(state.p2.battle_area[1].unit_id is None, "target unit should be destroyed")
    assert_true(state.phase == "main" and state.priority == "P1", "battle should return to main priority")


def test_runtime_block_command() -> None:
    state = make_main_state("harness_block")
    state.phase = "battle"
    state.step = "block"
    state.priority = "P2"
    state.current_attacker = 0
    state.p1.battle_area[0] = BattleSlot(
        slot=0,
        unit_id="st01/ST01-005",
        ap=2,
        hp=2,
        damage=0,
        status="active",
        turns_on_field=1,
    )
    state.p2.battle_area[1] = BattleSlot(
        slot=1,
        unit_id="st01/ST01-009",
        ap=3,
        hp=2,
        damage=0,
        status="active",
        keywords=["Blocker"],
        turns_on_field=1,
    )
    ok, reason = _handle_command(state, "P2", "block 1")
    assert_true(ok, f"block should be legal: {reason}")
    assert_true(state.p1.battle_area[0].unit_id is None, "attacker should be destroyed")
    assert_true(state.p2.battle_area[1].unit_id is None, "blocker should be destroyed")


def test_replay_yaml_public_safe_consideration() -> None:
    state = make_main_state("harness_replay")
    state.p1.battle_area[0] = BattleSlot(
        slot=0,
        unit_id="st01/ST01-009",
        pilot_id=None,
        ap=3,
        hp=2,
        damage=1,
        status="rested",
        keywords=["Blocker"],
        turns_on_field=1,
    )
    state.p1.trash = ["st01/ST01-001"]
    state.p2.removal = ["st01/ST01-002"]
    save_state(state)
    from skills_py.gameplay_log import append_event, gameplay_log_path, replay_path

    append_event(
        state,
        "decision_applied",
        "P1",
        "P1",
        "P1 執行：pass",
        command="pass",
        result={"ok": True, "reason": ""},
        ai_evaluation={
            "chosen_command": "pass",
            "candidates": [],
            "consideration": "依公開場面、防禦層與優先權評估後選擇此指令。",
        },
    )
    loaded = yaml.safe_load(gameplay_log_path(state.game_id).read_text(encoding="utf-8"))
    assert_true(loaded["events"][0]["ai_evaluation"]["consideration"], "YAML should store consideration")
    assert_true("hand_cards" not in loaded["events"][0]["features"]["p1"], "YAML features must not store hand cards")
    assert_true("deck_cards" not in loaded["events"][0]["features"]["p1"], "YAML features must not store deck cards")
    assert_true("shield_cards" not in loaded["events"][0]["features"]["p1"], "YAML features must not store shield cards")
    replay = replay_path(state.game_id).read_text(encoding="utf-8")
    assert_true("- 考量：" in replay, "replay should render consideration")
    assert_true("公開狀態快照：" in replay, "replay should render public state snapshot")
    assert_true("P1 場面：\n      欄位0 [st01/ST01-009]" in replay, "replay should render public slot details")
    assert_true("P1 trash：st01/ST01-001" in replay, "replay should render public trash")
    assert_true("P2 removal：st01/ST01-002" in replay, "replay should render public removal")
    assert_true("hand_cards" not in replay, "replay must not expose hidden hand key")
    assert_true("deck_cards" not in replay, "replay must not expose hidden deck key")
    assert_true("shield_cards" not in replay, "replay must not expose hidden shield key")
    assert_true("gameState.md" not in replay, "replay must not dump raw state path")


def test_replay_review_flags_non_blocking_deploy_under_lethal() -> None:
    replay_harness = _load_replay_harness_module()
    events = [
        {
            "seq": 1,
            "event_type": "decision_received",
            "actor": "P1",
            "command": "deploy st01/ST01-003",
            "features": {
                "p1": {
                    "shields": 2,
                    "base": {"alive": False},
                    "board": {"blockers": 0},
                },
                "p2": {
                    "board": {
                        "slots": [
                            {"unit_id": "public-unit-a", "turns_on_field": 1},
                            {"unit_id": "public-unit-b", "turns_on_field": 1},
                            {"unit_id": "public-unit-c", "turns_on_field": 1},
                        ]
                    }
                },
            },
        },
        {
            "seq": 2,
            "event_type": "decision_applied",
            "actor": "P1",
            "command": "deploy st01/ST01-003",
            "features": {
                "p1": {
                    "shields": 2,
                    "base": {"alive": False},
                    "board": {"blockers": 0},
                }
            },
        },
    ]
    signals = replay_harness._lethal_race_deploy_signals(events)
    assert_true(signals and "面臨下回合斬殺仍部署" in signals[0], "review should flag non-blocking deploy under lethal")


def test_live_llm_contract() -> None:
    state = init_game("harness_live_llm")
    state.first_player = "P1"
    state.active_player = "P1"
    state.priority = "P1"
    decision = ai_decide(state, "P1", {"keep", "redraw"})
    action = decision.command.split(maxsplit=1)[0].lower()
    assert_true(action in {"keep", "redraw"}, f"live LLM returned invalid mulligan command: {decision.command}")
    assert_true(decision.consideration != "", "live LLM should return CONSIDER")
    assert_true("st01/" not in decision.consideration, "live LLM CONSIDER must not expose card ids")
    assert_true("手牌" not in decision.consideration, "adapter must sanitize hidden hand wording")


def run(live_llm: bool = False) -> None:
    original_active = ACTIVE_GAME_FILE.read_text(encoding="utf-8") if ACTIVE_GAME_FILE.exists() else None
    try:
        cleanup_harness_state()
        test_ai_output_contract()
        test_ai_decide_uses_gcg_agent_and_reprompts_invalid_allowed()
        test_agent_server_adapter_posts_decide_request()
        test_agent_server_adapter_preserves_error_response_metadata()
        test_agent_server_init_and_append_helpers()
        test_codex_app_server_backend_separates_player_threads()
        test_codex_app_server_backend_initializes_canonical_game_rooms()
        test_codex_app_server_backend_reuses_persisted_session_metadata()
        test_codex_app_server_backend_appends_to_orchestrator_room()
        test_codex_app_server_backend_reuses_player_thread_for_decisions()
        test_codex_app_server_backend_repairs_after_judge_reject()
        test_codex_app_server_backend_fails_closed_after_second_judge_reject()
        test_codex_app_server_backend_curates_memory_as_draft_only()
        test_codex_app_server_backend_rejects_hidden_curator_source()
        test_codex_app_server_backend_health_reports_start_failure()
        test_player_base_instructions_include_experience_context()
        test_player_decision_prompt_includes_explicit_context_only()
        test_player_decision_prompt_does_not_auto_inject_legacy_skills()
        test_memory_store_returns_llm_readable_candidates_only()
        test_memory_store_does_not_retrieve_card_lesson_from_generic_command_words()
        test_ai_decide_does_not_replace_active_game_pointer()
        test_ai_evaluation_includes_agent_server_metadata()
        test_replay_review_counts_applied_ai_metadata()
        test_consideration_sanitizer_blocks_hidden_info()
        test_display_lists_concrete_attack_legality()
        test_display_lists_concrete_block_legality()
        test_runtime_attack_enemy_unit()
        test_runtime_block_command()
        test_replay_yaml_public_safe_consideration()
        test_replay_review_flags_non_blocking_deploy_under_lethal()
        if live_llm:
            test_live_llm_contract()
    finally:
        cleanup_harness_state()
        if original_active is None:
            ACTIVE_GAME_FILE.unlink(missing_ok=True)
        else:
            ACTIVE_GAME_FILE.write_text(original_active, encoding="utf-8")
    suffix = " with live LLM." if live_llm else "."
    print(f"GCG direction harness passed{suffix}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run GCG runtime/agent-server direction harness")
    parser.add_argument("--live-llm", action="store_true", help="also call the configured live AI provider")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(live_llm=args.live_llm)
