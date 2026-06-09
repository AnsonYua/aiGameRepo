"""
AI player client for GCG V2.

This layer owns player-isolated sessions, prompt assembly, and lesson
injection. It does not validate strategy or mutate game state.
"""

import json
import os
from urllib import error, request


def _load_local_env():
    """
    Load simple KEY=VALUE pairs from a nearby .env file when present.

    Keep this dependency-free for local testing.
    """
    search_paths = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"),
    ]

    for path in search_paths:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("\"'")
                os.environ.setdefault(key, value)
        break


class InMemorySessionStore:
    """
    Simple per-process session store keyed by game and player.
    """

    def __init__(self):
        self._sessions = {}

    def get(self, game_id, player_id):
        return self._sessions.get((game_id, player_id))

    def save(self, game_id, player_id, session):
        self._sessions[(game_id, player_id)] = session
        return session


class FilePromptLoader:
    """
    Load base player prompt from disk, with a stable built-in fallback.
    """

    def __init__(self, prompt_path=None):
        self.prompt_path = prompt_path or os.getenv("GCG_PLAYER_PROMPT_PATH")

    def load_player_prompt(self, player_id):
        prompt_parts = [self._default_prompt(player_id)]
        if self.prompt_path and os.path.exists(self.prompt_path):
            with open(self.prompt_path, "r", encoding="utf-8") as handle:
                prompt_parts.append(handle.read().strip())
        return "\n\n".join(part for part in prompt_parts if part)

    def _default_prompt(self, player_id):
        return (
            f"你是 GCG 對戰玩家 {player_id}。\n"
            "你只能根據 public-safe viewer state 做決策。\n"
            "你只能輸出一行單一步 command。\n"
            "不要輸出解釋、不要輸出 JSON、不要輸出 markdown。"
        )


class NoopLessonSelector:
    """
    Default selector for teams that have not wired lesson retrieval yet.
    """

    def select(self, player_id, viewer_bundle, limit=3):
        del player_id
        del viewer_bundle
        del limit
        return []


class AiPlayerClient:
    """
    High-level AI wrapper used by simulator runner.
    """

    def __init__(
        self,
        prompt_loader=None,
        lesson_selector=None,
        session_store=None,
        api_key=None,
        base_url=None,
        model=None,
        timeout_seconds=60,
    ):
        _load_local_env()
        self.prompt_loader = prompt_loader or FilePromptLoader()
        self.lesson_selector = lesson_selector or NoopLessonSelector()
        self.session_store = session_store or InMemorySessionStore()
        self.api_key = api_key or os.getenv("GCG_DEEPSEEK_API_KEY", "")
        self.base_url = (
            base_url
            or os.getenv("GCG_DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        ).rstrip("/")
        self.model = model or os.getenv("GCG_DEEPSEEK_MODEL", "deepseek-v4-pro")
        self.timeout_seconds = timeout_seconds

    def ensure_player_session(self, game_id, player_id):
        """
        Ensure each player owns one isolated AI session per game.
        """
        existing = self.session_store.get(game_id=game_id, player_id=player_id)
        if existing is not None:
            return existing

        session = {
            "session_id": f"{game_id}:{player_id}",
            "game_id": game_id,
            "player_id": player_id,
            "model": self.model,
            "system_prompt": self.prompt_loader.load_player_prompt(player_id),
        }
        return self.session_store.save(
            game_id=game_id,
            player_id=player_id,
            session=session,
        )

    def decide(self, game_id, player_id, viewer_bundle):
        """
        Build one decision prompt and return one command string.
        """
        session = self.ensure_player_session(game_id=game_id, player_id=player_id)
        lessons = self.lesson_selector.select(
            player_id=player_id,
            viewer_bundle=viewer_bundle,
            limit=3,
        )
        prompt = self._build_decision_prompt(
            game_id=game_id,
            player_id=player_id,
            viewer_bundle=viewer_bundle,
            lessons=lessons,
        )
        raw_text = self._generate_command(
            session=session,
            prompt=prompt,
        )
        return self._normalize_command(raw_text)

    def _build_decision_prompt(self, game_id, player_id, viewer_bundle, lessons):
        viewer_state = viewer_bundle.get("viewer_state", {})

        return {
            "request_type": "gcg_decision",
            "game_id": game_id,
            "player_id": player_id,
            "instructions": [
                "只輸出單一步 command。",
                "不要輸出說明。",
                "若 viewer_state.pending_choice.visible 為 true，輸出 choose <option_id>。",
                "若沒有更好行動且規則允許，可以輸出 pass。",
            ],
            "lessons": lessons,
            "viewer_state": viewer_state,
            "viewer_markdown": viewer_bundle.get("markdown", ""),
            "output_contract": {
                "format": "single_command_text",
                "examples": [
                    "choose go_first",
                    "choose go_second",
                    "choose keep",
                    "choose redraw",
                    "pass",
                ],
            },
        }

    def _generate_command(self, session, prompt):
        if not self.api_key:
            raise RuntimeError("Missing GCG_DEEPSEEK_API_KEY for AiPlayerClient.")

        payload = {
            "model": session.get("model", self.model),
            "messages": [
                {
                    "role": "system",
                    "content": session["system_prompt"],
                },
                {
                    "role": "user",
                    "content": json.dumps(prompt, ensure_ascii=False, indent=2),
                },
            ],
            "temperature": 0.2,
        }
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=body,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(
                http_request,
                timeout=self.timeout_seconds,
            ) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                f"DeepSeek request failed with HTTP {exc.code}: {detail}"
            ) from exc
        except error.URLError as exc:
            raise RuntimeError(f"DeepSeek request failed: {exc.reason}") from exc

        return self._extract_text(json.loads(raw_body))

    def _extract_text(self, response_json):
        choices = response_json.get("choices") or []
        if choices:
            message = choices[0].get("message") or {}
            content = message.get("content", "")
            if isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                content = "".join(parts)
            if isinstance(content, str) and content.strip():
                return content.strip()

        output = response_json.get("output") or []
        for item in output:
            if not isinstance(item, dict):
                continue
            contents = item.get("content") or []
            for content in contents:
                if isinstance(content, dict) and content.get("type") == "output_text":
                    text = content.get("text", "").strip()
                    if text:
                        return text

        raise RuntimeError("DeepSeek response did not contain command text.")

    def _normalize_command(self, raw_text):
        if not isinstance(raw_text, str):
            raise RuntimeError(
                "AI provider returned non-text command: "
                f"{json.dumps(raw_text, ensure_ascii=False)}"
            )

        command = raw_text.strip()
        if not command:
            raise RuntimeError("AI provider returned empty command text.")

        first_line = command.splitlines()[0].strip()
        if not first_line:
            raise RuntimeError("AI provider returned blank first command line.")
        return first_line
