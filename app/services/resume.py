"""Resume text extraction and a transparent readiness rubric grounded in the student's record."""

import io
import re
import zipfile

from app.data.loader import DataStore
from app.models.resume import ResumeAnalysis, ResumeFinding, ScoreComponent, SkillWithCourses
from app.services.career_matching import CORE_SKILL_SHARE, CareerProfile, match_careers, resolve_career
from app.services.dashboard import UnknownCareerError
from app.services.skills import extract_skills, skill_set
from app.services.student_profile import StudentNotFoundError, completed_course_ids, in_progress_course_ids

MAX_BYTES = 2 * 1024 * 1024
MIN_TEXT_CHARS = 100
WEIGHTS = {"career": 0.35, "verified": 0.25, "quantified": 0.20, "structure": 0.20}
PORTFOLIO_EXPERIENCES = {"Internship", "Co-op", "Undergraduate Research", "Hackathon", "Competitive Team"}

# Common ways a vocabulary skill is written on a resume. Keys are dataset skill names.
ALIASES = {
    "Version Control": ["git", "github", "gitlab", "version control"],
    "Git": ["git", "github", "gitlab"],
    "Cloud": ["aws", "azure", "gcp", "google cloud", "cloud"],
    "Containers": ["docker", "kubernetes", "containers", "containerization"],
    "SQL": ["sql", "postgresql", "postgres", "mysql", "sqlite", "t-sql"],
    "Object-Oriented Design": ["object-oriented", "object oriented", "oop"],
    "Machine Learning": ["machine learning", "scikit-learn", "sklearn"],
    "Deep Learning": ["deep learning", "neural network", "neural networks"],
    "JavaScript": ["javascript", "typescript", "node.js", "nodejs", "react"],
    "REST APIs": ["rest api", "rest apis", "restful", "fastapi", "flask"],
    "Linux": ["linux", "unix", "bash"],
    "Testing": ["testing", "unit test", "unit tests", "pytest", "junit"],
    "CI/CD": ["ci/cd", "github actions", "jenkins", "continuous integration"],
    "Data Structures": ["data structures"],
    "Statistics": ["statistics", "statistical"],
    "Visualization": ["visualization", "data visualization", "matplotlib", "plotly"],
    "AI": ["ai", "artificial intelligence"],
}
SINGLE_LETTER_SKILLS = {"C", "R"}  # only counted as list items, e.g. "Languages: Python, C, R"
SECTIONS = {
    "Education": r"education",
    "Experience": r"experience|employment|work history",
    "Projects": r"projects?",
    "Skills": r"(technical )?skills|technologies",
}
BULLET = re.compile(r"^\s*(?:[-•*–▪●◦‣]|\d+[.)])\s+")
YEARS_AND_DATES = re.compile(r"\b(19|20)\d{2}\b|\b\d{1,2}/\d{1,2}(/\d{2,4})?\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")


class ResumeError(ValueError):
    pass


# ---------------------------------------------------------------- extraction

def extract_text(filename: str, data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise ResumeError("Resume files must be 2 MB or smaller.")
    name = filename.lower()
    if name.endswith(".pdf"):
        from pypdf import PdfReader

        try:
            reader = PdfReader(io.BytesIO(data))
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:  # pypdf raises many types for malformed files
            raise ResumeError("Couldn't read that PDF.") from exc
    elif name.endswith(".docx"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "replace")
        except (zipfile.BadZipFile, KeyError) as exc:
            raise ResumeError("Couldn't read that Word document.") from exc
        xml = re.sub(r"</w:p>", "\n", xml)
        text = re.sub(r"<[^>]+>", "", xml)
    elif name.endswith((".txt", ".md")):
        text = data.decode("utf-8", "replace")
    else:
        raise ResumeError("Upload a PDF, DOCX, TXT, or MD file.")
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) < MIN_TEXT_CHARS:
        raise ResumeError("Couldn't find enough text — if this is a scanned PDF, upload a text-based version.")
    return text


