"""Skill extraction: transcript -> completed courses -> catalog skill_tags."""

import logging
from collections.abc import Iterable

from app.data.loader import Course
from app.models.dashboard import SkillItem

logger = logging.getLogger(__name__)


def extract_skills(course_ids: Iterable[str], catalog: dict[str, Course]) -> list[SkillItem]:
    """Skills covered by the given courses, each with the courses that teach it."""
    by_skill: dict[str, set[str]] = {}
    for course_id in course_ids:
        course = catalog.get(course_id)
        if course is None:
            logger.warning("Course %s not found in catalog; skipping", course_id)
            continue
        for skill in course.skills:
            by_skill.setdefault(skill, set()).add(course_id)
    return [SkillItem(skill=s, courses=sorted(c)) for s, c in sorted(by_skill.items())]


def skill_set(items: Iterable[SkillItem]) -> set[str]:
    return {item.skill for item in items}
