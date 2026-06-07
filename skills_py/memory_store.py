from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).parent.parent.absolute()
LESSONS_DIR = PROJECT_ROOT / "experience" / "lessons"


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
        lesson_id = str(data.get("id") or path.stem)
        lessons.append(Lesson(lesson_id=lesson_id, data=data, path=path))
    return lessons


def search_candidate_lessons(prompt: str, max_candidates: int = 8) -> list[Lesson]:
    prompt_terms = _terms(prompt)
    scored: list[tuple[int, Lesson]] = []
    for lesson in load_reviewed_lessons():
        lesson_text = _lesson_search_text(lesson)
        lesson_terms = _terms(lesson_text)
        score = len(prompt_terms.intersection(lesson_terms))
        for card_id in re.findall(r"\b[a-z]{2}\d{2}/[A-Z0-9-]+\b", prompt, flags=re.IGNORECASE):
            if card_id.lower() in lesson_text.lower():
                score += 10
        if score > 0:
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
        for key in ("applies_when", "bad_example", "better_example", "player_instruction", "judge_instruction", "notes"):
            value = data.get(key)
            if value:
                lines.append(f"{key}: {value}")
        chunks.append("\n".join(lines))
    return "\n\n---\n\n".join(chunks)


def filter_lessons_by_ids(lessons: list[Lesson], selected_ids: list[str]) -> list[Lesson]:
    wanted = {lesson_id.strip() for lesson_id in selected_ids if lesson_id.strip()}
    return [lesson for lesson in lessons if lesson.lesson_id in wanted]


def _lesson_search_text(lesson: Lesson) -> str:
    return yaml.safe_dump(lesson.data, allow_unicode=True, sort_keys=True)


def _terms(text: str) -> set[str]:
    return {term.lower() for term in re.findall(r"[A-Za-z0-9_/.-]+|[\u4e00-\u9fff]+", text) if len(term.strip()) >= 2}
