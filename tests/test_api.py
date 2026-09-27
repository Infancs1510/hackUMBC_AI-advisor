import json

from app.ai.backboard import BackboardError
from app.ai.gemini import GeminiError
from app.ai.prompts import heuristic_memories, is_allowed_memory, parse_extracted_memories
from app.config import Settings
from app.models.advisor import MemoryItem
from tests.conftest import ALUMNUS, FIRST_TERM, TRANSFER_JUNIOR, FakeGemini, FakeMemory


def context_from(gemini: FakeGemini) -> dict:
    prompt = next(c["prompt"] for c in gemini.calls if not c["json_output"])
    return json.loads(prompt.split("CONTEXT (JSON):\n", 1)[1].split("\n\nSTUDENT MESSAGE:", 1)[0])


# --- Endpoints -------------------------------------------------------------------------

def test_health(base_client):
    body = base_client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["data"]["students"] == 1800
    assert body["data"]["courses"] == 72


def test_dashboard_for_real_student(base_client):
    response = base_client.get(f"/api/dashboard/{TRANSFER_JUNIOR}")
    assert response.status_code == 200
    body = response.json()
    assert body["student"]["gpa"] == 3.0
    assert body["student"]["credits_earned"] == 76
    assert body["skills"]
    assert len(body["career_matches"]) == 8
    assert body["selected_career"] == body["career_matches"][0]["career"]
    assert body["pathway"]["recommended_courses"]
    assert body["salary"]["entry_level"]["sample_size"] > 0


def test_dashboard_first_term_student_has_null_gpa(base_client):
    body = base_client.get(f"/api/dashboard/{FIRST_TERM}").json()
    assert body["student"]["gpa"] is None
    assert body["skills"] == []


def test_dashboard_selected_career_and_errors(base_client):
    body = base_client.get(f"/api/dashboard/{TRANSFER_JUNIOR}", params={"career": "cybersecurity"}).json()
    assert body["selected_career"] == "Cybersecurity"
    assert base_client.get(f"/api/dashboard/{TRANSFER_JUNIOR}", params={"career": "Astronaut"}).status_code == 404
    assert base_client.get("/api/dashboard/CID-000000").status_code == 404
    alum = base_client.get(f"/api/dashboard/{ALUMNUS}")
    assert alum.status_code == 404 and alum.json()["is_alumnus"] is True
    assert base_client.get("/api/dashboard/not-an-id").status_code == 422


def test_careers(base_client):
    careers = base_client.get("/api/careers").json()["careers"]
    assert len(careers) == 8
    detail = base_client.get("/api/careers/IT Business %26 Product").json()
    assert detail["career"] == "IT Business & Product"
    assert detail["salary"]["entry_level"]["median"] == detail["median_entry_salary"]
    assert detail["alumni_outcomes"]["alumni_count"] > 0
    assert base_client.get("/api/careers/Astronaut").status_code == 404


def test_cors_allows_frontend_origin(base_client):
    response = base_client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"


def test_default_gemini_models_are_valid():
    settings = Settings(_env_file=None)
    assert settings.gemini_model == "gemini-2.0-flash"
    assert settings.gemini_fallback_model == "gemini-1.5-flash"


# --- Advisor ---------------------------------------------------------------------------

