#!/usr/bin/env python3
"""Run a local GCG V2 AI-vs-AI simulation.

Examples:

    # 正式：LLM player + LLM effect interpreter（需要 GCG_DEEPSEEK_API_KEY）
    python3 run_simulator.py

    # 離線：scripted player + reference interpreter（不需要 API key，僅 ST01）
    python3 run_simulator.py --players scripted --interpreter reference
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gcg.sim.bootstrap import build_simulator  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Run local gcgV2 AI-vs-AI simulator")
    parser.add_argument("--players", choices=("llm", "scripted", "hermes"), default="llm")
    parser.add_argument("--interpreter", choices=("llm", "reference"), default="llm")
    parser.add_argument("--first-player", choices=("P1", "P2"))
    parser.add_argument("--decision-player", choices=("P1", "P2"))
    parser.add_argument("--max-steps", type=int, default=400)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main():
    logging.basicConfig(
        level=getattr(logging, os.getenv("GCG_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)
    simulator = build_simulator(
        players=args.players,
        interpreter=args.interpreter,
        max_steps=args.max_steps,
    )
    simulator.start_game(
        first_player=args.first_player,
        decision_player=args.decision_player,
    )
    result = simulator.run()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
