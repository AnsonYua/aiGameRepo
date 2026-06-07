from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .card_db import get_card


PROJECT_ROOT = Path(__file__).parent.parent.absolute()
AGENTS_DIR = PROJECT_ROOT / "agents"
TACTICAL_SKILLS_DIR = PROJECT_ROOT / "gcg_skills"


@dataclass(frozen=True)
class AgentSpec:
    spec_id: str
    metadata: dict[str, Any]
    body: str
    path: Path


@dataclass(frozen=True)
class TacticalSkill:
    skill_id: str
    metadata: dict[str, Any]
    body: str
    path: Path


def render_agent_instructions(agent_id: str, **context: str) -> str:
    spec = load_agent_spec(agent_id)
    rendered = _render_template(spec.body, context)
    return rendered.strip() + "\n"


def render_player_decision_prompt(
    prompt: str,
    player_id: str,
    selected_lessons_text: str = "",
    card_text_context: str = "",
    judge_feedback: str = "",
) -> str:
    _ = player_id
    rendered = "\n\n".join(
        part
        for part in [
            prompt.strip(),
            _optional_section("公開卡片文字（public-safe，供 LLM 判斷語意）：", card_text_context),
            _optional_section("本次相關經驗 lessons（由 LLM selector 選出，只作決策提示）：", selected_lessons_text),
            _optional_section("Judge 修正意見（請依此重新產生 COMMAND）：", judge_feedback),
            "再次確認：COMMAND 只能輸出命令本體，不可包含 `—` 後面的顯示說明。",
        ]
        if part
    )
    return rendered


def render_judge_prompt(
    prompt: str,
    player_output: str,
    selected_lessons_text: str = "",
    card_text_context: str = "",
) -> str:
    return "\n\n".join(
        part
        for part in [
            "請審查以下 GCG AI player 決策。你只做 LLM 語意審查，不改 state，不執行 command。",
            prompt.strip(),
            _optional_section("公開卡片文字（public-safe）：", card_text_context),
            _optional_section("本次相關經驗 lessons：", selected_lessons_text),
            "Player output:",
            player_output.strip(),
            "\n".join([
                "請只輸出以下格式：",
                "VERDICT: accept 或 reject",
                "REASON: <繁體中文 public-safe 理由>",
                "SUGGESTED_COMMAND: <可省略；若提供，只能是提示，Python 不會直接套用>",
                "",
                "若 COMMAND 語意完整且可交給 runtime 驗證，請 accept。",
                "若 COMMAND 缺少公開目標、複製了顯示說明、違反 selected lesson，或與公開卡片文字明顯矛盾，請 reject。",
            ]),
        ]
        if part
    )


def render_selector_prompt(prompt: str, candidate_lessons_text: str, card_text_context: str = "") -> str:
    return "\n\n".join(
        part
        for part in [
            "請從候選 lessons 選出本次 GCG 決策真正相關的經驗。你不決定 move，不輸出 COMMAND。",
            prompt.strip(),
            _optional_section("公開卡片文字（public-safe）：", card_text_context),
            "候選 lessons:",
            candidate_lessons_text.strip(),
            "\n".join([
                "請只輸出以下格式：",
                "SELECTED_LESSON_IDS: <逗號分隔 id；若無則留空>",
                "REASON: <繁體中文，簡短說明為何選或不選>",
            ]),
        ]
        if part
    )


def render_curator_prompt(source_text: str) -> str:
    return "\n\n".join([
        "請根據以下 public-safe 對局/review 內容，萃取可重用 lesson draft。",
        "不要寫 hidden hand/deck/shield card id。不要把單局偶然現象過度泛化。",
        "請輸出 YAML，欄位包含：id, status, lesson_type, confidence, summary, applies_when, bad_example, better_example, player_instruction, judge_instruction, notes。",
        "status 必須是 draft。",
        "Public-safe source:",
        source_text.strip(),
    ])


