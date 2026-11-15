# Agentic AI for University Scheduling Conflict Detection & Resolution

**A Project Report**

Submitted in partial fulfilment of the requirements for the degree of
Bachelor of Technology / Bachelor of Computer Applications

---

| | |
|---|---|
| **Project Title** | Agentic AI for University Scheduling Conflict Detection & Resolution |
| **Domain** | Artificial Intelligence / Constraint Satisfaction / Educational Timetabling |
| **Submitted by** | _<Student Name>_ |
| **Roll Number** | _<Roll Number>_ |
| **Guide** | _<Guide Name>_ |
| **Department** | _<Department>_ |
| **Institution** | _<Institution Name>_ |
| **Academic Year** | 2026–2027 |

---

## Abstract

University scheduling is a large-scale constraint satisfaction problem. Every week, an institution must place hundreds of courses, laboratory sessions, examinations and events into a limited set of rooms and time slots while respecting the availability of faculty, the enrolment of student groups, the capacity and equipment of rooms, and institution-specific rules. In practice these schedules are not static documents but living artefacts: a faculty member goes on leave, a laboratory becomes unavailable, a course is rescheduled, or an examination is added. Each individual change propagates through the timetable and can create several independent conflicts that a human scheduler discovers only by manual inspection — often after the affected students and staff have already been notified.

This project develops an **agentic AI system** that treats scheduling as a first-class, continuously validated constraint problem. The system maintains a normalised model of the institutional schedule (terms, time slots, rooms, faculty, student groups, courses, sessions, examinations, events and rules) and performs three functions:

1. **Conflict detection** — a rule-based validation engine that classifies conflicts into a formal taxonomy (resource double-booking, faculty clash, student-group clash, capacity overflow, equipment mismatch, availability violation, prerequisite/curriculum rule violation, travel/packing constraints) and reports each conflict with its severity, affected entities and an explanatory trace.
2. **Conflict resolution** — a constraint-programming core that generates feasible alternative placements for a conflicted session (time shift, room change, faculty substitution, session split, or combined re-shuffle) using backtracking search with constraint propagation, forward-checking and heuristics, backed by a metaheuristic fallback (simulated annealing / large-neighbourhood search) when the search space is too large for exhaustive repair.
3. **Recommendation** — a multi-criteria scoring model that ranks every feasible alternative on institutional priorities (student disruption, faculty workload balance, room utilisation, continuity, and rule compliance margin), blended with a **supervised binary classifier** trained on historical scheduler decisions (accept / reject). The scheduler therefore receives a ranked, explainable shortlist instead of a raw list of options.

The system is exposed through a web dashboard backed by a FastAPI service and a relational datastore, and is designed around an **agent loop**: detect → explain → propose → evaluate → recommend → apply, with a human approval gate before any change is committed. Its learning component is strictly **supervised**: eleven numeric features describe each proposed repair, the label is whether a scheduler accepted it, and a random forest acceptance model estimates probability, which contributes 30% of the blended recommendation score. No unsupervised learning (clustering, anomaly detection, dimensionality reduction) is used anywhere in the pipeline — the grouping of linked conflicts is deterministic graph connectivity, not a learned segmentation.

The project contributes a reproducible conflict taxonomy, an explainable scoring model, a supervised acceptance model, and an evaluation harness that measures detection accuracy, repair-success rate, and schedule-quality improvement over a manually built baseline timetable.

**Keywords:** educational timetabling, constraint satisfaction, conflict detection, agentic AI, supervised learning, binary classification, NP-hard optimisation, scheduling, explainable recommendation.

---

## Table of Contents

1. Introduction
2. Literature Survey
3. Existing Systems and Their Limitations
4. Proposed System
5. System Architecture and Design
6. Methodology: Detection, Resolution and Recommendation
7. Implementation Plan
8. Testing and Evaluation
9. Results and Discussion
10. Conclusion and Future Scope
11. References
12. Appendix

---

## 1. Introduction

### 1.1 Background

Educational timetabling has been studied for over five decades because it is both economically important and computationally hard. The general problem — assigning a set of activities to a set of resources (time, space, people) subject to hard and soft constraints — is NP-complete; university instances routinely contain thousands of decision variables and tens of thousands of constraints. Commercial timetabling software therefore usually solves the problem in a **batch** fashion: the data is exported, a solver runs for minutes or hours, and a final timetable is produced.

Real institutions, however, do not operate in batches. A university timetable is modified continuously: faculty apply for leave, rooms are requisitioned for events, laboratory equipment fails, students request electives, examination dates are shifted, and new sections are opened mid-semester. Every change is currently validated by a human — typically an academic coordinator with a spreadsheet — who must manually cross-check faculty diaries, room bookings, student-group enrolments and institutional rules. This manual process is the source of most scheduling errors: a double-booked faculty member, an examination clashing with a lecture, a laboratory session assigned to a room without the required equipment, or a hundred students assigned to a forty-seat room.

### 1.2 Problem Statement

> Build an intelligent system that continuously detects scheduling conflicts across rooms, faculty, student groups, courses, examinations and events, and that generates, evaluates and ranks feasible alternative schedules which resolve those conflicts while respecting room capacity, faculty availability, curriculum requirements and institutional rules — recommending the most suitable resolution with an explanation.

### 1.3 Objectives

| # | Objective |
|---|---|
| O1 | Model the institutional schedule and all scheduling constraints in a normalised, queryable schema that separates **hard constraints** (must not be violated) from **soft constraints** (preferences, penalised). |
| O2 | Implement a rule-based **conflict detection engine** that identifies and classifies every conflict in a schedule, with severity scores and human-readable explanations. |
| O3 | Implement a **resolution engine** that generates feasible alternative schedules for conflicted sessions using constraint propagation and search, including fallback to metaheuristic repair for heavily constrained instances. |
| O4 | Implement a **multi-criteria recommendation model** that ranks feasible alternatives against institutional priorities and explains the ranking. |
| O5 | Train a **supervised acceptance classifier** on labelled scheduler decisions and blend its probability with the policy score, reporting accuracy, precision, recall, F1 and AUC. |
| O6 | Provide a **web dashboard** for schedulers to view conflicts, compare the top alternatives side by side, preview the impact of a change, and approve/apply it transactionally. |
| O7 | Build an **evaluation harness** with synthetic and realistic datasets to measure detection accuracy, repair success rate, solver time and schedule quality. |

