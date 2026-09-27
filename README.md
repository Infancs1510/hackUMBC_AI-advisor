# HackUMBC 2026 — Career Intelligence Backend

Python/FastAPI backend for a UMBC career-intelligence dashboard built for HackUMBC 2026.

The application uses the supplied synthetic student, alumni, course, transcript, experience, and employment datasets to help current students explore skills, careers, salary outcomes, and academic pathways.

It also provides an AI career advisor powered by Gemini with conversational memory through Backboard.

---

## Architecture

The backend intentionally separates factual data, analytics, memory, and AI generation.

```text
                   ┌──────────────────────┐
                   │  HackUMBC CSV Data   │
                   │                      │
                   │ Students             │
                   │ Alumni               │
                   │ Transcripts          │
                   │ Courses              │
                   │ Experiences          │
                   │ Employment           │
                   └──────────┬───────────┘
                              │
                              ▼
                   ┌──────────────────────┐
                   │    Python Backend    │
                   │                      │
                   │ Profile calculations │
                   │ Skill extraction     │
                   │ Career matching      │
                   │ Salary analytics     │
                   │ Pathways             │
                   └──────────┬───────────┘
                              │
                ┌─────────────┴─────────────┐
                ▼                           ▼
       ┌────────────────┐          ┌────────────────┐
       │   Backboard    │          │     Gemini     │
       │                │          │                │
       │ User memory    │          │ AI responses   │
       │ Preferences    │          │ Explanations   │
       │ Goals          │          │ Conversation   │
       └────────────────┘          └────────────────┘
```

### Source of truth

The supplied dataset is the source of truth for factual student, alumni, course, transcript, experience, employment, and salary information.

### Python

Python calculates derived information from the dataset.

### Backboard

Backboard stores useful conversational memory and user preferences.

### Gemini

Gemini turns structured backend information into natural-language career guidance.

Gemini is not used as a database.

---

# Dataset

The project uses the synthetic HackUMBC 2026 dataset.

The dataset includes:

| File                     | Purpose                            |
| ------------------------ | ---------------------------------- |
| `students_current.csv`   | Current Fall 2026 students         |
| `alumni.csv`             | Historical graduates               |
| `transcripts.csv`        | Course attempts                    |
| `employment_history.csv` | Alumni employment history          |
| `student_experience.csv` | Student activities and experiences |
| `course_catalog.csv`     | Course information and skills      |

The dataset contains both current students and historical alumni.

`employment_history.csv` is alumni-only.

A `campus_id` belongs to either a current student or an alumnus, not both.

---

# Core features

## Student profile

The backend calculates:

* GPA
* credits earned
* completed courses
* internships
* co-ops
* certifications
* engagement
* skills

---

## Skill extraction

Student skills are derived from completed courses:

```text
Student
   ↓
Transcript
   ↓
Completed courses
   ↓
Course catalog
   ↓
Skill tags
   ↓
Student skill set
```

The skill vocabulary comes directly from the dataset.

---

## Career matching

Historical alumni employment data is used to identify skills associated with different careers.

A career match is based on skill overlap.

For example:

```text
Student:
Python
SQL
Statistics

Career:
Data Engineer

Matched:
Python
SQL

Missing:
ETL
Cloud
```

The match score represents skill overlap.

It should not be interpreted as a probability of employment or career success.

---

## Salary analytics

Salary statistics are calculated from the supplied employment records.

Supported statistics include:

* sample size
* median
* 25th percentile
* 75th percentile
* minimum
* maximum

The supplied salaries are nominal dollars for the year the job started.

The application does not silently inflation-adjust salaries.

---

## Career pathways

The pathway engine connects:

```text
Current skills
      ↓
Missing skills
      ↓
Relevant courses
      ↓
Relevant experiences
      ↓
Career
```

Recommended courses must exist in the supplied course catalog.

---

# AI Career Advisor

## Endpoint

```http
POST /api/advisor
```

Example request:

```json
{
  "campus_id": "CID-123456",
  "message": "What should I take next semester?"
}
```

The backend gathers relevant information before calling Gemini.

```text
Student data
     +
Calculated skills
     +
Career/pathway information
     +
Backboard memory
     ↓
Structured AI context
     ↓
Gemini
     ↓
Advisor response
```

