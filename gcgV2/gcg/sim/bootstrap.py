"""Wiring helpers：組裝完整 simulator stack。"""

from __future__ import annotations

from .. import config
from ..ai.llm_client import LlmClient
from ..ai.player_client import AiPlayerClient
from ..ai.prompt_builder import PromptBuilder
from ..cards import CardDatabase, DeckConfig
from ..effects.dictionary import EffectDictionary
from ..effects.interpreter import LlmEffectInterpreter
from ..effects.reference_st01 import ReferenceSt01Interpreter
from ..engine.action_enumerator import ActionEnumerator
from ..engine.rules_index import RulesIndex
from ..engine.runtime import Runtime
from ..engine.state_store import StateStore
from ..engine.viewer import ViewerStateBuilder
from ..gamelog.gameplay_logger import GameplayLogger
from ..gamelog.writers import AiTraceWriter, GameplayYamlWriter, SnapshotWriter
from .runner import SimulatorRunner
from .scripted_player import ScriptedPlayer


def build_simulator(
    players="llm",
    interpreter="llm",
    output_root=None,
    max_steps=400,
):
    """組裝 simulator。

    players: "llm"（正式）或 "scripted"（測試/離線）
    interpreter: "llm"（正式）或 "reference"（測試/離線，僅 ST01）
    """
    output_root = output_root or config.output_root()
    card_database = CardDatabase()
    deck_config = DeckConfig()
    rules_index = RulesIndex(card_database)
    snapshot_writer = SnapshotWriter(output_root)
    state_store = StateStore(
        card_database=card_database,
        deck_config=deck_config,
        snapshot_writer=snapshot_writer,
    )
    yaml_writer = GameplayYamlWriter(output_root)
    gameplay_logger = GameplayLogger(yaml_writer=yaml_writer, state_store=state_store)
    ai_trace_writer = AiTraceWriter(output_root)

    dictionary = EffectDictionary()
    if interpreter == "llm":
        effect_interpreter = LlmEffectInterpreter(
            llm_client=LlmClient(),
            dictionary=dictionary,
            trace_writer=ai_trace_writer,
        )
    elif interpreter == "reference":
        effect_interpreter = ReferenceSt01Interpreter(dictionary)
    else:
        raise ValueError(f"unknown interpreter mode: {interpreter}")

    runtime = Runtime(
        state_store=state_store,
        card_database=card_database,
        rules_index=rules_index,
        effect_interpreter=effect_interpreter,
        gameplay_logger=gameplay_logger,
    )
    action_enumerator = ActionEnumerator(
        state_store=state_store,
        card_database=card_database,
        rules_index=rules_index,
        effect_engine=runtime.effect_engine,
        interpreter=effect_interpreter,
    )

    if players == "llm":
        llm_client = LlmClient()
        player_map = {
            "P1": AiPlayerClient(llm_client=llm_client, ai_trace_writer=ai_trace_writer),
            "P2": AiPlayerClient(llm_client=llm_client, ai_trace_writer=ai_trace_writer),
        }
    elif players == "scripted":
        player_map = {"P1": ScriptedPlayer(), "P2": ScriptedPlayer()}
    else:
        raise ValueError(f"unknown players mode: {players}")

    return SimulatorRunner(
        runtime=runtime,
        state_store=state_store,
        action_enumerator=action_enumerator,
        viewer_builder=ViewerStateBuilder(),
        prompt_builder=PromptBuilder(card_db=card_database, rules_index=rules_index),
        players=player_map,
        gameplay_logger=gameplay_logger,
        ai_trace_writer=ai_trace_writer,
        max_steps=max_steps,
    )
