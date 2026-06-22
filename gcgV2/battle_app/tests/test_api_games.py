from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


BATTLE_APP_ROOT = Path(__file__).resolve().parents[1]
GCGV2_ROOT = BATTLE_APP_ROOT.parent
if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))
if str(BATTLE_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(BATTLE_APP_ROOT))

from battle_app.api import games as api_games  # noqa: E402


class ApiGamesTest(unittest.TestCase):
    def test_card_detail_does_not_initialize_mongo_store(self):
        request = object.__new__(api_games.handler)
        request.path = "/api/games/missing-game/card?card_id=st01/ST01-008"
        sent = []
        request._send_json = lambda payload, status=200: sent.append((payload, status))

        with patch.object(api_games, "get_store", side_effect=AssertionError("should not touch Mongo")):
            request._handle_get()

        self.assertEqual(sent[0][1], 200)
        self.assertEqual(sent[0][0]["id"], "ST01-008")


if __name__ == "__main__":
    unittest.main()
