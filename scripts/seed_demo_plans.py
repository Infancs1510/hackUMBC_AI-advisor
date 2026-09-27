"""Seed demo registration plans so the advisor's Plan Review Queue has something to review.

Demo data only: each student's plan is their roadmap's suggested courses for next term, and a
couple of plans deliberately include an already-completed course so the "prerequisite check"
category shows up. Seeded plans are marked with a "[demo]" note and can be removed with --clear.

    python -m scripts.seed_demo_plans          # add ~12 demo plans
    python -m scripts.seed_demo_plans --clear  # remove them
"""

import argparse
import random
import sqlite3
from contextlib import closing

from app.config import get_settings
from app.data.loader import load_data
from app.data.parsing import NEXT_TERM
from app.services.career_matching import build_career_profiles
from app.services.plans import PlanStore
from app.services.roadmap import build_roadmap
from app.services.student_profile import completed_course_ids

DEMO_NOTE = "[demo] Seeded plan for the review-queue demo."


def clear(store: PlanStore) -> int:
    with closing(sqlite3.connect(store.db_path)) as conn, conn:
        return conn.execute("DELETE FROM registration_plans WHERE note LIKE '[demo]%'").rowcount


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--clear", action="store_true", help="remove seeded demo plans")
    parser.add_argument("--count", type=int, default=12)
    args = parser.parse_args()

    settings = get_settings()
    plans = PlanStore(settings.app_db_path)
    if args.clear:
        print(f"Removed {clear(plans)} demo plans from {plans.db_path}")
        return

    data = load_data(settings.data_dir)
    profiles = build_career_profiles(data.employment)
    rng = random.Random(2026)
    students = data.students
    upper = students[students["class_level"].isin(["Junior", "Senior"])]
    at_risk = list(students[students["academic_standing"] != "Good Standing"].index)
    picks = rng.sample(at_risk, min(2, len(at_risk))) + rng.sample(list(upper.index), args.count)

    added = 0
    for i, campus_id in enumerate(picks):
        if added >= args.count or plans.for_student(campus_id):
            continue
        roadmap = build_roadmap(data, profiles, campus_id)
        next_term = next((t for t in roadmap.terms if t.term == NEXT_TERM), None)
        courses = [c.course_id for c in next_term.courses] if next_term else []
        if not courses:
            continue
        if i in (2, 3):  # show the prerequisite-check category: add a course they already passed
            done = sorted(completed_course_ids(data.transcript_for(campus_id)))
            if done:
                courses.append(done[-1])
        plans.submit(campus_id, courses, DEMO_NOTE)
        added += 1
    print(f"Added {added} demo plans for {NEXT_TERM} to {plans.db_path}. Remove with --clear.")


if __name__ == "__main__":
    main()
