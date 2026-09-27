import pytest

from app.models.auth import CurrentUser
from app.services.auth import AuthError, AuthService
from tests.conftest import ADVISOR_PASSWORD, ALUMNUS, FIRST_TERM, STUDENT_PASSWORD, TRANSFER_JUNIOR


def login(client, username, password):
    return client.post("/api/auth/login", json={"username": username, "password": password})


# --- Login -------------------------------------------------------------------------------

def test_student_login_and_me(base_client):
    response = login(base_client, TRANSFER_JUNIOR.lower(), STUDENT_PASSWORD)
    assert response.status_code == 200
    body = response.json()
    assert body["user"] == {"role": "student", "campus_id": TRANSFER_JUNIOR, "display_name": TRANSFER_JUNIOR}
    me = base_client.get("/api/auth/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.json()["campus_id"] == TRANSFER_JUNIOR


def test_advisor_login(base_client):
    body = login(base_client, "Advisor", ADVISOR_PASSWORD).json()
    assert body["user"]["role"] == "advisor" and body["user"]["campus_id"] is None


@pytest.mark.parametrize(
    "username,password",
    [
        (TRANSFER_JUNIOR, "wrong"),
        ("CID-000000", STUDENT_PASSWORD),  # unknown ID
        (ALUMNUS, STUDENT_PASSWORD),  # alumni cannot sign in
        ("advisor", STUDENT_PASSWORD),
        ("not-an-id", STUDENT_PASSWORD),
    ],
)
def test_bad_logins_share_one_error(base_client, username, password):
    response = login(base_client, username, password)
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid username or password"


def test_tokens_reject_tampering_and_expiry():
    auth = AuthService("secret", 60, "s", "advisor", "a")
    token = auth.issue(CurrentUser(role="student", campus_id=TRANSFER_JUNIOR, display_name="x")).token
    assert auth.verify(token).campus_id == TRANSFER_JUNIOR

    payload, signature = token.split(".")
    forged = auth.issue(CurrentUser(role="advisor", campus_id=None, display_name="x")).token.split(".")[0]
    with pytest.raises(AuthError):
        auth.verify(f"{forged}.{signature}")
    with pytest.raises(AuthError):
        AuthService("other-secret", 60, "s", "advisor", "a").verify(token)
    with pytest.raises(AuthError):
        auth.verify(token, now=10**12)
    with pytest.raises(AuthError):
        auth.verify("garbage")


# --- Access rules ------------------------------------------------------------------------

def test_endpoints_require_sign_in(base_client):
    assert base_client.get(f"/api/dashboard/{TRANSFER_JUNIOR}").status_code == 401
    assert base_client.get(f"/api/alumni/{ALUMNUS}").status_code == 401
    assert base_client.get("/api/caseload").status_code == 401
    assert base_client.post("/api/advisor", json={"campus_id": TRANSFER_JUNIOR, "message": "hi"}).status_code == 401
    bad = base_client.get(f"/api/dashboard/{TRANSFER_JUNIOR}", headers={"Authorization": "Bearer nope"})
    assert bad.status_code == 401
    # Public aggregate data stays open.
    assert base_client.get("/api/health").status_code == 200
    assert base_client.get("/api/careers").status_code == 200


def test_student_sees_only_self(student_client):
    client = student_client(TRANSFER_JUNIOR)
    assert client.get(f"/api/dashboard/{TRANSFER_JUNIOR}").status_code == 200
    assert client.get(f"/api/dashboard/{FIRST_TERM}").status_code == 403
    assert client.get(f"/api/alumni/{ALUMNUS}").status_code == 403
    assert client.get("/api/caseload").status_code == 403
    assert client.post("/api/advisor", json={"campus_id": FIRST_TERM, "message": "hi"}).status_code == 403


def test_advisor_sees_everyone_but_not_student_chat(advisor_client):
    assert advisor_client.get(f"/api/dashboard/{FIRST_TERM}").status_code == 200
    assert advisor_client.get(f"/api/alumni/{ALUMNUS}").status_code == 200
    assert advisor_client.get("/api/caseload").status_code == 200
    # AI chat and memory are personal to the student.
    assert advisor_client.post("/api/advisor", json={"campus_id": FIRST_TERM, "message": "hi"}).status_code == 403
    assert advisor_client.get(f"/api/advisor/{FIRST_TERM}/memories").status_code == 403


# --- Caseload ----------------------------------------------------------------------------

def test_caseload_lists_all_students_with_flags(advisor_client, store):
    body = advisor_client.get("/api/caseload", params={"page_size": 100}).json()
    assert body["total"] == len(store.students)
    assert len(body["students"]) == 100
    counts = body["facets"]["flag_counts"]
    standing = store.students["academic_standing"].isin(["Academic Warning", "Academic Probation"]).sum()
    assert counts["academic_standing"] == standing
    upper = store.students[store.students["class_level"].isin(["Junior", "Senior"])]
    assert counts["no_internship"] == (upper["internship_count"] == 0).sum()
    # Default sort puts the most severe flags first (standing and graduation risk weigh 3, others 1).
    from app.services.caseload import FLAG_SEVERITY

    severity = [sum(FLAG_SEVERITY[f["code"]] for f in s["flags"]) for s in body["students"]]
    assert severity == sorted(severity, reverse=True)


def test_caseload_filters(advisor_client):
    body = advisor_client.get("/api/caseload", params={"flag": "academic_standing", "page_size": 100}).json()
    assert body["total"] > 0
    assert all(s["academic_standing"] != "Good Standing" for s in body["students"])

    body = advisor_client.get("/api/caseload", params={"q": TRANSFER_JUNIOR.lower()}).json()
    assert [s["campus_id"] for s in body["students"]] == [TRANSFER_JUNIOR]

    body = advisor_client.get(
        "/api/caseload", params={"major": "Information Systems", "class_level": "Senior", "sort": "gpa_asc"}
    ).json()
    assert all(s["major"] == "Information Systems" and s["class_level"] == "Senior" for s in body["students"])
    gpas = [s["gpa"] for s in body["students"] if s["gpa"] is not None]
    assert gpas == sorted(gpas)


def test_caseload_first_term_student_has_no_top_career(advisor_client):
    row = advisor_client.get("/api/caseload", params={"q": FIRST_TERM}).json()["students"][0]
    assert row["gpa"] is None
    assert row["top_career"] is None and row["top_career_score"] == 0
