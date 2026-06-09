from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).parent.parent.absolute()
LESSONS_DIR = PROJECT_ROOT / "experience" / "lessons"
ALLOWED_LESSON_KEYS = {
    "id",
    "source_game",
    "status",
    "lesson_type",
    "confidence",
    "summary",
    "applies_when",
    "bad_example",
    "better_example",
    "player_instruction",
    "judge_instruction",
    "notes",
}
HIDDEN_INFO_TERMS = ("hidden", "手牌內容", "盾牌內容", "牌庫內容", "shield_cards", "deck_cards", "hand_cards")
GENERIC_TERMS = {
    "command",
    "commands",
    "consider",
    "legal_actions",
    "player_id",
    "game_id",
    "return",
    "exactly",
    "probe",
    "pass",
    "使用",
    "指令",
    "玩家",
    "公開",
    "經驗",
    "選擇",
}


@dataclass(frozen=True)
class Lesson:
    lesson_id: str
    data: dict[str, Any]
    path: Path


def load_reviewed_lessons() -> list[Lesson]:
    lessons: list[Lesson] = []
    if not LESSONS_DIR.exists():
        return lessons
    for path in sorted(LESSONS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            continue
        if str(data.get("status") or "").strip() != "reviewed":
            continue
        if not _schema_is_allowed(data):
            continue
        if _contains_hidden_info(data):
            continue
        lesson_id = str(data.get("id") or path.stem)
        lessons.append(Lesson(lesson_id=lesson_id, data=data, path=path))
    return lessons


def search_candidate_lessons(prompt: str, max_candidates: int = 8) -> list[Lesson]:
    prompt_terms = _terms(prompt) - GENERIC_TERMS
    prompt_card_ids = _card_ids(prompt)
    scored: list[tuple[int, Lesson]] = []
    for lesson in load_reviewed_lessons():
        lesson_text = _lesson_search_text(lesson)
        lesson_card_ids = _card_ids(lesson_text)
        if lesson_card_ids and not prompt_card_ids.intersection(lesson_card_ids):
            continue
        lesson_terms = _terms(lesson_text) - GENERIC_TERMS
        score = len(prompt_terms.intersection(lesson_terms))
        for card_id in prompt_card_ids:
            if card_id in lesson_text.lower():
                score += 10
        if score >= 2 or (prompt_card_ids and prompt_card_ids.intersection(lesson_card_ids)):
            scored.append((score, lesson))
    scored.sort(key=lambda item: (-item[0], item[1].lesson_id))
    return [lesson for _, lesson in scored[:max_candidates]]


def format_lessons(lessons: list[Lesson]) -> str:
    chunks: list[str] = []
    for lesson in lessons:
        data = lesson.data
        lines = [
            f"id: {lesson.lesson_id}",
            f"lesson_type: {data.get('lesson_type', '')}",
            f"confidence: {data.get('confidence', '')}",
            f"summary: {data.get('summary', '')}",
        ]
        for key in ("applies_when", "player_instruction", "judge_instruction", "notes"):
            value = data.get(key)
            if value:
                lines.append(f"{key}: {value}")
        if data.get("bad_example") or data.get("better_example"):
            lines.append("examples_are_for_reasoning_not_copying:")
            if data.get("bad_example"):
                lines.append(f"  bad: {_quote_example(str(data.get('bad_example')))}")
            if data.get("better_example"):
                lines.append(f"  better_pattern: {_quote_example(str(data.get('better_example')))}")
        chunks.append("\n".join(lines))
    return "\n\n---\n\n".join(chunks)


def filter_lessons_by_ids(lessons: list[Lesson], selected_ids: list[str]) -> list[Lesson]:
    wanted = {lesson_id.strip() for lesson_id in selected_ids if lesson_id.strip()}
    return [lesson for lesson in lessons if lesson.lesson_id in wanted]


def _lesson_search_text(lesson: Lesson) -> str:
    return yaml.safe_dump(lesson.data, allow_unicode=True, sort_keys=True)


def _terms(text: str) -> set[str]:
    return {term.lower() for term in re.findall(r"[A-Za-z0-9_/.-]+|[\u4e00-\u9fff]+", text) if len(term.strip()) >= 2}


def _card_ids(text: str) -> set[str]:
    return {match.lower() for match in re.findall(r"\b[a-z]{2}\d{2}/[A-Z0-9-]+\b", text, flags=re.IGNORECASE)}


def _schema_is_allowed(data: dict[str, Any]) -> bool:
    return set(data).issubset(ALLOWED_LESSON_KEYS)


def _contains_hidden_info(data: dict[str, Any]) -> bool:
    text = yaml.safe_dump(data, allow_unicode=True, sort_keys=True).lower()
    return any(term.lower() in text for term in HIDDEN_INFO_TERMS)


def _quote_example(example: str) -> str:
    return f"「{example}」（案例，不是可直接複製的 COMMAND）"
