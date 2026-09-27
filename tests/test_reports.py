from app.services.reports import KEEP_RUNS, REPORTS


def test_catalog_lists_every_report_with_a_metric(advisor_client, student_client):
    assert student_client().get("/api/reports").status_code == 403
    body = advisor_client.get("/api/reports").json()
    assert [r["key"] for r in body["reports"]] == [r.key for r in REPORTS]
    assert all(r["metric"]["value"] and r["columns"] for r in body["reports"])
    snap = body["snapshot"]
    assert snap["students"] == 1800 and snap["alumni"] == 3200 and snap["next_term"] == "Spring 2027"
    demand = next(r for r in body["reports"] if r["key"] == "course_demand")
    assert demand["chart"] and demand["chart"][0]["value"] >= demand["chart"][-1]["value"]


def run(client, key):
    r = client.post(f"/api/reports/{key}/runs")
    assert r.status_code == 201, r.text
    return r.json()


def test_reports_match_the_data(advisor_client):
    progress = run(advisor_client, "caseload_progress")
    assert progress["row_count"] == 1800 == len(progress["rows"])
    cols = progress["columns"]
    assert all(0 <= row[cols.index("credits_pct")] <= 100 for row in progress["rows"])

    roster = run(advisor_client, "attention_roster")
    rc = roster["columns"]
    assert all(r[rc.index("academic_standing")] != "Good Standing" or r[rc.index("graduation_risk")] == "Yes" for r in roster["rows"])

    gateway = run(advisor_client, "gateway_outcomes")
    gc = gateway["columns"]
    assert {r[0] for r in gateway["rows"]} >= {"CMSC201", "CMSC202", "MATH151"}
    for r in gateway["rows"]:
        assert r[gc.index("d")] + r[gc.index("f")] + r[gc.index("w")] <= r[gc.index("graded_attempts")]
        assert abs(r[gc.index("pass_rate_pct")] + r[gc.index("dfw_rate_pct")] - 100) < 0.2  # A-C + D/F/W = all graded

    alumni = run(advisor_client, "alumni_outcomes")
    assert sum(r[1] for r in alumni["rows"]) <= 3200

    alignment = run(advisor_client, "career_alignment")
    assert sum(r[3] for r in alignment["rows"]) == 1800


def test_runs_are_saved_snapshots(advisor_client):
    first = run(advisor_client, "advising_activity")
    assert advisor_client.get(f"/api/report-runs/{first['id']}").json()["rows"] == first["rows"]
    history = advisor_client.get("/api/report-runs").json()
    assert history["kept"] == KEEP_RUNS and history["runs"][0]["id"] == first["id"]
    assert "rows" not in history["runs"][0]
    assert advisor_client.delete(f"/api/report-runs/{first['id']}").status_code == 204
    assert advisor_client.get(f"/api/report-runs/{first['id']}").status_code == 404
    assert advisor_client.post("/api/reports/nope/runs").status_code == 404


def test_history_keeps_only_recent_runs(advisor_client):
    for _ in range(KEEP_RUNS + 2):
        run(advisor_client, "gateway_outcomes")
    assert len(advisor_client.get("/api/report-runs").json()["runs"]) == KEEP_RUNS
