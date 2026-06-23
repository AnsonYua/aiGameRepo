"""Minimal OpenAI-compatible chat client（DeepSeek 介面）。"""

from __future__ import annotations

import json
from urllib import error, request

from .. import config


class LlmError(RuntimeError):
    pass


class LlmClient:
    def __init__(self, api_key=None, base_url=None, model=None, timeout_seconds=None):
        settings = config.llm_settings()
        self.api_key = api_key or settings["api_key"]
        self.base_url = (base_url or settings["base_url"]).rstrip("/")
        self.model = model or settings["model"]
        self.timeout_seconds = timeout_seconds or settings["timeout_seconds"]

    def chat(self, system_prompt, user_prompt, temperature=0.2):
        if not self.api_key:
            raise LlmError("Missing GCG_DEEPSEEK_API_KEY for LlmClient.")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
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
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                raw_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LlmError(f"LLM request failed with HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise LlmError(f"LLM request failed: {exc.reason}") from exc
        return self._extract_text(json.loads(raw_body))

    def _extract_text(self, response_json):
        choices = response_json.get("choices") or []
        if choices:
            choice = choices[0] or {}
            text = choice.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            message = choice.get("message") or {}
            content = message.get("content", "")
            if isinstance(content, list):
                parts = [
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") in {"text", "output_text"}
                ]
                content = "".join(parts)
            if isinstance(content, str) and content.strip():
                return content.strip()
        raise LlmError(
            "LLM response did not contain text: "
            f"{json.dumps(response_json, ensure_ascii=False)[:800]}"
        )
