"""Tests for HermesPlayerClient using unittest (mocked subprocess)."""

import io
import json
import subprocess
import unittest
from unittest.mock import patch, MagicMock

from gcg.ai.hermes_player_client import HermesPlayerClient

_MOCK_PAYLOAD = {
    "request_type": "gcg_main_decision",
    "player_id": "P1",
    "legal_commands": ["pass", "play_card st01/ST01-008 0"],
    "viewer_state": {"phase": "main"},
}


class TestHermesPlayerClient(unittest.TestCase):

    # ------------------------------------------------------------------
    # argv construction
    # ------------------------------------------------------------------

    @patch("gcg.ai.hermes_player_client.subprocess.run")
    def test_argv_contains_expected_flags(self, mock_run):
        """Verify the subprocess argv includes all required flags."""
        mock_run.return_value = MagicMock(
            returncode=0, stdout="CONSIDER: test.\nCOMMAND: pass\n", stderr="",
        )
        client = HermesPlayerClient(wrapper="gcg-player", source_tag="gcg-p1")
        client.decide("g001", "P1", _MOCK_PAYLOAD)

        argv = mock_run.call_args[0][0]
        self.assertIn("gcg-player", argv)
        self.assertIn("-t", argv)
        self.assertIn("none", argv)
        self.assertIn("-s", argv)
        self.assertIn("gcg-strategy", argv)
        self.assertIn("--max-turns", argv)
        self.assertIn("1", argv)
        self.assertIn("--source", argv)
        self.assertIn("gcg-p1", argv)
        self.assertIn("-Q", argv)

    # ------------------------------------------------------------------
    # normalization
    # ------------------------------------------------------------------

    @patch("gcg.ai.hermes_player_client.subprocess.run")
    def test_decide_returns_structured_output(self, mock_run):
        """Normalization extracts CONSIDER + COMMAND lines."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="CONSIDER: 先攻有利。\nCOMMAND: choose go_first\n",
            stderr="",
        )
        client = HermesPlayerClient()
        result = client.decide("g001", "P1", _MOCK_PAYLOAD)
        self.assertIn("CONSIDER: 先攻有利。", result)
        self.assertIn("COMMAND: choose go_first", result)

    @patch("gcg.ai.hermes_player_client.subprocess.run")
    def test_normalize_skips_non_structured_lines(self, mock_run):
        """Lines without CONSIDER:/REASON:/COMMAND: prefix are filtered."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="```\nCONSIDER: 保留手牌。\nCOMMAND: pass\n```\n",
            stderr="",
        )
        client = HermesPlayerClient()
        result = client.decide("g001", "P1", _MOCK_PAYLOAD)
        # markdown fences should be stripped
        self.assertNotIn("```", result)
        self.assertIn("CONSIDER: 保留手牌。", result)
        self.assertIn("COMMAND: pass", result)

    # ------------------------------------------------------------------
    # error handling
    # ------------------------------------------------------------------

    @patch("gcg.ai.hermes_player_client.subprocess.run")
    def test_decide_raises_on_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=0, stdout="", stderr="",
        )
        client = HermesPlayerClient()
        with self.assertRaisesRegex(RuntimeError, "empty output"):
            client.decide("g001", "P1", _MOCK_PAYLOAD)

    @patch("gcg.ai.hermes_player_client.subprocess.run")
    def test_decide_raises_on_nonzero_exit(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="something went wrong",
        )
        client = HermesPlayerClient()
        with self.assertRaisesRegex(RuntimeError, "exit code 1"):
            client.decide("g001", "P1", _MOCK_PAYLOAD)

    @patch("gcg.ai.hermes_player_client.subprocess.run")
    def test_decide_raises_on_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=1)
        client = HermesPlayerClient(timeout=1)
        with self.assertRaisesRegex(RuntimeError, "timed out"):
            client.decide("g001", "P1", _MOCK_PAYLOAD)

    @patch("gcg.ai.hermes_player_client.subprocess.run")
    def test_decide_raises_on_wrapper_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        client = HermesPlayerClient(wrapper="/nonexistent/gcg-player")
        with self.assertRaisesRegex(RuntimeError, "not found"):
            client.decide("g001", "P1", _MOCK_PAYLOAD)

    # ------------------------------------------------------------------
    # ai_trace logging
    # ------------------------------------------------------------------

    @patch("gcg.ai.hermes_player_client.subprocess.run")
    def test_ai_trace_writer_is_called(self, mock_run):
        """When ai_trace_writer is provided, append_trace is called."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="CONSIDER: test.\nCOMMAND: pass\n",
            stderr="",
        )
        trace_writer = MagicMock()
        client = HermesPlayerClient(ai_trace_writer=trace_writer)
        client.decide("g001", "P1", _MOCK_PAYLOAD)

        trace_writer.append_trace.assert_called_once()
        call_kwargs = trace_writer.append_trace.call_args.kwargs
        self.assertEqual(call_kwargs["game_id"], "g001")
        self.assertEqual(call_kwargs["player_id"], "P1")
        self.assertIn("normalized_reply", call_kwargs)
        self.assertIn("raw_reply", call_kwargs)
        self.assertIn("prompt", call_kwargs)

    # ------------------------------------------------------------------
    # prompt size limit
    # ------------------------------------------------------------------

    def test_decide_raises_on_oversized_prompt(self):
        """Prompts exceeding _PROMPT_SIZE_LIMIT (100KB) raise immediately."""
        big_payload = {"data": "x" * 100_000}
        client = HermesPlayerClient()
        with self.assertRaisesRegex(RuntimeError, "too large"):
            client.decide("g001", "P1", big_payload)


# ------------------------------------------------------------------
# P1/P2 source_tag isolation
# ------------------------------------------------------------------

class TestPlayerIsolation(unittest.TestCase):

    def test_p1_and_p2_have_different_source_tags(self):
        """P1 and P2 use distinct source_tag values to avoid session
        collision in Hermes session store."""
        p1 = HermesPlayerClient(source_tag="gcg-p1")
        p2 = HermesPlayerClient(source_tag="gcg-p2")
        self.assertEqual(p1.source_tag, "gcg-p1")
        self.assertEqual(p2.source_tag, "gcg-p2")
        self.assertNotEqual(p1.source_tag, p2.source_tag)


class TestBuildPrompt(unittest.TestCase):

    def test_build_prompt_contains_player_id(self):
        prompt = HermesPlayerClient._build_prompt("P2", _MOCK_PAYLOAD)
        self.assertIn("P2", prompt)
        self.assertIn("legal_commands", prompt)
        self.assertIn("CONSIDER:", prompt)
        self.assertIn("COMMAND:", prompt)

    def test_build_prompt_contains_json_payload(self):
        prompt = HermesPlayerClient._build_prompt("P1", _MOCK_PAYLOAD)
        self.assertIn("play_card st01/ST01-008 0", prompt)
        self.assertIn("viewer_state", prompt)


class TestNormalize(unittest.TestCase):

    def test_normalize_keeps_consider_and_command(self):
        raw = "CONSIDER: 理由。\nCOMMAND: pass\n"
        result = HermesPlayerClient._normalize(raw)
        self.assertIn("CONSIDER: 理由。", result)
        self.assertIn("COMMAND: pass", result)

    def test_normalize_removes_extra_lines(self):
        raw = "思考過程...\nCONSIDER: 測試。\nCOMMAND: pass\n"
        result = HermesPlayerClient._normalize(raw)
        self.assertNotIn("思考過程", result)

    def test_normalize_fallback_to_first_line(self):
        raw = "some raw output"
        result = HermesPlayerClient._normalize(raw)
        self.assertEqual(result, "some raw output")

    def test_normalize_empty(self):
        result = HermesPlayerClient._normalize("")
        self.assertEqual(result, "")

    def test_normalize_supports_reason_alias(self):
        raw = "REASON: 因為...\nCOMMAND: pass\n"
        result = HermesPlayerClient._normalize(raw)
        self.assertIn("REASON:", result)
        self.assertIn("COMMAND:", result)


if __name__ == "__main__":
    unittest.main()
