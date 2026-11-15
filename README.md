# Agentic AI for University Scheduling Conflict Detection & Resolution

A working system that **detects** timetable conflicts, **generates** feasible repairs,
**ranks** them against institutional priorities plus a **supervised acceptance model**,
and **applies** the chosen fix with a human approval gate and full audit trail.

- Project report: [`Project_Report.md`](Project_Report.md)
- Formatted Word report: [`LPU_Scheduling_Conflict_Resolution_Project_Report.docx`](LPU_Scheduling_Conflict_Resolution_Project_Report.docx)
- Backend: FastAPI + SQLite + a pure-Python constraint engine
- Frontend: single-page dashboard (no build step)

---

## Quick start

```bash
pip install -r requirements.txt
python -m uvicorn backend.app.main:app --port 8000
```

Open <http://127.0.0.1:8000>.

Regenerate the formatted report after updating project details with `python generate_scheduling_report.py`.

The sample term (1,020 scheduled classes, 51 rooms, 320 faculty, and 98 student
sections) is seeded automatically on first start. It includes 30 controlled
conflicts (17 critical) across all eight conflict types, including 14 large-campus
stress cases for faculty clashes and room-capacity violations.

```bash
python -m pytest backend/tests -q     # 39 tests: API, engine, and model
python -m backend.tools.benchmark     # measured evaluation numbers
```

---

## How it works

```
dashboard ──REST──► FastAPI orchestrator
                     ├── Schedule model (SQLite, in-memory Context)
                     ├── Conflict detector  (sweep line, O(n log n + k))
                     ├── Resolution engine  (domain → hard filter → strategies)
                     ├── Scoring & ranking  (5 criteria + supervised acceptance model)
                     └── Workflow & audit   (preview, approve, snapshot, rollback)
```

**One invariant makes the system trustworthy:** feasibility is decided only by the
constraint registry. The resolver proposes; the registry validates; nothing is applied
unless the patch is clean and the schedule does not get worse.

### Hard constraints (block a schedule)

| ID | Rule | Conflict |
|---|---|---|
| H1 | Room double-booking | C1 |
| H2 | Faculty double-booking | C2 |
| H3 | Student-group clash | C3 |
| H4 | Room capacity | C4 |
| H5 | Room equipment / type | C5 |
| H6 | Faculty availability & leave | C6 |
| H7 | Curriculum rules (max 2 same-course/day, daily load cap) | C7 |
| H8 | Examination window | C8 |

Soft constraints S1–S6 (student gaps, faculty balance, room utilisation, time
preference, continuity, spread) are penalised, never blocking.

### Repair strategies generated

`A1` time shift · `A2` room change · `A3` faculty substitution · `A1+A2` combined ·
`A4` full re-placement · `A6` linked-group re-shuffle (when conflicts are cyclic).

### Recommendation criteria

`disruption`, `faculty impact`, `room adequacy`, `continuity`, `rule margin` — weights
are configurable from the dashboard and re-rank every alternative live.

### Supervised learning (no unsupervised methods)

The one learned component is a **binary classifier** that predicts whether a scheduler
will accept an already-feasible repair.

| | |
|---|---|
| Task | binary classification (accept / reject) |
| Features | 11 numeric features (time shift, day/room/instructor change, fill ratio, instructor load, continuity, start hour, sessions moved, students affected, equipment surplus) |
| Labels | recorded scheduler decisions; bootstrapped from the institutional policy with 7% label noise, then real approvals are added on retrain |
| Model | Random forest (80 trees, depth 7, min_samples_leaf 6, Gini splits) · pure-Python, inspectable trees · bootstrap feature subsets |
| Blend | `total = 0.70 · policy score + 0.30 · P(accept)` |
| Held-out | accuracy 0.821 · precision 0.875 · recall 0.797 · F1 0.834 · AUC 0.882 · log-loss 0.452 |

There is **no** clustering, anomaly detection, dimensionality reduction or
self-supervision in the codebase. Linked-conflict grouping is deterministic union-find
over shared resources, not a learned segmentation. Retrain from the UI (Model tab) or
`POST /api/model/train`; the audit log records every training run.

---

## API

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health`, `/api/stats`, `/api/constraints` | status, counts, rule catalogue |
| POST | `/api/seed`, `/api/import` | load sample dataset / import your own |
| GET | `/api/schedule` | full timetable |
| POST | `/api/detect` | scan the term for conflicts |
| GET | `/api/conflicts?status=open` | open conflicts |
| POST | `/api/conflicts/{id}/resolve` | generate + rank up to K alternatives |
| GET | `/api/conflicts/{id}/alternatives` | stored alternatives |
| POST | `/api/alternatives/{id}/preview` | diff, rule check, penalty before/after |
| POST | `/api/alternatives/{id}/apply` | transactional apply (version checked) |
| POST | `/api/sessions/{id}/move` | manual move with validation |
| GET/POST | `/api/policy` | recommendation weights |
| GET/POST | `/api/model`, `/api/model/train` | supervised model metrics / retrain |
| GET | `/api/audit`, POST `/api/rollback/{audit_id}` | history and rollback |

Interactive docs: <http://127.0.0.1:8000/docs>.

---

## Data model

Tables: `term`, `time_slot`, `room`, `faculty`, `student_group`, `course`, `session`,
`session_group`, `faculty_availability`, `conflict`, `alternative`, `audit_log`, `meta`.
Dataset format is plain JSON — see [`data/sample_university.json`](data/sample_university.json)
and regenerate it with `python data/generate_sample.py`.

To import your own data, `POST /api/import` with the same shape:

```json
{
  "term":   {"name": "...", "starts_on": "...", "ends_on": "..."},
  "slots":  [{"id": 1, "day": 1, "start": "09:00", "end": "10:00", "is_exam": false}],
  "rooms":  [{"id": 1, "code": "L-101", "capacity": 60, "kind": "lecture", "features": ["projector"]}],
  "faculty":[{"id": 1, "name": "Dr. A. Rao", "max_hours_week": 18}],
  "groups": [{"id": 1, "name": "CSE-3A", "strength": 38, "programme": "CSE", "semester": 3}],
  "courses":[{"id": 1, "code": "CS301", "title": "Operating Systems", "credits": 4}],
  "availability": [{"faculty_id": 7, "day": 2, "start": "09:00", "end": "12:00", "kind": "leave"}],
  "sessions":[{"id": 1, "course_id": 1, "faculty_id": 1, "room_id": 1, "slot_id": 1,
               "kind": "lecture", "group_ids": [1], "required_features": []}]
}
```

---

## Repository layout

```
backend/app/            API, models, constraints, detection, resolution, scoring, ml, workflow
backend/tests/          39 tests (engine + API/workflow + supervised model)
backend/tools/          benchmark / evaluation harness
data/                   sample dataset + deterministic generator
frontend/               dashboard (index.html, app.js, styles.css)
Project_Report.md       full project report
```

## Expanded sample term

| Metric | Result |
|---|---|
| Scheduled classes | 1,020 |
| Faculty | 320 |
| Student sections | 98 |
| Rooms | 51 |
| Detected conflicts | 30 (17 critical) |
| Large-campus stress cases | 14 (7 faculty clashes, 7 capacity violations) |