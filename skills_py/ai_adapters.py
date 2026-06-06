import os
import shlex
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.parent.absolute()


CODEX_GCG_PROMPT_PREFIX = """You are the GCG AI player for a card game runtime.

You must not edit files, inspect hidden state files, or call tools. Decide only from
the visible runtime display below.

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
"""


@dataclass
class AIAdapterResult:
    stdout: str
    stderr: str = ""
    returncode: int = 0
    elapsed_seconds: float = 0.0
    provider: str = ""
    argv: list[str] | None = None


class AIAdapter:
    provider = "base"

    def run(self, prompt: str, timeout_seconds: float) -> AIAdapterResult:
        raise NotImplementedError


def _argv_from_env(env_name: str, default: list[str]) -> list[str]:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    return shlex.split(raw)


def _gatekeeper_hint(returncode: int, stdout: str, stderr: str) -> str:
    if returncode == -9 and not stdout.strip() and not stderr.strip():
        return "process was killed with SIGKILL; on macOS this can mean Gatekeeper blocked the CLI binary."
    return ""


class OpencodeAdapter(AIAdapter):
    provider = "opencode"

    def run(self, prompt: str, timeout_seconds: float) -> AIAdapterResult:
        argv = _argv_from_env(
            "GCG_AI_OPENCODE_ARGV",
            ["opencode", "run", "--agent", os.environ.get("GCG_AI_OPENCODE_AGENT", "gcg-ai-player")],
        )
        started = time.monotonic()
        completed = subprocess.run(
            [*argv, prompt],
            cwd=str(PROJECT_ROOT),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
        )
        elapsed_seconds = time.monotonic() - started
        stderr = completed.stderr
        hint = _gatekeeper_hint(completed.returncode, completed.stdout, completed.stderr)
        if hint:
            stderr = hint
        return AIAdapterResult(
            stdout=completed.stdout,
            stderr=stderr,
            returncode=completed.returncode,
            elapsed_seconds=elapsed_seconds,
            provider=self.provider,
            argv=[*argv, "<prompt>"],
        )


class CodexCliAdapter(AIAdapter):
    provider = "codex"

    def run(self, prompt: str, timeout_seconds: float) -> AIAdapterResult:
        argv = _argv_from_env(
            "GCG_AI_CODEX_ARGV",
            [
                "codex",
                "exec",
                "--color",
                "never",
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--skip-git-repo-check",
                "-c",
                "approval_policy=never",
            ],
        )
        codex_prompt = "\n\n".join([CODEX_GCG_PROMPT_PREFIX, prompt])
        output_path = ""
        if "-o" not in argv and "--output-last-message" not in argv:
            temp = tempfile.NamedTemporaryFile(prefix="gcg_codex_", suffix=".txt", delete=False)
            output_path = temp.name
            temp.close()
            argv = [*argv, "--output-last-message", output_path]

        prompt_mode = os.environ.get("GCG_AI_CODEX_PROMPT_MODE", "stdin").strip().lower()
        if prompt_mode == "argv":
            run_argv = [*argv, codex_prompt]
            stdin_text = None
        else:
            run_argv = [*argv, "-"]
            stdin_text = codex_prompt

        started = time.monotonic()
        try:
            completed = subprocess.run(
                run_argv,
                cwd=str(PROJECT_ROOT),
                text=True,
                input=stdin_text,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            stdout = completed.stdout
            stderr = completed.stderr
            returncode = completed.returncode
            if output_path:
                path = Path(output_path)
                if path.exists():
                    final_message = path.read_text(encoding="utf-8").strip()
                    if final_message:
                        stdout = final_message
        finally:
            if output_path:
                try:
                    Path(output_path).unlink()
                except FileNotFoundError:
                    pass
        elapsed_seconds = time.monotonic() - started
        hint = _gatekeeper_hint(returncode, stdout, stderr)
        if hint:
            stderr = hint
        return AIAdapterResult(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            elapsed_seconds=elapsed_seconds,
            provider=self.provider,
            argv=[*argv, "<prompt>" if prompt_mode == "argv" else "-"],
        )


class ClaudeCodeAdapter(AIAdapter):
    provider = "claude"

    def run(self, prompt: str, timeout_seconds: float) -> AIAdapterResult:
        raise RuntimeError("claude provider placeholder only; implement Claude Code adapter in the next phase.")


def get_ai_adapter(provider: str | None = None) -> AIAdapter:
    selected = (provider or os.environ.get("GCG_AI_PROVIDER", "opencode")).strip().lower()
    if selected == "opencode":
        return OpencodeAdapter()
    if selected in {"codex", "codex-cli", "codex_cli"}:
        return CodexCliAdapter()
    if selected in {"claude", "claude-code", "claude_code"}:
        return ClaudeCodeAdapter()
    raise RuntimeError(f"未知 AI provider：{selected}")


def probe_provider(provider: str | None = None, timeout_seconds: float = 30.0) -> AIAdapterResult:
    prompt = "\n".join([
        "player_id: P1",
        "first_player: P1",
        "legal_actions: pass",
        "",
        "Probe only. Return exactly:",
        "CONSIDER: probe",
        "COMMAND: pass",
    ])
    return get_ai_adapter(provider).run(prompt, timeout_seconds)