def build_card_text_context(prompt: str, max_cards: int = 12) -> str:
    card_ids = []
    seen = set()
    for match in re.findall(r"\b[a-z]{2}\d{2}/[A-Z0-9-]+\b", prompt, flags=re.IGNORECASE):
        card_id = match.strip()
        key = card_id.lower()
        if key in seen:
            continue
        seen.add(key)
        card_ids.append(card_id)
    lines: list[str] = []
    for card_id in card_ids[:max_cards]:
        card = get_card(card_id)
        if not card:
            continue
        lines.append(_format_card_text(card_id, card))
    return "\n\n".join(lines)


def load_agent_spec(agent_id: str) -> AgentSpec:
    path = AGENTS_DIR / f"{agent_id}.md"
    metadata, body = _load_frontmatter_markdown(path)
    spec_id = str(metadata.get("id") or agent_id)
    return AgentSpec(spec_id=spec_id, metadata=metadata, body=body, path=path)


def select_tactical_skills(prompt: str, max_skills: int = 4) -> list[TacticalSkill]:
    selected: list[TacticalSkill] = []
    for path in sorted(TACTICAL_SKILLS_DIR.glob("*.md")):
        metadata, body = _load_frontmatter_markdown(path)
        skill_id = str(metadata.get("id") or path.stem)
        skill = TacticalSkill(skill_id=skill_id, metadata=metadata, body=body, path=path)
        if _skill_matches_prompt(skill, prompt):
            selected.append(skill)
    if not selected:
        fallback = TACTICAL_SKILLS_DIR / "deployment-evaluation.md"
        if fallback.exists():
            metadata, body = _load_frontmatter_markdown(fallback)
            selected.append(TacticalSkill(str(metadata.get("id") or fallback.stem), metadata, body, fallback))
    return selected[:max_skills]


def _load_frontmatter_markdown(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + len("\n---\n") :]
    data = yaml.safe_load(raw) or {}
    return data if isinstance(data, dict) else {}, body


def _render_template(text: str, context: dict[str, str]) -> str:
    rendered = text
    for key, value in context.items():
        rendered = rendered.replace("{{" + key + "}}", value)
    rendered = re.sub(r"\{\{[A-Za-z0-9_]+\}\}", "", rendered)
    return rendered


def _optional_section(title: str, body: str) -> str:
    body = body.strip()
    if not body:
        return ""
    return f"{title}\n{body}"


def _format_card_text(card_id: str, card: dict[str, Any]) -> str:
    effects = card.get("effects") if isinstance(card, dict) else {}
    descriptions = effects.get("description", []) if isinstance(effects, dict) else []
    if not isinstance(descriptions, list):
        descriptions = []
    rules = effects.get("rules", []) if isinstance(effects, dict) else []
    rule_summaries = []
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            rule_summaries.append(
                {
                    "type": rule.get("type"),
                    "action": rule.get("action"),
                    "target": rule.get("target"),
                    "parameters": rule.get("parameters"),
                    "timing": rule.get("timing"),
                }
            )
    data = {
        "card_id": card_id,
        "name": card.get("name", card_id),
        "cardType": card.get("cardType", ""),
        "level": card.get("level", 0),
        "cost": card.get("cost", 0),
        "description": descriptions,
        "rules_summary": rule_summaries,
    }
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False).strip()


def _skill_matches_prompt(skill: TacticalSkill, prompt: str) -> bool:
    triggers = skill.metadata.get("triggers") if isinstance(skill.metadata, dict) else None
    if not isinstance(triggers, dict):
        return False
    keywords = triggers.get("keywords")
    if isinstance(keywords, list):
        for keyword in keywords:
            if isinstance(keyword, str) and keyword and keyword in prompt:
                return True
    return False


def _format_tactical_skills(skills: list[TacticalSkill]) -> str:
    if not skills:
        return "（無額外技能）"
    chunks = []
    for skill in skills:
        chunks.append(f"## {skill.skill_id}\n{skill.body.strip()}")
    return "\n\n".join(chunks)
