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

## Health

```http
GET /api/health
```

Returns backend status.

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

Returns historical career information and observed salary/skill statistics: skill frequencies, skills by seniority, salary by seniority and start year, and alumni first-job outcomes (internship share, remote share, how the job was found).

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

# Frontend integration

The frontend is a separate HTML/CSS/JavaScript application.

The frontend should primarily:

1. Select a student.
2. Call the dashboard endpoint.
3. Render the returned JSON.
4. Display career matches.
5. Display pathways.
6. Display salary information.
7. Send advisor questions to `/api/advisor`.

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