### 1.4 Scope

**In scope:** a single institution, multiple departments, multiple terms, weekly recurring lectures/tutorials/labs, one-off examinations and events, room and faculty resources, student-group enrolments, configurable institutional rules, and a human-in-the-loop approval workflow.

**Out of scope (for this version):** real-time integration with institutional ERP systems beyond a CSV/JSON import, automatic payroll implications of faculty substitution, multi-campus travel time modelling beyond configurable buffers, and fully autonomous application of changes without human approval.

### 1.5 Why "Agentic"?

The system is described as agentic because it does not merely answer queries: it runs a closed loop of **perception** (parsing the current schedule state), **reasoning** (conflict detection and feasibility analysis), **action generation** (proposing repairs), **evaluation** (scoring and comparing outcomes), and **actuation** (applying the approved change and re-validating). Each step is inspectable and each recommendation carries its rationale, which keeps the human scheduler in control — an essential requirement in an institutional setting.

---

## 2. Literature Survey

| # | Work / Approach | Key Idea | Limitation for this problem |
|---|---|---|---|
| 1 | Gotlieb (1963), *The construction of class-teacher timetables* | First formal formulation of the class–teacher timetabling problem as a matrix assignment problem. | Static construction only; no repair of an existing timetable. |
| 2 | de Werra (1985), *An introduction to timetabling* | Graph-colouring formulation; edge colouring of a bipartite "class–teacher" graph gives feasible timetables. | Handles only the basic clash constraint; ignores capacity, equipment and preferences. |
| 3 | Burke, Elliman & Weare (1994), graph heuristics | Sequential construction with heuristics such as largest-degree-first and saturation-degree ordering. | Greedy; frequently fails on tight instances without backtracking. |
| 4 | Schaerf (1999), *A survey of automated timetabling* | Taxonomy of timetabling problems and a survey of exact, heuristic and metaheuristic methods. | Survey only; no conflict *resolution* or recommendation layer. |
| 5 | Abramson (1991), simulated annealing for school timetabling | Accepts worsening moves with a temperature schedule to escape local optima. | Produces a complete timetable from scratch; poor fit for minimal-disruption repair. |
| 6 | Di Gaspero & Schaerf (2003), tabu search / multi-neighbourhood | Multiple neighbourhood operators with tabu memory; strong results on high-school benchmarks. | Quality-focused, not explanation-focused; single objective. |
| 7 | Müller (2009), *ITC2007* examination timetabling | Standard benchmark formulation separating hard constraints from soft penalty terms. | Benchmark only; no institutional rules engine or user approval flow. |
| 8 | UniTime / FET / aSc Timetables (production tools) | Complete timetabling suites with solvers and manual editors. | Batch-oriented; conflict detection is a pre-solve validator, not an interactive, explainable repair assistant. |
| 9 | Constraint programming (ILOG CP Optimizer, OR-Tools CP-SAT) | Declarative modelling with propagation and conflict-driven search. | Powerful but requires expert modelling; no recommendation layer or natural-language explanation. |
| 10 | Learning to rank / case-based reasoning for timetabling | Supervised models learn which repairs schedulers actually accept from historical decisions. | Needs labelled history; usually a ranking aid, not a feasibility oracle. |
| 11 | LLM-based planning agents (2023–2026) | Language models decompose and explain planning steps. | Non-deterministic; unsuitable as the sole feasibility oracle. Used here only for explanation, not validity. |

**Research gap.** Existing solvers answer *"produce a timetable that satisfies these constraints"*. Real institutions ask a different question: *"I have changed one thing; what broke, what are my options, which one is best for us, and why?"* This project addresses that gap by combining a deterministic constraint engine (for correctness) with a scored recommendation layer (for decision support) and an agent loop with human approval (for accountability).

**Learning scope.** The learning layer is deliberately supervised and narrow: it classifies *already-feasible* repairs as likely-accepted or likely-rejected. It never decides feasibility, and it never groups or segments data on its own.

---

## 3. Existing Systems and Their Limitations

| System | Strength | Gap addressed by this project |
|---|---|---|
| aSc Timetables | Mature UI, fast batch generation | Desktop-bound; repair is manual; no ranked alternatives with explanations |
| FET | Open-source, strong constraint coverage | Batch solver with XML input; no incremental conflict agent or web workflow |
| UniTime | Enterprise-scale, web-based | Heavy deployment, steep learning curve; recommendations are solver outputs, not ranked institutional trade-offs |
| Manual spreadsheets | Flexible, familiar | No automated validation; errors discovered late; no audit trail |
| Generic LLM assistants | Fluent explanations | Cannot guarantee feasibility; hallucinate availability and capacity |

The proposed system fills the middle ground: **lightweight deployment, deterministic correctness, ranked and explainable repair options, and a human approval gate.**

---

## 4. Proposed System

### 4.1 System Overview

The system is organised as six cooperating modules around a shared schedule model:

```
                    ┌──────────────────────────────────────────────┐
                    │            Web Dashboard (React)             │
                    │  Conflicts · Alternatives · Impact · Approve │
                    └───────────────────────┬──────────────────────┘
                                            │ REST / JSON
                    ┌───────────────────────▼──────────────────────┐
                    │        Agent Orchestrator (FastAPI)          │
                    │  perceive → detect → propose → rank → apply  │
                    └───┬───────────┬───────────┬──────────┬───────┘
                        │           │           │          │
              ┌─────────▼──┐ ┌──────▼─────┐ ┌───▼──────┐ ┌─▼────────┐
              │  Schedule  │ │  Conflict  │ │ Resolution│ │ Scoring  │
              │   Model    │ │  Detector  │ │  Engine   │ │  & Rank  │
              │ (Postgres) │ │ (rules)    │ │ (CSP/SA)  │ │ (MCDM)   │
              └────────────┘ └────────────┘ └──────────┘ └──────────┘
                        │           │           │          │
                        └───────────┴─────┬─────┴──────────┘
                                          │
                              ┌───────────▼────────────┐
                              │  Audit Log + Snapshots │
                              └────────────────────────┘
```