Raw CSV files are not sent directly to Gemini.

---

# AI Memory

Backboard is used for personalized conversational memory.

## Information that belongs in Backboard

Examples:

```text
Career interests
Career goals
Industry preferences
Course preferences
Internship goals
Previously discussed career plans
Relevant conversation context
```

Example:

```json
{
  "career_interests": [
    "Data Engineering"
  ],
  "goals": [
    "Get an internship before junior year"
  ],
  "preferences": [
    "Prefer courses with fewer prerequisites"
  ]
}
```

## Information that does NOT belong in Backboard

Do not use AI memory as the authoritative source for:

* GPA
* transcript
* completed courses
* credits
* official major
* official graduation year
* salary statistics
* employment records
* course catalog information
* calculated career statistics

These are retrieved/calculated by the backend.

For example, if a student tells the AI:

> "I think my GPA is 3.8."

The system should not overwrite the student's actual GPA.

The backend should retrieve the GPA from the dataset.

---

# Why this separation matters

The architecture prevents AI memory from becoming inconsistent with the academic dataset.

```text
                    FACTS
                      │
                      ▼
                Dataset / DB
                      │
                      ▼
                 Python
                      │
              ┌───────┴───────┐
              ▼               ▼
        Calculations       AI Context
                              │
                     ┌────────┴────────┐
                     ▼                 ▼
                Backboard          Gemini
                  memory          response
```

This means:

* Academic facts remain deterministic.
* Career calculations remain reproducible.
* AI memory personalizes conversations.
* Gemini explains rather than invents data.

---

# API

## Authentication

This is a simple demo login, not production authentication.

```http
POST /api/auth/login   {"username": "CID-116490", "password": "umbc-demo"}
GET  /api/auth/me
```

* **Students** sign in with their campus ID and the shared `STUDENT_DEMO_PASSWORD`. Only current students can sign in.
* **Advisors** sign in with `ADVISOR_USERNAME` / `ADVISOR_PASSWORD`.
* Login returns a bearer token (HMAC-signed with `AUTH_SECRET`, valid for 8 hours). Send it as `Authorization: Bearer <token>`.
* Every failed login returns the same `401`, so the response doesn't reveal which IDs exist.

| Endpoint | Signed out | Student | Advisor |
| --- | --- | --- | --- |
| `/api/health`, `/api/careers*` | ✓ | ✓ | ✓ |
| `/api/dashboard/{id}`, `/api/degree/{id}`, `/api/roadmap/{id}`, `/api/market/{id}` | 401 | own ID only | any student |
| `/api/alumni/{id}` | 401 | 403 | ✓ |
| `/api/caseload` | 401 | 403 | ✓ |
| `/api/advisor`, `/api/advisor/{id}/memories`, `/api/students/{id}/career-goal` | 401 | own ID only | 403 (chat, memory and goals are personal) |

---

## Health

```http
GET /api/health
```

Returns backend status.

---

## Caseload (advisors)

```http
GET /api/caseload?q=&major=&class_level=&standing=&career=&flag=&sort=flags&page=1&page_size=25
```

Lists every current student with their GPA, credits, standing, internships, top career match, and attention flags. It also returns filter options and the number of students with each flag. The caseload is precomputed at startup.

Flags are calculated from the dataset:

| Flag | Rule |
| --- | --- |
| `academic_standing` | Academic Warning or Academic Probation |
| `no_internship` | Junior or Senior with no internship or co-op |
| `low_career_match` | Junior or Senior whose top career match is below 30 (the junior median is 50) |

`sort` is one of `flags`, `campus_id`, `gpa_asc`, `gpa_desc`, `match_asc`, `match_desc`.

---

## Dashboard

```http
GET /api/dashboard/{campus_id}
```

Returns the data required to render the student's dashboard.

Optional query parameter: `?career=Cybersecurity` builds the pathway and salary for that career instead of the top match (case-insensitive).

Alumni IDs return `404` with `"is_alumnus": true`; use the alumni endpoint for them.

Example structure:

```json
{
  "student": {
    "campus_id": "CID-116490",
    "major": "Computer Science",
    "track": "Data Science",
    "class_level": "Junior",
    "gpa": 3.0,
    "calculated_gpa": 3.0,
    "credits_earned": 76,
    "credits_in_progress": 15,
    "internship_count": 1,
    "credential_count": 2,
    "completed_courses": [],
    "in_progress_courses": [],
    "internships": [],
    "credentials": [],
    "activities": []
  },
  "skills": [{ "skill": "Algorithms", "courses": ["CMSC341"] }],
  "in_progress_skills": [],
  "career_matches": [
    {
      "career": "Software Engineering",
      "score": 33.7,
      "projected_score": 43.0,
      "matched_skills": ["Algorithms", "Data Structures"],
      "missing_skills": ["Testing", "Version Control"],
      "missing_core_skills": ["Testing", "Version Control"]
    }
  ],
  "selected_career": "Software Engineering",
  "pathway": {
    "career": "Software Engineering",
    "next_term": "Spring 2027",
    "recommended_courses": [
      {
        "course_id": "CMSC345",
        "title": "Software Design and Development",
        "status": "eligible",
        "skills_gained": ["Software Design", "Testing", "Git"],
        "offered_next_term": true,
        "missing_prerequisites": []
      }
    ],
    "prerequisite_steps": [],
    "skills_not_covered_by_catalog": [],
    "alumni_outcomes": {
      "alumni_count": 481,
      "share_with_internship": 0.748,
      "first_job_remote_share": 0.146,
      "found_via": {}
    }
  },
  "salary": {
    "entry_level": { "sample_size": 651, "median": 74000, "p25": 66250, "p75": 83750 },
    "by_seniority": {},
    "entry_level_by_start_year": []
  }
}
```

Arrays are abbreviated above. Field notes:

* `gpa` is `null` for first-term students. `calculated_gpa` is recomputed from transcripts as a check.
* `projected_score` is the match score if in-progress courses are completed. It breaks ties for first-term students, who all score 0.
* Course `status` is `eligible`, `eligible_after_current_term` (prerequisite in progress), or `needs_prerequisites`. `prerequisite_steps` lists the takeable courses that unlock blocked recommendations.
* Prerequisites of courses a student has passed count as satisfied, since transfer credit has no transcript rows.

---

## Degree audit

```http
GET /api/degree/{campus_id}
```

The degree audit for a current student. The student can see their own; advisors can see any student's. It returns:

* the transcript grouped by `requirement_category` (Major Core, Major Elective, Supporting Coursework, General Education), with completed and in-progress credits for each;
* **remaining required courses**: catalog courses whose `required_for_majors` includes the student's major and that the student hasn't taken, each with a prerequisite status and whether it's offered next term;
* **courses satisfied by prior credit**: required courses implied by transfer credit (for example, CMSC201 when the student passed CMSC202);
* F and W attempts;
* a credit summary: earned, in progress, remaining after this term, upper-division, and transfer credits.

The dataset doesn't define how many credits each category requires, so the audit reports only credits completed, never "X of Y".

---

## Roadmap

```http
GET /api/roadmap/{campus_id}?career=
```

A suggested term-by-term plan toward graduation and a target career. The target defaults to the student's top match. The student can see their own; advisors can see any student's.

How the plan is built:

1. **Targets:** the major's remaining required courses, plus career courses chosen by a cost-aware greedy set cover. Each course's value is its weighted coverage of the career's missing skills divided by 1 + the prerequisites it would add, within a budget of 6 extra courses.
2. **Prerequisites:** unmet prerequisites are added transitively.
3. **Scheduling:** courses are placed from Spring 2027 onward (Spring and Fall only), in terms when they're typically offered and after their prerequisites, with at most 4 per term. Courses that unlock the longest chains go first.
4. **After expected graduation:** only required courses are still placed. Career courses that don't fit are listed in `unscheduled`, and the skills still missing are listed in `skills_after_plan_missing`.

Each term reports the match score once it's complete. General education and elective credits are not planned.

---

## Market insights

```http
GET /api/market/{campus_id}?major=Computer%20Science
```

A market view built from **alumni outcomes, not live job postings**. The alumni's entry-level job records stand in for the market. The student can see their own; advisors can see any student's. `major` limits the view to alumni of one major.

It returns:

* headline figures: entry-level role counts, the median first-job salary (nominal) overall and by major, and the clearance and remote shares;
* **career shifts:** each career's change in share of entry roles between 2015–2020 and 2023–2026, in percentage points;
* **skill demand:** the top skills in entry roles, their trend, and whether the student has each one (or which catalog course teaches it);
* **rising skills;**
* **industry placement:** alumni first-job industries with the median salary for each, and first-destination shares among alumni who reported an outcome;
* **personal fit:** the average share of a recent entry role's skills the student has, the most in-demand skills they're missing (with a course for each), and the recent alumni roles (2023–26) most like their skill set.

---

## Career goal

```http
GET /api/students/{campus_id}/career-goal
PUT /api/students/{campus_id}/career-goal   {"career": "Cybersecurity"}
```

Saves the student's primary career goal in **Backboard memory**, since a goal is a preference, not an academic fact. Saving a new goal replaces the previous one. The AI advisor sees the goal in its memory search and focuses on that career. Only the student can use this endpoint.

---

## Appointments

```http
GET  /api/appointments/slots
GET  /api/appointments?include_past=false
POST /api/appointments                 {"reason": "course_planning", "modality": "virtual", "start": "2026-09-29T10:00:00-04:00", "notes": "..."}
PATCH /api/appointments/{id}           {"start": "...", "modality": "...", "notes": "..."}
POST /api/appointments/{id}/cancel
POST /api/appointments/{id}/complete          advisor
POST /api/appointments/{id}/no-show           advisor, once the appointment has started
GET  /api/appointments/schedule?week=         advisor week view (any date in the week; weekends show the coming week)
PUT  /api/appointments/{id}/session-note      advisor {"note": "..."}; empty clears it
```

Advising appointments are **data the app creates**, so they're stored in a small SQLite database (`APP_DB_PATH`, default `app_data/app.db`, git-ignored), separate from the read-only CSVs.

* **Slots:** 30-minute sessions on weekdays (six a day) for the next two working weeks, in `ADVISING_TIMEZONE` (default America/New_York), with at least 2 hours' notice.
* **Booking rules:** a database index makes double-booking a slot impossible, and each student can have only one upcoming appointment (change it with reschedule).
* **Advising brief:** when a student books, the backend saves a brief from their record for the advisor: GPA, credits, standing, expected graduation, remaining required courses, top career match, and the saved career goal from Backboard.
* **Access:** students book, reschedule and cancel their own appointments. Advisors see everyone's upcoming appointments with the briefs, and can cancel them.
* **Advisor week view:** every Monday–Friday slot with its state (open, unbooked, booked, completed, no-show), the appointment and brief, cancelled appointments, and weekly totals.
* **Session notes:** private advisor notes per appointment. They're returned only by the advisor schedule endpoint and never to students.
* **No email:** nothing is sent. The page offers an `.ics` "Add to calendar" download.

---

## Reports

```http
GET    /api/reports                    catalog: every report with a live headline figure, plus a data snapshot
POST   /api/reports/{key}/runs         build from current data and save a snapshot (columns + rows)
GET    /api/report-runs                saved snapshots, newest first (the most recent 30 are kept)
GET    /api/report-runs/{id}
DELETE /api/report-runs/{id}
```

Advisor-only. Reports: `caseload_progress`, `attention_roster` (warning/probation or graduation risk, with review notes, meeting requests and appointments), `gateway_outcomes` (lower-level core courses: pass and D/F/W rates and repeats, across all transcripts, IP excluded), `career_alignment`, `alumni_outcomes` (first job family, nominal median salary), `advising_activity` (everything recorded in the app), and `course_demand` (remaining required courses students can take next term — an estimate, not registration data). The page builds the CSV and a printable view (save as PDF from the print dialog) in the browser.

---

## Resume & portfolio

```http
GET    /api/resume/{campus_id}?career=           latest resume + analysis
POST   /api/resume/{campus_id}                    multipart "file": PDF, DOCX, TXT or MD (2 MB max)
DELETE /api/resume/{campus_id}
POST   /api/resume/{campus_id}/ai-feedback?career=
GET    /api/portfolio/{campus_id}
POST   /api/portfolio/{campus_id}/projects        {"title", "description", "link", "skills"}
DELETE /api/portfolio/{campus_id}/projects/{id}
```

