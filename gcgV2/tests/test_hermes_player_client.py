"""Tests for HermesPlayerClient (mocked subprocess)."""

import pytest
from gcg.ai.hermes_player_client import HermesPlayerClient

MOCK_PAYLOAD = {
    "request_type": "gcg_main_decision",
    "player_id": "P1",
    "legal_commands": ["pass", "play_card st01/ST01-008 0"],
    "viewer_state": {"phase": "main"},
}


def test_decide_does_not_crash():
    client = HermesPlayerClient(wrapper="echo")
    result = client.decide("g001", "P1", MOCK_PAYLOAD)
    assert isinstance(result, str)


def test_decide_raises_on_empty_output():
    client = HermesPlayerClient(wrapper="true")
    with pytest.raises(RuntimeError, match="empty output"):
        client.decide("g001", "P1", MOCK_PAYLOAD)


def test_decide_timeout():
    helper = __file__.rsplit("/", 1)[0] + "/_hang_helper.py"
    client = HermesPlayerClient(wrapper=helper, timeout=1)
    with pytest.raises(RuntimeError, match="timed out"):
        client.decide("g001", "P1", MOCK_PAYLOAD)


def test_decide_wrapper_not_found():
    client = HermesPlayerClient(wrapper="/nonexistent/xyz")
    with pytest.raises(RuntimeError, match="not found"):
        client.decide("g001", "P1", MOCK_PAYLOAD)