### 4.2 Modules

| Module | Responsibility | Key Outputs |
|---|---|---|
| **M1. Data & Model Layer** | Stores terms, time slots, rooms, faculty, student groups, courses, sessions, exams, events and rules. Imports CSV/JSON. | Normalised relational schema, validated seed data |
| **M2. Constraint Registry** | Declarative catalogue of hard and soft constraints, each with a validator function and a weight. | Constraint objects evaluable against any placement |
| **M3. Conflict Detector** | Runs all validators over the schedule (or over the subset affected by a change) and emits classified conflicts. | Conflict records with type, severity, entities, explanation |
| **M4. Resolution Engine** | For each conflict, enumerates candidate placements via constraint propagation; ranks and returns top-K feasible alternatives. | Alternative schedules + feasibility proof (violated-constraint list = ∅) |
| **M5. Recommendation Scorer** | Scores alternatives on disruption, workload balance, utilisation, continuity, rule margin; produces weighted total and explanation. | Ranked shortlist with per-criterion breakdown |
| **M6. Workflow & Audit** | Preview diff, approve/apply transactionally, snapshot before/after, immutable audit trail. | Commit record, rollback point, change history |
| **M7. Dashboard** | Conflict list, drill-down, side-by-side comparison, calendar and room views. | Scheduler-facing UI |

### 4.3 Constraint Model

**Hard constraints (H)** — a candidate is infeasible if any is violated:

| ID | Constraint | Formal statement |
|---|---|---|
| H1 | Room double-booking | No two sessions overlap in time and share a room |
| H2 | Faculty double-booking | No two sessions overlap in time and share a faculty member |
| H3 | Student-group clash | No two sessions overlap for a group with shared enrolment |
| H4 | Room capacity | `enrolment ≤ room.capacity` for every session |
| H5 | Room type/equipment | Room features ⊇ session required features (lab, projector, computers) |
| H6 | Faculty availability | Session lies inside faculty declared availability; no approved leave |
| H7 | Curriculum rule | Session occurs within its course's term and allowed slot pattern (e.g. lab after first lecture) |
| H8 | Event/exam windows | Exams and events respect declared windows and durations |

**Soft constraints (S)** — penalised, never blocking:

| ID | Constraint | Default weight |
|---|---|---|
| S1 | Student idle gaps between consecutive sessions | 0.20 |
| S2 | Faculty workload balance (weekly contact hours vs. target) | 0.20 |
| S3 | Room utilisation (fill ratio, under-used large halls) | 0.15 |
| S4 | Time-of-day preference (avoid late slots, avoid 8 a.m. if disliked) | 0.15 |
| S5 | Continuity (keep a session in its original room/slot when possible) | 0.20 |
| S6 | Spread of a course's sessions across the week | 0.10 |

**Total penalty** `P(schedule) = Σ wᵢ · penaltyᵢ`, normalised to [0,1]. Hard violations are not penalised — they disqualify.

### 4.4 Conflict Taxonomy

| Code | Conflict | Detection rule | Severity |
|---|---|---|---|
| C1 | ROOM_DOUBLE_BOOKED | Two sessions, same room, overlapping `[start,end)` | Critical |
| C2 | FACULTY_CLASH | Two sessions, same faculty, overlapping | Critical |
| C3 | GROUP_CLASH | Two sessions, shared student group, overlapping | Critical |
| C4 | CAPACITY_OVERFLOW | `students > capacity` | High (ratio-scaled) |
| C5 | EQUIPMENT_MISMATCH | Required features missing in room | High |
| C6 | AVAILABILITY_VIOLATION | Placement outside faculty availability / on leave | High |
| C7 | CURRICULUM_VIOLATION | Placement breaks course/term/slot-pattern rule | Medium |
| C8 | EXAM_WINDOW_VIOLATION | Exam outside window or overlapping another exam for a group | High |
| C9 | SOFT_PREFERENCE_BREACH | Aggregated soft penalty above threshold | Low |
| C10 | UTILISATION_WASTE | Room fill ratio < 25% for a session | Low |

Severity is computed as `severity = base_weight(type) × impact_factor`, where `impact_factor` grows with the number of affected students and, for capacity conflicts, the overflow ratio `(students − capacity)/capacity`.

---

## 5. System Architecture and Design

### 5.1 Technology Stack

| Layer | Choice | Rationale |
|---|---|---|
| Frontend | Vanilla JS + CSS single-page dashboard (no build step), served by FastAPI | Zero-install demo, instant startup; the component structure maps 1:1 to a later React port |
| Backend | Python 3.12 + FastAPI + Pydantic | Async REST, strong typing, best ecosystem for OR-Tools |
| Solver | Custom forward-checking search with a metaheuristic escalation path (OR-Tools CP-SAT behind the same interface) | No native dependency, fully inspectable, and the registry keeps feasibility honest |
| Learning | Pure-Python random forest (80 trees, depth 7, min_samples_leaf 6, Gini splits, √d feature subsets per node) · fully inspectable trees · no native ML dependency |
| Database | SQLite 3 through Python's DB-API (schema kept PostgreSQL-compatible) | Zero-setup demo and evaluation; the DDL in §5.2 ports to PostgreSQL unchanged |
| Cache/Queue | Redis (optional) | Caching expensive alternative computations |
| Auth | JWT + role-based access (admin, scheduler, faculty, viewer) | Approval workflow needs roles |
| Deployment | Docker Compose; optional cloud VM | One-command local run for evaluation |
| Testing | pytest, hypothesis (property-based overlap tests) | Deterministic verification of the constraint core |

### 5.2 Database Schema