* **Storage:** only the latest resume is kept, in the app SQLite database. It is never saved to Backboard, and it's sent to Gemini only when the student requests AI suggestions.
* **Readiness score:** from a published rubric, **not an ATS score**. Every component is shown.

  | Component | Weight | What it measures |
  | --- | --- | --- |
  | Target-career keywords | 35% | Coverage weighted by how often alumni roles listed each skill |
  | Verified skills listed | 25% | Share of in-demand skills from completed courses that appear on the resume |
  | Quantified bullets | 20% | Bullets with a number, % or $, ignoring years and dates |
  | Structure | 20% | Section headings, a contact email, and length |

  Components that don't apply (e.g. no completed courses yet) are left out, and the other weights are rescaled.
* **Skill detection:** uses the dataset's 119-skill vocabulary with a small alias table (GitHub → Git / Version Control, PostgreSQL → SQL, Docker → Containers…). The single-letter skills C and R only count as list items.
* **Findings come from the record:**
  * skills earned in completed courses but missing from the resume (with the courses);
  * internships, research, hackathons and competitive teams on record that the resume doesn't mention;
  * core career skills not covered by the resume or courses;
  * unquantified bullets and missing sections;
  * skills claimed without course evidence.
* **AI suggestions:** Gemini is told to suggest only what the findings or the resume support and to use placeholders like `[N%]` instead of inventing metrics.
* **Portfolio:**
  * *verified* items from the record: internships, co-ops, research, hackathons, competitive teams, certifications, and completed upper-level courses with their skills;
  * *self-reported* projects the student adds. Their skills are limited to the dataset vocabulary, so they line up with career matching.

Students manage their own resume and projects. Advisors can view a student's portfolio but not their resume.

---

## Advisor workflow

```http
GET    /api/advisor-dashboard
GET    /api/caseload?reviewed=false&flagged=true&flag=graduation_risk&track=Cybersecurity
PUT    /api/caseload/{campus_id}/review      {"note": "..."}
DELETE /api/caseload/{campus_id}/review
POST   /api/meeting-requests                 {"campus_id", "reason", "message"}   (advisor)
GET    /api/meeting-requests                 (students: their own open requests; advisors: all open)
POST   /api/meeting-requests/{id}/dismiss
POST   /api/appointments/{id}/complete       (advisor)
```

* **Dashboard summary:**
  * caseload counts by major and class level, standing counts, flag counts, and reviewed/unreviewed counts;
  * upcoming appointments;
  * the track distribution, and the top-career distribution;
  * next-term **course demand**: remaining required courses students can take next term, counted across the caseload;
  * the fastest-rising alumni career, with how many students top-match it.
* **Graduation-risk flag:** set when a degree-only roadmap can't fit a student's remaining required courses before their expected graduation. It ignores career targets, because the planner always schedules degree courses before career electives.
* **Reviews and meeting requests:** stored in the app database alongside appointments. A student sees an open request on their Appointments page, and booking any appointment answers it.
* **Caseload build:** the caseload (with a roadmap per student) and the pathway analytics are built in a background thread at startup and cached.

```http
GET /api/analytics/pathways     (advisor)
```

Cohort analytics for all current students:

* **KPIs:**
  * **on pace:** the share whose degree plan fits before expected graduation;
  * the credit-weighted Major Core average grade, and GPA bands;
  * **foundation complete:** sophomores and above with no lower-division required courses left;
  * internship participation for juniors and seniors.
* **Tracks and class levels:** per track, students, average GPA, capstone readiness (CMSC447 / IS450) and top career matches; per class level, on-pace vs graduation-risk counts.
* **Course bottlenecks:** the highest historical D/F/W rates across students and alumni (200+ attempts). Rated "high" at 1.7× the median and "moderate" at 1.4×. Each shows current enrolment, next-term demand, and students with an unfinished F/W.
* **Career alignment:** per career, the students who top-match it, the alumni share trend, how many have every core skill, and the **bridge course** that would give the most of them a missing core skill.
* **Interventions:** rules over the analytics above, each with an action (batch meeting requests, or a pre-filtered roster link).

There are no seat counts, waitlists or pass-rate targets in the dataset, so none are shown.

---

## Registration plans

