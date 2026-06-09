import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class AIAdapterResult:
    stdout: str
    stderr: str = ""
    returncode: int = 0
    elapsed_seconds: float = 0.0
    provider: str = ""
    argv: list[str] | None = None
    metadata: dict | None = None


class AIAdapter:
    provider = "base"

    def run(self, prompt: str, timeout_seconds: float) -> AIAdapterResult:
        raise NotImplementedError


class AgentServerAdapter(AIAdapter):
    provider = "agent-server"

    def run(self, prompt: str, timeout_seconds: float) -> AIAdapterResult:
        game_id = _prompt_value(prompt, "game_id") or "unknown_game"
        player_id = _prompt_value(prompt, "player_id") or "unknown_player"
        started = time.monotonic()
        data = _agent_server_post(
            "/decide",
            {
                "game_id": game_id,
                "player_id": player_id,
                "prompt": prompt,
                "timeout_seconds": timeout_seconds,
            },
            timeout_seconds + 5.0,
            require_ok=False,
        )
        elapsed_seconds = time.monotonic() - started
        return AIAdapterResult(
            stdout=str(data.get("stdout") or ""),
            stderr=str(data.get("stderr") or ""),
            returncode=int(data.get("returncode") or 0),
            elapsed_seconds=float(data.get("elapsed_seconds") or elapsed_seconds),
            provider=str(data.get("provider") or self.provider),
            argv=["POST", f"{_agent_server_base_url()}/decide"],
            metadata={
                key: data.get(key)
                for key in (
                    "judge",
                    "judge_history",
                    "judge_mode",
                    "repair_attempted",
                    "selected_lesson_ids",
                    "candidate_lesson_ids",
                    "selector_output",
                    "stage_seconds",
                    "card_text_context_included",
                )
                if key in data
            },
        )


def agent_server_enabled() -> bool:
    return _selected_provider() in {"agent-server", "agent_server", "codex-server", "codex_server"}


def agent_server_init_game(game_id: str, timeout_seconds: float = 30.0) -> dict:
    return _agent_server_post(
        "/init-game",
        {"game_id": game_id, "timeout_seconds": timeout_seconds},
        timeout_seconds + 5.0,
    )


def agent_server_append(game_id: str, role: str, message: str, timeout_seconds: float = 10.0) -> dict:
    return _agent_server_post(
        "/append",
        {
            "game_id": game_id,
            "role": role,
            "message": message,
            "timeout_seconds": timeout_seconds,
        },
        timeout_seconds + 5.0,
    )


def get_ai_adapter(provider: str | None = None) -> AIAdapter:
    selected = _selected_provider(provider)
    if selected in {"agent-server", "agent_server", "codex-server", "codex_server"}:
        return AgentServerAdapter()
    raise RuntimeError(f"不支援的 AI provider：{selected}；本專案目前主路徑只支援 agent-server。")


def probe_provider(provider: str | None = None, timeout_seconds: float = 30.0) -> AIAdapterResult:
    prompt = "\n".join([
        "game_id: probe_game",
        "player_id: P1",
        "first_player: P1",
        "legal_actions: pass",
        "",
        "Probe only. Return exactly:",
        "CONSIDER: probe",
        "COMMAND: pass",
    ])
    return get_ai_adapter(provider).run(prompt, timeout_seconds)


def _agent_server_post(path: str, payload: dict, timeout_seconds: float, require_ok: bool = True) -> dict:
    base_url = _agent_server_base_url()
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if require_ok:
            detail = body.strip()
            raise RuntimeError(f"agent-server {path} failed: HTTP {exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"agent-server unreachable at {base_url}: {exc.reason}") from exc
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"agent-server {path} returned invalid JSON: {body[:200]}") from exc
    if require_ok and int(data.get("returncode") or 0) != 0:
        raise RuntimeError(str(data.get("stderr") or f"agent-server {path} failed"))
    return data


def _agent_server_base_url() -> str:
    return os.environ.get("GCG_AGENT_SERVER_URL", "http://127.0.0.1:8890").rstrip("/")


def _selected_provider(provider: str | None = None) -> str:
    return (provider or os.environ.get("GCG_AI_PROVIDER", "agent-server")).strip().lower()


def _prompt_value(prompt: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", prompt, flags=re.MULTILINE)
    return match.group(1).strip() if match else ""