def test_advisor_context_is_structured_and_grounded(make_client, store):
    gemini = FakeGemini()
    client = make_client(gemini=gemini)
    response = client.post("/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "What should I take next semester?"})
    assert response.status_code == 200
    body = response.json()
    assert body["reply"] == "Here is my advice."
    assert body["services"] == {"gemini": "ok", "backboard": "ok"}

    context = context_from(gemini)
    facts = context["facts"]
    assert facts["student"]["gpa"] == 3.0
    for course in facts["focus_career"]["recommended_courses"]:
        assert course["course_id"] in store.catalog
    assert body["recommended_course_ids"] == [c["course_id"] for c in facts["focus_career"]["recommended_courses"]]
    # No raw dataset rows or identifiers are sent to Gemini.
    assert TRANSFER_JUNIOR not in json.dumps(context)
    assert "tuition" not in json.dumps(facts["student"])


def test_advisor_focus_career_from_message(make_client):
    gemini = FakeGemini()
    body = make_client(gemini=gemini).post(
        "/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "Is Health IT a good fit for me?"}
    ).json()
    assert body["focus_career"] == "Health IT"
    assert context_from(gemini)["facts"]["focus_career"]["career"] == "Health IT"


def test_advisor_memory_persists_across_requests(make_client):
    memory = FakeMemory()
    extracted = '{"memories": [{"category": "career_interest", "content": "Interested in data engineering."}]}'
    client = make_client(gemini=FakeGemini(memories_json=extracted), memory=memory)

    first = client.post("/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "I love data engineering."}).json()
    assert first["memories_saved"] == [{"content": "Interested in data engineering.", "category": "career_interest"}]

    gemini = FakeGemini(memories_json=extracted)
    client = make_client(gemini=gemini, memory=memory)
    second = client.post("/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "What next?"}).json()
    assert second["memories_used"][0]["content"] == "Interested in data engineering."
    assert second["memories_saved"] == []  # duplicate not re-saved
    assert context_from(gemini)["student_memory"][0]["content"] == "Interested in data engineering."

    listed = client.get(f"/api/advisor/{TRANSFER_JUNIOR}/memories").json()
    assert len(listed["memories"]) == 1
    # Memories are per student.
    assert client.get(f"/api/advisor/{FIRST_TERM}/memories").json()["memories"] == []


def test_memory_never_overrides_dataset_facts(make_client):
    memory = FakeMemory()
    memory.store[TRANSFER_JUNIOR] = [MemoryItem(content="Student says their GPA is 3.8.", category="context")]
    extracted = '{"memories": [{"category": "context", "content": "GPA is 3.8."}]}'
    gemini = FakeGemini(memories_json=extracted)
    body = make_client(gemini=gemini, memory=memory).post(
        "/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "My GPA is 3.8, right?"}
    ).json()
    assert context_from(gemini)["facts"]["student"]["gpa"] == 3.0
    assert body["memories_saved"] == []


def test_advisor_falls_back_when_gemini_fails(make_client):
    body = make_client(gemini=FakeGemini(error=GeminiError("boom"))).post(
        "/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "I want to become a data scientist."}
    ).json()
    assert body["services"]["gemini"] == "error"
    assert "unavailable" in body["reply"]
    # Heuristic extraction still saves the goal.
    assert body["memories_saved"] and body["memories_saved"][0]["category"] == "goal"


def test_advisor_without_keys(make_client):
    body = make_client(gemini=FakeGemini(configured=False), memory=FakeMemory(configured=False)).post(
        "/api/advisor", json={"campus_id": FIRST_TERM, "message": "Help"}
    ).json()
    assert body["services"] == {"gemini": "not_configured", "backboard": "not_configured"}
    assert body["reply"]


def test_advisor_survives_backboard_failure(make_client):
    body = make_client(memory=FakeMemory(error=BackboardError("down"))).post(
        "/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "I prefer remote work."}
    ).json()
    assert body["services"]["backboard"] == "error"
    assert body["reply"] == "Here is my advice."
    assert body["memories_saved"] == []


def test_advisor_invalid_requests(make_client):
    client = make_client()
    assert client.post("/api/advisor", json={"campus_id": "CID-000000", "message": "hi"}).status_code == 404
    assert client.post("/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": ""}).status_code == 422
    assert client.post("/api/advisor", json={"campus_id": "bad", "message": "hi"}).status_code == 422


# --- Memory guard ----------------------------------------------------------------------

def test_memory_guard_rejects_academic_facts():
    assert not is_allowed_memory(MemoryItem(content="Has a 3.8 GPA.", category="context"))
    assert not is_allowed_memory(MemoryItem(content="Earned 90 credits.", category="context"))
    assert not is_allowed_memory(MemoryItem(content="Expects a $120k salary.", category="goal"))
    assert not is_allowed_memory(MemoryItem(content="Likes Python.", category="unknown"))
    assert is_allowed_memory(MemoryItem(content="Wants an internship before graduating.", category="goal"))


def test_parse_extracted_memories_handles_bad_json():
    assert parse_extracted_memories("not json") == []
    assert parse_extracted_memories('{"memories": [{"category": "goal"}]}') == []


def test_heuristic_memories():
    items = heuristic_memories("What is CMSC461? I'm interested in cybersecurity. My GPA is 3.2.")
    assert [i.category for i in items] == ["career_interest"]


def test_focus_career_from_partial_name(profiles):
    from app.models.advisor import AdvisorRequest
    from app.services.advisor import pick_focus_career

    def pick(message):
        return pick_focus_career(AdvisorRequest(campus_id=TRANSFER_JUNIOR, message=message), message, profiles)

    assert pick("I'm interested in machine learning") == "Machine Learning & AI"
    assert pick("Should I go into cloud work?") == "Infrastructure & Cloud"
    assert pick("What about Software Engineering?") == "Software Engineering"
    assert pick("What should I take next semester?") is None
    assert pick("I said it again") is None  # 'IT' must match as a whole phrase, not inside words


def test_remembered_interest_sets_focus_but_message_wins(make_client):
    memory = FakeMemory()
    memory.store[TRANSFER_JUNIOR] = [MemoryItem(content="Interested in cybersecurity.", category="career_interest")]
    client = make_client(memory=memory)
    body = client.post("/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "What next?"}).json()
    assert body["focus_career"] == "Cybersecurity"
    body = client.post("/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "What about Health IT?"}).json()
    assert body["focus_career"] == "Health IT"


def test_extraction_prompt_lists_known_memories(make_client):
    memory = FakeMemory()
    memory.store[TRANSFER_JUNIOR] = [MemoryItem(content="Prefers remote work.", category="preference")]
    gemini = FakeGemini()
    make_client(gemini=gemini, memory=memory).post(
        "/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "Remote jobs?"}
    )
    extraction = next(c["prompt"] for c in gemini.calls if c["json_output"])
    assert "ALREADY REMEMBERED" in extraction and "Prefers remote work." in extraction


# --- Alumni ----------------------------------------------------------------------------

def test_alumni_view(base_client, store):
    response = base_client.get(f"/api/alumni/{ALUMNUS}")
    assert response.status_code == 200
    body = response.json()
    row = store.alumni.loc[ALUMNUS]
    assert body["alumnus"]["final_gpa"] == float(row["final_gpa"])
    assert body["alumnus"]["net_cost_usd"] == int(row["net_cost_usd"])
    assert body["first_job"]["title"] == row["first_job_title"]
    assert body["first_job"]["annual_salary_usd"] == int(row["first_job_annual_salary_usd"])
    history = body["employment_history"]
    assert len(history) == len(store.employment[store.employment["campus_id"] == ALUMNUS])
    assert [j["start_date"] for j in history] == sorted(j["start_date"] for j in history)
    for job in history:
        assert (job["end_date"] is None) == job["is_current"]
    assert body["first_job_career_match"]["career"] == row["first_job_family"]
    assert len(body["career_matches"]) == 8


def test_alumni_without_job_records(base_client, store):
    unemployed = store.alumni[store.alumni["first_destination"] == "No Response"].index[0]
    body = base_client.get(f"/api/alumni/{unemployed}").json()
    assert body["first_job"] is None
    assert body["first_job_career_match"] is None
    assert body["employment_history"] == []


def test_alumni_errors(base_client):
    student = base_client.get(f"/api/alumni/{TRANSFER_JUNIOR}")
    assert student.status_code == 404 and student.json()["is_student"] is True
    assert base_client.get("/api/alumni/CID-000000").status_code == 404
    assert f"/api/alumni/{ALUMNUS}" in base_client.get(f"/api/dashboard/{ALUMNUS}").json()["detail"]
