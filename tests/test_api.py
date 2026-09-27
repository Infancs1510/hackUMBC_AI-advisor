import json

from app.ai.backboard import BackboardError
from app.ai.gemini import GeminiError
from app.ai.prompts import heuristic_memories, is_allowed_memory, parse_extracted_memories
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


def test_dashboard_for_real_student(advisor_client):
    response = advisor_client.get(f"/api/dashboard/{TRANSFER_JUNIOR}")
    assert response.status_code == 200
    body = response.json()
    assert body["student"]["gpa"] == 3.0
    assert body["student"]["credits_earned"] == 76
    assert body["skills"]
    assert len(body["career_matches"]) == 8
    assert body["selected_career"] == body["career_matches"][0]["career"]
    assert body["pathway"]["recommended_courses"]
    assert body["salary"]["entry_level"]["sample_size"] > 0


def test_dashboard_first_term_student_has_null_gpa(advisor_client):
    body = advisor_client.get(f"/api/dashboard/{FIRST_TERM}").json()
    assert body["student"]["gpa"] is None
    assert body["skills"] == []


def test_dashboard_selected_career_and_errors(advisor_client):
    body = advisor_client.get(f"/api/dashboard/{TRANSFER_JUNIOR}", params={"career": "cybersecurity"}).json()
    assert body["selected_career"] == "Cybersecurity"
    assert advisor_client.get(f"/api/dashboard/{TRANSFER_JUNIOR}", params={"career": "Astronaut"}).status_code == 404
    assert advisor_client.get("/api/dashboard/CID-000000").status_code == 404
    alum = advisor_client.get(f"/api/dashboard/{ALUMNUS}")
    assert alum.status_code == 404 and alum.json()["is_alumnus"] is True
    assert advisor_client.get("/api/dashboard/not-an-id").status_code == 422


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
    # Another student's memories are off limits.
    assert client.get(f"/api/advisor/{FIRST_TERM}/memories").status_code == 403


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
    body = make_client(
        gemini=FakeGemini(configured=False), memory=FakeMemory(configured=False), as_student=FIRST_TERM
    ).post(
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
    assert client.post("/api/advisor", json={"campus_id": "CID-000000", "message": "hi"}).status_code == 403
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

def test_alumni_view(advisor_client, store):
    response = advisor_client.get(f"/api/alumni/{ALUMNUS}")
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


def test_alumni_without_job_records(advisor_client, store):
    unemployed = store.alumni[store.alumni["first_destination"] == "No Response"].index[0]
    body = advisor_client.get(f"/api/alumni/{unemployed}").json()
    assert body["first_job"] is None
    assert body["first_job_career_match"] is None
    assert body["employment_history"] == []


def test_alumni_errors(advisor_client):
    student = advisor_client.get(f"/api/alumni/{TRANSFER_JUNIOR}")
    assert student.status_code == 404 and student.json()["is_student"] is True
    assert advisor_client.get("/api/alumni/CID-000000").status_code == 404
    assert f"/api/alumni/{ALUMNUS}" in advisor_client.get(f"/api/dashboard/{ALUMNUS}").json()["detail"]


# --- Degree audit ----------------------------------------------------------------------

def test_degree_audit_for_transfer_student(student_client, store):
    body = student_client(TRANSFER_JUNIOR).get(f"/api/degree/{TRANSFER_JUNIOR}").json()
    assert body["credits"]["earned"] == 76 and body["credits"]["in_progress"] == 15
    assert body["credits"]["remaining_after_current_term"] == 120 - 76 - 15
    groups = {g["category"]: g for g in body["requirement_groups"]}
    assert [g["category"] for g in body["requirement_groups"]][0] == "Major Core"
    core = groups["Major Core"]
    assert {c["course_id"] for c in core["completed"]} >= {"CMSC202", "CMSC203", "CMSC341"}
    assert {c["course_id"] for c in core["in_progress"]} == {"CMSC313", "CMSC331"}
    # Group credits add up to the transcript's earned credits (transfer credit has no rows).
    transcript = store.transcript_for(TRANSFER_JUNIOR)
    assert sum(g["completed_credits"] for g in body["requirement_groups"]) == int(transcript["credits_earned"].sum())
    assert body["credits"]["transfer_credits"] == 76 - int(transcript["credits_earned"].sum())
    # CMSC201 and ENGL100 are implied by CMSC202 / ENGL393, so they are not "remaining".
    assert set(body["satisfied_by_prior_credit"]) == {"CMSC201", "ENGL100"}
    remaining = {c["course_id"]: c for c in body["remaining_required_courses"]}
    assert set(remaining) == {"CMSC411", "CMSC421", "CMSC441", "CMSC447"}
    assert remaining["CMSC447"]["status"] == "eligible"
    assert remaining["CMSC411"]["status"] == "eligible_after_current_term"  # needs CMSC313, in progress


def test_degree_audit_first_term_and_access(student_client, advisor_client):
    body = student_client(FIRST_TERM).get(f"/api/degree/{FIRST_TERM}").json()
    assert all(g["completed"] == [] for g in body["requirement_groups"])
    assert body["remaining_required_courses"]
    assert student_client(FIRST_TERM).get(f"/api/degree/{TRANSFER_JUNIOR}").status_code == 403
    assert advisor_client.get(f"/api/degree/{TRANSFER_JUNIOR}").status_code == 200
    assert advisor_client.get(f"/api/degree/{ALUMNUS}").status_code == 404



# --- Career pathways: market, roadmap, goal --------------------------------------------

def test_career_detail_entry_market(base_client, store):
    detail = base_client.get("/api/careers/Cybersecurity").json()
    market = detail["entry_market"]
    entry = store.employment[(store.employment["job_family"] == "Cybersecurity") & (store.employment["seniority_level"] == "Entry")]
    assert market["spell_count"] == len(entry)
    assert market["requires_clearance_share"] == round(float(entry["requires_clearance"].mean()), 3)
    assert market["top_employers"][0]["count"] == entry["employer"].value_counts().iloc[0]
    assert market["top_regions"][0]["name"] == entry["region"].value_counts().index[0]
    certs = detail["alumni_outcomes"]["top_certifications"]
    assert certs and all(0 < c["share"] <= 1 for c in certs)


def test_roadmap_endpoint(student_client, advisor_client):
    body = student_client(TRANSFER_JUNIOR).get(f"/api/roadmap/{TRANSFER_JUNIOR}", params={"career": "Cybersecurity"}).json()
    assert body["career"] == "Cybersecurity" and len(body["terms"]) >= 2
    assert student_client(TRANSFER_JUNIOR).get(f"/api/roadmap/{FIRST_TERM}").status_code == 403
    assert advisor_client.get(f"/api/roadmap/{FIRST_TERM}").status_code == 200
    assert student_client(TRANSFER_JUNIOR).get(f"/api/roadmap/{TRANSFER_JUNIOR}", params={"career": "Astronaut"}).status_code == 404


def test_career_goal_saved_to_memory(make_client):
    memory = FakeMemory()
    client = make_client(memory=memory)
    assert client.get(f"/api/students/{TRANSFER_JUNIOR}/career-goal").json()["career"] is None
    saved = client.put(f"/api/students/{TRANSFER_JUNIOR}/career-goal", json={"career": "health it"}).json()
    assert saved == {"campus_id": TRANSFER_JUNIOR, "career": "Health IT", "backboard": "ok"}
    assert client.get(f"/api/students/{TRANSFER_JUNIOR}/career-goal").json()["career"] == "Health IT"
    assert client.put(f"/api/students/{TRANSFER_JUNIOR}/career-goal", json={"career": "Astronaut"}).status_code == 404
    assert client.put(f"/api/students/{FIRST_TERM}/career-goal", json={"career": "Health IT"}).status_code == 403


def test_career_goal_without_backboard(make_client):
    client = make_client(memory=FakeMemory(configured=False))
    body = client.put(f"/api/students/{TRANSFER_JUNIOR}/career-goal", json={"career": "Health IT"}).json()
    assert body["backboard"] == "not_configured" and body["career"] is None



# --- Market insights -------------------------------------------------------------------

def test_market_insights(student_client, store):
    body = student_client(TRANSFER_JUNIOR).get(f"/api/market/{TRANSFER_JUNIOR}").json()
    entry = store.employment[store.employment["seniority_level"] == "Entry"]
    assert body["scope"]["entry_role_count"] == len(entry)
    assert body["clearance_share"] == round(float(entry["requires_clearance"].mean()), 3)
    shares = [s["share"] for s in body["skill_demand"]]
    assert shares == sorted(shares, reverse=True)
    statuses = {s["skill"]: s["status"] for s in body["skill_demand"]}
    assert statuses["Algorithms"] == "have" and statuses["SQL"] == "missing"
    assert all(b["status"] == "missing" for b in body["bridge_skills"])
    assert all(b["course"] in store.catalog for b in body["bridge_skills"] if b["course"])
    assert abs(sum(body["placement"].values()) - 1) < 0.01
    for role in body["similar_roles"]:
        assert role["start_year"] >= 2023 and 0 < role["coverage"] <= 1
        assert set(role["matched_skills"]).isdisjoint(role["missing_skills"])
    # Salaries are nominal: first-job median equals the raw median of alumni first-job salaries.
    employed = store.alumni[store.alumni["first_job_annual_salary_usd"].astype(str) != "Not Applicable"]
    assert body["first_job_salary"]["median"] == round(float(employed["first_job_annual_salary_usd"].astype(int).median()))


def test_market_major_filter_and_first_term(student_client, advisor_client, store):
    body = student_client(FIRST_TERM).get(f"/api/market/{FIRST_TERM}", params={"major": "Information Systems"}).json()
    assert body["scope"]["major"] == "Information Systems"
    assert body["scope"]["alumni_count"] == int((store.alumni["major"] == "Information Systems").sum())
    assert body["role_skill_coverage"] == 0 and body["similar_roles"] == []
    assert student_client(FIRST_TERM).get(f"/api/market/{FIRST_TERM}", params={"major": "Art"}).status_code == 422
    assert student_client(FIRST_TERM).get(f"/api/market/{TRANSFER_JUNIOR}").status_code == 403
    assert advisor_client.get(f"/api/market/{TRANSFER_JUNIOR}").status_code == 200


def test_cors_preflight_allows_write_methods(base_client):
    for method in ["POST", "PUT", "PATCH", "DELETE"]:
        response = base_client.options(
            "/api/students/CID-116490/career-goal",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": method,
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
        assert response.status_code == 200, method
        assert method in response.headers["access-control-allow-methods"]
