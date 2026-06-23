from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from gcg.cards import CardDatabase
from gcg.effects.reference_st01 import ReferenceSt01Interpreter
from gcg.effects.schema_loader import CardEffectSchemaLoader
from gcg.engine.rules_index import RulesIndex


class SchemaCardDatabaseTest(unittest.TestCase):
    def test_default_card_database_reads_schema_metadata(self):
        card_db = CardDatabase()
        card = card_db.get("st01/ST01-001")

        self.assertEqual(card["id"], "ST01-001")
        self.assertEqual(card["name"], "高達")
        self.assertEqual(card["cardType"], "unit")
        self.assertEqual(card["level"], 4)
        self.assertEqual(card["cost"], 3)
        self.assertEqual(card["ap"], 3)
        self.assertEqual(card["hp"], 4)
        self.assertEqual(card["traits"], ["地球聯邦", "WB隊"])
        self.assertEqual(card["link"], ["阿姆羅・雷"])

    def test_schema_rules_provide_command_pilot_designation(self):
        card_db = CardDatabase()
        schema_index = CardEffectSchemaLoader().load()
        rules = RulesIndex(card_db, schema_index=schema_index)

        self.assertEqual(
            rules.pilot_designation("ST01-012"),
            {"name": "隼人・小林", "ap": 0, "hp": 1},
        )

    def test_card_data_env_override_still_reads_json_metadata(self):
        old_value = os.environ.get("GCG_CARD_DATA_ROOT")
        try:
            with tempfile.TemporaryDirectory(prefix="gcg_card_data_") as tmpdir:
                path = Path(tmpdir) / "customCard.json"
                path.write_text(
                    json.dumps({
                        "cards": {
                            "x": {
                                "id": "X-001",
                                "name": "JSON Card",
                                "cardType": "unit",
                                "level": 1,
                                "cost": 0,
                                "ap": 2,
                                "hp": 3,
                            }
                        }
                    }),
                    encoding="utf-8",
                )
                os.environ["GCG_CARD_DATA_ROOT"] = tmpdir

                card_db = CardDatabase()

            self.assertEqual(card_db.source, "json")
            self.assertEqual(card_db.get("X-001")["name"], "JSON Card")
        finally:
            if old_value is None:
                os.environ.pop("GCG_CARD_DATA_ROOT", None)
            else:
                os.environ["GCG_CARD_DATA_ROOT"] = old_value

    def test_reference_st01_pair_condition_matches_schema_traits(self):
        spec = ReferenceSt01Interpreter().interpret({"id": "ST01-002"}, "PAIRING_COMPLETE")

        traits = spec["primitive_steps"][0]["condition"]["traits"]
        self.assertIn("WB隊", traits)


if __name__ == "__main__":
    unittest.main()
