import io
import zipfile

import pytest

from app.services.career_matching import build_career_profiles
from app.services.resume import ResumeError, analyze_resume, detect_skills, extract_text
from tests.conftest import FIRST_TERM, TRANSFER_JUNIOR, FakeGemini, FakeMemory

RESUME = """Jordan Sample
jordan.sample@example.com

Education
UMBC — B.S. Computer Science, expected Spring 2028

Experience
AI Research Intern, Federal Health Data Office — Fall 2026
- Built Python scripts to clean clinical datasets for model training
- Improved data loading speed by 35% by rewriting pipeline stages
- Presented findings to the analytics team

Projects
Course Scheduler
- Wrote a C++ program using graphs and priority queues to generate schedules

Skills
Languages: Python, C++, C
Tools: Git, Linux, SQL
Concepts: Algorithms, Data Structures, Statistics
"""


def make_pdf(text: str) -> bytes:
    """Minimal single-page PDF with one line of text per input line."""
    text = text.replace("—", "-")  # the built-in Helvetica encoding is Latin-1
    lines = [l.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for l in text.splitlines()]
    stream = "BT /F1 10 Tf 12 TL 40 780 Td " + " ".join(f"({l}) '" for l in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{obj}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def make_docx(text: str) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{l}</w:t></w:r></w:p>" for l in text.splitlines())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body>{body}</w:body></w:document>')
    return buf.getvalue()


# --- extraction & detection --------------------------------------------------------------

@pytest.mark.parametrize("name,data", [
    ("r.txt", RESUME.encode()),
    ("r.docx", make_docx(RESUME)),
    ("r.pdf", make_pdf(RESUME)),
])
def test_extract_text_formats(name, data):
    text = extract_text(name, data)
    assert "Federal Health Data Office" in text and "Skills" in text


def test_extract_text_errors():
    with pytest.raises(ResumeError):
        extract_text("r.exe", RESUME.encode())
    with pytest.raises(ResumeError):
        extract_text("r.txt", b"too short")
    with pytest.raises(ResumeError):
        extract_text("r.txt", b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(ResumeError):
        extract_text("r.pdf", b"not a pdf at all" * 20)


def test_detect_skills_aliases_and_single_letters(store):
    found = detect_skills("Tools: GitHub, PostgreSQL, Docker\nLanguages: Python, C, R", store.all_skills)
    assert {"Version Control", "Git", "SQL", "Containers", "Python", "C", "R"} <= found
    assert not {"C", "R"} & detect_skills("Our R and D group earned a C grade once.", store.all_skills)
    assert "C++" in detect_skills("Built it in C++.", store.all_skills)
    assert "C" not in detect_skills("Built it in C++.", store.all_skills)


# --- analysis ------------------------------------------------------------------------------

def test_analysis_grounded_in_record(store, profiles):
    a = analyze_resume(RESUME, store, profiles, TRANSFER_JUNIOR, "Software Engineering")
    assert a.target_career == "Software Engineering" and 0 <= a.score <= 100
    assert {"Python", "C++", "SQL", "Algorithms"} <= set(a.skills_found)
    # Earned in CMSC304/ENGL393 but not on the resume.
    missing = {m.skill: m.courses for m in a.verified_skills_missing}
    assert missing["Technical Writing"] == ["CMSC304", "ENGL393"]
    # Record activities the resume doesn't mention; the internship it does mention is not listed.
    assert any("Bitcamp" in e for e in a.experiences_missing)
    assert not any("Federal Health Data Office" in e for e in a.experiences_missing)
    assert a.bullets_total == 4 and a.bullets_quantified == 1
    assert set(a.sections_found) == {"Education", "Experience", "Projects", "Skills"}
    weights = {c.key: c.weight for c in a.components}
    assert abs(sum(weights.values()) - 1) < 1e-9
    expected = round(sum(c.score * c.weight for c in a.components))
    assert a.score == expected
    assert a.findings[0].priority == "high"


def test_first_term_analysis_skips_verified_component(store, profiles):
    a = analyze_resume(RESUME, store, profiles, FIRST_TERM, "Software Engineering")
    verified = next(c for c in a.components if c.key == "verified")
    assert verified.score is None
    scored = [c for c in a.components if c.score is not None]
    assert a.score == round(sum(c.score * c.weight for c in scored) / sum(c.weight for c in scored))


# --- API -----------------------------------------------------------------------------------

def upload(client, campus_id, name="resume.txt", data=RESUME.encode()):
    return client.post(f"/api/resume/{campus_id}", files={"file": (name, data)})


def test_resume_api_lifecycle(make_client, advisor_client):
    gemini = FakeGemini(reply="- Add Technical Writing to Skills")
    client = make_client(gemini=gemini, memory=FakeMemory(), as_student=TRANSFER_JUNIOR)
    assert client.get(f"/api/resume/{TRANSFER_JUNIOR}").json()["resume"] is None

    body = upload(client, TRANSFER_JUNIOR, "resume.pdf", make_pdf(RESUME)).json()
    assert body["resume"]["filename"] == "resume.pdf"
    assert body["analysis"]["target_career"] == "Software Engineering"  # top match when no goal saved

    retargeted = client.get(f"/api/resume/{TRANSFER_JUNIOR}", params={"career": "cybersecurity"}).json()
    assert retargeted["analysis"]["target_career"] == "Cybersecurity"

    feedback = client.post(f"/api/resume/{TRANSFER_JUNIOR}/ai-feedback").json()
    assert feedback == {"suggestions": "- Add Technical Writing to Skills", "gemini": "ok"}
    prompt = gemini.calls[-1]["prompt"]
    assert "Technical Writing (CMSC304, ENGL393)" in prompt and "RESUME TEXT" in prompt
    assert "Never invent numbers" in gemini.calls[-1]["system"]

    assert upload(client, TRANSFER_JUNIOR, "resume.exe").status_code == 400
    assert advisor_client.get(f"/api/resume/{TRANSFER_JUNIOR}").status_code == 403
    assert make_client(as_student=FIRST_TERM).get(f"/api/resume/{TRANSFER_JUNIOR}").status_code == 403

    assert client.delete(f"/api/resume/{TRANSFER_JUNIOR}").status_code == 204
    assert client.get(f"/api/resume/{TRANSFER_JUNIOR}").json()["resume"] is None
    assert client.post(f"/api/resume/{TRANSFER_JUNIOR}/ai-feedback").status_code == 404


def test_ai_feedback_without_gemini(make_client):
    client = make_client(gemini=FakeGemini(configured=False), as_student=FIRST_TERM)
    upload(client, FIRST_TERM)
    body = client.post(f"/api/resume/{FIRST_TERM}/ai-feedback").json()
    assert body["gemini"] == "not_configured" and body["suggestions"]
    client.delete(f"/api/resume/{FIRST_TERM}")


def test_portfolio(make_client, advisor_client):
    client = make_client(as_student=TRANSFER_JUNIOR)
    body = client.get(f"/api/portfolio/{TRANSFER_JUNIOR}").json()
    titles = {v["title"] for v in body["verified"]}
    assert "AI Research Intern" in titles
    assert any(t.startswith("CMSC341") for t in titles)
    assert all(v["kind"] in {"experience", "coursework"} for v in body["verified"])

    created = client.post(f"/api/portfolio/{TRANSFER_JUNIOR}/projects", json={
        "title": "Course Scheduler", "description": "Graph-based schedule generator",
        "link": "https://github.com/example/scheduler", "skills": ["C++", "Algorithms", "Blockchain Wizardry"],
    })
    assert created.status_code == 201
    project = created.json()
    assert project["skills"] == ["Algorithms", "C++"]  # only dataset vocabulary is kept
    assert client.post(f"/api/portfolio/{TRANSFER_JUNIOR}/projects", json={"title": "x", "link": "not a url"}).status_code == 422
    assert advisor_client.get(f"/api/portfolio/{TRANSFER_JUNIOR}").json()["projects"][0]["title"] == "Course Scheduler"
    assert advisor_client.delete(f"/api/portfolio/{TRANSFER_JUNIOR}/projects/{project['id']}").status_code == 403
    assert client.delete(f"/api/portfolio/{TRANSFER_JUNIOR}/projects/{project['id']}").status_code == 204
    assert client.delete(f"/api/portfolio/{TRANSFER_JUNIOR}/projects/{project['id']}").status_code == 404
