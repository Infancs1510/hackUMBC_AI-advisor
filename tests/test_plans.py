from tests.conftest import FIRST_TERM, IS_FRESHMAN, TRANSFER_JUNIOR


def statuses(validation):
    return {c["course_id"]: c["status"] for c in validation["courses"]}


def test_validate_plan_against_catalog_and_record(student_client):
    client = student_client(TRANSFER_JUNIOR)
    v = client.post(f"/api/plans/{TRANSFER_JUNIOR}/validate", json={
        "courses": ["CMSC447", "cmsc411", "CMSC341", "CMSC313", "CMSC448", "CMSC999", "CMSC447"],
    }).json()
    s = statuses(v)
    assert s["CMSC447"] == "ok"                 # prerequisites met now
    assert s["CMSC411"] == "ok"                 # needs CMSC313, which is in progress this term
    assert s["CMSC341"] == "blocked"            # already completed
    assert s["CMSC313"] == "blocked"            # in progress this term
    assert s["CMSC448"] == "blocked"            # needs CMSC345; also Fall-only
    assert s["CMSC999"] == "blocked"            # not in the catalog
    assert len(v["courses"]) == 6               # duplicates dropped
    assert v["blocked"] and v["category"] == "prereq"
    assert "CMSC421" in v["missing_required"] and "CMSC447" not in v["missing_required"]
    assert v["total_credits"] == sum(c["credits"] for c in v["courses"])


def test_plan_review_workflow(student_client, advisor_client):
    student = student_client(TRANSFER_JUNIOR)
    view = student.get(f"/api/plans/{TRANSFER_JUNIOR}").json()
    assert view["plan"] is None and view["suggested"] and "don't register" in view["notice"]

    bad = student.put(f"/api/plans/{TRANSFER_JUNIOR}", json={"courses": ["CMSC447", "CMSC341"], "note": "First try"}).json()
    assert bad["status"] == "submitted" and bad["validation"]["category"] == "prereq"
    queue = advisor_client.get("/api/plans").json()
    item = next(p for p in queue["plans"] if p["campus_id"] == TRANSFER_JUNIOR)
    assert item["class_level"] == "Junior" and item["gpa"] == 3.0
    assert advisor_client.post(f"/api/plans/{bad['id']}/approve", json={}).status_code == 409
    assert advisor_client.post(f"/api/plans/{bad['id']}/request-changes", json={"note": ""}).status_code == 422
    changed = advisor_client.post(f"/api/plans/{bad['id']}/request-changes", json={"note": "Drop CMSC341, you passed it."}).json()
    assert changed["status"] == "changes_requested"
    assert student.get(f"/api/plans/{TRANSFER_JUNIOR}").json()["plan"]["advisor_note"] == "Drop CMSC341, you passed it."

    good = student.put(f"/api/plans/{TRANSFER_JUNIOR}", json={"courses": ["CMSC447", "CMSC411", "CMSC421", "CMSC441"]}).json()
    assert good["id"] == bad["id"] and good["status"] == "submitted" and good["advisor_note"] == ""
    assert good["validation"]["category"] == "ready" and good["validation"]["total_credits"] == 12
    batch = advisor_client.post("/api/plans-approve-ready").json()
    assert good["id"] in batch["approved"]
    assert student.get(f"/api/plans/{TRANSFER_JUNIOR}").json()["plan"]["status"] == "approved"
    assert advisor_client.post(f"/api/plans/{good['id']}/approve", json={}).status_code == 409  # already decided

    assert student.delete(f"/api/plans/{TRANSFER_JUNIOR}").status_code == 204
    assert student.get(f"/api/plans/{TRANSFER_JUNIOR}").json()["plan"] is None


def test_meeting_category_for_standing_issues(advisor_client, student_client, app):
    at_risk = next(r for r in app.state.caseload.get().students if r.academic_standing == "Academic Probation")
    client = student_client(at_risk.campus_id)
    suggested = client.get(f"/api/plans/{at_risk.campus_id}").json()["suggested"] or ["ENGL100"]
    plan = client.put(f"/api/plans/{at_risk.campus_id}", json={"courses": suggested}).json()
    assert plan["validation"]["category"] == "meeting"
    assert any("Academic Probation" in r for r in plan["validation"]["meeting_reasons"])
    assert plan["id"] not in advisor_client.post("/api/plans-approve-ready").json()["approved"]
    assert advisor_client.get("/api/plans", params={"category": "meeting"}).json()["plans"][0]["campus_id"] == at_risk.campus_id
    client.delete(f"/api/plans/{at_risk.campus_id}")


def test_plan_access(student_client, advisor_client):
    assert student_client(FIRST_TERM).put(f"/api/plans/{IS_FRESHMAN}", json={"courses": ["IS300"]}).status_code == 403
    assert student_client(FIRST_TERM).get(f"/api/plans/{IS_FRESHMAN}").status_code == 403
    assert student_client(FIRST_TERM).get("/api/plans").status_code == 403
    assert advisor_client.put(f"/api/plans/{IS_FRESHMAN}", json={"courses": ["IS300"]}).status_code == 403
    assert advisor_client.get(f"/api/plans/{IS_FRESHMAN}").status_code == 200
    assert student_client(FIRST_TERM).put(f"/api/plans/{FIRST_TERM}", json={"courses": []}).status_code == 422
