from __future__ import annotations

import unittest

from gcg.cards import CardDatabase
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


if __name__ == "__main__":
    unittest.main()
