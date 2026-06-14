"""Shared test helpers：組裝測試用 stack（reference interpreter + temp output）。"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

GCGV2_ROOT = Path(__file__).resolve().parents[1]
if str(GCGV2_ROOT) not in sys.path:
    sys.path.insert(0, str(GCGV2_ROOT))

from gcg.ai.prompt_builder import PromptBuilder  # noqa: E402
from gcg.cards import CardDatabase, DeckConfig  # noqa: E402
from gcg.effects.dictionary import EffectDictionary  # noqa: E402
from gcg.effects.reference_st01 import ReferenceSt01Interpreter  # noqa: E402
from gcg.engine.action_enumerator import ActionEnumerator  # noqa: E402
from gcg.engine.command_parser import CommandParser  # noqa: E402
from gcg.engine.rules_index import RulesIndex  # noqa: E402
from gcg.engine.runtime import Runtime  # noqa: E402
from gcg.engine.state_store import StateStore  # noqa: E402
from gcg.engine.viewer import ViewerStateBuilder  # noqa: E402
from gcg.gamelog.gameplay_logger import GameplayLogger  # noqa: E402
from gcg.gamelog.writers import AiTraceWriter, GameplayYamlWriter, SnapshotWriter  # noqa: E402
from gcg.sim.runner import SimulatorRunner  # noqa: E402
from gcg.sim.scripted_player import ScriptedPlayer  # noqa: E402


class TestStack:
    def __init__(self, output_root=None):
        self.output_root = Path(output_root or tempfile.mkdtemp(prefix="gcgv2_test_"))
        self.card_database = CardDatabase()
        self.deck_config = DeckConfig()
        self.rules_index = RulesIndex(self.card_database)
        self.dictionary = EffectDictionary()
        self.interpreter = ReferenceSt01Interpreter(self.dictionary)
        self.state = StateStore(
            card_database=self.card_database,
            deck_config=self.deck_config,
            snapshot_writer=SnapshotWriter(self.output_root),
        )
        self.yaml_writer = GameplayYamlWriter(self.output_root)
        self.logger = GameplayLogger(yaml_writer=self.yaml_writer, state_store=self.state)
        self.runtime = Runtime(
            state_store=self.state,
            card_database=self.card_database,
            rules_index=self.rules_index,
            effect_interpreter=self.interpreter,
            gameplay_logger=self.logger,
        )
        self.enumerator = ActionEnumerator(
            state_store=self.state,
            card_database=self.card_database,
            rules_index=self.rules_index,
            effect_engine=self.runtime.effect_engine,
            interpreter=self.interpreter,
        )
        self.parser = CommandParser()

    def new_game(self):
        game_id = self.state.create_game_shell()
        self.logger.open_game(game_id)
        return game_id

    def start_midgame(self, active_player="P1", turn=3):
        """快速建立一個進入 main phase 的對局（雙方資源 5，跳過開局流程）。"""
        self.new_game()
        state = self.state.get_state()
        state["opening"]["first_player"] = "P1"
        state["opening"]["second_player"] = "P2"
        state["opening"]["mulligan_done"] = {"P1": True, "P2": True}
        self.state.shuffle_main_deck("P1")
        self.state.shuffle_main_deck("P2")
        self.state.draw_cards("P1", 5)
        self.state.draw_cards("P2", 5)
        self.state.place_shields("P1", 6)
        self.state.place_shields("P2", 6)
        self.state.deploy_ex_base("P1")
        self.state.deploy_ex_base("P2")
        for player_id in ("P1", "P2"):
            self.state.get_player_state(player_id)["resources"]["active"] = 5
        self.state.set_turn(turn)
        self.state.set_active_player(active_player)
        self.state.set_priority_player(active_player)
        self.state.set_phase("main")
        self.state.set_step(None)
        return self.state.get_game_id()

    def set_hand(self, player_id, card_ids):
        self.state.get_player_state(player_id)["hand"] = list(card_ids)

    def put_unit(self, player_id, card_id, slot_index, status="active", turns_on_field=1):
        keywords = self.rules_index.keywords(card_id)
        self.state._place_unit(player_id, card_id, slot_index, keywords=keywords)
        slot = self.state.get_slot(player_id, slot_index)
        slot["status"] = status
        slot["turns_on_field"] = turns_on_field
        return slot

    def parse(self, text, player_id):
        return self.parser.parse(text, player_id)

    def build_full_simulator(self, max_steps=400):
        return SimulatorRunner(
            runtime=self.runtime,
            state_store=self.state,
            action_enumerator=self.enumerator,
            viewer_builder=ViewerStateBuilder(),
            prompt_builder=PromptBuilder(),
            players={"P1": ScriptedPlayer(), "P2": ScriptedPlayer()},
            gameplay_logger=self.logger,
            ai_trace_writer=AiTraceWriter(self.output_root),
            command_parser=self.parser,
            max_steps=max_steps,
        )