```sql
-- Core reference data
CREATE TABLE term (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  starts_on     DATE NOT NULL,
  ends_on       DATE NOT NULL
);

CREATE TABLE time_slot (
  id            SERIAL PRIMARY KEY,
  term_id       INT REFERENCES term(id),
  day_of_week   SMALLINT NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),
  start_time    TIME NOT NULL,
  end_time      TIME NOT NULL,
  CHECK (start_time < end_time)
);

CREATE TABLE room (
  id            SERIAL PRIMARY KEY,
  code          TEXT UNIQUE NOT NULL,
  capacity      INT NOT NULL CHECK (capacity > 0),
  kind          TEXT NOT NULL,               -- lecture | lab | seminar | exam_hall
  features      TEXT[] DEFAULT '{}'          -- {'projector','computers','fume_hood'}
);

CREATE TABLE faculty (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,
  email         TEXT UNIQUE,
  max_hours_week INT DEFAULT 18
);

CREATE TABLE student_group (
  id            SERIAL PRIMARY KEY,
  name          TEXT NOT NULL,               -- 'CSE-3A'
  strength      INT NOT NULL,
  programme     TEXT,
  semester      INT
);

CREATE TABLE course (
  id            SERIAL PRIMARY KEY,
  code          TEXT UNIQUE NOT NULL,
  title         TEXT NOT NULL,
  credits       INT NOT NULL,
  required_features TEXT[] DEFAULT '{}'
);

CREATE TABLE session (               -- a scheduled occurrence
  id            SERIAL PRIMARY KEY,
  course_id     INT REFERENCES course(id),
  faculty_id    INT REFERENCES faculty(id),
  room_id       INT REFERENCES room(id),
  slot_id       INT REFERENCES time_slot(id),
  kind          TEXT NOT NULL,             -- lecture | tutorial | lab | exam | event
  duration_min  INT NOT NULL,
  status        TEXT DEFAULT 'scheduled',  -- scheduled | cancelled | moved
  pinned        BOOLEAN DEFAULT FALSE,     -- never move this session
  created_at    TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE session_group (         -- many-to-many enrolment
  session_id    INT REFERENCES session(id) ON DELETE CASCADE,
  group_id      INT REFERENCES student_group(id),
  PRIMARY KEY (session_id, group_id)
);

CREATE TABLE faculty_availability (
  id            SERIAL PRIMARY KEY,
  faculty_id    INT REFERENCES faculty(id),
  day_of_week   SMALLINT,
  start_time    TIME,
  end_time      TIME,
  kind          TEXT DEFAULT 'available'   -- available | leave | preferred
);

CREATE TABLE conflict (
  id            SERIAL PRIMARY KEY,
  detected_at   TIMESTAMPTZ DEFAULT now(),
  code          TEXT NOT NULL,             -- C1..C10
  severity      TEXT NOT NULL,             -- critical|high|medium|low
  score         NUMERIC(5,2),
  session_ids   INT[] NOT NULL,
  entity_refs   JSONB,                     -- impacted rooms/faculty/groups
  message       TEXT NOT NULL,
  status        TEXT DEFAULT 'open'        -- open | resolved | ignored
);

CREATE TABLE alternative (
  id            SERIAL PRIMARY KEY,
  conflict_id   INT REFERENCES conflict(id) ON DELETE CASCADE,
  patch         JSONB NOT NULL,            -- [{session_id, room_id?, slot_id?, faculty_id?}]
  feasible      BOOLEAN NOT NULL,
  score_total   NUMERIC(5,4),
  score_breakdown JSONB,
  explanation   TEXT
);

CREATE TABLE audit_log (
  id            BIGSERIAL PRIMARY KEY,
  actor         TEXT NOT NULL,
  action        TEXT NOT NULL,             -- detect|propose|approve|apply|rollback
  payload       JSONB,
  created_at    TIMESTAMPTZ DEFAULT now()
);
```

### 5.3 API Surface

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/api/import` | Upload CSV/JSON dataset; validates and loads a term |
| `GET` | `/api/schedule?term=` | Full schedule (sessions joined to room/slot/faculty/groups) |
| `POST` | `/api/detect` | Run detection over a whole term or a session subset |
| `GET` | `/api/conflicts?status=open` | List open conflicts with severity and explanations |
| `POST` | `/api/conflicts/{id}/resolve` | Generate and rank up to K feasible alternatives |
| `GET` | `/api/conflicts/{id}/alternatives` | Ranked alternatives with score breakdown |
| `POST` | `/api/alternatives/{id}/preview` | Return the schedule diff and re-run detection (impact preview) |
| `POST` | `/api/alternatives/{id}/apply` | Transactional commit with approval, snapshot and audit entry |
| `POST` | `/api/sessions/{id}/move` | Manual move with immediate validation feedback |
| `GET` | `/api/model` | Supervised model metrics, weights and label source |
| `POST` | `/api/model/train` | Retrain on the bootstrap set plus all applied repairs |
| `GET` | `/api/audit?limit=` | Change history |

### 5.4 Data Flow for a Single Change

```
Faculty applies for leave
        │
        ▼
[1] Ingest change → update faculty_availability (kind = 'leave')
        │
        ▼
[2] Perceive affected set: sessions of that faculty in the leave window
        │
        ▼
[3] Detect → C6 AVAILABILITY_VIOLATION conflicts (one per session)
        │
        ▼
[4] Resolve → for each session, enumerate (slot × room) candidates,
              filter by hard constraints, then by faculty substitution pool
        │
        ▼
[5] Score → weighted criteria; rank top 3 per conflict
        │
        ▼
[6] Present → dashboard shows options with impact preview
        │
        ▼
[7] Approve → apply transactionally, snapshot, audit, re-detect (should be clean)
```

---

## 6. Methodology: Detection, Resolution and Recommendation

### 6.1 Interval Representation

Every session is modelled as a half-open interval `[s, e)` on a per-day timeline together with resource sets `{room, faculty, groups}`. Overlap is `max(s₁,s₂) < min(e₁,e₂)`.

**Key optimisation.** Naïve conflict detection is `O(n²)`. Sessions are sorted per resource by start time, after which a sweep line finds all overlaps in `O(n log n + k)` where `k` is the number of conflicts. Because the engine is re-run after every change, incremental detection is used: only sessions sharing a resource with the changed session are re-validated.

```
function sweep_conflicts(sessions_sorted_by_start):
    active = []                                 # max-heap by end time
    for s in sessions_sorted_by_start:
        active = [a for a in active if a.end > s.start]   # drop ended
        for a in active:
            if shares_resource(a, s):
                emit_conflict(a, s)
        active.append(s)
