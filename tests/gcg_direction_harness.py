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
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from skills_py import ai_adapters, ai_player
from skills_py.ai_adapters import AIAdapterResult
from skills_py.gcg_agent_server import GAME_ROLES, JUDGE_ROLE, ORCHESTRATOR_ROLE, CodexAppServerBackend
from skills_py.ai_player import _parse_ai_output, _public_safe_consideration, ai_decide
from skills_py.game_engine import init_game, save_state
from skills_py.game_state import BattleSlot, GameState
from skills_py.gcg_display import render
from skills_py.gcg_runtime import _handle_command


ACTIVE_GAME_FILE = PROJECT_ROOT / ".gcg_active_game"
GAME_STATES_DIR = PROJECT_ROOT / "game-states"


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
            self.notifications.append(
                {
                    "method": "item/completed",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                        "item": {"type": "agentMessage", "text": "CONSIDER: fake\nCOMMAND: pass"},
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
    assert_true(body["game_id"] == "harness_agent", "agent-server request should include game_id from prompt")
    assert_true(body["player_id"] == "P1", "agent-server request should include player_id from prompt")
    assert_true(body["timeout_seconds"] == 10, "agent-server request should include timeout")


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


def test_codex_app_server_backend_initializes_four_game_rooms() -> None:
    fake_client = FakeCodexClient()
    backend = CodexAppServerBackend(client=fake_client)
    result = backend.init_game("harness_agent_rooms", 10)
    threads = result["threads"]

    assert_true(result["returncode"] == 0, f"init_game should succeed: {result}")
    assert_true(set(threads) == set(GAME_ROLES), "init_game should create the four canonical GCG rooms")
    assert_true(len(set(threads.values())) == 4, "each GCG room should have its own Codex thread")
    assert_true(len(fake_client.thread_requests) == 4, "backend should call thread/start exactly four times")
    session_dir = GAME_STATES_DIR / "harness_agent_rooms" / "ai_sessions"
    for role in GAME_ROLES:
        path = session_dir / f"{role.replace(':', '_')}.json"
        assert_true(path.exists(), f"session metadata should be written for {role}")


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
    assert_true(len(fake_client.thread_requests) == 4, "decide should not create extra threads after init_game")


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
        test_agent_server_init_and_append_helpers()
        test_codex_app_server_backend_separates_player_threads()
        test_codex_app_server_backend_initializes_four_game_rooms()
        test_codex_app_server_backend_appends_to_orchestrator_room()
        test_codex_app_server_backend_reuses_player_thread_for_decisions()
        test_codex_app_server_backend_health_reports_start_failure()
        test_ai_decide_does_not_replace_active_game_pointer()
        test_consideration_sanitizer_blocks_hidden_info()
        test_display_lists_concrete_attack_legality()
        test_display_lists_concrete_block_legality()
        test_runtime_attack_enemy_unit()
        test_runtime_block_command()
        test_replay_yaml_public_safe_consideration()
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