```http
GET    /api/plans/{campus_id}              student's next-term plan + roadmap suggestions (student or advisor)
POST   /api/plans/{campus_id}/validate     check a draft {"courses": [...]}
PUT    /api/plans/{campus_id}              submit / resubmit {"courses": [...], "note": "..."}
DELETE /api/plans/{campus_id}              withdraw
GET    /api/plans?status=&category=        advisor review queue
POST   /api/plans/{id}/approve             {"note": "..."}           (blocked plans can't be approved)
POST   /api/plans/{id}/request-changes     {"note": "..."}           (note required)
POST   /api/plans-approve-ready            batch-approve every "ready" plan
```

This is an in-app review of students' next-term course plans. **It doesn't register students or change university holds**; the UI says so.

* **Course checks:** each course is checked against the catalog and the student's record.
  * **Blocked:** not in the catalog, already completed (including transfer credit implied by later courses), in progress now, or missing a prerequisite after this term.
  * **Warning:** not usually offered in Spring.
  * **Credit load:** under 12 or over 18 credits is flagged.
* **Categories:**
  * **meeting:** the student is on academic warning or probation, or has graduation risk. These never batch-approve.
  * **prereq:** any course is blocked or has a warning.
  * **ready:** everything else.
* **Demo data:** `python -m scripts.seed_demo_plans` adds about 12 plans marked `[demo]` so the queue has something in it; `--clear` removes them.

---

## Alumni

```http
GET /api/alumni/{campus_id}
```

Returns an alum's degree record, first destination, first job, full employment history, experiences, coursework skills, and how that coursework matched each career (including the career of their first job).

`first_job` is `null` and `employment_history` is empty for alumni who did not report employment.

---

## Career list

```http
GET /api/careers
```

Returns available careers derived from employment data.

A career is a `job_family` in `employment_history.csv` (8 in total). Its skill profile is how often each skill appears in `role_skill_tags` for **entry-level** job spells. Skills listed in at least 90% of entry-level spells are its core skills. Skills listed in fewer than 15% are ignored.

The match score is the frequency-weighted share of a career's skills that the student covers, from 0 to 100.

---

## Career details

```http
GET /api/careers/{career}
```

Returns historical career information and observed salary/skill statistics:

* skill frequencies and skills by seniority;
* salary by seniority and start year;
* the **entry-level market**: top employers (fictitious names), top regions, and the share of roles needing a clearance or working remotely;
* alumni first-job outcomes: internship share, remote share, how the job was found, and the certifications those alumni held.

Career names are case-insensitive. URL-encode `&`, e.g. `/api/careers/IT%20Business%20%26%20Product`.

---

## Advisor

```http
POST /api/advisor
```

Sends a question to the AI career advisor.

Request:

```json
{ "campus_id": "CID-116490", "message": "What should I take next semester?", "career": null }
```

`career` is optional. When it is omitted, the advisor chooses which career to focus on in this order:

1. A career named in the message ("machine learning" matches Machine Learning & AI).
2. A career interest remembered in Backboard.
3. The top skill match.

Response:

```json
{
  "campus_id": "CID-116490",
  "reply": "For Spring 2027, ...",
  "focus_career": "Machine Learning & AI",
  "recommended_course_ids": ["CMSC475", "CMSC478"],
  "memories_used": [{ "content": "Prefers remote work.", "category": "preference" }],
  "memories_saved": [],
  "services": { "gemini": "ok", "backboard": "ok" }
}
```

`services` values are `ok`, `not_configured`, or `error`.

* If Gemini is unavailable, `reply` is a deterministic summary built from the dataset.
* If Backboard is unavailable, the advisor still answers without memory.

---

## Advisor memory

```http
GET /api/advisor/{campus_id}/memories
```

Lists what the advisor remembers about a student.

Memory handling:

* Each student has their own Backboard assistant. Its name is a hash of the `campus_id`, so the raw ID is never sent to Backboard.
* A deterministic filter drops any memory that mentions GPA, grades, credits, transcripts, or salary before it is saved.

---

# Data conventions

The dataset documentation is authoritative.

Important rules include:

### `"Not Applicable"`

`"Not Applicable"` is a literal value.

It must be filtered before numeric conversion.

Do not automatically interpret it as zero.

### Grades

Supported grades include:

```text
A
B
C
D
F
W
IP
```