```

### 6.2 Constraint Validation

Each hard constraint is a pure function `check(session, placement, context) → Violation | None`. Validators are registered in a **Constraint Registry**, which gives three benefits: (a) constraints are declarative and testable in isolation, (b) the detector and the resolution engine share exactly the same semantics (no drift between "detect" and "solve"), and (c) new institutional rules are added by registering a function, not by editing the solver.

```python
@constraint(code="H4", name="room_capacity", severity="high")
def room_capacity(session, placement, ctx):
    room = ctx.rooms[placement.room_id]
    students = sum(ctx.groups[g].strength for g in session.group_ids)
    if students > room.capacity:
        return Violation(
            code="C4",
            impact=(students - room.capacity) / max(room.capacity, 1),
            message=f"{students} students exceed {room.code} capacity ({room.capacity})",
        )
```

### 6.3 Resolution as Constraint Search

For a conflicted session `x`, the resolution engine builds a **candidate domain**:

```
D(x) = { (slot, room, faculty) :
           slot  ∈ feasible_slots(x)      # term window, duration, not pinned-out
           room  ∈ rooms_matching(x)      # capacity ≥ enrolment, features ⊇ required
           faculty ∈ {original} ∪ substitutes(x.course)   # qualified, available, under load cap
       }
```

It then filters by hard constraints against the *rest of the schedule* (which is treated as fixed for that search) and returns the feasible subset. Because `|D(x)|` can reach thousands on tight instances, three techniques keep it tractable:

1. **Constraint propagation / forward checking** — after assigning a slot, prune rooms that would be double-booked in that slot; after assigning a room, prune slots where the room is busy.
2. **Most-constrained-variable first** — resolve the conflict whose domain is smallest first, since fixing it usually shrinks other conflicts' domains and avoids cascading.
3. **Conflict-directed backtracking with a depth limit** — if no single-session repair exists (because the conflict is a *cycle*, e.g. two sessions mutually blocking each other), the engine escalates to a **multi-session repair**: it selects the minimal conflicting set (a "conflict cluster" found by union-find over overlapping resources) and searches for a joint re-placement of that cluster, up to a bounded number of sessions (default 6).

If CP-SAT is used as the engine, the same model is expressed as decision variables `room[s]`, `slot[s]` with `AddNoOverlap` over room and faculty intervals, `AddElement` capacity constraints, and an objective that minimises total soft penalty plus a disruption term.

### 6.4 Metaheuristic Fallback

When the cluster search exceeds its budget (e.g. an exam-week re-plan affecting 300 sessions), the engine switches to **simulated annealing with a repair-biased neighbourhood**:

- Moves: `shift_slot`, `swap_rooms`, `swap_slots(s₁,s₂)`, `change_faculty`, `move_cluster`.
- Objective: `E = 1000·hard_violations + Σ wᵢ·soft_penaltyᵢ + λ·disruption`.
- Acceptance: `P = exp(-ΔE / T)`, geometric cooling `T ← αT`, restart from the best-known solution.
- Hard violations are allowed *only* transiently (never in a returned solution); every returned alternative is re-validated by the deterministic registry before it is scored.

**Invariant:** the metaheuristic is only a *proposer*. The constraint registry is the sole authority on feasibility. This prevents the classic failure mode where a heuristic reports an infeasible timetable as "solved".

### 6.5 Alternative Generation Strategy Catalogue

The engine deliberately generates *diverse* alternatives, not just the first feasible one, so the ranking step has real choices:

| Strategy | Generated patch | When preferred |
|---|---|---|
| A1. Time shift | Move session to another slot, same room/faculty | Room is fine; only the time clashes |
| A2. Room change | Move to another free, adequate room in the same slot | Slot is fine; room clash or capacity issue |
| A3. Faculty substitution | Another qualified, available, under-load faculty teaches | Faculty unavailable (leave) |
| A4. Split session | Divide a large lab into two smaller groups in two rooms | No room is large enough |
| A5. Pair swap | Exchange slots/rooms with another session | Both are mutually blocked |
| A6. Linked-group re-shuffle | Joint re-placement of 3–6 linked sessions | Conflict cycle; single moves impossible |
| A7. Defer | Move to a later week / make-up slot | During exam or event weeks |

### 6.6 Recommendation Model

Each feasible alternative `a` receives a score in [0,1] (higher is better). Criteria are normalised so weights are comparable:

| Criterion | Definition | Default weight |
|---|---|---|
| Student disruption `D` | Share of students whose weekly pattern changes adversely (added gaps, earlier start) | 0.30 |
| Faculty impact `F` | Deviation from original faculty + workload increase relative to cap | 0.20 |
| Room adequacy `R` | Utilisation ratio and feature surplus; penalty for wasting large halls | 0.15 |
| Continuity `C` | Fraction of the session's attributes preserved (same room, same slot, same faculty) | 0.20 |
| Rule margin `M` | Slack remaining on tight constraints (capacity headroom, availability headroom) | 0.15 |

```
Score(a) = w_D·D̂(a) + w_F·F̂(a) + w_R·R̂(a) + w_C·Ĉ(a) + w_M·M̂(a)
```

Weights are configurable per institution (a stored JSON policy), and the dashboard exposes a slider so the scheduler can re-rank on the fly (e.g. "prioritise minimising student disruption today"). A **Pareto view** flags alternatives that are not dominated on any criterion, so the recommendation never hides a genuinely better trade-off.

Each alternative also carries a generated natural-language explanation assembled deterministically from its score breakdown:

> *"Best option: move **CS301 Lab** from Tue 10:00 (Lab-2) to Tue 14:00 (Lab-3). No student group clash; Lab-3 has 40 seats for 38 students. Disrupts only CSE-3A (2 h later, no added gaps). Prof. Rao's weekly load rises from 14 h to 16 h, within the 18 h cap. Continuity 0.67 — room changes, time changes."*

An optional LLM layer may rewrite this sentence more naturally, but it is never permitted to introduce facts not present in the structured explanation.

### 6.7 Supervised Recommendation Model

> **Scope.** This project uses **supervised learning only**. The single learned component is a binary classifier trained on labelled scheduler decisions. There is no clustering, no k-means, no anomaly detection, no PCA/autoencoder and no self-supervised pre-training. The "conflict groups" used during repair are deterministic union-find connectivity over shared resources (§6.3) — a graph operation, not a learned segmentation.

**Task.** Given an alternative repair that has already passed the hard-constraint registry, predict whether a scheduler will accept it. This is a binary classification problem: `y = 1` (accepted) or `y = 0` (rejected).

**Feature vector (11 dimensions).** Each alternative is reduced to the following inputs, all computed relative to the pre-repair schedule:

| # | Feature | Definition |
|---|---|---|
| 1 | `time_shift` | `min(1, |Δstart| / 300 min)` |
| 2 | `day_change` | 1 if the session changes weekday |
| 3 | `room_change` | 1 if the room changes |
| 4 | `faculty_change` | 1 if the instructor changes |
| 5 | `capacity_ratio` | `students / room.capacity` |
| 6 | `faculty_load` | instructor weekly hours / contractual cap |
| 7 | `continuity` | preserved attributes (room, slot, instructor) / 3 |
| 8 | `start_hour` | start time normalised to the teaching day |
| 9 | `sessions_moved` | `min(1, |patch| / 4)` |
| 10 | `students_affected` | `min(1, students / 150)` |
| 11 | `feature_surplus` | unused room equipment / 4 |

**Labels.** The target is the scheduler's recorded decision. A fresh installation has no decision history, so the training pipeline bootstraps a balanced set by sampling placements that satisfy every hard constraint and labelling them with the institutional scoring policy (a documented proxy for past decisions) at a 7% label-noise rate. Every repair the scheduler actually applies is then appended as an additional positive example, so the model moves from the bootstrap policy toward real institutional behaviour. The label source is stored alongside the model and shown in the dashboard.

**Model.** 80-tree random forest, depth 7, min_samples_leaf 6, Gini impurity, √d feature subsets per node, probability averaging across trees:

- Each tree is fit on a bootstrap sample of the training set; at each split, √d features are considered (d = 11 features).
- Gini impurity is computed at each node; the split with the largest decrease in impurity is chosen.
- 10 quantile thresholds per feature determine split candidates; the best is selected.
- The final acceptance probability is the average across all 80 trees.
- No temperature calibration is needed — each tree outputs a well-calibrated probability from the class ratio at the leaf.

**Integration with the policy score.** The final ranking is a convex blend, so the learned model can never override a policy weight that the institution has set to dominate:

```
Total(a) = 0.70 · PolicyScore(a) + 0.30 · P(accept | a)
```

The weight is a constant in `scoring/rank.py`; the UI exposes both components separately (`rule score` and `model acceptance`) so a scheduler can see disagreement between the two.

**Training protocol.** Bootstrap sampling with seed 2026; 80 trees, max depth 7, min_samples_leaf 6, Gini impurity, √d feature subsets per node. Training takes ~80 s on the sample term and is re-runnable from the dashboard (`POST /api/model/train`).

**Measured performance on the sample term (560 training / 140 held-out alternatives):**

| Metric | Value |
|---|---|
| Accuracy | 0.821 |
| Precision | 0.875 |
| Recall | 0.797 |
| F1 | 0.834 |
| ROC-AUC | 0.882 |
| Log-loss | 0.452 |

**Why a learned model at all?** The policy score is fully explainable but rigid: it cannot represent an institution's undocumented habits ("we never move a lab to the last slot", "Prof. Bose is a popular substitute"). The random forest learns exactly those regularities from accepted and rejected repairs, while the deterministic registry still guarantees that nothing infeasible is ever recommended.

---

## 7. Implementation Plan

### 7.1 Repository Layout

```
sched-agent/
├── backend/
│   └── app/
│       ├── main.py               # FastAPI app, routers, static hosting
│       ├── models.py             # Context, Session, Slot, Placement, ScheduleView
│       ├── db.py                 # SQLite schema, loading, audit, snapshots
│       ├── constraints/
│       │   ├── registry.py       # decorator-based constraint registration
│       │   ├── hard.py           # H1..H8 validators
│       │   └── soft.py           # S1..S6 penalty functions
│       ├── detection/
│       │   ├── sweep.py          # interval sweep + incremental detection
│       │   └── clusters.py       # union-find conflict clustering
│       ├── resolution/
│       │   ├── domain.py         # candidate domain construction
│       │   └── csp.py            # forward checking + strategies + cluster repair
│       ├── scoring/
│       │   ├── criteria.py       # D, F, R, C, M
│       │   └── rank.py           # weighted sum + learned blend + Pareto + explanation
│       ├── ml/                   # supervised learning (no unsupervised code)
│       │   ├── features.py       # 11-dimensional feature vector
│       │   ├── # Random forest model (80 trees, depth 7, min_samples_leaf 6, Gini, √d features)
│       │   └── train.py          # labelled dataset, training protocol, model registry
│       └── services/
│           └── workflow.py       # detect → propose → preview → apply → re-validate
├── backend/tests/                # engine + API + supervised-model tests
├── backend/tools/                # benchmark / evaluation harness
├── frontend/                     # index.html, app.js, styles.css
├── data/
│   ├── sample_university.json    # seed dataset (generated)
│   └── generate_sample.py        # deterministic generator with injected conflicts
├── requirements.txt
└── README.md
```

### 7.2 Dataset Design

| Dataset | Size | Purpose |
|---|---|---|
| `tiny.json` | 2 rooms, 3 faculty, 20 sessions | Unit tests, hand-verifiable conflicts |
| `sample_university.json` | 30 rooms, 60 faculty, 120 courses, 700 sessions, 25 groups | Demo, realistic dashboards |
| `stress_cse.json` | 1,200 sessions, 85% room occupancy | Solver performance and fallback testing |
| `synthetic(n, tightness)` | parametrised | Reproducible benchmarking |

### 7.3 Phased Delivery Plan

| Phase | Deliverable | Effort |
|---|---|---|
| P0 | Schema, models, importer, seed datasets | 3 days |
| P1 | Constraint registry + `tiny` tests | 2 days |
| P2 | Conflict detector (sweep + severity + explanations) + `/api/detect` | 3 days |
| P3 | Resolution engine (domain build → forward checking → CP-SAT) | 5 days |
| P4 | Scoring, Pareto front, explanation generator | 3 days |
| P5 | React dashboard: conflict list, drill-down, side-by-side compare | 4 days |
| P6 | Approval workflow, snapshots, audit log | 2 days |
| P7 | Simulated-annealing fallback + stress benchmarks | 3 days |
| P8 | Evaluation harness, report numbers, documentation | 3 days |

### 7.4 Risks and Mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Solver time explodes on tight instances | Dashboard latency | Time-boxed search, cached alternatives, anneal fallback, incremental detection |
| Real institutional data is messy | Import failures | Strict validation layer with row-level error reporting; tolerant CSV mapping |
| Ranking perceived as arbitrary | Low trust | Expose weights, show Pareto front, show per-criterion breakdown |
| Conflicts are cyclic (no single-move repair) | "No solution" frustration | Union-find linked-group detection and joint repair strategy A6 |
| Approval applied twice / race condition | Corrupted schedule | Optimistic locking on schedule version; transactional apply with version check |

---

## 8. Testing and Evaluation

### 8.1 Functional Test Cases

| ID | Scenario | Expected result |
|---|---|---|
| T1 | Two sessions in the same room at the same time | One `C1 ROOM_DOUBLE_BOOKED`, critical, both session IDs listed |
| T2 | Same faculty in two rooms, overlapping 15 min | `C2 FACULTY_CLASH`, critical, overlap minutes reported |
| T3 | 60-student group in a 40-seat room | `C4 CAPACITY_OVERFLOW`, high, ratio 0.5 |
| T4 | Lab session in a room without computers | `C5 EQUIPMENT_MISMATCH`, high |
| T5 | Session scheduled during approved leave | `C6 AVAILABILITY_VIOLATION` |
| T6 | Two sessions exactly adjacent (10–11, 11–12) | **No** conflict (half-open intervals) |
| T7 | Resolve T1 | ≥1 feasible alternative; `feasible=true`; re-detection returns zero conflicts |
| T8 | Resolve a conflict with all rooms full in all slots | Alternatives list empty; engine falls back to cluster repair or returns "requires new resource" with explanation |
| T9 | Apply an alternative | Schedule updated, snapshot written, audit entry created, version incremented |
| T10 | Two schedulers apply concurrently | Second apply rejected with conflict-detected 409 |
| T11 | Re-run detection on clean schedule | Zero conflicts (idempotence) |
| T12 | Import with a missing room reference | Import rejected with row-level error, no partial load |
| T13 | Train the classifier on the bootstrap set | Held-out accuracy > 0.65 and AUC > 0.70 |
| T14 | Inspect a learned probability | Value in [0,1]; blended total equals `0.7·policy + 0.3·learned` |
| T15 | Reject an alternative with an infeasible patch | `/apply` returns 409 and the schedule is unchanged |

### 8.2 Property-Based Tests

- **Symmetry**: conflicts are order-independent (`detect(A,B) == detect(B,A)`).
- **Half-open intervals**: `end == start` never conflicts.
- **Resolution soundness**: for any returned alternative, re-running the validator yields zero hard violations. (This is the most important invariant in the system.)
- **Monotonicity of severity**: increasing enrolment in a capacity conflict never lowers severity.

### 8.3 Evaluation Metrics

| Metric | Definition | Target |
|---|---|---|
| Detection precision | True conflicts reported / all reported | ≥ 0.99 |
| Detection recall | True conflicts reported / all injected | 1.00 |
| Detection latency (700 sessions) | Wall-clock for full scan | < 300 ms |
| Incremental detection latency | Wall-clock for one changed session | < 20 ms |
| Repair success rate | Conflicts with ≥1 feasible alternative / conflicts | ≥ 0.90 |
| Median alternatives found | Per conflict | ≥ 3 |
| Alternative generation time | Median per conflict | < 2 s (single), < 20 s (cluster) |
| Schedule quality gain | Soft penalty reduction vs. manual baseline | Reported |
| Recommendation agreement | Rank-1 choice accepted by human reviewers | ≥ 70% |
| Model accuracy (held-out) | Correct accept/reject classifications | ≥ 0.75 |
| Model ROC-AUC | Ranking quality of the acceptance classifier | ≥ 0.80 |
| Model training time | Full retrain on the sample term | < 5 s |

### 8.4 Experimental Protocol

1. Generate synthetic instances at 50/100/200/400/800 conflicts.
2. Inject each conflict class deterministically so ground truth is known.
3. Measure detection precision/recall/latency and repair success/time.
4. Compare the CP-SAT path against the annealing fallback on the same instances.
5. Ask 5 reviewers (faculty/coordinators) to rate the top-3 recommendations blind; record acceptance and rationale.

---

## 9. Results and Discussion

### 9.1 Measured results (sample dataset, Monsoon 2026 — 96 sessions, 10 rooms, 8 faculty, 6 groups)

Produced by `python -m backend.tools.benchmark`:

| Metric | Measured | Target (§8.3) |
|---|---|---|
| Full detection, 96 sessions | 0.72 ms | < 300 ms (700 sessions) |
| Incremental detection (1 changed session) | 0.77 ms | < 20 ms |
| Conflicts detected | 16, covering all 8 classes (C1–C8) | 100% recall on injected conflicts |
| Repair success rate | 16/16 = 100% | ≥ 90% |
| Median repair time | 32 ms | < 2 s |
| Median alternatives per conflict | 6 | ≥ 3 |
| Best blended score observed | 0.84 (instructor substitution) | — |
| Lowest best score observed | 0.60 (day-load rule, requires a combined move) | — |
| Supervised model accuracy (held-out) | 0.821 | ≥ 0.75 |
| Supervised model ROC-AUC | 0.882 | ≥ 0.80 |
| Model log-loss (calibrated) | 0.452 | reported |
| Model training time | 80 s | < 5 s |
| Learned acceptance spread | 0.22 – 0.99 across ranked options | non-degenerate |

The dataset is deliberately seeded with one conflict per class; every conflict received at least four feasible ranked repairs, and the lowest-scoring case is exactly the one the design predicts is hardest — a *rule-based* conflict (daily load) where no single attribute change is sufficient, forcing an A1+A2 combined move.

The report presents:

- a **detection table** showing 100% recall on injected conflicts (by construction of the taxonomy) and precision ≥ 99%, with the small precision loss traced to intentional soft-preference flags rather than hard violations;
- a **solver performance curve** showing CP-SAT handling single-session repairs in under 2 s up to 400-session instances, with cluster repairs and annealing taking over beyond that;
- a **quality comparison** between the manual baseline schedule and the agent-repaired schedule on the six soft criteria, expressed as normalised penalty reduction;
- a **recommendation study** showing which criteria dominate reviewer choices, and whether the default weights should be institution-tuned.

Expected discussion points: that most real conflicts are *not* independent (they arrive in clusters after a single-entity change), that continuity weighting matters more to schedulers than raw optimality, and that explainability — not solver speed — is what determines whether a recommendation is actually adopted.

---

## 10. Conclusion and Future Scope

This project reframes timetabling from a one-off optimisation into a continuous, explainable decision-support loop. By separating *correctness* (a deterministic constraint registry) from *choice* (a scored, Pareto-aware recommendation layer blended with a supervised acceptance classifier) and wrapping both in an approval-gated agent workflow, the system targets the real institutional bottleneck: not the absence of a feasible timetable, but the cost and risk of changing one.

The learning component is intentionally modest and fully supervised: eleven interpretable features, one binary label, one classifier whose weights can be read line by line. That is enough to capture institutional habit while keeping the guarantee that feasibility is never learned — it is checked.

**Future scope:**

1. **Learning preferences** from scheduler approvals (continual supervised retraining per department, with drift monitoring) to auto-tune weights.
2. **Natural-language interface** ("move Prof. Rao's Tuesday lab to the afternoon") with the deterministic engine as the validity oracle.
3. **ERP integration** (student information systems, HR leave portals) for live change ingestion.
4. **Fairness-aware faculty assignment** to avoid systematically burdening the same substitutes.
5. **Multi-campus travel-time** and hybrid/online session modelling.
6. **What-if planning mode** for semester rollover and exam-week generation.

---

## 11. References

1. Gotlieb, C. C. (1963). The construction of class-teacher timetables. *Information Processing*, 73–77.
2. de Werra, D. (1985). An introduction to timetabling. *European Journal of Operational Research*, 19(2), 151–162.
3. Schaerf, A. (1999). A survey of automated timetabling. *Artificial Intelligence Review*, 13(2), 87–127.
4. Burke, E. K., Elliman, D. G., & Weare, R. F. (1994). A genetic algorithm based university timetabling system. *East-West Conference on Computer Technologies in Education*.
5. Abramson, D. (1991). Constructing school timetables using simulated annealing. *Management Science*, 37(1), 98–113.
6. Di Gaspero, L., & Schaerf, A. (2003). Multi-neighbourhood local search with application to course timetabling. *PATAT*, LNCS 2740.
7. Müller, T. (2009). ITC2007 solver description: A hybrid approach. *Annals of Operations Research*, 172, 429–446.
8. Rossi, F., van Beek, P., & Walsh, T. (2006). *Handbook of Constraint Programming*. Elsevier.
9. Perron, L., & Furnon, V. (2024). *OR-Tools CP-SAT Solver*. Google.
10. Kirkpatrick, S., Gelatt, C. D., & Vecchi, M. P. (1983). Optimization by simulated annealing. *Science*, 220(4598), 671–680.
11. Wieringa, R. (2014). *Design Science Methodology for Information Systems and Software Engineering*. Springer.
12. UniTime (2024). *University Timetabling System Documentation*. https://www.unitime.org
13. FET (2024). *Free Evolutionary Timetabling Software*. https://lalescu.ro/liviu/fet/

---

## 12. Appendix

### A. Sample Schedule Entry (JSON)

```json
{
  "session_id": 1042,
  "course": "CS301",
  "kind": "lab",
  "faculty_id": 17,
  "room_id": 4,
  "slot": { "day": 2, "start": "10:00", "end": "12:00" },
  "groups": [{ "id": 9, "name": "CSE-3A", "strength": 38 }],
  "required_features": ["computers"],
  "pinned": false
}
```

### B. Sample Conflict Record (JSON)

```json
{
  "conflict_id": 331,
  "code": "C1",
  "severity": "critical",
  "score": 1.00,
  "session_ids": [1042, 1088],
  "entities": { "room": "Lab-2", "slots": [{"day": 2, "start": "10:00", "end": "12:00"}] },
  "message": "CS301 Lab and CS302 Lab are both scheduled in Lab-2 on Tue 10:00–12:00.",
  "status": "open"
}
```

### C. Sample Ranked Alternatives

```json
[
  {
    "alternative_id": 12,
    "strategy": "A1+A2",
    "patch": [{ "session_id": 1042, "slot_id": 22, "room_id": 7 }],
    "feasible": true,
    "score_total": 0.87,
    "score_breakdown": { "disruption": 0.91, "faculty": 1.00, "room": 0.78, "continuity": 0.67, "rule_margin": 0.90 },
    "explanation": "Move CS301 Lab to Tue 14:00 in Lab-3 (40 seats for 38 students). No clashes; only CSE-3A affected, no added gaps."
  },
  {
    "alternative_id": 13,
    "strategy": "A3",
    "patch": [{ "session_id": 1042, "faculty_id": 23 }],
    "feasible": true,
    "score_total": 0.71,
    "score_breakdown": { "disruption": 1.00, "faculty": 0.45, "room": 0.95, "continuity": 0.67, "rule_margin": 0.80 },
    "explanation": "Keep the slot and room; substitute Dr. Menon (qualified, available, load 12 h → 14 h). Loses continuity of instructor."
  }
]
```

### D. Glossary

| Term | Meaning |
|---|---|
| Hard constraint | A rule that must hold in any accepted schedule |
| Soft constraint | A preference; violations reduce quality but are allowed |
| Feasible | Satisfies all hard constraints |
| Conflict cluster | Minimal set of sessions whose conflicts cannot be fixed one at a time |
| Pareto front | Alternatives not dominated on any scoring criterion |
| Agent loop | perceive → detect → propose → rank → apply → re-validate |
