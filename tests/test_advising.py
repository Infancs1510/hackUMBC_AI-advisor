from collections import Counter

from tests.conftest import FIRST_TERM, IS_FRESHMAN, TRANSFER_JUNIOR, FakeMemory


def all_rows(client, **params):
    return client.get("/api/caseload", params={"page_size": 100, **params}).json()


def test_graduation_risk_flag_matches_roadmap(advisor_client, store, profiles):
    from app.services.roadmap import build_roadmap

    body = all_rows(advisor_client, flag="graduation_risk")
    assert body["total"] > 0
    for row in body["students"][:10]:
        # Career choice must not change graduation risk: degree courses always come first.
        for career in [None, "Cybersecurity", "Health IT"]:
            roadmap = build_roadmap(store, profiles, row["campus_id"], career)
            assert any(t.after_expected_graduation for t in roadmap.terms)
    first = advisor_client.get("/api/caseload", params={"q": TRANSFER_JUNIOR}).json()["students"][0]
    # CMSC447 is eligible now; CMSC411/421/441 open up once this term's courses finish.
    assert first["remaining_required_count"] == 4
    assert set(first["next_required"]) == {"CMSC447", "CMSC411", "CMSC421", "CMSC441"}


def test_flagged_filter(advisor_client):
    body = all_rows(advisor_client, flagged=True)
    assert body["total"] == advisor_client.get("/api/advisor-dashboard").json()["flagged_students"]
    assert all(s["flags"] for s in body["students"])


def test_review_workflow(advisor_client, student_client):
    put = advisor_client.put(f"/api/caseload/{IS_FRESHMAN}/review", json={"note": "Discussed IS300 timing"})
    assert put.status_code == 200 and put.json()["note"] == "Discussed IS300 timing"
    row = advisor_client.get("/api/caseload", params={"q": IS_FRESHMAN}).json()["students"][0]
    assert row["reviewed_at"] and row["review_note"] == "Discussed IS300 timing"
    unreviewed = {r["campus_id"] for r in all_rows(advisor_client, reviewed=False, q=IS_FRESHMAN)["students"]}
    assert IS_FRESHMAN not in unreviewed
    assert student_client(IS_FRESHMAN).put(f"/api/caseload/{IS_FRESHMAN}/review", json={"note": "x"}).status_code == 403
    assert advisor_client.put("/api/caseload/CID-000000/review", json={"note": ""}).status_code == 404
    assert advisor_client.delete(f"/api/caseload/{IS_FRESHMAN}/review").status_code == 204
    assert advisor_client.get("/api/caseload", params={"q": IS_FRESHMAN}).json()["students"][0]["reviewed_at"] is None


def test_advisor_dashboard_summary(advisor_client, student_client, store, app):
    body = advisor_client.get("/api/advisor-dashboard").json()
    assert body["total_students"] == len(store.students) == sum(body["by_major"].values())
    assert body["standing_counts"]["Academic Probation"] == int((store.students["academic_standing"] == "Academic Probation").sum())
    assert sum(t["count"] for t in body["tracks"]) == len(store.students)
    caseload = app.state.caseload.get().students
    demand = Counter(c for r in caseload for c in r.next_required)
    assert [(d["course_id"], d["students"]) for d in body["course_demand"]] == demand.most_common(len(body["course_demand"]))
    assert body["flagged_students"] == sum(1 for r in caseload if r.flags)
    assert body["rising_career"]["shift"]["change_pts"] > 0
    assert student_client(TRANSFER_JUNIOR).get("/api/advisor-dashboard").status_code == 403