# ---------------------------------------------------------------- skill detection

def _pattern(term: str) -> str:
    return rf"(?<![\w+#/]){re.escape(term)}(?![\w+#/])"


def detect_skills(text: str, vocabulary: frozenset[str]) -> set[str]:
    found = set()
    lowered = text.lower()
    for skill in vocabulary:
        if skill in SINGLE_LETTER_SKILLS:
            if re.search(rf"(?:^|[,|•;:(]\s*){skill}(?=\s*(?:[,|•;)]|$))", text, re.MULTILINE):
                found.add(skill)
            continue
        terms = [skill.lower(), *ALIASES.get(skill, [])]
        if any(re.search(_pattern(t), lowered) for t in terms):
            found.add(skill)
    return found


# ---------------------------------------------------------------- analysis

def target_career(
    store: DataStore, profiles: dict[str, CareerProfile], campus_id: str, requested: str | None, goal: str | None
) -> str:
    if requested:
        resolved = resolve_career(requested, profiles)
        if resolved is None:
            raise UnknownCareerError(requested)
        return resolved
    if goal and resolve_career(goal, profiles):
        return resolve_career(goal, profiles)
    transcript = store.transcript_for(campus_id)
    have = skill_set(extract_skills(completed_course_ids(transcript), store.catalog))
    learning = skill_set(extract_skills(in_progress_course_ids(transcript), store.catalog))
    return match_careers(have, profiles, learning)[0].career