W and IP are excluded from GPA calculations.

### Current students

Students in their first term may have no GPA.

Do not treat missing GPA as `0.00`.

### Employment dates

A blank `end_date` indicates an active/current job when `is_current` is true.

### Skills

Skill lists are pipe-delimited:

```text
Python|SQL|Data Modeling
```

The course and employment skill vocabularies are designed to be directly comparable.

---

# Environment variables

Create a `.env` file locally.

Example:

```env
GEMINI_API_KEY=your_key_here
GEMINI_MODEL=gemini-3.8-flash
GEMINI_FALLBACK_MODEL=gemini-3.5-flash
BACKBOARD_API_KEY=your_key_here

FRONTEND_ORIGIN=http://localhost:3000
```

| Variable | Default | Notes |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Without it, the advisor returns deterministic summaries. |
| `GEMINI_MODEL` | `gemini-3.8-flash` | Main model. |
| `GEMINI_FALLBACK_MODEL` | `gemini-3.5-flash` | Used when the main model returns 429 (quota) or 500/503. Leave it empty to disable. |
| `BACKBOARD_API_KEY` | — | Without it, the advisor runs without memory. |
| `FRONTEND_ORIGIN` | `http://localhost:3000` | Comma-separated list of allowed CORS origins. |
| `DATA_DIR` | `./data` | Folder containing the six CSVs. |
| `AUTH_SECRET` | random at startup | Signs login tokens. Set it so sessions survive restarts. |
| `STUDENT_DEMO_PASSWORD` | `umbc-demo` | Shared password for every student account. |
| `ADVISOR_USERNAME` / `ADVISOR_PASSWORD` | `advisor` / `advisor-demo` | Advisor login. |
| `ADVISOR_DISPLAY_NAME` | `Academic Advisor` | Name shown on the appointments page. |
| `APP_DB_PATH` | `app_data/app.db` | SQLite file for appointments. |
| `ADVISING_TIMEZONE` | `America/New_York` | Time zone for advising slots. |

Never commit `.env`.

A `.env.example` file should be committed instead.

---

# Running locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Start FastAPI:

```bash
uvicorn app.main:app --reload
```

The backend will normally be available at:

```text
http://localhost:8000
```

Interactive API documentation:

```text
http://localhost:8000/docs
```

---

# Frontend

`frontend/` is a plain HTML/CSS/JavaScript app with no build step:

| Page | Who | What |
| --- | --- | --- |
| `index.html` | everyone | Sign in, with Student and Advisor tabs |
| `student.html` | students | Overview: profile, skills, career alignment, focus pathway, and the AI advisor chat |
| `degree.html` | students | Degree & Skills: requirement categories, remaining required courses, skills matrix, experiential learning, credit mix |
| `market.html` | students | Market Insights: headline figures, skill demand vs. your skills, rising skills and career shifts, industry placement, your alignment, alumni roles like yours |
| `appointments.html` | students | Book, reschedule or cancel an advising session; preview the brief the advisor receives; add to calendar (.ics); preparation checklist |
| `resume.html` | students | Resume & Portfolio: upload (PDF/DOCX/TXT), readiness rubric, record-grounded findings, AI rewrite suggestions, verified + self-reported portfolio |
| `plan.html` | students | Spring course plan: build from roadmap suggestions or open requirements, live catalog checks, submit for advisor review, see the decision |
| `pathways.html` | students | Career Pathways: career cards, deep dive (employers, regions, salary, key courses with score gains, alumni certifications, skill readiness), roadmap, save a career goal |
| `advisor.html` | advisors | Advisor dashboard: caseload KPIs, attention queue (mark reviewed, request a meeting), track and career distribution, schedule with briefs (complete or cancel), data alerts |
| `roster.html` | advisors | Student roster & triage: summary strip; filters (search, major, track, class, standing, flag, review status); sorting and paging; follow-up status (review note, meeting request, appointment); single or batch meeting requests; CSV export of the current filter; urgent watchlist; flag definitions |
| `schedule.html` | advisors | Appointments & schedule: week navigator, day timeline with the current or next session spotlighted (brief, complete / no-show / cancel), week grid, capacity strip, private session notes, flagged students with no appointment (request a meeting), booking rules |
| `reports.html` | advisors | Reports & exports: data sources, seven report cards with live figures (CSV or print/PDF), saved report history with re-download, print and delete |
| `plans.html` | advisors | Plan review queue: ready / prerequisite check / meeting-first categories, per-course checks, approve, request changes with a note, batch-approve ready plans |
| `analytics.html` | advisors | Degree pathway analytics: KPIs, track concentrations, progression by class level, course bottlenecks (with follow-up requests), career alignment and bridge courses, suggested interventions |
| `student-file.html` | advisors | Read-only student file (`#CID-…`): the student's dashboard, or the alumni view for alumni IDs |