def test_meeting_request_loop(make_client, advisor_client):
    created = advisor_client.post("/api/meeting-requests", json={
        "campus_id": FIRST_TERM, "reason": "degree_check", "message": "Let's plan your spring schedule.",
    })
    assert created.status_code == 201
    request_id = created.json()["id"]
    assert advisor_client.post("/api/meeting-requests", json={"campus_id": FIRST_TERM, "reason": "degree_check"}).status_code == 409

    student = make_client(memory=FakeMemory(), as_student=FIRST_TERM)
    mine = student.get("/api/meeting-requests").json()["requests"]
    assert [r["id"] for r in mine] == [request_id] and mine[0]["reason_label"] == "Degree progress check"
    other = make_client(as_student=TRANSFER_JUNIOR)
    assert other.get("/api/meeting-requests").json()["requests"] == []
    assert other.post(f"/api/meeting-requests/{request_id}/dismiss").status_code == 403
    assert other.post("/api/meeting-requests", json={"campus_id": FIRST_TERM, "reason": "degree_check"}).status_code == 403

    # Booking an appointment answers the request, and the advisor can mark it completed.
    slot = next(s["start"] for d in student.get("/api/appointments/slots").json()["days"] for s in d["slots"] if s["available"])
    appt = student.post("/api/appointments", json={"reason": "degree_check", "modality": "virtual", "start": slot}).json()
    assert student.get("/api/meeting-requests").json()["requests"] == []
    assert student.post(f"/api/appointments/{appt['id']}/complete").status_code == 403
    done = advisor_client.post(f"/api/appointments/{appt['id']}/complete").json()
    assert done["status"] == "completed"
    assert advisor_client.post(f"/api/appointments/{appt['id']}/complete").status_code == 409
    assert all(a["id"] != appt["id"] for a in advisor_client.get("/api/appointments").json()["appointments"])


def test_student_can_dismiss_request(make_client, advisor_client):
    created = advisor_client.post("/api/meeting-requests", json={"campus_id": IS_FRESHMAN, "reason": "career_planning"}).json()
    student = make_client(as_student=IS_FRESHMAN)
    assert student.post(f"/api/meeting-requests/{created['id']}/dismiss").json()["status"] == "dismissed"
    assert student.get("/api/meeting-requests").json()["requests"] == []


def test_track_filter(advisor_client, store):
    body = all_rows(advisor_client, track="Cybersecurity Management")
    assert body["total"] == int((store.students["track"] == "Cybersecurity Management").sum())
    assert all(s["track"] == "Cybersecurity Management" for s in body["students"])
    assert "Health Information Technology" in body["facets"]["tracks"]


def test_pathway_analytics(advisor_client, student_client, store, app):
    body = advisor_client.get("/api/analytics/pathways").json()
    k = body["kpis"]
    assert k["total_students"] == len(store.students)
    assert k["on_pace"] + body["levels"][0]["graduation_risk"] <= k["total_students"]
    assert sum(k["gpa_bands"].values()) == k["total_students"]
    assert sum(l["students"] for l in body["levels"]) == k["total_students"]
    assert sum(t["students"] for t in body["tracks"]) == k["total_students"]
    assert 2.0 < k["major_core_average"] < 4.0
    # Bottlenecks are sorted by D/F/W rate and grounded in the transcripts.
    rates = [b["dfw_rate"] for b in body["bottlenecks"]]
    assert rates == sorted(rates, reverse=True) and rates[0] > body["dfw_median"]
    t = store.transcripts
    top = body["bottlenecks"][0]
    done = t[(t["course_id"] == top["course_id"]) & (t["grade"] != "IP")]
    assert top["dfw_rate"] == round(float(done["grade"].isin(["D", "F", "W"]).mean()), 3)
    # Internship insight comes from alumni.csv.
    i = body["internship_insight"]
    assert i["return_offers"] == int((store.alumni["first_job_found_via"] == "Return Offer from Internship").sum())
    # Every meeting intervention targets real current students.
    for iv in body["interventions"]:
        if iv["action"] and iv["action"]["type"] == "meetings":
            assert iv["action"]["campus_ids"] and all(store.is_student(c) for c in iv["action"]["campus_ids"])
    assert student_client(TRANSFER_JUNIOR).get("/api/analytics/pathways").status_code == 403
