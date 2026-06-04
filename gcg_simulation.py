#!/usr/bin/env python3
import argparse
import atexit
import json
import os
import readline
import shutil
import subprocess
import sys
import time
import socket
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).parent.absolute()


def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


def check_opencode():
    if not shutil.which("opencode"):
        print("Error: 'opencode' CLI not found. Please install opencode first.")
        sys.exit(1)


def parse_run_output(output: str) -> str:
    text = output.strip()
    if not text:
        return ""
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            for key in ("content", "response", "text", "message", "output"):
                if key in data:
                    val = data[key]
                    if isinstance(val, str):
                        return val
                    if isinstance(val, dict):
                        for k2 in ("content", "text", "message"):
                            if k2 in val:
                                return str(val[k2])
            return json.dumps(data, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        pass
    return text


class GCGSimulation:
    def __init__(self, p1_mode="human", p2_mode="ai"):
        self.p1_mode = p1_mode
        self.p2_mode = p2_mode
        self.server_process = None
        self.port = None
        self.server_started = False

        self.orchestrator_started = False
        self.ai_player_started = False

        self.conversation_log = []
        self.game_id = None
        self.state = None
        self.step_count = 0

        atexit.register(self.cleanup)

    def cleanup(self):
        if self.server_process:
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
            self.server_process = None

    def _ensure_pw_env(self):
        env = os.environ.copy()
        env["OPENCODE_SERVER_PASSWORD"] = ""
        return env

    def start_server(self):
        self.port = find_free_port()
        env = self._ensure_pw_env()
        self.server_process = subprocess.Popen(
            ["opencode", "serve", "--port", str(self.port)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(3)
        self.server_started = True
        print(f"  Server started on port {self.port}")

    def _run_opencode(self, message, agent=None, use_continue=False):
        cmd = ["opencode", "run", message]
        if use_continue:
            cmd.append("-c")
        cmd.extend(["--attach", f"http://127.0.0.1:{self.port}", "--format", "json"])
        if agent:
            cmd.extend(["--agent", agent])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                env=self._ensure_pw_env(),
            )
            return result.stdout
        except subprocess.TimeoutExpired:
            print("  ! Command timed out after 300s")
            return None

    def _orchestrator(self, command):
        raw = self._run_opencode(command, use_continue=self.orchestrator_started)
        self.orchestrator_started = True
        parsed = parse_run_output(raw) if raw else ""
        self.conversation_log.append({"role": "orchestrator", "cmd": command, "resp": parsed})
        return parsed

    def _ai_player(self, message="decide"):
        raw = self._run_opencode(message, agent="gcg-ai-player", use_continue=self.ai_player_started)
        self.ai_player_started = True
        parsed = parse_run_output(raw) if raw else ""
        return parsed

    def _read_game_id(self):
        path = PROJECT_ROOT / ".gcg_active_game"
        if path.exists():
            self.game_id = path.read_text().strip()
            return self.game_id
        return None

    def _read_game_state(self):
        if not self.game_id:
            if not self._read_game_id():
                return None
        path = PROJECT_ROOT / "game-states" / self.game_id / "gameState.md"
        if path.exists():
            import yaml
            try:
                content = path.read_text()
                self.state = yaml.safe_load(content)
                return self.state
            except Exception:
                return None
        return None

    def _phase_info(self):
        if not self.state:
            return None, None, None, None, None
        return (
            self.state.get("phase"),
            self.state.get("step"),
            self.state.get("priority"),
            self.state.get("game_over", False),
            self.state.get("winner"),
        )

    def _current_player_mode(self, priority):
        if priority == "P1":
            return self.p1_mode
        if priority == "P2":
            return self.p2_mode
        return None

    def run(self):
        check_opencode()
        print("╔" + "═" * 62 + "╗")
        print(f"║  GCG 模擬器 — 零邏輯協調層                               ║")
        print(f"║  P1={self.p1_mode.upper():5}  P2={self.p2_mode.upper():5}                                   ║")
        print("║  輸入 help 查看指令，exit 離開                                ║")
        print("╚" + "═" * 62 + "╝")
        self.start_server()

        print("  發送 start game 至 orchestrator...")
        self._orchestrator("start game")
        time.sleep(2)
        self._read_game_id()

        while True:
            if not self._read_game_state():
                time.sleep(1)
                continue

            phase, step, priority, game_over, winner = self._phase_info()

            if game_over:
                print(f"\n  遊戲結束 — 勝者：{winner}")
                self._save_replay(winner)
                break

            mode = self._current_player_mode(priority)

            if phase == "pre-game":
                if mode == "ai":
                    cmd = self._ai_player()
                    self.conversation_log.append({"role": "ai", "cmd": cmd})
                else:
                    cmd = self._read_human()
                if cmd:
                    self._orchestrator(cmd)

            elif phase == "start":
                self._orchestrator("pass")

            elif phase == "draw":
                self._orchestrator("draw")

            elif phase == "resource":
                self._orchestrator("resource")

            elif phase == "main":
                if mode == "ai":
                    cmd = self._ai_player()
                    self.conversation_log.append({"role": "ai", "cmd": cmd})
                else:
                    cmd = self._read_human()
                if cmd:
                    self._orchestrator(cmd)

            elif phase == "battle":
                if step in ("damage", "battle_end"):
                    time.sleep(0.3)
                    continue
                if mode == "ai":
                    cmd = self._ai_player()
                    self.conversation_log.append({"role": "ai", "cmd": cmd})
                else:
                    cmd = self._read_human()
                if cmd:
                    self._orchestrator(cmd)

            elif phase == "end":
                if step == "cleanup":
                    self._orchestrator("pass")
                    continue
                if mode == "ai":
                    cmd = self._ai_player()
                    self.conversation_log.append({"role": "ai", "cmd": cmd})
                else:
                    cmd = self._read_human()
                if cmd:
                    self._orchestrator(cmd)

            else:
                time.sleep(1)

            self.step_count += 1

    def _read_human(self):
        while True:
            try:
                cmd = input("  > ").strip()
                if not cmd:
                    continue
                if cmd == "help":
                    self._print_help()
                    continue
                if cmd == "exit":
                    self.cleanup()
                    sys.exit(0)
                if cmd == "log":
                    self._print_log()
                    continue
                if cmd == "replay":
                    self._save_replay(None)
                    continue
                return cmd
            except (KeyboardInterrupt, EOFError):
                print()
                self.cleanup()
                sys.exit(0)

    def _print_help(self):
        print("""
遊戲指令：
  pass / end turn          讓過 / 結束回合
  draw                     抽牌
  resource                 部署資源
  keep / redraw            保留 / 重抽（調度）
  play/deploy <card_id>    出牌 / 部署卡牌
  attack <slot>            宣告攻擊
  block <slot>             宣告阻擋
  concede                  投降

系統指令：
  help                     顯示此說明
  log                      顯示對話記錄
  replay                   立即儲存重播
  exit                     離開""")

    def _print_log(self):
        print(f"\n  對話記錄（{len(self.conversation_log)} 筆）：")
        for i, entry in enumerate(self.conversation_log):
            role = entry.get("role", "orchestrator")
            cmd = entry.get("cmd", "")
            resp = entry.get("resp", "")
            print(f"  [{i+1}] {role.upper()}：{cmd}")
            if resp:
                print(f"       ← {resp}")

    def _shield_count(self, player):
        shields = player.get("shields")
        if isinstance(shields, list):
            return len(shields)
        if isinstance(shields, int):
            return shields
        return 0

    def _save_replay(self, winner):
        state = self._read_game_state()
        if not state:
            state = self.state or {}

        ts = datetime.now()
        lines = []
        lines.append("=" * 64)
        lines.append("  GCG 牌局重播")
        lines.append("=" * 64)
        lines.append("")
        lines.append(f"日期：        {ts.strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"勝者：      {winner or state.get('winner', 'N/A')}")
        lines.append(f"總回合數：  {state.get('turn', 0)}")
        lines.append(f"先手玩家：{state.get('first_player', 'N/A')}")
        lines.append("")
        lines.append("─" * 56)
        lines.append("  戰鬥記錄")
        lines.append("─" * 56)
        lines.append("")

        for entry in state.get("battle_log", []):
            lines.append(f"  {entry}")

        lines.append("")
        lines.append("─" * 56)
        lines.append("  最終統計")
        lines.append("─" * 56)
        lines.append("")

        for p_key, label in [("p1", "P1"), ("p2", "P2")]:
            pl = state.get(p_key, {})
            lines.append(f"  {label}：")
            base = pl.get("base", {})
            hp = base.get("hp", 0) - base.get("damage", 0)
            status = "存活" if base.get("alive") else "破壞"
            lines.append(f"    基地：  {base.get('card_id', 'EX-BASE')} HP={hp}/{base.get('hp', 0)}（{status}）")
            lines.append(f"    盾牌：{self._shield_count(pl)}")
            hand = pl.get("hand_cards", [])
            lines.append(f"    手牌：   {len(hand)}張")
            lines.append(f"    牌庫：   {pl.get('deck_count', 0)}")
            res = pl.get("resources", {})
            lines.append(f"    資源：    直立={res.get('active', 0)} 橫置={res.get('rested', 0)} EX={res.get('ex', 0)}")
            ba = pl.get("battle_area", [])
            units = [s for s in ba if s.get("unit_id")]
            lines.append(f"    戰區： {len(units)}個單位")
            for s in ba:
                uid = s.get("unit_id")
                if uid:
                    st = s.get("status")
                    st_t = "直立" if st == "active" else "橫置" if st == "rested" else (st or "")
                    lines.append(f"      欄位 {s['slot']}：{uid} AP={s['ap']}/HP={s['hp'] - s['damage']} {st_t}")
            lines.append(f"    廢棄區：  {len(pl.get('trash', []))}張")
            lines.append("")

        lines.append("─" * 56)
        lines.append("  對話記錄")
        lines.append("─" * 56)
        lines.append("")

        if self.conversation_log:
            for i, entry in enumerate(self.conversation_log):
                role = entry.get("role", "orchestrator")
                cmd = entry.get("cmd", "")
                resp = entry.get("resp", "")
                lines.append(f"  [{i+1}] {role.upper()}：{cmd}")
                if resp:
                    lines.append(f"       ← {resp}")
        else:
            lines.append("  （無對話記錄）")

        lines.append("")
        lines.append("─" * 56)
        lines.append("  最終遊戲狀態（YAML）")
        lines.append("─" * 56)
        lines.append("")

        import yaml
        yaml_str = yaml.dump(state, default_flow_style=False, allow_unicode=True, sort_keys=False)
        lines.append(yaml_str)

        content = "\n".join(lines)
        replay_dir = PROJECT_ROOT / "replays"
        replay_dir.mkdir(exist_ok=True)
        fname = f"gcg_replay_{ts.strftime('%Y%m%d_%H%M%S')}.md"
        path = replay_dir / fname
        path.write_text(content)
        print(f"\n  ✓ 重播已儲存 → {path}")


def main():
    parser = argparse.ArgumentParser(description="GCG 模擬器 — 零邏輯協調層")
    parser.add_argument("--p1", choices=["human", "ai"], default="human", help="P1 mode (default: human)")
    parser.add_argument("--p2", choices=["human", "ai"], default="ai", help="P2 mode (default: ai)")
    parser.add_argument("--replay", action="store_true", help="Generate replay from existing state")
    args = parser.parse_args()

    if args.replay:
        sim = GCGSimulation()
        sim._read_game_id()
        state = sim._read_game_state()
        winner = state.get("winner") if state else None
        sim._save_replay(winner)
        return

    sim = GCGSimulation(p1_mode=args.p1, p2_mode=args.p2)
    sim.run()


if __name__ == "__main__":
    main()