Run it next to the API:

```bash
uvicorn app.main:app --reload             # API on :8000
python3 -m http.server 3000 -d frontend   # UI on http://localhost:3000
```

The UI calls `http://localhost:8000` by default. Add `?api=https://...` to the URL to point it elsewhere. The session token is kept in `sessionStorage`, one per browser tab.

The frontend should not independently calculate:

* GPA
* career match scores
* missing skills
* salary statistics
* pathway recommendations

Those calculations belong in Python.

---

# Error handling

The backend should gracefully handle:

* invalid `campus_id`
* missing data
* students with no completed coursework
* students with no GPA
* alumni without employment records
* missing Gemini API key
* missing Backboard API key
* Gemini failures
* Backboard failures

The core dashboard should continue functioning if the AI services are unavailable.

---

# Privacy and synthetic data

The supplied HackUMBC dataset is synthetic.

Nevertheless, the application should follow good data-handling practices.

Do not:

* expose API keys
* log unnecessary conversation contents
* store unnecessary personal information in AI memory
* send the entire dataset to Gemini
* use AI memory as the authoritative academic record

Only send the minimum context required to answer the user's question.

---

# Project structure

```text
.
├── app/
│   ├── main.py              # FastAPI app, CORS, error handlers
│   ├── config.py            # settings from env / .env
│   │
│   ├── api/                 # HTTP routes (thin)
│   │   ├── health.py
│   │   ├── dashboard.py
│   │   ├── alumni.py
│   │   ├── careers.py
│   │   ├── advisor.py
│   │   └── deps.py          # dependencies (overridden in tests)
│   │
│   ├── data/
│   │   ├── loader.py        # CSV loading + per-person lookups
│   │   ├── validator.py     # required columns, end_date invariant
│   │   └── parsing.py       # "Not Applicable", pipe lists, prerequisites, terms
│   │
│   ├── services/            # all calculations
│   │   ├── student_profile.py
│   │   ├── alumni_profile.py
│   │   ├── skills.py
│   │   ├── career_matching.py
│   │   ├── salary.py
│   │   ├── pathway.py
│   │   ├── dashboard.py
│   │   └── advisor.py       # advisor orchestration
│   │
│   ├── ai/
│   │   ├── gemini.py        # generateContent client, retry + fallback model
│   │   ├── backboard.py     # per-student memory
│   │   └── prompts.py       # system prompts, context builder, memory guard
│   │
│   └── models/              # Pydantic response models
│       ├── dashboard.py
│       ├── alumni.py
│       ├── career.py
│       └── advisor.py
│
├── tests/
├── data/
├── .env.example
├── requirements.txt
├── pytest.ini
└── README.md
```

---

# Testing

Run:

```bash
pytest
```

Tests should cover:

* GPA calculation
* `"Not Applicable"` handling
* W/IP handling
* skill extraction
* career matching
* missing skills
* salary statistics
* pathway recommendations
* invalid students
* advisor context generation
* AI service failure handling

The tests use the real dataset in `data/`. Gemini and Backboard are replaced with in-process fakes, and their HTTP clients are tested against mock transports, so tests never call external services or need API keys.

One test builds the dashboard or alumni view for every person in the dataset, which takes about 15 seconds. To skip it, run:

```bash
pytest -k "not every_alumnus"
```

---

# Design principle

The most important rule in this project is:

```text
CSV / Database
    = FACTS

Python
    = CALCULATIONS

Backboard
    = USER MEMORY

Gemini
    = CONVERSATION + EXPLANATION
```

Keep these responsibilities separate.

This makes the dashboard deterministic, the AI personalized, and the system easier to debug and demonstrate.