def analyze_resume(
    text: str, store: DataStore, profiles: dict[str, CareerProfile], campus_id: str, career: str
) -> ResumeAnalysis:
    if not store.is_student(campus_id):
        raise StudentNotFoundError(campus_id, is_alumnus=store.is_alumnus(campus_id))
    transcript = store.transcript_for(campus_id)
    verified = {s.skill: s.courses for s in extract_skills(completed_course_ids(transcript), store.catalog)}
    weights = profiles[career].skill_weights
    found = detect_skills(text, store.all_skills)
    lowered = text.lower()

    # Career keyword coverage (weighted by how often alumni roles asked for each skill).
    total = sum(weights.values()) or 1.0
    career_found = [s for s in weights if s in found]
    career_missing = [s for s in weights if s not in found]
    career_score = 100 * sum(weights[s] for s in career_found) / total

    # Verified skills that employers ask for, listed or not.
    relevant = {s: c for s, c in verified.items() if s in store.role_skills}
    listed = sorted(s for s in relevant if s in found)
    unlisted = sorted((s for s in relevant if s not in found), key=lambda s: (-weights.get(s, 0), s))
    verified_score = 100 * len(listed) / len(relevant) if relevant else None

    # Quantified bullets (numbers other than years/dates, %, $).
    lines = [l for l in text.splitlines() if l.strip()]
    bullets = [l for l in lines if BULLET.match(l)] or [l for l in lines if len(l.split()) >= 8]
    quantified = [b for b in bullets if re.search(r"\d|%|\$", YEARS_AND_DATES.sub("", b))]
    quant_score = 100 * len(quantified) / len(bullets) if bullets else 0.0

    # Structure: core sections, contact email, length.
    sections = [
        name for name, pattern in SECTIONS.items()
        if re.search(rf"^\s*(?:{pattern})\s*:?\s*$", text, re.IGNORECASE | re.MULTILINE)
    ]
    words = len(text.split())
    length_ok = 250 <= words <= 900
    has_email = bool(EMAIL.search(text))
    structure_score = 20 * len(sections) + (10 if has_email else 0) + (10 if length_ok else 5 if words >= 150 else 0)

    # Experiences on record that the resume doesn't mention.
    experiences = store.experiences_for(campus_id)
    experiences = experiences[experiences["experience_type"].isin(PORTFOLIO_EXPERIENCES)]
    missing_exp = [
        f"{r.experience_name} — {r.organization} ({r.term})"
        for r in experiences.itertuples(index=False)
        if r.experience_name.lower() not in lowered and r.organization.lower() not in lowered
    ]

    components = [
        ScoreComponent(key="career", label=f"{career} keywords", weight=WEIGHTS["career"], score=round(career_score, 1),
                       detail=f"{len(career_found)} of {len(weights)} skills alumni {career} roles asked for"),
        ScoreComponent(key="verified", label="Verified skills listed", weight=WEIGHTS["verified"],
                       score=None if verified_score is None else round(verified_score, 1),
                       detail=f"{len(listed)} of {len(relevant)} in-demand skills from your completed courses" if relevant
                       else "No completed-course skills yet"),
        ScoreComponent(key="quantified", label="Quantified impact", weight=WEIGHTS["quantified"], score=round(quant_score, 1),
                       detail=f"{len(quantified)} of {len(bullets)} bullets include a number, %, or $"),
        ScoreComponent(key="structure", label="Structure", weight=WEIGHTS["structure"], score=float(structure_score),
                       detail=f"Sections: {', '.join(sections) or 'none detected'} · {words} words{' · email' if has_email else ''}"),
    ]
    scored = [c for c in components if c.score is not None]
    overall = round(sum(c.score * c.weight for c in scored) / sum(c.weight for c in scored))

    findings: list[ResumeFinding] = []
    if missing_exp:
        findings.append(ResumeFinding(kind="experience_missing", priority="high",
            title="Add experience from your record",
            detail="These are on your student record but don't appear on your resume.", items=missing_exp))
    if unlisted:
        findings.append(ResumeFinding(kind="verified_skill_missing", priority="high",
            title="List skills you've already earned",
            detail="You completed courses that teach these in-demand skills, but they're not on your resume.",
            items=[f"{s} ({', '.join(relevant[s])})" for s in unlisted[:8]]))
    core_gaps = [s for s in career_missing if weights[s] >= CORE_SKILL_SHARE and s not in verified]
    if core_gaps:
        findings.append(ResumeFinding(kind="career_gap", priority="medium",
            title=f"Core {career} skills to build",
            detail="Every entry-level alumni role in this career listed these, and neither your resume nor your courses cover them yet.",
            items=core_gaps))
    if bullets and quant_score < 50:
        findings.append(ResumeFinding(kind="quantify", priority="medium",
            title="Quantify your impact",
            detail=f"Only {len(quantified)} of {len(bullets)} bullets include a number. Add real figures — users, time saved, dataset size, accuracy.",
            items=[b.strip(" -•*–")[:120] for b in bullets if b not in quantified][:3]))
    missing_sections = [s for s in SECTIONS if s not in sections]
    if missing_sections:
        findings.append(ResumeFinding(kind="section_missing", priority="medium" if len(missing_sections) > 1 else "low",
            title="Add standard section headings",
            detail="Clear headings on their own line help recruiters and parsers find each part.", items=missing_sections))
    if not has_email:
        findings.append(ResumeFinding(kind="contact", priority="medium", title="Add a contact email", detail="No email address was found."))
    if not length_ok:
        findings.append(ResumeFinding(kind="length", priority="low",
            title="Adjust length", detail=f"{words} words — aim for roughly 250–900 (one page for most students)."))
    unverified = sorted(s for s in found if s not in verified and s in store.role_skills)
    if unverified:
        findings.append(ResumeFinding(kind="unverified_claim", priority="low",
            title="Back these skills with evidence",
            detail="Listed on your resume but not taught by a course you've completed — point to a project, internship, or certification.",
            items=unverified[:10]))

    return ResumeAnalysis(
        target_career=career, score=overall, components=components,
        skills_found=sorted(found), career_skills_found=career_found, career_skills_missing=career_missing,
        verified_skills_listed=listed,
        verified_skills_missing=[SkillWithCourses(skill=s, courses=relevant[s]) for s in unlisted],
        unverified_skills=unverified, experiences_missing=missing_exp,
        bullets_total=len(bullets), bullets_quantified=len(quantified),
        sections_found=sections, word_count=words, findings=findings,
    )
